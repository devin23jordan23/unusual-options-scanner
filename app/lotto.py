from dataclasses import replace

from .config import LottoSettings
from .models import Alert, MarketSnapshot, OptionSide, Severity


SECTOR_ETF = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "SMH", "AVGO": "SMH", "AMD": "SMH", "MU": "SMH",
    "TSM": "SMH", "ARM": "SMH", "QCOM": "SMH", "MRVL": "SMH", "INTC": "SMH", "AMAT": "SMH",
    "LRCX": "SMH", "KLAC": "SMH", "ASML": "SMH", "SNDK": "SMH", "SMCI": "SMH", "DELL": "XLK",
    "VRT": "XLK", "ANET": "XLK", "AAOI": "XLK", "META": "QQQ", "AMZN": "QQQ", "GOOGL": "QQQ",
    "NFLX": "QQQ", "PLTR": "XLK", "NOW": "XLK", "ORCL": "XLK", "CRM": "XLK", "ADBE": "XLK",
    "SNOW": "XLK", "DDOG": "XLK", "NET": "XLK", "CRWD": "XLK", "PANW": "XLK", "ZS": "XLK",
    "OKTA": "XLK", "TEAM": "XLK", "MDB": "XLK", "SHOP": "QQQ", "COIN": "QQQ", "HOOD": "QQQ",
    "MSTR": "QQQ", "PYPL": "XLF", "SOFI": "XLF", "AFRM": "XLF", "UPST": "XLF",
    "JPM": "XLF", "BAC": "XLF", "MS": "XLF", "GS": "XLF", "C": "XLF", "SCHW": "XLF",
    "V": "XLF", "MA": "XLF", "AXP": "XLF", "XOM": "XLE", "CVX": "XLE", "BE": "XLK",
    "VST": "XLU", "CEG": "XLU", "NRG": "XLU", "OKLO": "XLU", "FSLR": "TAN", "ENPH": "TAN",
    "WMT": "XLP", "COST": "XLP", "TGT": "XLY", "MCD": "XLY", "CMG": "XLY", "LULU": "XLY",
    "NKE": "XLY", "SBUX": "XLY", "HD": "XLY", "LOW": "XLY", "UBER": "XLY", "ABNB": "XLY",
    "RBLX": "XLY", "LLY": "XLV", "UNH": "XLV", "MRNA": "XLV", "REGN": "XLV", "ISRG": "XLV",
    "BA": "XLI", "LMT": "XLI", "CAT": "XLI", "DE": "XLI",
}

BENCHMARK_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "SMH", "SOXX", "TAN"}


def context_symbols(universe: list[str]) -> list[str]:
    sectors = {SECTOR_ETF.get(symbol) for symbol in universe}
    return sorted(set(universe) | BENCHMARK_SYMBOLS | {s for s in sectors if s})


def evaluate_lotto(
    base_alert: Alert,
    quotes: dict[str, MarketSnapshot],
    underlying_volume_5m: int,
    settings: LottoSettings,
) -> Alert | None:
    if not settings.enabled or base_alert.alert_type != "contract":
        return None

    snap = base_alert.snapshot
    contract = snap.contract
    symbol = contract.symbol
    quote = quotes.get(symbol)
    if quote is None or snap.underlying_price is None or snap.underlying_price <= 0:
        return None

    if contract.dte > settings.max_dte or contract.dte < 0:
        return None
    if snap.mark <= 0 or snap.mark > settings.max_mark:
        return None
    if snap.volume < settings.min_contract_volume or base_alert.volume_delta_5m < settings.min_5m_volume:
        return None
    if snap.vol_oi is not None and snap.vol_oi < settings.min_vol_oi:
        return None

    otm_pct = option_otm_pct(snap)
    if otm_pct > settings.max_otm_pct or otm_pct < -0.04:
        return None

    abs_delta = abs(snap.delta) if snap.delta is not None else None
    if abs_delta is not None and not (settings.min_abs_delta <= abs_delta <= settings.max_abs_delta):
        return None

    spread_pct = option_spread_pct(snap)
    if spread_pct is not None and spread_pct > settings.max_spread_pct:
        return None

    direction = 1 if contract.side == OptionSide.CALL else -1
    stock_move = direction * (quote.percent_change or 0.0)
    sector_symbol = SECTOR_ETF.get(symbol)
    sector = quotes.get(sector_symbol) if sector_symbol else None
    sector_move = direction * ((sector.percent_change or 0.0) if sector else 0.0)

    market_symbol = "QQQ" if sector_symbol in {"XLK", "SMH", "SOXX"} or symbol in {"QQQ"} else "SPY"
    market = quotes.get(market_symbol)
    market_move = direction * ((market.percent_change or 0.0) if market else 0.0)

    score = 0
    reasons = []

    if base_alert.volume_delta_5m >= settings.min_5m_volume:
        score += 16
        reasons.append(f"option volume accelerating +{base_alert.volume_delta_5m:,} in 5m")
    if snap.vol_oi is not None and snap.vol_oi >= 2:
        score += 12
        reasons.append(f"Vol/OI {snap.vol_oi:.1f}x")
    elif snap.open_interest == 0:
        score += 8
        reasons.append("fresh volume on zero reported OI")

    if 0 <= otm_pct <= 0.025:
        score += 12
        reasons.append(f"near-money convex strike ({otm_pct * 100:.1f}% OTM)")
    elif otm_pct < 0:
        score += 7
        reasons.append("already slightly ITM")
    else:
        score += 6

    if abs_delta is not None:
        if 0.25 <= abs_delta <= 0.50:
            score += 10
            reasons.append(f"responsive delta {abs_delta:.2f}")
        else:
            score += 5
    if snap.gamma is not None and snap.gamma > 0:
        score += min(8, max(2, int(snap.gamma * 100)))
        reasons.append("positive gamma convexity")

    if spread_pct is not None:
        if spread_pct <= 0.12:
            score += 8
            reasons.append("tight bid/ask")
        elif spread_pct <= 0.20:
            score += 5

    if stock_move >= settings.stock_move_confirm_pct:
        score += 13
        reasons.append(f"underlying confirms {quote.percent_change:+.2f}%")
    elif stock_move > 0:
        score += 6

    if sector and sector_move >= settings.sector_move_confirm_pct:
        score += 8
        reasons.append(f"{sector_symbol} confirms {sector.percent_change:+.2f}%")
    elif sector and sector_move > 0:
        score += 3

    if market and market_move >= settings.market_move_confirm_pct:
        score += 7
        reasons.append(f"{market_symbol} confirms {market.percent_change:+.2f}%")
    elif market and market_move > 0:
        score += 3

    if underlying_volume_5m > 0:
        score += 6
        reasons.append(f"underlying 5m volume +{underlying_volume_5m:,}")

    if contract.dte <= 1:
        score += 5
        reasons.append("0-1DTE convexity")
    elif contract.dte <= 3:
        score += 3

    if score < settings.min_score:
        return None

    side = "CALL" if contract.side == OptionSide.CALL else "PUT"
    context = {
        "Lotto Score": f"{score}/100",
        "Stock Move": "n/a" if quote.percent_change is None else f"{quote.percent_change:+.2f}%",
        "Sector": "n/a" if sector is None or sector.percent_change is None else f"{sector_symbol} {sector.percent_change:+.2f}%",
        "Market": "n/a" if market is None or market.percent_change is None else f"{market_symbol} {market.percent_change:+.2f}%",
        "5m Stock Vol": f"{underlying_volume_5m:,}",
        "OTM / ITM": f"{otm_pct * 100:+.2f}%",
    }
    return replace(
        base_alert,
        alert_type="lotto",
        severity=Severity.EXTREME if score >= 88 else Severity.HIGH,
        title=f"LOTTO WATCH {side} - {contract.symbol} {contract.display}",
        reasons=reasons,
        lotto_score=min(score, 100),
        context_fields=context,
    )


def option_otm_pct(snapshot) -> float:
    spot = snapshot.underlying_price or 0
    if spot <= 0:
        return 1.0
    if snapshot.contract.side == OptionSide.CALL:
        return (snapshot.contract.strike - spot) / spot
    return (spot - snapshot.contract.strike) / spot


def option_spread_pct(snapshot) -> float | None:
    if snapshot.bid is None or snapshot.ask is None or snapshot.bid <= 0 or snapshot.ask <= 0:
        return None
    mid = (snapshot.bid + snapshot.ask) / 2
    if mid <= 0:
        return None
    return (snapshot.ask - snapshot.bid) / mid
