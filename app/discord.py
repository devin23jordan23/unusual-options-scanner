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
        payload = self.payload(alert)
        for attempt in range(3):
            try:
                import requests

                resp = requests.post(self.webhook_url, json=payload, timeout=10)
                resp.raise_for_status()
                LOG.info("Discord alert sent: %s", alert.title)
                return True
            except Exception as exc:
                LOG.warning("Discord send failed attempt %s: %s", attempt + 1, exc)
                time.sleep(2 ** attempt)
        return False

    def payload(self, alert: Alert) -> dict:
        snap = alert.snapshot
        color = 0x2ECC71 if snap.contract.side == OptionSide.CALL else 0xE74C3C
        if alert.severity.value == "EXTREME":
            color = 0xF1C40F
        fields = [
            {"name": "Contract", "value": f"{snap.contract.display} - {snap.contract.dte}DTE", "inline": True},
            {"name": "Volume", "value": f"{snap.volume:,}", "inline": True},
            {"name": "Open Interest", "value": f"{snap.open_interest:,}", "inline": True},
            {"name": "Vol/OI", "value": "n/a" if snap.vol_oi is None else f"{snap.vol_oi:.2f}x", "inline": True},
            {"name": "5m Volume Increase", "value": f"+{alert.volume_delta_5m:,}", "inline": True},
            {"name": "Underlying", "value": "n/a" if snap.underlying_price is None else f"${snap.underlying_price:.2f}", "inline": True},
        ]
        if alert.estimated_premium >= 100_000:
            fields.append({"name": "Estimated Activity", "value": f"${alert.estimated_premium:,.0f}", "inline": True})
        if alert.grouped_contracts:
            fields.append({"name": "Nearby Strikes", "value": "\n".join(s.contract.display.replace(f"{s.contract.symbol} ", "") for s in alert.grouped_contracts[:12]), "inline": False})
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
