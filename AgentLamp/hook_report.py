#!/usr/bin/env python3
"""Post one agent-lamp event and return without blocking the agent.

Cursor permission hooks must print a schema-valid allow decision. An empty
or invalid body blocks the command. On Cursor 3.23.x builds the printed
`allow` is recorded but Cursor keeps its own approval card; deny is the
response that actually stops work, and this script never prints deny.
"""

import glob
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

BRIDGE = os.environ.get("AGENTLAMP_BRIDGE", "http://127.0.0.1:8765/event")
APPS = {"cursor", "codebuddy", "codex"}
LOG_PATH = os.path.join(tempfile.gettempdir(), "agentlamp-hooks.log")
LOG_MAX = 256 * 1024


def _env_seconds(name, default, minimum):
    try:
        return max(minimum, float(os.environ.get(name, default)))
    except ValueError:
        return float(default)


# CodeBuddy can run one tool (or think) far longer than the bridge's
# 3-minute working-session TTL, and it emits no hook event while it waits.
# A per-session heartbeat process therefore re-posts "working" until the
# turn's Stop hook kills it. It self-terminates after the max age so a
# crashed agent (whose Stop never fires) cannot pin the lamp forever.
HEARTBEAT_INTERVAL_S = _env_seconds("AGENTLAMP_HEARTBEAT_INTERVAL_S", 30, 0.05)
HEARTBEAT_MAX_S = _env_seconds("AGENTLAMP_HEARTBEAT_MAX_S", 12 * 60 * 60, 60)


def log_event(app, event, data):
    """Append one compact line per hook call for later diagnosis."""
    info = {"ts": round(time.time(), 3), "app": app, "event": event}
    try:
        info["session"] = session_id(data)
    except Exception:
        pass
    for key in (
        "notification_type",
        "tool_name",
        "tool",
        "sandbox",
        "status",
        "failure_type",
    ):
        if key in data:
            info[key] = data.get(key)
    command = data.get("command")
    if isinstance(command, str):
        info["command"] = command[:80]
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX:
            os.remove(LOG_PATH)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(info) + "\n")
    except OSError:
        pass


def emit(payload):
    """Print the hook's required JSON, if any, then exit."""
    if payload is not None:
        sys.stdout.write(json.dumps(payload))
        sys.stdout.write("\n")
    raise SystemExit(0)


def post(app, session, state, heartbeat=False):
    payload = {"app": app, "session": session, "state": state}
    if heartbeat:
        # The bridge refreshes the session's timestamp without downgrading
        # an attention/error state it may have moved to in the meantime.
        payload["heartbeat"] = True
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        BRIDGE, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(request, timeout=0.4).read()
    except (urllib.error.URLError, TimeoutError, OSError):
        # The lamp bridge can be down. The agent still continues.
        pass


def heartbeat_path(app, session):
    digest = hashlib.sha256(session.encode()).hexdigest()[:16]
    return os.path.join(
        tempfile.gettempdir(), "agentlamp-heartbeat-%s-%s.pid" % (app, digest)
    )


def _read_pid(path):
    try:
        with open(path) as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid):
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _write_pid(path, pid):
    tmp = "%s.%d.tmp" % (path, pid)
    with open(tmp, "w") as handle:
        handle.write(str(pid))
    os.replace(tmp, path)


def start_heartbeat(app, session):
    """Spawn the detached per-session heartbeat, unless one is running."""
    if os.environ.get("AGENTLAMP_HEARTBEAT") == "0" or os.name != "posix":
        return
    path = heartbeat_path(app, session)
    if _pid_alive(_read_pid(path)):
        return
    try:
        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--heartbeat", app, session],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        _write_pid(path, proc.pid)
    except (OSError, subprocess.SubprocessError):
        pass


def stop_heartbeats(app, session=None):
    """Terminate one session's heartbeat, or every heartbeat for the app."""
    if session and session != "*":
        paths = [heartbeat_path(app, session)]
    else:
        paths = glob.glob(
            os.path.join(tempfile.gettempdir(), "agentlamp-heartbeat-%s-*.pid" % app)
        )
    for path in paths:
        pid = _read_pid(path)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        try:
            os.remove(path)
        except OSError:
            pass


def run_heartbeat(app, session):
    """Heartbeat loop; runs detached as ``--heartbeat <app> <session>``."""
    if app not in APPS or not session or session == "*":
        return
    path = heartbeat_path(app, session)
    existing = _read_pid(path)
    if existing and existing != os.getpid() and _pid_alive(existing):
        return  # Another heartbeat already owns this session.
    try:
        _write_pid(path, os.getpid())
        deadline = time.monotonic() + HEARTBEAT_MAX_S
        while time.monotonic() < deadline:
            if _read_pid(path) != os.getpid():
                return  # Stopped, or replaced by a newer heartbeat.
            post(app, session, "working", heartbeat=True)
            time.sleep(HEARTBEAT_INTERVAL_S)
    except OSError:
        pass
    finally:
        if _read_pid(path) == os.getpid():
            try:
                os.remove(path)
            except OSError:
                pass


def session_id(data):
    for key in ("conversation_id", "session_id", "turn_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return "default"


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--heartbeat":
        run_heartbeat(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) != 3 or sys.argv[1] not in APPS:
        emit(None)
    app, event = sys.argv[1], sys.argv[2]
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    session = session_id(data)
    log_event(app, event, data)

    if app == "cursor" and event == "before-submit":
        post(app, session, "working")
        emit({"continue": True})
    if app == "cursor" and event == "stop":
        post(app, session, "error" if data.get("status") == "error" else "idle")
        emit(None)
    if app == "cursor" and event in ("before-shell", "before-mcp"):
        # These hooks fire as execution begins, not while Cursor is waiting
        # on its approval card. They cannot identify "needs you".
        emit({"permission": "allow"})
    if app == "cursor" and event in ("after-shell", "after-mcp"):
        post(app, session, "working")
        emit(None)
    if app == "cursor" and event == "post-tool-failure":
        post(app, session, "working")
        emit(None)
    if app == "cursor" and event == "pre-tool":
        if data.get("tool_name") == "AskQuestion":
            post(app, session, "attention")
        emit({"permission": "allow"})
    if app == "cursor" and event == "post-tool":
        if data.get("tool_name") == "AskQuestion":
            post(app, session, "working")
        emit(None)

    if app == "codebuddy" and event == "prompt":
        post(app, session, "working")
        start_heartbeat(app, session)
        emit(None)
    if app == "codebuddy" and event == "stop":
        # Stop the heartbeats first so one cannot re-post working after the
        # clear. CodeBuddy emits tool events for child/subagent session IDs
        # but its Stop hook reports only the parent ID, so stop every
        # CodeBuddy heartbeat and clear every session: clearing just the
        # parent ID leaves child sessions pinned at working after the whole
        # turn has ended. A child that genuinely keeps working re-registers
        # through its next tool hook.
        stop_heartbeats(app)
        post(app, "*", "idle")
        emit(None)
    if app == "codebuddy" and event == "notify":
        # The IDE build ships no Notification call sites; when a surface
        # does send one, these types mean the agent is blocked on you. The
        # heartbeat keeps refreshing this session, but heartbeat posts do
        # not downgrade attention, so the lamp stays on "needs you".
        kind = data.get("notification_type")
        if kind in ("permission_prompt", "idle_prompt", "elicitation_dialog"):
            post(app, session, "attention")
        emit(None)
    if app == "codebuddy" and event == "pre-tool":
        # PreToolUse is a working signal, never an attention one: it cannot
        # distinguish "about to execute" from "waiting for approval", and
        # treating a slow tool as attention reversed the real states. It
        # also (re)starts the heartbeat that keeps a long-running tool —
        # which emits no further hook events until it finishes — from
        # expiring to idle at the bridge.
        post(app, session, "working")
        start_heartbeat(app, session)
        emit(None)
    if app == "codebuddy" and event == "post-tool":
        post(app, session, "working")
        start_heartbeat(app, session)
        emit(None)

    if app == "codex" and event == "prompt":
        post(app, session, "working")
        emit(None)
    if app == "codex" and event == "stop":
        post(app, session, "idle")
        emit(None)
    if app == "codex" and event == "permission":
        # No decision field: Codex keeps its normal approval prompt.
        post(app, session, "attention")
        emit(None)
    if app == "codex" and event == "post-tool":
        post(app, session, "working")
        emit(None)

    emit(None)


if __name__ == "__main__":
    main()