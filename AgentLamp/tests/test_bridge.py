import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bridge  # noqa: E402


class LampStateTests(unittest.TestCase):
    def test_attention_beats_error_and_working(self):
        lamp = bridge.LampState()
        lamp.event("cursor", "a", "working")
        lamp.event("cursor", "b", "error")
        lamp.event("cursor", "c", "attention")
        self.assertEqual(lamp.snapshot()["apps"]["cursor"], "attention")
        self.assertEqual(list(lamp.payload()), [3, 0, 0])

    def test_error_beats_working(self):
        lamp = bridge.LampState()
        lamp.event("codex", "a", "working")
        lamp.event("codex", "b", "error")
        self.assertEqual(lamp.payload()[2], 2)

    def test_idle_removes_only_that_session(self):
        lamp = bridge.LampState()
        lamp.event("cursor", "a", "working")
        lamp.event("cursor", "b", "working")
        self.assertTrue(lamp.event("cursor", "a", "idle"))
        self.assertEqual(lamp.snapshot()["apps"]["cursor"], "working")  # b stays
        lamp.event("cursor", "b", "idle")
        self.assertEqual(lamp.snapshot()["apps"]["cursor"], "idle")

    def test_override_wins_and_clears(self):
        lamp = bridge.LampState()
        lamp.event("cursor", "a", "attention")
        self.assertTrue(lamp.set_override("cursor", "idle"))
        self.assertEqual(lamp.snapshot()["apps"]["cursor"], "idle")
        self.assertTrue(lamp.set_override("cursor", None))
        self.assertEqual(lamp.snapshot()["apps"]["cursor"], "attention")

    def test_events_are_validated(self):
        lamp = bridge.LampState()
        self.assertFalse(lamp.event("vscode", "a", "working"))
        self.assertFalse(lamp.event("cursor", "a", "sleeping"))
        self.assertFalse(lamp.event("cursor", "", "working"))
        self.assertFalse(lamp.set_override("cursor", "busy"))
        self.assertFalse(lamp.set_override("nope", "idle"))
        self.assertEqual(list(lamp.payload()), [0, 0, 0])

    def test_sessions_expire_after_timeout(self):
        lamp = bridge.LampState()
        lamp.event("cursor", "old", "working")
        lamp.event("cursor", "fresh", "working")
        # Backdate one session past the timeout, as a crashed hook would leave.
        with lamp._lock:
            seen = time.monotonic() - bridge.TIMEOUT_S - 1
            lamp._sessions["cursor"]["old"] = ("working", seen)
        self.assertEqual(lamp.snapshot()["apps"]["cursor"], "working")
        # Once the fresh session also expires, the app reads idle again.
        with lamp._lock:
            for key, (_, _) in list(lamp._sessions["cursor"].items()):
                lamp._sessions["cursor"][key] = ("working", seen)
        self.assertEqual(lamp.snapshot()["apps"]["cursor"], "idle")

    def test_snapshot_exposes_echo_and_ages(self):
        lamp = bridge.LampState()
        snap = lamp.snapshot()
        self.assertIsNone(snap["ages"]["cursor"])
        self.assertEqual(snap["echo"], [])
        lamp.event("cursor", "a", "working")
        snap = lamp.snapshot()
        self.assertLess(snap["ages"]["cursor"], 2)
        lamp.note_echo(b"\x01\x00\x00")
        self.assertEqual(lamp.snapshot()["echo"], [1, 0, 0])


if __name__ == "__main__":
    unittest.main()