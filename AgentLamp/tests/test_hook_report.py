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


def marker_dir():
    return os.path.join(tempfile.gettempdir(), "agentlamp-pending")


def marker_file(app, kind, session, call):
    import hashlib

    key = ("%s:%s:%s:%s" % (app, kind, session, call)).encode()
    return os.path.join(marker_dir(), hashlib.sha1(key).hexdigest() + ".json")


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
        os.makedirs(os.path.join(self.tmp, "agentlamp-pending"), exist_ok=True)

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

    def marker(self, session, call, kind="shell", app="cursor"):
        return marker_file(app, kind, session, call)

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
                            '{"conversation_id":"t1","command":"npm test","sandbox":false}')
        self.assertEqual(json.loads(out), {"permission": "allow"})
        marker_path = marker_file("cursor", "shell", "t1", "npm test")
        # The test TMPDIR override changes the pending dir, so recompute it.
        import hashlib

        key = ("cursor:shell:t1:npm test").encode()
        real_path = os.path.join(self.tmp, "agentlamp-pending",
                                 hashlib.sha1(key).hexdigest() + ".json")
        self.assertTrue(os.path.exists(real_path), "marker should be armed")
        # No immediate attention: auto-run commands stay "working".
        self.server.assert_no_post()
        # The deferred child fires once the call is still unfinished.
        post = self.server.next_post(timeout=4.0)
        self.assertEqual(post["state"], "attention")
        self.assertFalse(os.path.exists(real_path))

    def test_after_shell_disarms_same_call(self):
        before = '{"conversation_id":"t1","command":"npm test","sandbox":false}'
        after = '{"conversation_id":"t1","command":"npm test"}'
        self.run_hook("cursor", "before-shell", before)
        self.run_hook("cursor", "after-shell", after)
        post = self.server.next_post()
        self.assertEqual(post["state"], "working")
        self.server.assert_no_post(timeout=2.5)  # timer never fires

    def test_other_call_cannot_disarm_pending_call(self):
        # The bug this guards: the marker is keyed per call, so a different
        # command completing must not clear a pending approval card's timer.
        self.run_hook("cursor", "before-shell",
                      '{"conversation_id":"t1","command":"dangerous deploy","sandbox":false}')
        self.run_hook("cursor", "after-shell",
                      '{"conversation_id":"t1","command":"ls -la"}')
        post = self.server.next_post()
        self.assertEqual(post["state"], "working")
        # The pending call's attention still fires on schedule.
        post = self.server.next_post(timeout=4.0)
        self.assertEqual(post["state"], "attention")
        self.assertEqual(post["session"], "t1")

    def test_denied_call_clears_pending(self):
        self.run_hook("cursor", "before-shell",
                      '{"conversation_id":"t1","command":"dangerous deploy","sandbox":false}')
        self.run_hook("cursor", "post-tool-failure",
                      '{"conversation_id":"t1","command":"dangerous deploy",'
                      '"failure_type":"permission_denied"}')
        post = self.server.next_post()
        self.assertEqual(post["state"], "working")
        self.server.assert_no_post(timeout=2.5)  # no late attention
        # Nothing left armed for the session.
        pending = os.listdir(os.path.join(self.tmp, "agentlamp-pending"))
        self.assertEqual(pending, [])

    def test_sandboxed_shell_never_flags(self):
        self.run_hook("cursor", "before-shell",
                      '{"conversation_id":"t1","command":"ls","sandbox":true}')
        self.server.assert_no_post()
        self.server.assert_no_post(timeout=1.5)

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