#!/usr/bin/env python3
"""Post one agent-lamp event and return without blocking the agent.

Cursor permission hooks must print a schema-valid allow decision. An empty
or invalid body blocks the command. Current Cursor builds ignore allow and
keep their own approval card; deny is the response that actually stops work,
and this script never prints deny.
"""

import json
import sys
import urllib.error
import urllib.request

BRIDGE = "http://127.0.0.1:8765/event"
APPS = {"cursor", "codebuddy", "codex"}


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


def main():
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
            post(app, session, "attention")
        emit({"permission": "allow"})
    if app == "cursor" and event in ("after-shell", "after-mcp"):
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
