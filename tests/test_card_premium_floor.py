import os
import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from app.config import Settings, load_settings
from app.models import OptionContract, OptionSide, OptionSnapshot
from app.scanner import Scanner


class CardPremiumFloorTests(unittest.TestCase):
    def test_existing_low_environment_override_cannot_lower_card_floor(self):
        with patch.dict(os.environ, {"UOA_MIN_CARD_PREMIUM": "30000"}):
            settings = load_settings()
        self.assertEqual(settings.min_card_premium, 150_000)

    def test_only_fresh_premium_above_150k_reaches_discord(self):
        scanner = Scanner.__new__(Scanner)
        scanner.settings = Settings()
        now = datetime(2026, 10, 28, 10, 30, tzinfo=ZoneInfo("America/New_York"))
        snapshots = []
        for symbol, mark in (("AMD", 1.49999), ("NVDA", 1.5), ("TSLA", 1.50001)):
            contract = OptionContract(symbol, f"{symbol}261028C00100000", date(2026, 10, 28), 100, OptionSide.CALL, 0)
            snapshots.append(OptionSnapshot(contract, 5_000, 1, mark, 100, now))
        scanner.data = Mock(option_snapshots=Mock(return_value=snapshots))
        scanner.rolling = Mock(has_history=Mock(return_value=True), volume_delta=Mock(return_value=1_000))
        scanner.daily_report = Mock()
        scanner.deduper = Mock(should_send_contract=Mock(return_value=True), should_send_ticker=Mock(return_value=True))
        scanner.discord = Mock(send_group=Mock(return_value=True))

        scanner.run_once()

        self.assertEqual(scanner.daily_report.record.call_count, 3)
        scanner.discord.send_group.assert_called_once()
        sent = scanner.discord.send_group.call_args.args[0]
        self.assertEqual([(alert.snapshot.contract.symbol, alert.estimated_premium) for alert in sent], [("TSLA", 150_001)])


if __name__ == "__main__":
    unittest.main()
