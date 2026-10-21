import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "hook_report.py")
PENDING = os.path.join(tempfile.gettempdir(), "agentlamp-pending")


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
        self.fail("unexpected post: %r" % (item,))


class HookReportTests(unittest.TestCase):
    def setUp(self):
        self.server = CaptureServer()
        self.tmp = tempfile.mkdtemp(prefix="agentlamp-test-")
        self.base_env = os.environ.copy()
        self.base_env["AGENTLAMP_BRIDGE"] = self.server.url()
        self.base_env["AGENTLAMP_DEFER_S"] = "1"
        self.base_env["TMPDIR"] = self.tmp

    def tearDown(self):
        self.server.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

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

    def marker_file(self, app, kind, session):
        import hashlib

        key = ("%s:%s:%s" % (app, kind, session)).encode()
        return os.path.join(self.tmp, "agentlamp-pending",
                            hashlib.sha1(key).hexdigest() + ".json")

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

    def test_before_shell_defers_attention(self):
        out = self.run_hook("cursor", "before-shell",
                            '{"conversation_id":"t1","sandbox":false}')
        self.assertEqual(json.loads(out), {"permission": "allow"})
        marker = self.marker_file("cursor", "shell", "t1")
        self.assertTrue(os.path.exists(marker), "marker should be armed")
        # No immediate attention: auto-run commands stay "working".
        self.server.assert_no_post()
        # The deferred child fires once the call is still unfinished.
        post = self.server.next_post(timeout=4.0)
        self.assertEqual(post["state"], "attention")
        self.assertFalse(os.path.exists(marker))

    def test_after_shell_disarms_attention(self):
        self.run_hook("cursor", "before-shell",
                     '{"conversation_id":"t1","sandbox":false}')
        self.run_hook("cursor", "after-shell",
                      '{"conversation_id":"t1"}')
        post = self.server.next_post()
        self.assertEqual(post["state"], "working")
        self.assertFalse(os.path.exists(self.marker_file("cursor", "shell", "t1")))
        self.server.assert_no_post()

    def test_sandboxed_shell_never_flags(self):
        self.run_hook("cursor", "before-shell",
                      '{"conversation_id":"t1","sandbox":true}')
        self.server.assert_no_post()
        self.assertFalse(os.path.exists(self.marker_file("cursor", "shell", "t1")))

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