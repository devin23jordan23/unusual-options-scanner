import json
import os
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime

from .models import Alert, OptionSnapshot, Severity


@dataclass
class LastAlert:
    sent_at: float
    volume: int
    severity: str
    premium_tier: str
    vol_oi_tier: str


class RollingState:
    def __init__(self, path: str | None = None, max_age_seconds: int = 900):
        self.path = path
        self.max_age_seconds = max_age_seconds
        self.snapshots = defaultdict(deque)
        self.persisted: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r") as f:
                self.persisted = json.load(f).get("contracts", {})
        except Exception:
            self.persisted = {}

    def save(self) -> None:
        if not self.path:
            return
        contracts = {}
        for option_symbol, snapshots in self.snapshots.items():
            if not snapshots:
                continue
            latest = snapshots[-1]
            if latest.volume <= 0:
                continue
            contracts[option_symbol] = {
                "volume": latest.volume,
                "timestamp": latest.timestamp.isoformat(),
            }
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"contracts": contracts}, f)

    def record(self, snapshot: OptionSnapshot) -> None:
        q = self.snapshots[snapshot.contract.option_symbol]
        q.append(snapshot)
        cutoff = snapshot.timestamp.timestamp() - self.max_age_seconds
        while q and q[0].timestamp.timestamp() < cutoff:
            q.popleft()

    def has_history(self, snapshot: OptionSnapshot) -> bool:
        if self.snapshots.get(snapshot.contract.option_symbol):
            return True
        return self.persisted_baseline(snapshot) is not None

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
        if baseline is not None:
            return max(snapshot.volume - baseline.volume, 0)
        if len(q) > 1:
            return max(snapshot.volume - q[0].volume, 0)
        persisted = self.persisted_baseline(snapshot)
        if persisted is not None:
            return max(snapshot.volume - persisted[0], 0)
        return 0

    def persisted_baseline(self, snapshot: OptionSnapshot) -> tuple[int, datetime] | None:
        raw = self.persisted.get(snapshot.contract.option_symbol)
        if not raw:
            return None
        try:
            timestamp = datetime.fromisoformat(raw["timestamp"])
            age = snapshot.timestamp.timestamp() - timestamp.timestamp()
            volume = int(raw["volume"])
        except (KeyError, TypeError, ValueError):
            return None
        if timestamp.date() != snapshot.timestamp.date():
            return None
        if age < 0 or age > self.max_age_seconds:
            return None
        if snapshot.volume < volume:
            return None
        return volume, timestamp


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
