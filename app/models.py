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
        return f"{self.symbol} {strike}{'C' if self.side == OptionSide.CALL else 'P'}"


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

    @property
    def vol_oi(self) -> Optional[float]:
        if self.open_interest <= 0:
            return None
        return self.volume / self.open_interest


@dataclass
class StockSnapshot:
    symbol: str
    price: float
    volume: int
    timestamp: datetime
    open_price: Optional[float] = None
    previous_close: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    volatility: Optional[float] = None

    @property
    def change_from_close_pct(self) -> Optional[float]:
        if not self.previous_close or self.previous_close <= 0:
            return None
        return (self.price - self.previous_close) / self.previous_close * 100

    @property
    def change_from_open_pct(self) -> Optional[float]:
        if not self.open_price or self.open_price <= 0:
            return None
        return (self.price - self.open_price) / self.open_price * 100

    @property
    def day_range_pct(self) -> Optional[float]:
        if not self.high_price or not self.low_price or self.low_price <= 0:
            return None
        return (self.high_price - self.low_price) / self.low_price * 100

    @property
    def range_position(self) -> Optional[float]:
        if not self.high_price or not self.low_price or self.high_price <= self.low_price:
            return None
        return (self.price - self.low_price) / (self.high_price - self.low_price)


@dataclass
class StockAlert:
    alert_type: str
    severity: Severity
    title: str
    snapshot: StockSnapshot
    reasons: list[str]
    volume_delta_5m: int = 0
    dollar_volume_5m: float = 0
    burst_ratio: Optional[float] = None
    price_change_5m_pct: Optional[float] = None


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
