import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.premarket import PremarketSettings
from app.premarket_worker import PremarketWorker, is_due, load_state


ET = ZoneInfo("America/New_York")


class PremarketWorkerTests(unittest.TestCase):
    def settings(self):
        return PremarketSettings(openai_api_key="test", discord_webhook="test")

    def test_report_remains_due_after_target_until_sent(self):
        state = {"sent": {}, "last_attempt": {}}
        late = datetime(2026, 9, 23, 11, 30, tzinfo=ET)
        self.assertTrue(is_due(self.settings(), state, "premarket", late, 300))
        self.assertTrue(is_due(self.settings(), state, "opening", late, 300))

    def test_sent_report_is_not_due_again_same_day(self):
        now = datetime(2026, 9, 23, 10, 0, tzinfo=ET)
        state = {"sent": {"premarket": "2026-09-23"}, "last_attempt": {}}
        self.assertFalse(is_due(self.settings(), state, "premarket", now, 300))

    def test_failed_report_waits_before_retry(self):
        now = datetime(2026, 9, 23, 10, 0, tzinfo=ET)
        state = {"sent": {}, "last_attempt": {"opening": (now - timedelta(seconds=60)).isoformat()}}
        self.assertFalse(is_due(self.settings(), state, "opening", now, 300))
        self.assertTrue(is_due(self.settings(), state, "opening", now + timedelta(seconds=301), 300))

    def test_worker_marks_success_and_persists_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            worker = PremarketWorker(self.settings(), path)
            now = datetime(2026, 9, 23, 8, 45, tzinfo=ET)
            with (
                patch("app.premarket_worker.generate_report", return_value="report"),
                patch("app.premarket_worker.publish_report", return_value=2),
            ):
                self.assertEqual(worker.run_once(now), ["premarket"])
            self.assertEqual(load_state(path)["sent"]["premarket"], "2026-09-23")
            self.assertEqual(worker.run_once(now), [])


if __name__ == "__main__":
    unittest.main()
