import logging
import time

from .models import Alert, OptionSide, StockAlert

LOG = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, alert: Alert | StockAlert) -> bool:
        if not self.webhook_url:
            LOG.info("discord webhook not configured; alert skipped: %s", alert.title)
            return False
        return self.send_payload(self.payload(alert), alert.title)

    def send_payload(self, payload: dict, label: str) -> bool:
        if not self.webhook_url:
            LOG.info("discord webhook not configured; payload skipped: %s", label)
            return False
        for attempt in range(3):
            try:
                import requests

                resp = requests.post(self.webhook_url, json=payload, timeout=10)
                resp.raise_for_status()
                LOG.info("Discord payload sent: %s", label)
                return True
            except Exception as exc:
                LOG.warning("Discord send failed attempt %s: %s", attempt + 1, exc)
                time.sleep(2 ** attempt)
        return False

    def payload(self, alert: Alert | StockAlert) -> dict:
        if isinstance(alert, StockAlert):
            return self.stock_payload(alert)
        snap = alert.snapshot
        color = 0x2ECC71 if snap.contract.side == OptionSide.CALL else 0xE74C3C
        if alert.severity.value == "EXTREME":
            color = 0xF1C40F
        if alert.alert_type == "ticker" and alert.grouped_contracts:
            strikes = sorted(s.contract.strike for s in alert.grouped_contracts)
            side_suffix = "C" if snap.contract.side == OptionSide.CALL else "P"
            strike_range = f"{format_strike(strikes[0])}{side_suffix}-{format_strike(strikes[-1])}{side_suffix}"
            total_volume = sum(s.volume for s in alert.grouped_contracts)
            total_oi = sum(s.open_interest for s in alert.grouped_contracts)
            ratio = None if total_oi <= 0 else total_volume / total_oi
            fields = [
                {"name": "Signal", "value": f"{len(alert.grouped_contracts)} contracts | {snap.contract.dte}DTE", "inline": True},
                {"name": "Strike Range", "value": strike_range, "inline": True},
                {"name": "Combined Volume", "value": f"{total_volume:,}", "inline": True},
                {"name": "Combined OI", "value": f"{total_oi:,}", "inline": True},
                {"name": "Combined Vol/OI", "value": "n/a" if ratio is None else f"{ratio:.2f}x", "inline": True},
                {"name": "Underlying", "value": "n/a" if snap.underlying_price is None else f"${snap.underlying_price:.2f}", "inline": True},
            ]
        else:
            fields = [
                {"name": "Contract", "value": f"{snap.contract.display} | {snap.contract.dte}DTE", "inline": True},
                {"name": "Volume / OI", "value": f"{snap.volume:,} / {snap.open_interest:,}", "inline": True},
                {"name": "Vol/OI", "value": "n/a" if snap.vol_oi is None else f"{snap.vol_oi:.2f}x", "inline": True},
                {"name": "Underlying", "value": "n/a" if snap.underlying_price is None else f"${snap.underlying_price:.2f}", "inline": True},
            ]
        if alert.alert_type == "contract":
            fields.append({"name": "Estimated Activity", "value": f"${alert.estimated_premium:,.0f}", "inline": True})
        fields.append({"name": "Reason", "value": "; ".join(alert.reasons[:4]), "inline": False})
        return {
            "username": "Unusual Options Scanner",
            "embeds": [{
                "title": alert.title,
                "description": f"{'Green Calls' if snap.contract.side == OptionSide.CALL else 'Red Puts'} | {alert.severity.value}",
                "color": color,
                "fields": fields,
                "footer": {"text": "Market data alert only. Not a trade recommendation."},
            }],
        }

    def stock_payload(self, alert: StockAlert) -> dict:
        snap = alert.snapshot
        change_close = pct_text(snap.change_from_close_pct)
        change_open = pct_text(snap.change_from_open_pct)
        price_change_5m = pct_text(alert.price_change_5m_pct)
        range_pos = "n/a" if snap.range_position is None else f"{snap.range_position * 100:.0f}%"
        color = 0x2ECC71
        if (snap.change_from_open_pct or snap.change_from_close_pct or alert.price_change_5m_pct or 0) < 0:
            color = 0xE74C3C
        if alert.severity.value == "EXTREME":
            color = 0xF1C40F
        fields = [
            {"name": "Price", "value": f"${snap.price:.2f}", "inline": True},
            {"name": "5m Volume", "value": f"{alert.volume_delta_5m:,}", "inline": True},
            {"name": "5m Dollar Volume", "value": f"${alert.dollar_volume_5m:,.0f}", "inline": True},
            {"name": "Burst Ratio", "value": "n/a" if alert.burst_ratio is None else f"{alert.burst_ratio:.2f}x", "inline": True},
            {"name": "Move", "value": f"Close {change_close} | Open {change_open} | 5m {price_change_5m}", "inline": True},
            {"name": "Range Position", "value": range_pos, "inline": True},
            {"name": "Reason", "value": "; ".join(alert.reasons[:5]), "inline": False},
        ]
        return {
            "username": "Unusual Volume Scanner",
            "embeds": [{
                "title": alert.title,
                "description": f"{snap.symbol} underlying volume | {alert.severity.value}",
                "color": color,
                "fields": fields,
                "footer": {"text": "Market data alert only. Not a trade recommendation."},
            }],
        }


def format_strike(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def pct_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"
