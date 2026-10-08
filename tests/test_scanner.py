import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from app.aggregation import ticker_level_alerts
from app.config import Settings, Thresholds, load_settings
from app.discord import DiscordNotifier
from app.daily_report import DailyOptionsReport
from app.metrics import estimated_premium, volume_oi_ratio
from app.models import OptionContract, OptionSide, OptionSnapshot, Severity
from app.rules import evaluate_contract
from app.scanner import Scanner, select_alerts, strongest_distinct_tickers
from app.schwab import SchwabClient
from app.state import AlertDeduper, RollingState
from app.oauth import callback_code
from app.pricing import spxw_price_context


def snap(symbol="NVDA", strike=195.0, side=OptionSide.CALL, volume=2500, oi=700, mark=2.0, dte=0, ts=None):
    ts = ts or datetime(2026, 9, 11, 10, 7, tzinfo=ZoneInfo("America/New_York"))
    contract = OptionContract(symbol, f"{symbol}260911C00195000", date(2026, 9, 11), strike, side, dte)
    return OptionSnapshot(contract, volume, oi, mark, 193.86, ts)


class ScannerUnitTests(unittest.TestCase):
    def test_new_symbols_survive_existing_universe_override(self):
        with patch.dict(os.environ, {"UOA_CORE_UNIVERSE": "SPY,AMD", "UOA_IN_PLAY": "NVDA"}):
            settings = load_settings()
        self.assertEqual(set(settings.active_universe), {"SPY", "AMD", "NVDA", "CSCO", "HPE", "SPX"})
        self.assertEqual(settings.thresholds_for("SPX"), settings.thresholds_for("SPY"))

    def test_spx_chain_includes_weekly_but_excludes_standard_index_contracts(self):
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        raw = lambda symbol: {"symbol": symbol, "strikePrice": 6500, "totalVolume": 100,
                              "openInterest": 10, "mark": 40, "bid": 39, "ask": 41,
                              "isIndexOption": True}
        chain = {"underlyingPrice": 6500, "callExpDateMap": {
            f"{today}:0": {"6500.0": [raw("SPXW  261008C06500000"), raw("SPX   261008C06500000")]}
        }}
        client = SchwabClient.__new__(SchwabClient)
        client.settings = Settings()
        client.get = Mock(return_value=chain)
        snapshots = client.option_snapshots_for_symbol("SPX")
        self.assertEqual({snapshot.contract.display for snapshot in snapshots}, {"SPXW 6500C"})
        self.assertTrue(all(snapshot.contract.symbol == "SPX" for snapshot in snapshots))
        self.assertTrue(all(snapshot.underlying_price == 6500 for snapshot in snapshots))
        self.assertEqual(client.get.call_count, 1)
        self.assertEqual(client.get.call_args.args[0], "/chains")
        self.assertEqual(client.get.call_args.args[1]["symbol"], "$SPX")
        alert = evaluate_contract(snapshots[0], 100, Thresholds())
        self.assertIsNotNone(alert)
        formatted = DiscordNotifier("").group_payload([alert])["embeds"][0]["description"]
        self.assertIn("SPXW 6500C", formatted)
        self.assertIn("Index $6500.00", formatted)

    def test_spx_chain_uses_index_quote_when_chain_omits_underlying_price(self):
        client = SchwabClient.__new__(SchwabClient)
        client.settings = Settings()
        client.get = Mock(side_effect=[{"callExpDateMap": {}, "putExpDateMap": {}},
                                       {"$SPX": {"quote": {"lastPrice": 6500}}}])
        self.assertEqual(client.option_snapshots_for_symbol("SPX"), [])
        self.assertEqual(client.get.call_args_list[1].args, ("/quotes", {"symbols": "$SPX"}))
    def test_spxw_survives_universe_override_and_uses_index_flow_thresholds(self):
        with patch.dict(os.environ, {"UOA_CORE_UNIVERSE": "SPY"}):
            settings = load_settings()
        self.assertIn("SPX", settings.active_universe)
        self.assertEqual(settings.thresholds_for("SPX"), settings.thresholds_for("SPY"))

    def test_spx_chain_accepts_spxw_only_and_retains_quote_times(self):
        now = datetime.now(ZoneInfo("America/New_York"))
        expiry = now.date().isoformat()
        def option(symbol):
            return {"symbol": symbol, "strikePrice": 7800, "bid": 1.10, "ask": 1.30,
                    "mark": 1.20, "last": 1.25, "totalVolume": 15_000,
                    "openInterest": 300, "quoteTimeInLong": int((now-timedelta(seconds=10)).timestamp()*1000),
                    "tradeTimeInLong": int((now-timedelta(seconds=45)).timestamp()*1000)}
        chain = {"underlyingPrice": 7800, "callExpDateMap": {f"{expiry}:0": {
            "7800.0": [option("SPXW  261008C07800000"), option("SPX   261008C07800000")]
        }}}
        client = SchwabClient.__new__(SchwabClient)
        client.settings = Settings()
        client.get = Mock(return_value=chain)

        snapshots = client.option_snapshots_for_symbol("SPX")

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].contract.display, "SPXW 7800C")
        self.assertEqual(client.get.call_args.args[1]["symbol"], "$SPX")
        self.assertAlmostEqual(snapshots[0].last_trade_price, 1.25)
        self.assertIn("Approx. $1.20", spxw_price_context(snapshots[0]))
        self.assertIn("recent print $1.25", spxw_price_context(snapshots[0]))
        alert = evaluate_contract(snapshots[0], 12_000, load_settings().thresholds_for("SPX"))
        self.assertIsNotNone(alert)
        description = DiscordNotifier("").group_payload([alert])["embeds"][0]["description"]
        self.assertIn("SPXW 7800C", description)
        self.assertIn("bid $1.10 / ask $1.30", description)
        self.assertIn("SPXW Price Context", {f["name"] for f in DiscordNotifier("").payload(alert)["embeds"][0]["fields"]})

    def test_spxw_price_context_falls_back_to_fresh_midpoint_then_unavailable(self):
        now = datetime(2026, 10, 8, 10, 30, tzinfo=ZoneInfo("America/New_York"))
        contract = OptionContract("SPX", "SPXW  261008P07800000", now.date(), 7800, OptionSide.PUT, 0)
        fresh = OptionSnapshot(contract, 1000, 100, 1.20, 7800, now, bid=1.10, ask=1.30,
                               quote_time=now-timedelta(seconds=5))
        stale = OptionSnapshot(contract, 1000, 100, 1.20, 7800, now, bid=1.10, ask=1.30,
                               quote_time=now-timedelta(minutes=6), last_trade_price=1.25,
                               last_trade_time=now-timedelta(minutes=6))
        recent_print = OptionSnapshot(contract, 1000, 100, 1.20, 7800, now, bid=1.10, ask=1.30,
                                      quote_time=now-timedelta(minutes=6), last_trade_price=1.25,
                                      last_trade_time=now-timedelta(seconds=50))
        self.assertIn("Approx. $1.20 (quote midpoint", spxw_price_context(fresh))
        self.assertIn("Approx. $1.25 (recent print", spxw_price_context(recent_print))
        self.assertEqual(spxw_price_context(stale), "Approx. price unavailable")

    def test_spx_delayed_chain_does_not_emit_spxw_price(self):
        client = SchwabClient.__new__(SchwabClient)
        client.settings = Settings()
        client.get = Mock(return_value={"isDelayed": True, "underlyingPrice": 7800})
        self.assertEqual(client.option_snapshots_for_symbol("SPX"), [])

    def test_daily_report_separates_spxw_flow_and_preserves_price_context(self):
        now = datetime(2026, 10, 8, 10, 30, tzinfo=ZoneInfo("America/New_York"))
        contract = OptionContract("SPX", "SPXW  261008C07800000", now.date(), 7800, OptionSide.CALL, 0)
        snapshot = OptionSnapshot(contract, 15_000, 300, 1.20, 7800, now,
                                  bid=1.10, ask=1.30, quote_time=now-timedelta(seconds=5))
        alert = evaluate_contract(snapshot, 12_000, load_settings().thresholds_for("SPX"))
        self.assertIsNotNone(alert)
        with tempfile.TemporaryDirectory() as tmp:
            report = DailyOptionsReport(os.path.join(tmp, "report.json"))
            report.record(alert)
            payload = report.payload(now)
        fields = {field["name"]: field["value"] for field in payload["embeds"][0]["fields"]}
        self.assertIn("SPXW Call Flow (separate)", fields)
        self.assertIn("Approx. $1.20", fields["SPXW Call Flow (separate)"])
        self.assertNotIn("SPXW", fields["Major Call Volume"])

    def test_daily_report_keeps_major_flow_and_excludes_watch(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = DailyOptionsReport(os.path.join(tmp, "report.json"), top_count=5)
            major = evaluate_contract(snap(symbol="AMD", volume=6482, oi=903, mark=2.5), 2141, Thresholds())
            watch = evaluate_contract(snap(symbol="MU", volume=500, oi=100, mark=3), 125, Thresholds(min_score=3))
            self.assertIsNotNone(major)
            self.assertEqual(watch.severity, Severity.WATCH)
            report.record(major)
            report.record(watch)
            self.assertEqual(len(report.contracts), 1)

    def test_daily_report_due_and_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = DailyOptionsReport(os.path.join(tmp, "report.json"), top_count=5)
            alert = evaluate_contract(snap(symbol="AMD", volume=6482, oi=903, mark=2.5), 2141, Thresholds())
            report.record(alert)
            now = datetime(2026, 9, 11, 16, 5, tzinfo=ZoneInfo("America/New_York"))
            self.assertTrue(report.is_due(now))
            payload = report.payload(now)
            self.assertIn("AMD", payload["embeds"][0]["fields"][0]["value"])
            report.mark_sent(now)
            self.assertFalse(report.is_due(now))

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

    def test_small_dollar_alert_is_suppressed_even_with_extreme_volume_oi(self):
        contract = snap(volume=5000, oi=1, mark=0.50)
        self.assertIsNone(evaluate_contract(contract, 599, Thresholds()))
        alert = evaluate_contract(contract, 600, Thresholds())
        self.assertIsNotNone(alert)
        self.assertEqual(alert.estimated_premium, 30_000)

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

    def test_fresh_long_dated_whale_bypasses_contract_count_and_score(self):
        thresholds = Thresholds(
            min_5m_volume_increase=5000,
            min_score=5,
            long_dte_min_premium=3_000_000,
            premium_whale=3_000_000,
            premium_extreme_whale=5_000_000,
        )
        contract = snap(symbol="SPY", volume=50, oi=1000, mark=200, dte=45)
        alert = evaluate_contract(contract, 50, thresholds)
        self.assertIsNotNone(alert)
        self.assertTrue(alert.long_dated_whale)
        self.assertEqual(alert.estimated_premium, 1_000_000)
        self.assertEqual(alert.severity, Severity.HIGH)
        self.assertIsNone(evaluate_contract(contract, 0, thresholds))
        self.assertIsNone(evaluate_contract(snap(volume=50, mark=200, dte=20), 50, thresholds))
        self.assertIsNone(evaluate_contract(snap(volume=50, mark=200, dte=61), 50, thresholds))
        self.assertIsNone(evaluate_contract(snap(volume=50, mark=199.99, dte=45), 50, thresholds))

    def test_long_dated_whale_can_pass_far_strike_filter(self):
        client = SchwabClient.__new__(SchwabClient)
        client.settings = Settings(symbol_overrides={"SPY": Thresholds(long_dte_min_premium=3_000_000)})
        contract = snap(symbol="SPY", strike=350, volume=50, mark=200, dte=45)
        self.assertEqual(client._filter_near_spot([contract], 193.86), [contract])

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
            duplicate = evaluate_contract(snap(volume=2300), 150, Thresholds(min_score=2))
            self.assertFalse(d.should_send_contract(duplicate, 300))

    def test_severity_escalation(self):
        alert = evaluate_contract(snap(volume=10000, oi=500, mark=3), 8000, Thresholds())
        self.assertEqual(alert.severity, Severity.EXTREME)
        self.assertEqual(DiscordNotifier("").payload(alert)["embeds"][0]["color"], 0x3498DB)

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

    def test_rolling_state_survives_same_day_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baseline.json")
            early = snap(volume=1900, ts=datetime(2026, 9, 11, 10, 2, tzinfo=ZoneInfo("America/New_York")))
            first = RollingState(path)
            first.record(early)
            first.save()

            late = snap(volume=2400, ts=datetime(2026, 9, 11, 10, 4, tzinfo=ZoneInfo("America/New_York")))
            restarted = RollingState(path)
            self.assertTrue(restarted.has_history(late))
            restarted.record(late)
            self.assertEqual(restarted.volume_delta(late, 300), 500)

    def test_rolling_state_ignores_previous_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baseline.json")
            prior = snap(volume=5000, ts=datetime(2026, 9, 10, 15, 59, tzinfo=ZoneInfo("America/New_York")))
            first = RollingState(path)
            first.record(prior)
            first.save()

            today = snap(volume=100, ts=datetime(2026, 9, 11, 9, 31, tzinfo=ZoneInfo("America/New_York")))
            restarted = RollingState(path)
            self.assertFalse(restarted.has_history(today))

    def test_alert_selection_caps_and_deduplicates_tickers(self):
        nvda = evaluate_contract(snap(symbol="NVDA", volume=7000, oi=500, mark=3), 4000, Thresholds())
        nvda_second = evaluate_contract(snap(symbol="NVDA", strike=200, volume=6000, oi=500, mark=2), 3000, Thresholds())
        tsla = evaluate_contract(snap(symbol="TSLA", volume=5000, oi=500, mark=2), 2500, Thresholds())
        selected = strongest_distinct_tickers([nvda_second, tsla, nvda], 2)
        self.assertEqual(len(selected), 2)
        self.assertEqual({a.snapshot.contract.symbol for a in selected}, {"NVDA", "TSLA"})

    def test_long_dated_whales_take_priority_beyond_regular_limit(self):
        regular = [evaluate_contract(snap(symbol=symbol, volume=8000, oi=500, mark=3), 5000, Thresholds())
                   for symbol in ("AMD", "TSLA", "META")]
        whales = [evaluate_contract(snap(symbol=symbol, volume=50, oi=1000, mark=200, dte=45), 50, Thresholds())
                  for symbol in ("NVDA", "SPY", "QQQ", "MSFT")]
        selected = select_alerts(regular + whales, 3)
        self.assertEqual({alert.snapshot.contract.symbol for alert in selected}, {"NVDA", "SPY", "QQQ", "MSFT"})
        self.assertTrue(all(alert.long_dated_whale for alert in selected))
        self.assertEqual(strongest_distinct_tickers(regular, 0), [])

    def test_distinct_long_dated_contracts_on_same_ticker_are_both_sent(self):
        first = evaluate_contract(snap(symbol="NVDA", strike=195, volume=50, mark=200, dte=45), 50, Thresholds())
        second = evaluate_contract(snap(symbol="NVDA", strike=200, volume=60, mark=200, dte=45), 60, Thresholds())
        self.assertEqual(select_alerts([first, second], 1), [second, first])

    def test_scanner_sends_whales_despite_ticker_cooldown_and_regular_cap(self):
        scanner = Scanner.__new__(Scanner)
        scanner.settings = Settings(core_universe={"NVDA"}, max_alerts_per_cycle=1)
        contracts = [snap(symbol=symbol, volume=50, oi=1000, mark=200, dte=45)
                     for symbol in ("NVDA", "SPY", "QQQ", "MSFT")]
        scanner.data = Mock(option_snapshots=Mock(return_value=contracts))
        scanner.rolling = Mock(has_history=Mock(return_value=True), volume_delta=Mock(return_value=50))
        scanner.daily_report = Mock()
        scanner.deduper = Mock(should_send_contract=Mock(return_value=True), should_send_ticker=Mock(return_value=False))
        scanner.discord = Mock(send_group=Mock(return_value=True))
        scanner.run_once()
        self.assertEqual(scanner.discord.send_group.call_count, 2)
        self.assertEqual([len(call.args[0]) for call in scanner.discord.send_group.call_args_list], [3, 1])
        scanner.deduper.should_send_ticker.assert_not_called()
        self.assertEqual(scanner.deduper.mark_contract.call_count, 4)

    def test_long_dated_whale_repeats_after_cooldown_or_new_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            deduper = AlertDeduper(os.path.join(tmp, "alerts.json"))
            first = evaluate_contract(snap(volume=50, oi=1000, mark=200, dte=45), 50, Thresholds())
            deduper.mark_contract(first)
            before_cooldown = evaluate_contract(snap(volume=60, oi=1000, mark=200, dte=45,
                                                      ts=datetime(2026, 9, 11, 10, 10, tzinfo=ZoneInfo("America/New_York"))), 50, Thresholds())
            same_day = evaluate_contract(snap(volume=100, oi=1000, mark=200, dte=45,
                                               ts=datetime(2026, 9, 11, 10, 13, tzinfo=ZoneInfo("America/New_York"))), 50, Thresholds())
            next_day = evaluate_contract(snap(volume=50, oi=1000, mark=200, dte=45,
                                              ts=datetime(2026, 9, 12, 10, 7, tzinfo=ZoneInfo("America/New_York"))), 50, Thresholds())
            self.assertFalse(deduper.should_send_contract(before_cooldown, 300))
            self.assertTrue(deduper.should_send_contract(same_day, 300))
            self.assertTrue(deduper.should_send_contract(next_day, 300))

    def test_daily_report_highlights_long_dated_whales(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = DailyOptionsReport(os.path.join(tmp, "report.json"), top_count=5)
            whale = evaluate_contract(snap(symbol="NVDA", volume=50, oi=1000, mark=200, dte=45), 50, Thresholds())
            report.record(whale)
            payload = report.payload(snap().timestamp)
            field = next(item for item in payload["embeds"][0]["fields"] if item["name"] == "Long-Dated $1M+ Activity")
            self.assertIn("NVDA", field["value"])
            self.assertIn("45DTE", field["value"])

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
        self.assertNotIn("Reason", names)
        self.assertIn("Estimated Activity", names)

    def test_estimated_activity_shows_below_large_threshold(self):
        alert = evaluate_contract(snap(volume=500, oi=100, mark=1), 360, Thresholds(min_score=3))
        payload = DiscordNotifier("").payload(alert)
        activity = next(field for field in payload["embeds"][0]["fields"] if field["name"] == "Estimated Activity")
        self.assertEqual(activity["value"], "$36,000")

    def test_compact_group_preserves_alert_details(self):
        extreme = evaluate_contract(snap(symbol="NVDA", volume=10000, oi=500, mark=3), 8000, Thresholds())
        put = evaluate_contract(snap(symbol="AMD", side=OptionSide.PUT, volume=6482, oi=903, mark=2.5), 2141, Thresholds())
        normal = evaluate_contract(snap(symbol="MU", volume=500, oi=100, mark=1), 360, Thresholds(min_score=3))
        alerts = [extreme, put, normal]
        notifier = DiscordNotifier("https://example.invalid/webhook")
        payload = notifier.group_payload(alerts)
        embed = payload["embeds"][0]
        self.assertEqual(len(payload["embeds"]), 1)
        self.assertIn("NVDA, AMD, MU", embed["title"])
        self.assertIn("🔥", embed["description"])
        self.assertIn("🔴 AMD PUT", embed["description"])
        self.assertIn("Est. $2,400,000", embed["description"])
        self.assertIn("Vol 10,000 / OI 500 · 20.00x · Stock $193.86", embed["description"])
        self.assertEqual(embed["color"], 0x3498DB)
        with patch.object(notifier, "send_payload", return_value=True) as send:
            self.assertTrue(notifier.send_group(alerts))
            send.assert_called_once_with(payload, "options alerts: NVDA, AMD, MU")

    def test_symbol_specific_thresholds(self):
        settings = Settings(symbol_overrides={"SPY": Thresholds(min_volume=5000)})
        self.assertEqual(settings.thresholds_for("SPY").min_volume, 5000)
        self.assertEqual(settings.thresholds_for("NVDA").min_volume, 500)


if __name__ == "__main__":
    unittest.main()
