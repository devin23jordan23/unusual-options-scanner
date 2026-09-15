from typing import Optional

from .models import OptionSnapshot


def volume_oi_ratio(volume: int, open_interest: int) -> Optional[float]:
    if open_interest <= 0:
        return None
    return volume / open_interest


def estimated_premium(snapshot: OptionSnapshot, volume_delta: int | None = None) -> float:
    contracts = snapshot.volume if volume_delta is None else max(volume_delta, 0)
    return max(snapshot.mark or 0, 0) * contracts * 100

