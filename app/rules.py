from .config import Thresholds, UnderlyingVolumeThresholds
from .metrics import estimated_premium
from .models import Alert, OptionSide, OptionSnapshot, Severity, StockAlert, StockSnapshot


def evaluate_contract(snapshot: OptionSnapshot, volume_delta_5m: int, thresholds: Thresholds) -> Alert | None:
    min_volume = thresholds.min_volume_0dte if snapshot.contract.dte == 0 else thresholds.min_volume
    min_delta = thresholds.min_5m_volume_increase_0dte if snapshot.contract.dte == 0 else thresholds.min_5m_volume_increase
    premium = estimated_premium(snapshot, volume_delta_5m)
    ratio = snapshot.vol_oi
    long_dte = snapshot.contract.dte > 7
    score = 0
    reasons = []

    # Require meaningful new activity; cumulative daily volume and low-OI ratios
    # alone should not resurrect an old contract.
    if volume_delta_5m < max(min_delta // 4, 1):
        return None

    if snapshot.volume >= min_volume:
        score += 1
        reasons.append("volume above threshold")
    if ratio is not None and ratio >= thresholds.vol_oi_unusual:
        score += 1
        reasons.append("volume exceeds open interest")
    if ratio is not None and ratio >= thresholds.vol_oi_very_unusual:
        score += 1
        reasons.append("very unusual volume/open-interest ratio")
    if ratio is not None and ratio >= thresholds.vol_oi_extreme:
        score += 1
        reasons.append("extreme volume/open-interest ratio")
    if premium >= thresholds.premium_large:
        score += 1
        reasons.append("large estimated premium activity")
    if premium >= thresholds.premium_major:
        score += 1
        reasons.append("major estimated premium activity")
    if premium >= thresholds.premium_whale:
        score += 1
        reasons.append("whale-size estimated premium activity")
    if volume_delta_5m >= min_delta:
        score += 1
        reasons.append("5m contract volume accelerating")
    if snapshot.contract.dte == 0:
        reasons.append("0DTE activity")
    if long_dte and premium >= thresholds.long_dte_min_premium:
        score += 2
        reasons.append("longer-dated high-premium flow")
    if long_dte and ratio is not None and ratio >= thresholds.long_dte_min_vol_oi and snapshot.volume >= thresholds.long_dte_min_volume:
        score += 1
        reasons.append("longer-dated volume exceeds open interest")
    if snapshot.open_interest == 0 and snapshot.volume >= min_volume * 2:
        score += 1
        reasons.append("high volume on zero reported open interest")

    if long_dte and not has_long_dte_signal(snapshot, premium, ratio, thresholds):
        return None
    if score < thresholds.min_score:
        return None

    side_word = "CALL" if snapshot.contract.side == OptionSide.CALL else "PUT"
    title = f"Unusual {side_word} activity - {snapshot.contract.symbol}"
    return Alert("contract", severity_for(score, premium, ratio, thresholds), title, snapshot, reasons, volume_delta_5m, premium)


def has_long_dte_signal(snapshot: OptionSnapshot, premium: float, ratio: float | None, thresholds: Thresholds) -> bool:
    if premium >= thresholds.long_dte_min_premium:
        return True
    return (
        premium >= thresholds.premium_major
        and snapshot.volume >= thresholds.long_dte_min_volume
        and ratio is not None
        and ratio >= thresholds.long_dte_min_vol_oi
    )


def severity_for(score: int, premium: float, ratio: float | None, thresholds: Thresholds) -> Severity:
    if premium >= thresholds.premium_extreme_whale or (ratio is not None and ratio >= thresholds.vol_oi_extreme and score >= 5):
        return Severity.EXTREME
    if premium >= thresholds.premium_whale or score >= 6:
        return Severity.HIGH
    if score >= 4 or premium >= thresholds.premium_major:
        return Severity.UNUSUAL
    return Severity.WATCH


def evaluate_underlying_volume(
    snapshot: StockSnapshot,
    volume_delta_5m: int,
    price_change_5m_pct: float | None,
    burst_ratio: float | None,
    thresholds: UnderlyingVolumeThresholds,
) -> StockAlert | None:
    if not thresholds.enabled:
        return None
    if snapshot.price < thresholds.min_price or snapshot.price > thresholds.max_price:
        return None
    if snapshot.volume < thresholds.min_volume_today:
        return None

    dollar_volume_5m = volume_delta_5m * snapshot.price
    if volume_delta_5m < max(thresholds.min_5m_volume // 4, 1):
        return None
    if volume_delta_5m < thresholds.min_5m_volume and dollar_volume_5m < thresholds.min_5m_dollar_volume:
        return None

    score = 0
    reasons = []
    direction = move_direction(snapshot, price_change_5m_pct)

    if volume_delta_5m >= thresholds.min_5m_volume:
        score += 1
        reasons.append("5m share volume spike")
    if dollar_volume_5m >= thresholds.min_5m_dollar_volume:
        score += 1
        reasons.append("large 5m dollar volume")
    if burst_ratio is not None and burst_ratio >= thresholds.min_burst_ratio:
        score += 1
        reasons.append("volume burst versus today's pace")
    if abs_or_zero(snapshot.change_from_close_pct) >= thresholds.min_change_from_close_pct:
        score += 1
        reasons.append("strong move from prior close")
    if abs_or_zero(snapshot.change_from_open_pct) >= thresholds.min_change_from_open_pct:
        score += 1
        reasons.append("strong move from open")
    if abs_or_zero(price_change_5m_pct) >= thresholds.min_5m_price_change_pct:
        score += 1
        reasons.append("fast 5m price move")
    if abs_or_zero(snapshot.day_range_pct) >= thresholds.min_day_range_pct:
        score += 1
        reasons.append("intraday range expansion")
    if range_confirms_direction(snapshot, direction, thresholds):
        score += 1
        reasons.append("near active side of day range")

    if score < thresholds.min_score:
        return None

    title = f"Unusual underlying volume - {snapshot.symbol}"
    return StockAlert(
        "underlying",
        underlying_severity(score, dollar_volume_5m, burst_ratio),
        title,
        snapshot,
        reasons,
        volume_delta_5m,
        dollar_volume_5m,
        burst_ratio,
        price_change_5m_pct,
    )


def move_direction(snapshot: StockSnapshot, price_change_5m_pct: float | None) -> int:
    moves = [
        snapshot.change_from_open_pct,
        snapshot.change_from_close_pct,
        price_change_5m_pct,
    ]
    total = sum(value for value in moves if value is not None)
    if total > 0:
        return 1
    if total < 0:
        return -1
    return 0


def range_confirms_direction(snapshot: StockSnapshot, direction: int, thresholds: UnderlyingVolumeThresholds) -> bool:
    position = snapshot.range_position
    if position is None:
        return False
    if direction >= 0 and position >= thresholds.high_range_position:
        return True
    if direction <= 0 and position <= thresholds.low_range_position:
        return True
    return False


def underlying_severity(score: int, dollar_volume_5m: float, burst_ratio: float | None) -> Severity:
    if score >= 7 and dollar_volume_5m >= 50_000_000 and (burst_ratio or 0) >= 3:
        return Severity.EXTREME
    if score >= 6 or dollar_volume_5m >= 35_000_000:
        return Severity.HIGH
    if score >= 5:
        return Severity.UNUSUAL
    return Severity.WATCH


def abs_or_zero(value: float | None) -> float:
    return abs(value) if value is not None else 0
