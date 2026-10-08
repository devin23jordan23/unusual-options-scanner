import json
import os
from datetime import datetime, time

from .models import Alert, OptionSide, Severity
from .pricing import spxw_price_context


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
            "long_dated_whale": alert.long_dated_whale,
            "instrument_group": "SPXW" if snap.contract.symbol == "SPX" else "OTHER",
            "price_context": spxw_price_context(snap) if snap.contract.symbol == "SPX" else None,
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
        others = [item for item in self.contracts.values() if item.get("instrument_group") != "SPXW"]
        spxw = [item for item in self.contracts.values() if item.get("instrument_group") == "SPXW"]
        calls = self.top(OptionSide.CALL.value, "OTHER")
        puts = self.top(OptionSide.PUT.value, "OTHER")
        call_total = sum(item["estimated_activity"] for item in others if item["side"] == OptionSide.CALL.value)
        put_total = sum(item["estimated_activity"] for item in others if item["side"] == OptionSide.PUT.value)
        whales = sorted((item for item in others if item.get("long_dated_whale")),
                        key=lambda item: item["estimated_activity"], reverse=True)[:self.top_count]
        fields = [
            {"name": "Major Call Volume", "value": report_lines(calls), "inline": False},
            {"name": "Major Put Volume", "value": report_lines(puts), "inline": False},
        ]
        if whales:
            fields.append({"name": "Long-Dated $1M+ Activity", "value": report_lines(whales), "inline": False})
        fields.append({"name": "Session Summary (excluding SPXW)" if spxw else "Session Summary", "value":
             f"Calls: {sum(x['side'] == OptionSide.CALL.value for x in others)} contracts / {money(call_total)} fresh est.\n"
             f"Puts: {sum(x['side'] == OptionSide.PUT.value for x in others)} contracts / {money(put_total)} fresh est.",
             "inline": False})
        if spxw:
            for side in (OptionSide.CALL.value, OptionSide.PUT.value):
                items = self.top(side, "SPXW")[:3]
                if items:
                    fields.append({"name": f"SPXW {side.title()} Flow (separate)",
                                   "value": report_lines(items), "inline": False})
        return {
            "username": "Unusual Options Scanner",
            "embeds": [{
                "title": f"Daily Options Flow Report - {now.strftime('%b %d, %Y')}",
                "description": "Strongest UNUSUAL, HIGH, and EXTREME options signals observed today.",
                "color": 0x3498DB,
                "fields": fields,
                "footer": {"text": "Scanner-qualified flow only. Estimated activity is not confirmed order-side data."},
            }],
        }

    def top(self, side: str, group: str | None = None) -> list[dict]:
        items = [entry for entry in self.contracts.values() if entry["side"] == side
                 and (group is None or (entry.get("instrument_group") or "OTHER") == group)]
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
        line = f"**{item['display']}** | {item['dte']}DTE | Vol/OI {ratio} | {money(item['estimated_activity'])} | {item['severity']}"
        if item.get("instrument_group") == "SPXW" and item.get("price_context"):
            line += f"\n{item['price_context']}"
        lines.append(line)
    return "\n".join(lines)


def money(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"
