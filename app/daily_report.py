import json
import os
from datetime import datetime, time

from .models import Alert, OptionSide, Severity


class DailyOptionsReport:
    def __init__(self, path: str, top_count: int = 5, report_time: time = time(16, 5)):
        self.path = path
        self.top_count = top_count
        self.report_time = report_time
        self.trade_date = ""
        self.sent_date = ""
        self.contracts: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r") as f:
                raw = json.load(f)
            self.trade_date = raw.get("trade_date", "")
            self.sent_date = raw.get("sent_date", "")
            self.contracts = raw.get("contracts", {})
        except Exception:
            self.trade_date = ""
            self.sent_date = ""
            self.contracts = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({
                "trade_date": self.trade_date,
                "sent_date": self.sent_date,
                "contracts": self.contracts,
            }, f, indent=2)

    def record(self, alert: Alert) -> None:
        if alert.alert_type != "contract" or alert.severity == Severity.WATCH:
            return
        snap = alert.snapshot
        trade_date = snap.timestamp.date().isoformat()
        if self.trade_date != trade_date:
            self.trade_date = trade_date
            self.contracts = {}
        key = snap.contract.option_symbol
        entry = {
            "symbol": snap.contract.symbol,
            "display": snap.contract.display,
            "side": snap.contract.side.value,
            "dte": snap.contract.dte,
            "volume": snap.volume,
            "open_interest": snap.open_interest,
            "vol_oi": snap.vol_oi,
            "estimated_activity": alert.estimated_premium,
            "severity": alert.severity.value,
        }
        previous = self.contracts.get(key)
        if previous and report_rank(previous) >= report_rank(entry):
            return
        self.contracts[key] = entry
        self.save()

    def is_due(self, now: datetime) -> bool:
        today = now.date().isoformat()
        return (
            now.weekday() < 5
            and now.time() >= self.report_time
            and self.trade_date == today
            and self.sent_date != today
            and bool(self.contracts)
        )

    def mark_sent(self, now: datetime) -> None:
        self.sent_date = now.date().isoformat()
        self.save()

    def payload(self, now: datetime) -> dict:
        calls = self.top(OptionSide.CALL.value)
        puts = self.top(OptionSide.PUT.value)
        call_total = sum(item["estimated_activity"] for item in self.contracts.values() if item["side"] == OptionSide.CALL.value)
        put_total = sum(item["estimated_activity"] for item in self.contracts.values() if item["side"] == OptionSide.PUT.value)
        return {
            "username": "Unusual Options Scanner",
            "embeds": [{
                "title": f"Daily Options Flow Report - {now.strftime('%b %d, %Y')}",
                "description": "Strongest UNUSUAL, HIGH, and EXTREME options signals observed today.",
                "color": 0x3498DB,
                "fields": [
                    {"name": "Major Call Volume", "value": report_lines(calls), "inline": False},
                    {"name": "Major Put Volume", "value": report_lines(puts), "inline": False},
                    {"name": "Session Summary", "value": f"Calls: {len([x for x in self.contracts.values() if x['side'] == OptionSide.CALL.value])} contracts / {money(call_total)} fresh est.\nPuts: {len([x for x in self.contracts.values() if x['side'] == OptionSide.PUT.value])} contracts / {money(put_total)} fresh est.", "inline": False},
                ],
                "footer": {"text": "Scanner-qualified flow only. Estimated activity is not confirmed order-side data."},
            }],
        }

    def top(self, side: str) -> list[dict]:
        items = [entry for entry in self.contracts.values() if entry["side"] == side]
        return sorted(items, key=report_rank, reverse=True)[:self.top_count]


def report_rank(entry: dict) -> tuple:
    severity = {"WATCH": 1, "UNUSUAL": 2, "HIGH": 3, "EXTREME": 4}.get(entry.get("severity", ""), 0)
    return severity, entry.get("estimated_activity", 0), entry.get("volume", 0)


def report_lines(items: list[dict]) -> str:
    if not items:
        return "No major signals recorded."
    lines = []
    for item in items:
        ratio = "n/a" if item.get("vol_oi") is None else f"{item['vol_oi']:.1f}x"
        lines.append(
            f"**{item['display']}** | {item['dte']}DTE | Vol/OI {ratio} | {money(item['estimated_activity'])} | {item['severity']}"
        )
    return "\n".join(lines)


def money(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"
