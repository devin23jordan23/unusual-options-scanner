from datetime import datetime, time
from zoneinfo import ZoneInfo


def is_market_open(tz_name: str = "America/New_York") -> bool:
    now = datetime.now(ZoneInfo(tz_name))
    if now.weekday() >= 5:
        return False
    return time(9, 30) <= now.time() <= time(16, 0)

