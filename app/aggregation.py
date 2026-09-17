from collections import defaultdict

from .config import Settings
from .models import Alert, OptionSide, OptionSnapshot, Severity


def ticker_level_alerts(snapshots: list[OptionSnapshot], settings: Settings) -> list[Alert]:
    grouped = defaultdict(list)
    for snap in snapshots:
        grouped[(snap.contract.symbol, snap.contract.side, snap.contract.dte)].append(snap)

    alerts = []
    for (symbol, side, dte), items in grouped.items():
        for cluster in clusters(sorted(items, key=lambda s: s.contract.strike), settings.cluster_max_strike_gap_pct):
            if len(cluster) < settings.cluster_min_contracts:
                continue
            side_name = "CALL" if side == OptionSide.CALL else "PUT"
            lead = max(cluster, key=lambda s: (s.volume, s.vol_oi or 0))
            alerts.append(Alert(
                "ticker",
                Severity.EXTREME if len(cluster) >= 5 else Severity.HIGH,
                f"{symbol} {side_name} ACTIVITY SURGE",
                lead,
                [f"{len(cluster)} nearby {dte}DTE strikes showing elevated {side_name.lower()} activity"],
                0,
                0,
                cluster,
            ))
    return alerts


def clusters(items: list[OptionSnapshot], max_gap_pct: float) -> list[list[OptionSnapshot]]:
    out = []
    current = []
    last = None
    for item in items:
        strike = item.contract.strike
        if last is None or abs(strike - last) / max(last, 1) <= max_gap_pct:
            current.append(item)
        else:
            out.append(current)
            current = [item]
        last = strike
    if current:
        out.append(current)
    return out
