#!/usr/bin/env python3
"""Local status bridge for the AgentLamp.

Hooks POST events to 127.0.0.1:8765. This process keeps one BLE link to the
ESP32-S3 and writes three state bytes. A menu bar is used when rumps is
installed; otherwise the same loop runs in the terminal.
"""

import asyncio
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHAR_UUID = "6f4c0002-8b3a-4c1e-9a2d-5e7b1c0a4d10"
APPS = ("cursor", "codebuddy", "codex")
RANK = {"idle": 0, "working": 1, "error": 2, "attention": 3}
BYTE = {name: value for value, name in enumerate(("idle", "working", "error", "attention"))}
TIMEOUT_S = 15 * 60
HOST = os.environ.get("AGENTLAMP_HOST", "127.0.0.1")
PORT = 8765


class LampState:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {app: {} for app in APPS}
        self._override = {app: None for app in APPS}
        self.linked = False
        self.echo = b""

    def event(self, app, session, state):
        if app not in APPS or state not in RANK or not session:
            return False
        now = time.monotonic()
        with self._lock:
            bucket = self._sessions[app]
            if state == "idle":
                bucket.pop(session, None)
            else:
                bucket[session] = (state, now)
            self._expire(now)
        return True

    def set_override(self, app, state):
        if app not in APPS:
            return False
        if state is not None and state not in RANK:
            return False
        with self._lock:
            self._override[app] = state
        return True

    def payload(self):
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            return bytes(BYTE[self._app_state(app)] for app in APPS)

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            return {
                "linked": self.linked,
                "apps": {app: self._app_state(app) for app in APPS},
                "override": dict(self._override),
            }

    def set_linked(self, linked):
        with self._lock:
            self.linked = linked

    def note_echo(self, data):
        with self._lock:
            self.echo = bytes(data)

    def _expire(self, now):
        for bucket in self._sessions.values():
            stale = [key for key, (_, seen) in bucket.items() if now - seen > TIMEOUT_S]
            for key in stale:
                del bucket[key]

    def _app_state(self, app):
        if self._override[app] is not None:
            return self._override[app]
        best = "idle"
        for state, _seen in self._sessions[app].values():
            if RANK[state] > RANK[best]:
                best = state
        return best


LAMP = LampState()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path != "/status":
            self._send(404, {"error": "not found"})
            return
        self._send(200, LAMP.snapshot())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "bad json"})
            return
        if self.path == "/event":
            ok = LAMP.event(body.get("app"), str(body.get("session") or ""), body.get("state"))
            self._send(200 if ok else 400, LAMP.snapshot())
            return
        if self.path == "/override":
            ok = LAMP.set_override(body.get("app"), body.get("state"))
            self._send(200 if ok else 400, LAMP.snapshot())
            return
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        return

    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve_http():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()


async def ble_loop():
    from bleak import BleakClient, BleakScanner

    while True:
        try:
            device = await BleakScanner.find_device_by_name("AgentLamp", timeout=6.0)
            if device is None:
                LAMP.set_linked(False)
                continue
            async with BleakClient(device) as client:
                LAMP.set_linked(True)
                print("BLE linked", device.address, flush=True)

                def on_notify(_char, data):
                    LAMP.note_echo(data)

                await client.start_notify(CHAR_UUID, on_notify)
                last = None
                while client.is_connected:
                    payload = LAMP.payload()
                    if payload != last:
                        await client.write_gatt_char(CHAR_UUID, payload, response=True)
                        last = payload
                        print("wrote", list(payload), flush=True)
                    await asyncio.sleep(0.25)
        except Exception as exc:
            LAMP.set_linked(False)
            print("BLE retry:", exc, flush=True)
            await asyncio.sleep(2)


def run_menu():
    import rumps

    class LampApp(rumps.App):
        def __init__(self):
            super().__init__("AgentLamp", title="Lamp")
            self.menu = ["Status", None]
            for app in APPS:
                self.menu.add(rumps.MenuItem(app))
                for label, state in (
                    ("Auto", None),
                    ("Idle", "idle"),
                    ("Working", "working"),
                    ("Needs you", "attention"),
                    ("Error", "error"),
                ):
                    item = rumps.MenuItem(f"{app}: {label}", callback=self._pick)
                    item.app_name = app
                    item.lamp_state = state
                    self.menu.add(item)
                self.menu.add(None)
            self.menu.add(rumps.MenuItem("Quit", callback=rumps.quit_application))
            rumps.Timer(self._refresh, 1).start()

        def _pick(self, sender):
            LAMP.set_override(sender.app_name, sender.lamp_state)

        def _refresh(self, _timer):
            snap = LAMP.snapshot()
            bits = []
            for app in APPS:
                state = snap["apps"][app]
                mark = {"idle": "·", "working": "●", "error": "!", "attention": "?"}[state]
                bits.append(mark)
            link = "up" if snap["linked"] else "down"
            self.title = "Lamp " + "".join(bits)
            self.menu["Status"].title = f"Link {link}  " + "  ".join(
                f"{app} {snap['apps'][app]}" for app in APPS
            )

    LampApp().run()


def main():
    threading.Thread(target=serve_http, daemon=True).start()
    print(f"AgentLamp bridge on http://{HOST}:{PORT}", flush=True)
    terminal = "--terminal" in sys.argv
    try:
        import rumps  # noqa: F401
        have_menu = True
    except ImportError:
        have_menu = False
    if terminal or not have_menu:
        if not have_menu:
            print("rumps is not installed; running in the terminal. Ctrl-C to stop.", flush=True)
        asyncio.run(ble_loop())
        return
    threading.Thread(target=lambda: asyncio.run(ble_loop()), daemon=True).start()
    run_menu()


if __name__ == "__main__":
    main()
