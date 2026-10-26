import json
import os
import queue
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "hook_report.py")

class CaptureServer:
    """Tiny local bridge that records every POST body hook_report makes."""

    def __init__(self):
        self.posts = queue.Queue()

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                data = b"{}"
                self.send_response(200)
                self.send_header(
                    "Content-Type", "application/json; charset=utf-8"
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                outer.posts.put(body)

            def log_message(self, fmt, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self):
        return "http://127.0.0.1:%d/event" % self.port

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def next_post(self, timeout=4.0):
        return self.posts.get(timeout=timeout)

    def assert_no_post(self, timeout=0.8):
        try:
            item = self.posts.get(timeout=timeout)
        except queue.Empty:
            return
        raise AssertionError("unexpected post: %r" % (item,))


class HookReportTests(unittest.TestCase):
    def setUp(self):
        self.server = CaptureServer()
        self.base_env = os.environ.copy()
        self.base_env["AGENTLAMP_BRIDGE"] = self.server.url()

    def tearDown(self):
        self.server.stop()

    def run_hook(self, app, event, stdin=""):
        proc = subprocess.run(
            [sys.executable, SCRIPT, app, event],
            input=stdin.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.base_env,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        return proc.stdout.decode()

    def test_before_submit_posts_working(self):
        out = self.run_hook("cursor", "before-submit",
                            '{"conversation_id":"t1"}')
        self.assertEqual(json.loads(out), {"continue": True})
        self.assertEqual(self.server.next_post(),
                         {"app": "cursor", "session": "t1", "state": "working"})
        self.server.assert_no_post()

    def test_stop_with_error_posts_error(self):
        self.run_hook("cursor", "stop",
                      '{"conversation_id":"t1","status":"error"}')
        self.assertEqual(self.server.next_post()["state"], "error")

    def test_before_shell_does_not_infer_attention(self):
        out = self.run_hook("cursor", "before-shell",
                            '{"conversation_id":"t1","command":"npm test","sandbox":false}')
        self.assertEqual(json.loads(out), {"permission": "allow"})
        self.server.assert_no_post(timeout=1.5)

    def test_after_shell_restores_working(self):
        after = '{"conversation_id":"t1","command":"npm test"}'
        self.run_hook("cursor", "after-shell", after)
        post = self.server.next_post()
        self.assertEqual(post["state"], "working")

    def test_failed_tool_returns_to_working(self):
        self.run_hook("cursor", "post-tool-failure",
                      '{"conversation_id":"t1","command":"dangerous deploy",'
                      '"failure_type":"permission_denied"}')
        post = self.server.next_post()
        self.assertEqual(post["state"], "working")

    def test_sandboxed_shell_never_flags(self):
        self.run_hook("cursor", "before-shell",
                      '{"conversation_id":"t1","command":"ls","sandbox":true}')
        self.server.assert_no_post(timeout=1.5)

    def test_codebuddy_pre_tool_does_not_infer_attention(self):
        out = self.run_hook("codebuddy", "pre-tool",
                            '{"session_id":"cb1","tool_name":"Bash"}')
        self.assertEqual(out, "")
        self.server.assert_no_post(timeout=1.5)

    def test_codebuddy_post_tool_sets_working(self):
        self.run_hook("codebuddy", "post-tool",
                      '{"session_id":"cb1","tool_name":"Bash"}')
        post = self.server.next_post()
        self.assertEqual(post["state"], "working")

    def test_codebuddy_notify_types(self):
        self.run_hook("codebuddy", "notify",
                      '{"session_id":"cb1","notification_type":"elicitation_dialog"}')
        self.assertEqual(self.server.next_post()["state"], "attention")
        self.run_hook("codebuddy", "notify",
                      '{"session_id":"cb1","notification_type":"auth_success"}')
        self.server.assert_no_post()

    def test_codebuddy_stop_sets_idle(self):
        self.run_hook("codebuddy", "stop", '{"session_id":"cb1"}')
        self.assertEqual(self.server.next_post()["state"], "idle")

    def test_garbage_input_is_safe(self):
        out = self.run_hook("cursor", "post-tool", "this is not json")
        self.assertEqual(out, "")
        self.server.assert_no_post()

    def test_unknown_args_emit_nothing(self):
        out = self.run_hook("vscode", "prompt", "{}")  # not in APPS
        self.assertEqual(out, "")
        self.server.assert_no_post()


if __name__ == "__main__":
    unittest.main()