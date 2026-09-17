import logging
import os
import time

from .aggregation import ticker_level_alerts
from .config import Settings
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
        self.rolling = RollingState()
        self.deduper = AlertDeduper(os.path.join(settings.data_dir, "alert_state.json"))

    def run(self) -> None:
        LOG.info("scanner started mode=%s universe=%s", self.settings.mode, ",".join(self.settings.active_universe))
        cycle = 0
        while True:
            cycle += 1
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
        snapshots = self.data.option_snapshots(self.settings.active_universe)
        abnormal = []
        candidates = []
        for snap in snapshots:
            has_history = self.rolling.has_history(snap)
            self.rolling.record(snap)
            if not has_history:
                continue
            delta = self.rolling.volume_delta(snap, 300)
            alert = evaluate_contract(snap, delta, self.settings.thresholds_for(snap.contract.symbol))
            if not alert:
                continue
            abnormal.append(snap)
            cooldown = self.settings.thresholds_for(snap.contract.symbol).contract_cooldown_seconds
            if self.deduper.should_send_contract(alert, cooldown):
                candidates.append(alert)
        now_ts = time.time()
        for alert in ticker_level_alerts(abnormal, self.settings):
            key = f"{alert.snapshot.contract.symbol}:{alert.snapshot.contract.side.value}:{alert.snapshot.contract.dte}"
            cooldown = self.settings.thresholds_for(alert.snapshot.contract.symbol).ticker_cooldown_seconds
            if self.deduper.should_send_ticker(key, now_ts, cooldown):
                candidates.append(alert)

        eligible = [
            alert for alert in candidates
            if self.deduper.should_send_ticker(
                f"{alert.snapshot.contract.symbol}:ALL",
                now_ts,
                self.settings.symbol_cooldown_seconds,
            )
        ]
        selected = strongest_distinct_tickers(eligible, self.settings.max_alerts_per_cycle)
        for alert in selected:
            if self.discord.send(alert):
                self.deduper.mark_ticker(f"{alert.snapshot.contract.symbol}:ALL", now_ts)
                if alert.alert_type == "contract":
                    self.deduper.mark_contract(alert)
                    continue
                key = f"{alert.snapshot.contract.symbol}:{alert.snapshot.contract.side.value}:{alert.snapshot.contract.dte}"
                self.deduper.mark_ticker(key, now_ts)
        LOG.info(
            "scan complete snapshots=%s qualified=%s selected=%s",
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
