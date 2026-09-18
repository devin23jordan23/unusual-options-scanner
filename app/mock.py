from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Settings
from .models import OptionContract, OptionSide, OptionSnapshot, StockSnapshot


class MockData:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.step = 0
        self.series = {
            ("NVDA", 195.0, OptionSide.CALL): [900, 1400, 2500, 5000, 6482],
            ("NVDA", 197.5, OptionSide.CALL): [100, 600, 1600, 3100, 4200],
            ("NVDA", 200.0, OptionSide.CALL): [100, 450, 1300, 2800, 3900],
            ("AMD", 142.0, OptionSide.PUT): [300, 900, 2100, 3882, 5100],
            ("AMD", 140.0, OptionSide.PUT): [120, 500, 1400, 2600, 3400],
            ("SPY", 650.0, OptionSide.CALL): [5000, 6000, 7200, 9500, 12500],
        }
        self.stocks = {
            "COIN": {
                "price": [302.10, 304.80, 309.20, 314.50, 318.10],
                "volume": [1_100_000, 1_260_000, 1_760_000, 2_420_000, 3_110_000],
                "open": 299.80,
                "close": 298.40,
                "low": 298.90,
                "high": [304.00, 305.20, 309.80, 315.00, 318.50],
            },
            "HOOD": {
                "price": [118.20, 118.70, 120.10, 122.20, 123.40],
                "volume": [900_000, 1_020_000, 1_310_000, 1_850_000, 2_280_000],
                "open": 117.90,
                "close": 117.35,
                "low": 117.80,
                "high": [118.80, 119.00, 120.50, 122.60, 123.60],
            },
        }

    def option_snapshots(self, symbols: list[str]) -> list[OptionSnapshot]:
        now = datetime.now(ZoneInfo(self.settings.timezone))
        exp = now.date()
        out = []
        for (symbol, strike, side), volumes in self.series.items():
            if symbol not in symbols:
                continue
            idx = min(self.step, len(volumes) - 1)
            contract = OptionContract(symbol, f"{symbol}{exp:%y%m%d}{'C' if side == OptionSide.CALL else 'P'}{int(strike * 1000):08d}", exp, strike, side, 0)
            mark = 2.35 if symbol == "NVDA" else 1.35
            oi = 903 if symbol == "NVDA" else 721
            underlying = 193.86 if symbol == "NVDA" else 141.20 if symbol == "AMD" else 649.75
            out.append(OptionSnapshot(contract, volumes[idx], oi, mark, underlying, now))
        self.step += 1
        return out

    def stock_snapshots(self, symbols: list[str]) -> list[StockSnapshot]:
        now = datetime.now(ZoneInfo(self.settings.timezone))
        out = []
        for symbol, data in self.stocks.items():
            if symbol not in symbols:
                continue
            idx = min(self.step, len(data["price"]) - 1)
            out.append(StockSnapshot(
                symbol=symbol,
                price=data["price"][idx],
                volume=data["volume"][idx],
                timestamp=now,
                open_price=data["open"],
                previous_close=data["close"],
                high_price=data["high"][idx],
                low_price=data["low"],
            ))
        return out
