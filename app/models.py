from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class OptionSide(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class Severity(str, Enum):
    WATCH = "WATCH"
    UNUSUAL = "UNUSUAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


@dataclass(frozen=True)
class OptionContract:
    symbol: str
    option_symbol: str
    expiration: date
    strike: float
    side: OptionSide
    dte: int

    @property
    def display(self) -> str:
        strike = int(self.strike) if self.strike == int(self.strike) else self.strike
        root = self.option_symbol.split()[0] if self.symbol == "SPX" and self.option_symbol else self.symbol
        if root not in {"SPX", "SPXW"}:
            root = self.symbol
        return f"{root} {strike}{'C' if self.side == OptionSide.CALL else 'P'}"


@dataclass
class OptionSnapshot:
    contract: OptionContract
    volume: int
    open_interest: int
    mark: float
    underlying_price: Optional[float]
    timestamp: datetime
    bid: Optional[float] = None
    ask: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    quote_time: Optional[datetime] = None
    last_trade_time: Optional[datetime] = None
    last_trade_price: Optional[float] = None

    @property
    def vol_oi(self) -> Optional[float]:
        if self.open_interest <= 0:
            return None
        return self.volume / self.open_interest


@dataclass
class Alert:
    alert_type: str
    severity: Severity
    title: str
    snapshot: OptionSnapshot
    reasons: list[str]
    volume_delta_5m: int = 0
    estimated_premium: float = 0
    grouped_contracts: list[OptionSnapshot] = field(default_factory=list)
    long_dated_whale: bool = False

    def premium_tier(self) -> str:
        if self.estimated_premium >= 2_000_000:
            return "extreme"
        if self.estimated_premium >= 1_000_000:
            return "whale"
        if self.estimated_premium >= 500_000:
            return "major"
        if self.estimated_premium >= 100_000:
            return "large"
        return "none"

    def vol_oi_tier(self) -> str:
        ratio = self.snapshot.vol_oi
        if ratio is None:
            return "none"
        if ratio >= 7:
            return "extreme"
        if ratio >= 4:
            return "very_unusual"
        if ratio >= 2:
            return "unusual"
        return "normal"
