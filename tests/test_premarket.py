import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.premarket import PremarketSettings, extract_output_text, scheduled_now, scheduled_report, split_report


class PremarketUnitTests(unittest.TestCase):
    def settings(self):
        return PremarketSettings(openai_api_key="test", discord_webhook="test")

    def test_schedule_guard_accepts_configured_window(self):
        now = datetime(2026, 9, 21, 8, 49, tzinfo=ZoneInfo("America/New_York"))
        self.assertTrue(scheduled_now(self.settings(), now))
        self.assertEqual(scheduled_report(self.settings(), now), "premarket")

        opening = datetime(2026, 9, 21, 9, 59, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(scheduled_report(self.settings(), opening), "opening")

    def test_schedule_guard_rejects_wrong_time_and_weekend(self):
        early = datetime(2026, 9, 21, 7, 45, tzinfo=ZoneInfo("America/New_York"))
        weekend = datetime(2026, 9, 20, 8, 45, tzinfo=ZoneInfo("America/New_York"))
        self.assertFalse(scheduled_now(self.settings(), early))
        self.assertFalse(scheduled_now(self.settings(), weekend))

    def test_extracts_response_output_text(self):
        response = {
            "output": [
                {"type": "web_search_call"},
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Part one"},
                        {"type": "output_text", "text": "Part two"},
                    ],
                },
            ]
        }
        self.assertEqual(extract_output_text(response), "Part one\nPart two")

    def test_split_report_preserves_content_within_limit(self):
        report = "First section\n" + ("A" * 25) + "\nLast section"
        chunks = split_report(report, limit=12)
        self.assertTrue(all(len(chunk) <= 12 for chunk in chunks))
        self.assertEqual("\n".join(chunks).replace("\n", ""), report.replace("\n", ""))


if __name__ == "__main__":
    unittest.main()
