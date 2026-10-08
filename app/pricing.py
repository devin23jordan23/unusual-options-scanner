"""Price context for SPXW flow, never an inferred buyer fill."""

from zoneinfo import ZoneInfo

from .models import OptionSnapshot

ET = ZoneInfo("America/New_York")


def spxw_price_context(snapshot: OptionSnapshot) -> str:
    """Use a fresh two-sided quote, with a recent print as separate context."""
    now = snapshot.timestamp
    trade = snapshot.last_trade_time
    quote = snapshot.quote_time
    recent_trade = (trade is not None and snapshot.last_trade_price is not None
                    and snapshot.last_trade_price > 0 and 0 <= (now - trade).total_seconds() <= 300)
    fresh_quote = (quote is not None and snapshot.bid is not None and snapshot.ask is not None
                   and snapshot.bid >= 0 and snapshot.ask > 0 and snapshot.ask >= snapshot.bid
                   and 0 <= (now - quote).total_seconds() <= 90)

    if fresh_quote and snapshot.bid > 0:
        midpoint = (snapshot.bid + snapshot.ask) / 2
        detail = f"Approx. ${midpoint:.2f} (quote midpoint {quote.astimezone(ET):%H:%M:%S} ET)"
    elif recent_trade:
        detail = f"Approx. ${snapshot.last_trade_price:.2f} (recent print {trade.astimezone(ET):%H:%M:%S} ET)"
    else:
        detail = "Approx. price unavailable"

    if fresh_quote:
        detail += f" · bid ${snapshot.bid:.2f} / ask ${snapshot.ask:.2f} @ {quote.astimezone(ET):%H:%M:%S} ET"
    if recent_trade and fresh_quote:
        detail += f" · recent print ${snapshot.last_trade_price:.2f} @ {trade.astimezone(ET):%H:%M:%S} ET"
    return detail
