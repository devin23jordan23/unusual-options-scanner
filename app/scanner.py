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
from .rules import evaluate_contract
from .state import AlertDeduper, RollingState, severity_rank

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
        self.rolling = RollingState(os.path.join(settings.data_dir, "option_volume_baseline.json"))
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
        if snapshots:
            self.rolling.save()
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
        for offset in range(0, len(selected), 3):
            group = selected[offset:offset + 3]
            if self.discord.send_group(group):
                for alert in group:
                    self.deduper.mark_ticker(ticker_dedupe_key(alert), now_ts)
                    if alert.alert_type == "contract":
                        self.deduper.mark_contract(alert)
        LOG.info(
            "scan complete option_snapshots=%s qualified=%s selected=%s",
            len(snapshots),
            len(candidates),
            len(selected),
        )


def strongest_distinct_tickers(alerts, limit: int):
    ranked = sorted(alerts, key=alert_rank, reverse=True)
    selected = []
    seen = set()
    for alert in ranked:
        symbol = alert.snapshot.contract.symbol
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
        alert.estimated_premium,
        alert.snapshot.vol_oi or 0,
    )


def ticker_dedupe_key(alert) -> str:
    return f"{alert.snapshot.contract.symbol}:ALL"


def ticker_cooldown(alert, settings: Settings) -> int:
    return settings.symbol_cooldown_seconds
