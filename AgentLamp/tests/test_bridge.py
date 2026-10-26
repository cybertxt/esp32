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

    def test_wildcard_idle_clears_all_app_sessions(self):
        lamp = bridge.LampState()
        lamp.event("codebuddy", "parent", "working")
        lamp.event("codebuddy", "child", "working")
        lamp.event("cursor", "other-app", "working")
        self.assertTrue(lamp.event("codebuddy", "*", "idle"))
        snap = lamp.snapshot()
        self.assertEqual(snap["apps"]["codebuddy"], "idle")
        self.assertEqual(snap["sessions"]["codebuddy"], [])
        self.assertEqual(snap["apps"]["cursor"], "working")

    def test_wildcard_cannot_set_non_idle_state(self):
        lamp = bridge.LampState()
        self.assertFalse(lamp.event("codebuddy", "*", "working"))
        self.assertEqual(lamp.snapshot()["apps"]["codebuddy"], "idle")

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
        lamp.event("cursor", "attention-session", "attention")
        old = time.monotonic() - bridge.TIMEOUT_S - 1
        with lamp._lock:
            # Both an old attention session past the long TTL and a working
            # session past the (shorter) working TTL are reaped.
            lamp._sessions["cursor"]["old-attention"] = ("attention", old)
            lamp._sessions["cursor"]["old-working"] = (
                "working",
                time.monotonic() - bridge.WORKING_TIMEOUT_S - 1,
            )
        snap = lamp.snapshot()
        self.assertEqual(snap["apps"]["cursor"], "attention")
        labels = [s["session"] for s in snap["sessions"]["cursor"]]
        self.assertEqual(labels, ["attention-se"])

    def test_stale_working_expires_faster_than_attention(self):
        lamp = bridge.LampState()
        lamp.event("cursor", "still-waiting", "attention")
        with lamp._lock:
            lamp._sessions["cursor"]["stale-working"] = (
                "working",
                time.monotonic() - bridge.WORKING_TIMEOUT_S - 1,
            )
        snap = lamp.snapshot()
        self.assertEqual(snap["apps"]["cursor"], "attention")
        labels = [s["session"] for s in snap["sessions"]["cursor"]]
        self.assertIn("still-waitin", labels)
        self.assertNotIn("stale-worki", labels)
        # A fresh working session is untouched by the short TTL.
        lamp.event("cursor", "fresh-work", "working")
        labels = [s["session"] for s in lamp.snapshot()["sessions"]["cursor"]]
        self.assertIn("fresh-work", labels)

    def test_snapshot_lists_sessions(self):
        lamp = bridge.LampState()
        lamp.event("cursor", "abcd1234ef5678", "working")
        entries = lamp.snapshot()["sessions"]["cursor"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["session"], "abcd1234ef56")
        self.assertEqual(entries[0]["state"], "working")
        self.assertLessEqual(entries[0]["age_s"], 2)

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


class CursorLogTests(unittest.TestCase):
    def test_approval_requested_maps_to_attention(self):
        line = (
            '2026-10-26 11:49:29.905 [info] [ComposerWakelockManager] '
            'Released wakelock id=8 reason="user-approval-requested" '
            "composerId=abc123-def456\n"
        )
        self.assertEqual(
            bridge.cursor_log_event(line), ("abc123-def456", "attention")
        )

    def test_agent_loop_resumed_maps_to_working(self):
        line = (
            '2026-10-26 11:49:33.374 [info] [ComposerWakelockManager] '
            'Acquired wakelock id=9 reason="agent-loop-resumed" '
            "composerId=abc123-def456\n"
        )
        self.assertEqual(
            bridge.cursor_log_event(line), ("abc123-def456", "working")
        )

    def test_unrelated_wakelock_line_is_ignored(self):
        line = (
            '2026-10-26 11:49:59.000 [info] [ComposerWakelockManager] '
            'Released wakelock id=9 reason="generation-ended" '
            "composerId=abc123-def456\n"
        )
        self.assertIsNone(bridge.cursor_log_event(line))


if __name__ == "__main__":
    unittest.main()