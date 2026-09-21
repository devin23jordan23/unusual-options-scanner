import logging
import os
import time
from datetime import datetime, time as clock_time
from zoneinfo import ZoneInfo

from .config import Settings
from .daily_report import DailyOptionsReport
from .discord import DiscordNotifier
from .lotto import context_symbols, evaluate_lotto
from .market_hours import is_market_open
from .mock import MockData
from .rules import evaluate_contract
from .state import AlertDeduper, MarketRollingState, RollingState, severity_rank

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
        self.market_rolling = MarketRollingState()
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
        market_context = self.data.market_snapshots(context_symbols(self.settings.active_universe))
        self.market_rolling.record_many(market_context)
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
            lotto = evaluate_lotto(
                alert,
                market_context,
                self.market_rolling.volume_delta(snap.contract.symbol, 300),
                self.settings.lotto,
            )
            candidate = lotto or alert
            cooldown = (
                self.settings.lotto.alert_cooldown_seconds
                if candidate.alert_type == "lotto"
                else self.settings.thresholds_for(snap.contract.symbol).contract_cooldown_seconds
            )
            if self.deduper.should_send_contract(candidate, cooldown):
                candidates.append(candidate)
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
                if alert.alert_type in {"contract", "lotto"}:
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
        2 if alert.alert_type == "lotto" else 1 if alert.alert_type == "ticker" else 0,
        alert.volume_delta_5m,
        alert.estimated_premium,
        alert.snapshot.vol_oi or 0,
    )


def ticker_dedupe_key(alert) -> str:
    suffix = "LOTTO" if alert.alert_type == "lotto" else "ALL"
    return f"{alert.snapshot.contract.symbol}:{suffix}"


def ticker_cooldown(alert, settings: Settings) -> int:
    if alert.alert_type == "lotto":
        return settings.lotto.alert_cooldown_seconds
    return settings.symbol_cooldown_seconds
