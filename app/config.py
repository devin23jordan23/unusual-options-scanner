import os
from dataclasses import dataclass, field, replace


CORE_UNIVERSE = {
    "SPY", "QQQ", "IWM", "DIA", "SMH", "SOXX", "XLK", "XLF", "XLE", "GLD", "USO", "SLV", "MTUM",
    "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL", "NFLX", "AVGO", "AMD", "PLTR", "COIN",
    "HOOD", "MSTR",
    "MU", "TSM", "ARM", "QCOM", "MRVL", "INTC", "AMAT", "LRCX", "KLAC", "ASML", "SNDK", "SMCI",
    "DELL", "VRT", "ANET", "NBIS", "AAOI",
    "NOW", "ORCL", "CRM", "ADBE", "SNOW", "DDOG", "NET", "CRWD", "PANW", "ZS", "OKTA", "TEAM",
    "MDB", "SHOP",
    "BE", "VST", "CEG", "NRG", "OKLO", "FSLR", "ENPH",
    "PYPL", "SOFI", "AFRM", "UPST", "RBLX", "UBER", "ABNB",
    "JPM", "BAC", "MS", "GS", "C", "SCHW", "V", "MA", "AXP",
    "WMT", "TGT", "COST", "MCD", "CMG", "LULU", "NKE", "SBUX", "HD", "LOW",
    "LLY", "UNH", "MRNA", "REGN", "ISRG",
    "BA", "LMT", "CAT", "DE",
    "XOM", "CVX",
}


def csv_set(raw: str) -> set[str]:
    return {x.strip().upper() for x in raw.split(",") if x.strip()}


@dataclass(frozen=True)
class Thresholds:
    min_volume: int = 500
    min_volume_0dte: int = 350
    vol_oi_unusual: float = 2.0
    vol_oi_very_unusual: float = 4.0
    vol_oi_extreme: float = 7.0
    premium_large: float = 100_000
    premium_major: float = 500_000
    premium_whale: float = 1_000_000
    premium_extreme_whale: float = 2_000_000
    min_5m_volume_increase: int = 600
    min_5m_volume_increase_0dte: int = 350
    min_score: int = 3
    contract_cooldown_seconds: int = 300
    ticker_cooldown_seconds: int = 600
    long_dte_min_volume: int = 250
    long_dte_min_vol_oi: float = 2.0
    long_dte_min_premium: float = 1_000_000


@dataclass(frozen=True)
class Settings:
    mode: str = "live"
    timezone: str = "America/New_York"
    poll_seconds: int = 60
    mock_cycles: int = 0
    data_dir: str = "data"
    discord_webhook: str = ""
    log_level: str = "INFO"
    core_universe: set[str] = field(default_factory=lambda: set(CORE_UNIVERSE))
    in_play: set[str] = field(default_factory=set)
    max_dte: int = 60
    strike_range_pct: float = 0.10
    cluster_min_contracts: int = 3
    cluster_max_strike_gap_pct: float = 0.025
    max_alerts_per_cycle: int = 3
    symbol_cooldown_seconds: int = 900
    thresholds: Thresholds = field(default_factory=Thresholds)
    symbol_overrides: dict[str, Thresholds] = field(default_factory=dict)

    @property
    def active_universe(self) -> list[str]:
        return sorted(self.core_universe | self.in_play)

    def thresholds_for(self, symbol: str) -> Thresholds:
        return self.symbol_overrides.get(symbol.upper(), self.thresholds)


def load_settings() -> Settings:
    t = Thresholds(
        min_volume=int(os.getenv("UOA_MIN_VOLUME", "500")),
        min_volume_0dte=int(os.getenv("UOA_MIN_VOLUME_0DTE", "350")),
        vol_oi_unusual=float(os.getenv("UOA_VOL_OI_UNUSUAL", "2.0")),
        vol_oi_very_unusual=float(os.getenv("UOA_VOL_OI_VERY_UNUSUAL", "4.0")),
        vol_oi_extreme=float(os.getenv("UOA_VOL_OI_EXTREME", "7.0")),
        premium_large=float(os.getenv("UOA_PREMIUM_LARGE", "100000")),
        premium_major=float(os.getenv("UOA_PREMIUM_MAJOR", "500000")),
        premium_whale=float(os.getenv("UOA_PREMIUM_WHALE", "1000000")),
        premium_extreme_whale=float(os.getenv("UOA_PREMIUM_EXTREME_WHALE", "2000000")),
        min_5m_volume_increase=int(os.getenv("UOA_MIN_5M_VOLUME_INCREASE", "600")),
        min_5m_volume_increase_0dte=int(os.getenv("UOA_MIN_5M_VOLUME_INCREASE_0DTE", "350")),
        min_score=int(os.getenv("UOA_MIN_SCORE", "3")),
        contract_cooldown_seconds=int(os.getenv("UOA_CONTRACT_COOLDOWN_SECONDS", "300")),
        ticker_cooldown_seconds=int(os.getenv("UOA_TICKER_COOLDOWN_SECONDS", "600")),
        long_dte_min_volume=int(os.getenv("UOA_LONG_DTE_MIN_VOLUME", "250")),
        long_dte_min_vol_oi=float(os.getenv("UOA_LONG_DTE_MIN_VOL_OI", "2.0")),
        long_dte_min_premium=float(os.getenv("UOA_LONG_DTE_MIN_PREMIUM", "1000000")),
    )
    etf_t = replace(
        t,
        min_volume=int(os.getenv("UOA_INDEX_MIN_VOLUME", "2500")),
        min_volume_0dte=int(os.getenv("UOA_INDEX_MIN_VOLUME_0DTE", "3500")),
        min_5m_volume_increase=int(os.getenv("UOA_INDEX_MIN_5M_VOLUME_INCREASE", "2000")),
        min_5m_volume_increase_0dte=int(os.getenv("UOA_INDEX_MIN_5M_VOLUME_INCREASE_0DTE", "3000")),
        min_score=max(t.min_score, int(os.getenv("UOA_INDEX_MIN_SCORE", "4"))),
    )
    mega_etf_t = replace(
        etf_t,
        min_volume=int(os.getenv("UOA_MEGA_ETF_MIN_VOLUME", "7500")),
        min_volume_0dte=int(os.getenv("UOA_MEGA_ETF_MIN_VOLUME_0DTE", "12000")),
        min_5m_volume_increase=int(os.getenv("UOA_MEGA_ETF_MIN_5M_VOLUME_INCREASE", "5000")),
        min_5m_volume_increase_0dte=int(os.getenv("UOA_MEGA_ETF_MIN_5M_VOLUME_INCREASE_0DTE", "8000")),
        min_score=max(etf_t.min_score, int(os.getenv("UOA_MEGA_ETF_MIN_SCORE", "5"))),
        premium_large=float(os.getenv("UOA_MEGA_ETF_PREMIUM_LARGE", "500000")),
        premium_major=float(os.getenv("UOA_MEGA_ETF_PREMIUM_MAJOR", "1500000")),
        premium_whale=float(os.getenv("UOA_MEGA_ETF_PREMIUM_WHALE", "3000000")),
        premium_extreme_whale=float(os.getenv("UOA_MEGA_ETF_PREMIUM_EXTREME_WHALE", "5000000")),
        ticker_cooldown_seconds=int(os.getenv("UOA_MEGA_ETF_TICKER_COOLDOWN_SECONDS", "900")),
        long_dte_min_premium=float(os.getenv("UOA_MEGA_ETF_LONG_DTE_MIN_PREMIUM", "3000000")),
    )
    core = csv_set(os.getenv("UOA_CORE_UNIVERSE", ",".join(sorted(CORE_UNIVERSE)))) or set(CORE_UNIVERSE)
    etfs = {"IWM", "DIA", "SMH", "SOXX", "XLK", "XLF", "XLE", "GLD", "USO", "SLV", "MTUM"}
    return Settings(
        mode=os.getenv("SCANNER_MODE", "live").lower(),
        timezone=os.getenv("SCANNER_TIMEZONE", "America/New_York"),
        poll_seconds=int(os.getenv("UOA_POLL_SECONDS", "60")),
        mock_cycles=int(os.getenv("UOA_MOCK_CYCLES", "0")),
        data_dir=os.getenv("DATA_DIR", "data"),
        discord_webhook=os.getenv("DISCORD_UNUSUAL_OPTIONS_WEBHOOK", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        core_universe=core,
        in_play=csv_set(os.getenv("UOA_IN_PLAY", "")),
        max_dte=int(os.getenv("UOA_MAX_DTE", "60")),
        strike_range_pct=float(os.getenv("UOA_STRIKE_RANGE_PCT", "0.10")),
        cluster_min_contracts=int(os.getenv("UOA_CLUSTER_MIN_CONTRACTS", "3")),
        cluster_max_strike_gap_pct=float(os.getenv("UOA_CLUSTER_MAX_STRIKE_GAP_PCT", "0.025")),
        max_alerts_per_cycle=int(os.getenv("UOA_MAX_ALERTS_PER_CYCLE", "3")),
        symbol_cooldown_seconds=int(os.getenv("UOA_SYMBOL_COOLDOWN_SECONDS", "900")),
        thresholds=t,
        symbol_overrides={**{symbol: etf_t for symbol in etfs}, "SPY": mega_etf_t, "QQQ": mega_etf_t},
    )
