import logging
import time

from .models import Alert, OptionSide

LOG = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, alert: Alert) -> bool:
        if not self.webhook_url:
            LOG.info("discord webhook not configured; alert skipped: %s", alert.title)
            return False
        return self.send_payload(self.payload(alert), alert.title)

    def send_group(self, alerts: list[Alert]) -> bool:
        if not alerts:
            return True
        label = ", ".join(alert.snapshot.contract.symbol for alert in alerts)
        return self.send_payload(self.group_payload(alerts), f"options alerts: {label}")

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

    def payload(self, alert: Alert) -> dict:
        snap = alert.snapshot
        color = 0x2ECC71 if snap.contract.side == OptionSide.CALL else 0xE74C3C
        if alert.severity.value == "EXTREME":
            color = 0x3498DB
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

    def group_payload(self, alerts: list[Alert]) -> dict:
        if not alerts:
            raise ValueError("Cannot format an empty alert group")
        symbols = ", ".join(alert.snapshot.contract.symbol for alert in alerts)
        sides = {alert.snapshot.contract.side for alert in alerts}
        color = 0x3498DB if any(alert.severity.value == "EXTREME" for alert in alerts) else (
            0xE74C3C if sides == {OptionSide.PUT} else 0x2ECC71 if sides == {OptionSide.CALL} else 0x95A5A6
        )
        sections = []
        for alert in alerts:
            snap = alert.snapshot
            contract = snap.contract
            marker = "🔥 " if alert.severity.value == "EXTREME" else ""
            side_marker = "🟢" if contract.side == OptionSide.CALL else "🔴"
            side = "CALL" if contract.side == OptionSide.CALL else "PUT"
            spot = "n/a" if snap.underlying_price is None else f"${snap.underlying_price:.2f}"
            if alert.alert_type == "ticker" and alert.grouped_contracts:
                strikes = sorted(item.contract.strike for item in alert.grouped_contracts)
                suffix = "C" if contract.side == OptionSide.CALL else "P"
                strike_text = f"{format_strike(strikes[0])}{suffix}-{format_strike(strikes[-1])}{suffix}"
                volume = sum(item.volume for item in alert.grouped_contracts)
                oi = sum(item.open_interest for item in alert.grouped_contracts)
                ratio = None if oi <= 0 else volume / oi
                detail = f"{len(alert.grouped_contracts)} contracts · {strike_text} · {contract.dte} DTE"
            else:
                volume = snap.volume
                oi = snap.open_interest
                ratio = snap.vol_oi
                detail = f"{format_strike(contract.strike)}{'C' if side == 'CALL' else 'P'} · {contract.dte} DTE · Est. ${alert.estimated_premium:,.0f}"
            ratio_text = "n/a" if ratio is None else f"{ratio:.2f}x"
            sections.append(
                f"**{marker}{side_marker} {contract.symbol} {side} · {alert.severity.value}**\n"
                f"{detail}\n"
                f"Vol {volume:,} / OI {oi:,} · {ratio_text} · Stock {spot}"
            )
        return {
            "username": "Unusual Options Scanner",
            "embeds": [{
                "title": f"Unusual Options · {symbols}",
                "description": "\n\n".join(sections),
                "color": color,
                "footer": {"text": "Market data alert only. Not a trade recommendation."},
            }],
        }

def format_strike(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"
