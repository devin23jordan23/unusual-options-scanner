import json
import os
from collections import defaultdict, deque
from dataclasses import asdict, dataclass

from .models import Alert, OptionSnapshot, Severity


@dataclass
class LastAlert:
    sent_at: float
    volume: int
    severity: str
    premium_tier: str
    vol_oi_tier: str


class RollingState:
    def __init__(self, max_age_seconds: int = 900):
        self.max_age_seconds = max_age_seconds
        self.snapshots = defaultdict(deque)

    def record(self, snapshot: OptionSnapshot) -> None:
        q = self.snapshots[snapshot.contract.option_symbol]
        q.append(snapshot)
        cutoff = snapshot.timestamp.timestamp() - self.max_age_seconds
        while q and q[0].timestamp.timestamp() < cutoff:
            q.popleft()

    def has_history(self, snapshot: OptionSnapshot) -> bool:
        return bool(self.snapshots.get(snapshot.contract.option_symbol))

    def volume_delta(self, snapshot: OptionSnapshot, seconds: int = 300) -> int:
        q = self.snapshots.get(snapshot.contract.option_symbol)
        if not q:
            return 0
        cutoff = snapshot.timestamp.timestamp() - seconds
        baseline = None
        for item in q:
            if item.timestamp.timestamp() <= cutoff:
                baseline = item
            else:
                break
        baseline = baseline or q[0]
        return max(snapshot.volume - baseline.volume, 0)


class AlertDeduper:
    def __init__(self, path: str):
        self.path = path
        self.contracts: dict[str, LastAlert] = {}
        self.tickers: dict[str, float] = {}
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r") as f:
                raw = json.load(f)
            self.contracts = {k: LastAlert(**v) for k, v in raw.get("contracts", {}).items()}
            self.tickers = {k: float(v) for k, v in raw.get("tickers", {}).items()}
        except Exception:
            self.contracts = {}
            self.tickers = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"contracts": {k: asdict(v) for k, v in self.contracts.items()}, "tickers": self.tickers}, f, indent=2)

    def should_send_contract(self, alert: Alert, cooldown_seconds: int) -> bool:
        last = self.contracts.get(alert.snapshot.contract.option_symbol)
        if not last:
            return True
        now = alert.snapshot.timestamp.timestamp()
        if severity_rank(alert.severity.value) > severity_rank(last.severity):
            return True
        if alert.snapshot.volume >= max(last.volume * 1.5, last.volume + 1000):
            return True
        if alert.premium_tier() != last.premium_tier and alert.estimated_premium > premium_floor(last.premium_tier):
            return True
        return now - last.sent_at >= cooldown_seconds and alert.volume_delta_5m >= 1000

    def mark_contract(self, alert: Alert) -> None:
        self.contracts[alert.snapshot.contract.option_symbol] = LastAlert(
            alert.snapshot.timestamp.timestamp(),
            alert.snapshot.volume,
            alert.severity.value,
            alert.premium_tier(),
            alert.vol_oi_tier(),
        )
        self.save()

    def should_send_ticker(self, key: str, now_ts: float, cooldown_seconds: int) -> bool:
        last = self.tickers.get(key)
        return last is None or now_ts - last >= cooldown_seconds

    def mark_ticker(self, key: str, now_ts: float) -> None:
        self.tickers[key] = now_ts
        self.save()


def severity_rank(severity: str) -> int:
    return {Severity.WATCH.value: 1, Severity.UNUSUAL.value: 2, Severity.HIGH.value: 3, Severity.EXTREME.value: 4}.get(severity, 0)


def premium_floor(tier: str) -> float:
    return {"large": 100_000, "major": 500_000, "whale": 1_000_000, "extreme": 2_000_000}.get(tier, 0)
