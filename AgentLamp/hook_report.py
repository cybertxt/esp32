#!/usr/bin/env python3
"""Post one agent-lamp event and return without blocking the agent.

Cursor permission hooks must print a schema-valid allow decision. An empty
or invalid body blocks the command. On Cursor 3.23.x builds the printed
`allow` is recorded but Cursor keeps its own approval card; deny is the
response that actually stops work, and this script never prints deny.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

BRIDGE = os.environ.get("AGENTLAMP_BRIDGE", "http://127.0.0.1:8765/event")
APPS = {"cursor", "codebuddy", "codex"}
# An unsandboxed shell/MCP call raises attention only after it stays
# unfinished this long. Cursor fires beforeShellExecution for every
# command, auto-run or approval-pending, and the payload carries no flag
# telling the two apart, so an immediate blink would flag routine
# auto-run commands. Calls that finish disarm the marker before it fires.
DEFER_S = float(os.environ.get("AGENTLAMP_DEFER_S", "8"))
PENDING_DIR = os.path.join(tempfile.gettempdir(), "agentlamp-pending")


def emit(payload):
    """Print the hook's required JSON, if any, then exit."""
    if payload is not None:
        sys.stdout.write(json.dumps(payload))
        sys.stdout.write("\n")
    raise SystemExit(0)


def post(app, session, state):
    body = json.dumps({"app": app, "session": session, "state": state}).encode()
    request = urllib.request.Request(
        BRIDGE, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(request, timeout=0.4).read()
    except (urllib.error.URLError, TimeoutError, OSError):
        # The lamp bridge can be down. The agent still continues.
        pass


def session_id(data):
    for key in ("conversation_id", "session_id", "turn_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return "default"


def marker_path(app, kind, session):
    key = ("%s:%s:%s" % (app, kind, session)).encode()
    return os.path.join(PENDING_DIR, hashlib.sha1(key).hexdigest() + ".json")


def arm_attention(app, kind, session):
    """Schedule attention for an unsandboxed call that never finishes."""
    try:
        os.makedirs(PENDING_DIR)
    except OSError:
        pass
    path = marker_path(app, kind, session)
    try:
        with open(path, "w") as f:
            json.dump({"app": app, "session": session, "armed": time.time()}, f)
    except OSError:
        return
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), app, "defer", kind, path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def disarm_attention(app, kind, session):
    try:
        os.remove(marker_path(app, kind, session))
    except OSError:
        pass


def deferred_attention(path):
    """Child process: post attention unless a newer call re-armed the slot."""
    time.sleep(DEFER_S)
    try:
        with open(path) as f:
            info = json.load(f)
    except (OSError, ValueError):
        return
    elapsed = time.time() - info.get("armed", 0)
    if elapsed < DEFER_S - 0.5:
        # A newer call replaced the marker; its own child will handle it.
        return
    try:
        os.remove(path)
    except OSError:
        pass
    post(info.get("app"), info.get("session"), "attention")


def main():
    if len(sys.argv) == 5 and sys.argv[1] in APPS and sys.argv[2] == "defer":
        deferred_attention(sys.argv[4])
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

    if app == "cursor" and event == "before-submit":
        post(app, session, "working")
        emit({"continue": True})
    if app == "cursor" and event == "stop":
        post(app, session, "error" if data.get("status") == "error" else "idle")
        emit(None)
    if app == "cursor" and event in ("before-shell", "before-mcp"):
        if data.get("sandbox") is not True:
            arm_attention(app, "shell" if event == "before-shell" else "mcp", session)
        emit({"permission": "allow"})
    if app == "cursor" and event in ("after-shell", "after-mcp"):
        disarm_attention(app, "shell" if event == "after-shell" else "mcp", session)
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
        emit(None)
    if app == "codebuddy" and event == "stop":
        post(app, session, "idle")
        emit(None)
    if app == "codebuddy" and event == "notify":
        kind = data.get("notification_type")
        if kind in ("permission_prompt", "idle_prompt"):
            post(app, session, "attention")
        emit(None)
    if app == "codebuddy" and event == "post-tool":
        post(app, session, "working")
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