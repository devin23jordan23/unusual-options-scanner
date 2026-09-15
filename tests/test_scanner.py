import os
import tempfile
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.aggregation import ticker_level_alerts
from app.config import Settings, Thresholds
from app.metrics import estimated_premium, volume_oi_ratio
from app.models import OptionContract, OptionSide, OptionSnapshot, Severity
from app.rules import evaluate_contract
from app.state import AlertDeduper, RollingState


def snap(symbol="NVDA", strike=195.0, side=OptionSide.CALL, volume=2500, oi=700, mark=2.0, dte=0, ts=None):
    ts = ts or datetime(2026, 9, 11, 10, 7, tzinfo=ZoneInfo("America/New_York"))
    contract = OptionContract(symbol, f"{symbol}260911C00195000", date(2026, 9, 11), strike, side, dte)
    return OptionSnapshot(contract, volume, oi, mark, 193.86, ts)


class ScannerUnitTests(unittest.TestCase):
    def test_volume_oi_calculation(self):
        self.assertEqual(volume_oi_ratio(1000, 500), 2.0)

    def test_zero_oi_handling(self):
        self.assertIsNone(volume_oi_ratio(1000, 0))
        self.assertIsNotNone(evaluate_contract(snap(volume=1500, oi=0), 700, Thresholds(min_score=2)))

    def test_premium_estimate(self):
        self.assertEqual(estimated_premium(snap(mark=1.25), 400), 50_000)

    def test_dte_prioritization(self):
        alert = evaluate_contract(snap(volume=500, oi=100), 360, Thresholds(min_volume=1000, min_volume_0dte=350, min_score=2))
        self.assertIsNotNone(alert)
        self.assertIn("0DTE activity", alert.reasons)

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
        state.record(late)
        self.assertEqual(state.volume_delta(late, 300), 2900)

    def test_ticker_level_aggregation_and_clustering(self):
        alerts = ticker_level_alerts([snap(strike=190), snap(strike=192.5), snap(strike=195), snap(strike=240)], Settings(cluster_min_contracts=3))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(len(alerts[0].grouped_contracts), 3)

    def test_symbol_specific_thresholds(self):
        settings = Settings(symbol_overrides={"SPY": Thresholds(min_volume=5000)})
        self.assertEqual(settings.thresholds_for("SPY").min_volume, 5000)
        self.assertEqual(settings.thresholds_for("NVDA").min_volume, 500)


if __name__ == "__main__":
    unittest.main()

