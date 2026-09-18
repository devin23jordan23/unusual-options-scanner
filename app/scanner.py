import logging
import os
import time
from datetime import datetime, time as clock_time
from zoneinfo import ZoneInfo

from .config import Settings
from .daily_report import DailyOptionsReport
from .discord import DiscordNotifier
from .market_hours import is_market_open
from .mock import MockData
from .rules import evaluate_contract, evaluate_underlying_volume
from .state import AlertDeduper, RollingState, RollingStockState, severity_rank

LOG = logging.getLogger(__name__)


class Scanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.mode == "mock":
            self.data = MockData(settings)
        else:
            from .auth_server import start_auth_server
            from .schwab import SchwabClient

            self.data = SchwabClient(settings)
            start_auth_server(self.data)
        self.discord = DiscordNotifier(settings.discord_webhook)
        self.rolling = RollingState()
        self.rolling_stocks = RollingStockState()
        self.deduper = AlertDeduper(os.path.join(settings.data_dir, "alert_state.json"))
        self.daily_report = DailyOptionsReport(
            os.path.join(settings.data_dir, "daily_options_report.json"),
            settings.daily_report_top_count,
            clock_time(settings.daily_report_hour, settings.daily_report_minute),
        )

    def run(self) -> None:
        LOG.info("scanner started mode=%s universe=%s", self.settings.mode, ",".join(self.settings.active_universe))
        cycle = 0
        while True:
            cycle += 1
            now = datetime.now(ZoneInfo(self.settings.timezone))
            if self.settings.mode != "mock" and self.settings.daily_report_enabled and self.daily_report.is_due(now):
                if self.discord.send_payload(self.daily_report.payload(now), "daily options flow report"):
                    self.daily_report.mark_sent(now)
            if self.settings.mode != "mock" and not is_market_open(self.settings.timezone):
                LOG.info("market closed; sleeping")
                time.sleep(min(self.settings.poll_seconds, 300))
                continue
            self.run_once()
            if self.settings.mode == "mock" and self.settings.mock_cycles and cycle >= self.settings.mock_cycles:
                LOG.info("mock cycle limit reached")
                return
            time.sleep(1 if self.settings.mode == "mock" else self.settings.poll_seconds)

    def run_once(self) -> None:
        candidates = []
        stock_snapshots = []
        if self.settings.underlying_volume_thresholds.enabled and hasattr(self.data, "stock_snapshots"):
            stock_snapshots = self.data.stock_snapshots(self.settings.active_universe)
            for snap in stock_snapshots:
                has_history = self.rolling_stocks.has_history(snap)
                self.rolling_stocks.record(snap)
                if not has_history:
                    continue
                volume_delta = self.rolling_stocks.volume_delta(snap, 300)
                price_change = self.rolling_stocks.price_change_pct(snap, 300)
                burst_ratio = self.rolling_stocks.burst_ratio(snap, volume_delta, 300)
                alert = evaluate_underlying_volume(
                    snap,
                    volume_delta,
                    price_change,
                    burst_ratio,
                    self.settings.underlying_volume_thresholds,
                )
                if alert:
                    candidates.append(alert)

        snapshots = self.data.option_snapshots(self.settings.active_universe)
        for snap in snapshots:
            has_history = self.rolling.has_history(snap)
            self.rolling.record(snap)
            if not has_history:
                continue
            delta = self.rolling.volume_delta(snap, 300)
            alert = evaluate_contract(snap, delta, self.settings.thresholds_for(snap.contract.symbol))
            if not alert:
                continue
            self.daily_report.record(alert)
            cooldown = self.settings.thresholds_for(snap.contract.symbol).contract_cooldown_seconds
            if self.deduper.should_send_contract(alert, cooldown):
                candidates.append(alert)
        now_ts = time.time()
        eligible = [
            alert for alert in candidates
            if self.deduper.should_send_ticker(
                ticker_dedupe_key(alert),
                now_ts,
                ticker_cooldown(alert, self.settings),
            )
        ]
        selected = strongest_distinct_tickers(eligible, self.settings.max_alerts_per_cycle)
        for alert in selected:
            if self.discord.send(alert):
                self.deduper.mark_ticker(ticker_dedupe_key(alert), now_ts)
                if alert.alert_type == "contract":
                    self.deduper.mark_contract(alert)
        LOG.info(
            "scan complete stock_snapshots=%s option_snapshots=%s qualified=%s selected=%s",
            len(stock_snapshots),
            len(snapshots),
            len(candidates),
            len(selected),
        )


def strongest_distinct_tickers(alerts, limit: int):
    ranked = sorted(alerts, key=alert_rank, reverse=True)
    selected = []
    seen = set()
    for alert in ranked:
        symbol = alert_symbol(alert)
        if symbol in seen:
            continue
        seen.add(symbol)
        selected.append(alert)
        if len(selected) >= max(limit, 0):
            break
    return selected


def alert_rank(alert):
    return (
        severity_rank(alert.severity.value),
        1 if alert.alert_type == "ticker" else 0,
        alert.volume_delta_5m,
        getattr(alert, "estimated_premium", 0),
        getattr(alert, "dollar_volume_5m", 0),
        getattr(alert.snapshot, "vol_oi", None) or 0,
    )


def alert_symbol(alert) -> str:
    if alert.alert_type == "underlying":
        return alert.snapshot.symbol
    return alert.snapshot.contract.symbol


def ticker_dedupe_key(alert) -> str:
    suffix = "UNDERLYING" if alert.alert_type == "underlying" else "ALL"
    return f"{alert_symbol(alert)}:{suffix}"


def ticker_cooldown(alert, settings: Settings) -> int:
    if alert.alert_type == "underlying":
        return settings.underlying_volume_thresholds.cooldown_seconds
    return settings.symbol_cooldown_seconds
