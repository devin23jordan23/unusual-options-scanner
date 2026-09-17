import os
import tempfile
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.aggregation import ticker_level_alerts
from app.config import Settings, Thresholds
from app.discord import DiscordNotifier
from app.metrics import estimated_premium, volume_oi_ratio
from app.models import OptionContract, OptionSide, OptionSnapshot, Severity
from app.rules import evaluate_contract
from app.scanner import strongest_distinct_tickers
from app.state import AlertDeduper, RollingState
from app.oauth import callback_code


def snap(symbol="NVDA", strike=195.0, side=OptionSide.CALL, volume=2500, oi=700, mark=2.0, dte=0, ts=None):
    ts = ts or datetime(2026, 9, 11, 10, 7, tzinfo=ZoneInfo("America/New_York"))
    contract = OptionContract(symbol, f"{symbol}260911C00195000", date(2026, 9, 11), strike, side, dte)
    return OptionSnapshot(contract, volume, oi, mark, 193.86, ts)


class ScannerUnitTests(unittest.TestCase):
    def test_schwab_callback_code_extraction(self):
        url = "https://127.0.0.1/?code=sample%40code&session=abc"
        self.assertEqual(callback_code(url), "sample@code")

    def test_schwab_callback_code_missing(self):
        self.assertEqual(callback_code("https://127.0.0.1/"), "")

    def test_volume_oi_calculation(self):
        self.assertEqual(volume_oi_ratio(1000, 500), 2.0)

    def test_zero_oi_handling(self):
        self.assertIsNone(volume_oi_ratio(1000, 0))
        self.assertIsNotNone(evaluate_contract(snap(volume=1500, oi=0), 700, Thresholds(min_score=2)))

    def test_premium_estimate(self):
        self.assertEqual(estimated_premium(snap(mark=1.25), 400), 50_000)

    def test_dte_prioritization(self):
        alert = evaluate_contract(snap(volume=500, oi=100), 360, Thresholds(min_volume=1000, min_volume_0dte=350, min_score=3))
        self.assertIsNotNone(alert)
        self.assertIn("0DTE activity", alert.reasons)

    def test_zero_dte_label_is_not_enough_by_itself(self):
        alert = evaluate_contract(snap(volume=400, oi=500, mark=0.25), 25, Thresholds(min_score=2))
        self.assertIsNone(alert)

    def test_stale_cumulative_volume_is_suppressed(self):
        alert = evaluate_contract(snap(volume=9000, oi=10, mark=4), 0, Thresholds())
        self.assertIsNone(alert)

    def test_long_dte_whale_flow_passes(self):
        alert = evaluate_contract(snap(volume=6000, oi=1000, mark=2.0, dte=45), 6000, Thresholds())
        self.assertIsNotNone(alert)
        self.assertIn("longer-dated high-premium flow", alert.reasons)

    def test_long_dte_noise_is_suppressed(self):
        alert = evaluate_contract(snap(volume=700, oi=500, mark=1.0, dte=45), 0, Thresholds())
        self.assertIsNone(alert)

    def test_contract_threshold_evaluation(self):
        alert = evaluate_contract(snap(volume=6482, oi=903, mark=2.5), 2141, Thresholds())
        self.assertIsNotNone(alert)
        self.assertGreaterEqual(alert.snapshot.vol_oi, 7)

    def test_cooldown_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = AlertDeduper(os.path.join(tmp, "state.json"))
            first = evaluate_contract(snap(volume=2100), 900, Thresholds(min_score=2))
            self.assertTrue(d.should_send_contract(first, 300))
            d.mark_contract(first)
            duplicate = evaluate_contract(snap(volume=2300), 100, Thresholds(min_score=2))
            self.assertFalse(d.should_send_contract(duplicate, 300))

    def test_severity_escalation(self):
        alert = evaluate_contract(snap(volume=10000, oi=500, mark=3), 8000, Thresholds())
        self.assertEqual(alert.severity, Severity.EXTREME)

    def test_rolling_5m_acceleration(self):
        state = RollingState()
        early = snap(volume=1900, ts=datetime(2026, 9, 11, 10, 2, tzinfo=ZoneInfo("America/New_York")))
        late = snap(volume=4800, ts=datetime(2026, 9, 11, 10, 7, tzinfo=ZoneInfo("America/New_York")))
        state.record(early)
        self.assertTrue(state.has_history(late))
        state.record(late)
        self.assertEqual(state.volume_delta(late, 300), 2900)

    def test_first_snapshot_has_no_history(self):
        state = RollingState()
        first = snap()
        self.assertFalse(state.has_history(first))
        state.record(first)
        self.assertTrue(state.has_history(first))

    def test_alert_selection_caps_and_deduplicates_tickers(self):
        nvda = evaluate_contract(snap(symbol="NVDA", volume=7000, oi=500, mark=3), 4000, Thresholds())
        nvda_second = evaluate_contract(snap(symbol="NVDA", strike=200, volume=6000, oi=500, mark=2), 3000, Thresholds())
        tsla = evaluate_contract(snap(symbol="TSLA", volume=5000, oi=500, mark=2), 2500, Thresholds())
        selected = strongest_distinct_tickers([nvda_second, tsla, nvda], 2)
        self.assertEqual(len(selected), 2)
        self.assertEqual({a.snapshot.contract.symbol for a in selected}, {"NVDA", "TSLA"})

    def test_ticker_level_aggregation_and_clustering(self):
        alerts = ticker_level_alerts([snap(strike=190), snap(strike=192.5), snap(strike=195), snap(strike=240)], Settings(cluster_min_contracts=3))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(len(alerts[0].grouped_contracts), 3)
        payload = DiscordNotifier("").payload(alerts[0])
        names = {field["name"] for field in payload["embeds"][0]["fields"]}
        self.assertIn("Strike Range", names)
        self.assertNotIn("Nearby Strikes", names)
        self.assertNotIn("Estimated Activity", names)

    def test_contract_payload_hides_five_minute_volume(self):
        alert = evaluate_contract(snap(volume=6482, oi=903, mark=2.5), 2141, Thresholds())
        payload = DiscordNotifier("").payload(alert)
        self.assertEqual(payload["embeds"][0]["title"], "Unusual CALL activity - NVDA")
        names = {field["name"] for field in payload["embeds"][0]["fields"]}
        self.assertNotIn("New 5m Volume", names)
        self.assertIn("Reason", names)
        self.assertIn("Estimated Activity", names)

    def test_estimated_activity_shows_below_large_threshold(self):
        alert = evaluate_contract(snap(volume=500, oi=100, mark=1), 360, Thresholds(min_score=3))
        payload = DiscordNotifier("").payload(alert)
        activity = next(field for field in payload["embeds"][0]["fields"] if field["name"] == "Estimated Activity")
        self.assertEqual(activity["value"], "$36,000")

    def test_symbol_specific_thresholds(self):
        settings = Settings(symbol_overrides={"SPY": Thresholds(min_volume=5000)})
        self.assertEqual(settings.thresholds_for("SPY").min_volume, 5000)
        self.assertEqual(settings.thresholds_for("NVDA").min_volume, 500)


if __name__ == "__main__":
    unittest.main()
