import os
from dataclasses import dataclass, field, replace


CORE_UNIVERSE = {
    "SPY", "QQQ", "IWM",
    "TSLA", "NVDA", "AMD", "ARM", "QCOM", "MU", "TSM",
    "HOOD", "COIN", "MRNA",
    "META", "AMZN", "AAPL", "AVGO", "PLTR", "NFLX", "GOOGL", "MSFT",
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
    max_dte: int = 7
    strike_range_pct: float = 0.10
    cluster_min_contracts: int = 3
    cluster_max_strike_gap_pct: float = 0.025
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
    )
    index_t = replace(
        t,
        min_volume=int(os.getenv("UOA_INDEX_MIN_VOLUME", "2500")),
        min_volume_0dte=int(os.getenv("UOA_INDEX_MIN_VOLUME_0DTE", "1500")),
        min_5m_volume_increase=int(os.getenv("UOA_INDEX_MIN_5M_VOLUME_INCREASE", "2000")),
        min_5m_volume_increase_0dte=int(os.getenv("UOA_INDEX_MIN_5M_VOLUME_INCREASE_0DTE", "1500")),
        min_score=max(t.min_score, int(os.getenv("UOA_INDEX_MIN_SCORE", "4"))),
    )
    core = csv_set(os.getenv("UOA_CORE_UNIVERSE", ",".join(sorted(CORE_UNIVERSE)))) or set(CORE_UNIVERSE)
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
        max_dte=int(os.getenv("UOA_MAX_DTE", "7")),
        strike_range_pct=float(os.getenv("UOA_STRIKE_RANGE_PCT", "0.10")),
        cluster_min_contracts=int(os.getenv("UOA_CLUSTER_MIN_CONTRACTS", "3")),
        cluster_max_strike_gap_pct=float(os.getenv("UOA_CLUSTER_MAX_STRIKE_GAP_PCT", "0.025")),
        thresholds=t,
        symbol_overrides={"SPY": index_t, "QQQ": index_t, "IWM": index_t},
    )

