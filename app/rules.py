from .config import Thresholds
from .metrics import estimated_premium
from .models import Alert, OptionSide, OptionSnapshot, Severity


def evaluate_contract(snapshot: OptionSnapshot, volume_delta_5m: int, thresholds: Thresholds) -> Alert | None:
    min_volume = thresholds.min_volume_0dte if snapshot.contract.dte == 0 else thresholds.min_volume
    min_delta = thresholds.min_5m_volume_increase_0dte if snapshot.contract.dte == 0 else thresholds.min_5m_volume_increase
    premium = estimated_premium(snapshot, volume_delta_5m)
    ratio = snapshot.vol_oi
    long_dte = snapshot.contract.dte > 7
    score = 0
    reasons = []

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

    side_word = "call" if snapshot.contract.side == OptionSide.CALL else "put"
    return Alert("contract", severity_for(score, premium, ratio, thresholds), f"Unusual {side_word} activity detected", snapshot, reasons, volume_delta_5m, premium)


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
