import base64
import json
import logging
import os
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from .config import Settings
from .models import OptionContract, OptionSide, OptionSnapshot
from .oauth import callback_code

LOG = logging.getLogger(__name__)
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
BASE_URL = "https://api.schwabapi.com/marketdata/v1"
REDIRECT_URI = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1")


class SchwabClient:
    """Minimal read-only Schwab client, refactored from the existing Trading Scanner auth flow."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client_id = os.getenv("SCHWAB_CLIENT_ID", "")
        self.client_secret = os.getenv("SCHWAB_CLIENT_SECRET", "")
        self.seed_refresh_token = os.getenv("SCHWAB_REFRESH_TOKEN", "")
        self.seed_access_token = os.getenv("SCHWAB_ACCESS_TOKEN", "")
        self.auth_callback_url = os.getenv("SCHWAB_AUTH_CALLBACK_URL", "")
        os.makedirs(settings.data_dir, exist_ok=True)
        self.token_file = os.path.join(settings.data_dir, "schwab_tokens.json")
        if self.auth_callback_url and not os.path.exists(self.token_file):
            self.exchange_callback_url(self.auth_callback_url)

    def option_snapshots(self, symbols: list[str]) -> list[OptionSnapshot]:
        out: list[OptionSnapshot] = []
        for symbol in symbols:
            try:
                out.extend(self.option_snapshots_for_symbol(symbol))
            except Exception as exc:
                LOG.warning("Schwab chain failed for %s: %s", symbol, exc)
        return out

    def option_snapshots_for_symbol(self, symbol: str) -> list[OptionSnapshot]:
        underlying = self.quote_price(symbol)
        if not underlying:
            return []
        now = datetime.now(ZoneInfo(self.settings.timezone))
        params = {
            "symbol": symbol,
            "contractType": "ALL",
            "strategy": "SINGLE",
            "includeUnderlyingQuote": "true",
            "strikeCount": 40,
            "fromDate": now.date().isoformat(),
            "toDate": (now.date() + timedelta(days=self.settings.max_dte)).isoformat(),
        }
        data = self.get("/chains", params)
        chain_underlying = extract_underlying_price(data) or underlying
        snaps = []
        snaps.extend(self._parse_side(symbol, data.get("callExpDateMap", {}), OptionSide.CALL, chain_underlying, now))
        snaps.extend(self._parse_side(symbol, data.get("putExpDateMap", {}), OptionSide.PUT, chain_underlying, now))
        return self._filter_near_spot(snaps, chain_underlying)

    def quote_price(self, symbol: str) -> float | None:
        data = self.get("/quotes", {"symbols": symbol})
        quote = data.get(symbol, {}).get("quote", {})
        return num(quote.get("lastPrice") or quote.get("mark") or quote.get("closePrice"))

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        for attempt in range(2):
            resp = requests.get(f"{BASE_URL}{endpoint}", headers=self.headers(), params=params or {}, timeout=15)
            if resp.status_code == 401 and attempt == 0:
                self.refresh_tokens(self.load_tokens())
                continue
            resp.raise_for_status()
            return resp.json()
        return {}

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token()}", "Accept": "application/json"}

    def access_token(self) -> str:
        tokens = self.load_tokens()
        if not tokens:
            raise RuntimeError(f"Schwab auth required. Authorize at: {self.authorization_url()}")
        if expired(tokens):
            tokens = self.refresh_tokens(tokens)
        token = tokens.get("access_token")
        if not token:
            raise RuntimeError(f"Schwab auth required. Authorize at: {self.authorization_url()}")
        return token

    def authorization_url(self) -> str:
        query = urlencode({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": "readonly",
        })
        return f"{AUTH_URL}?{query}"

    def load_tokens(self) -> dict:
        if os.path.exists(self.token_file):
            with open(self.token_file, "r") as f:
                return json.load(f)
        if self.seed_refresh_token:
            tokens = {
                "refresh_token": self.seed_refresh_token,
                "access_token": self.seed_access_token,
                "expires_in": int(os.getenv("SCHWAB_EXPIRES_IN", "0") or 0),
                "saved_at": float(os.getenv("SCHWAB_TOKEN_SAVED_AT", "0") or 0),
            }
            if not tokens["access_token"] or expired(tokens):
                return self.refresh_tokens(tokens)
            return tokens
        if self.auth_callback_url:
            return self.exchange_callback_url(self.auth_callback_url)
        return {}

    def save_tokens(self, tokens: dict) -> None:
        tokens["saved_at"] = time.time()
        os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
        with open(self.token_file, "w") as f:
            json.dump(tokens, f, indent=2)

    def refresh_tokens(self, tokens: dict) -> dict:
        if not self.client_id or not self.client_secret:
            raise RuntimeError("SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET are required")
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": tokens.get("refresh_token", "")},
            timeout=15,
        )
        if resp.status_code in (400, 401, 403):
            raise RuntimeError("Schwab refresh token is expired or invalid; generate a fresh refresh token")
        resp.raise_for_status()
        new_tokens = resp.json()
        if "refresh_token" not in new_tokens:
            new_tokens["refresh_token"] = tokens.get("refresh_token")
        self.save_tokens(new_tokens)
        return new_tokens

    def exchange_callback_url(self, callback_url: str) -> dict:
        if not self.client_id or not self.client_secret:
            raise RuntimeError("SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET are required")
        code = callback_code(callback_url)
        if not code:
            raise RuntimeError("SCHWAB_AUTH_CALLBACK_URL does not contain a Schwab authorization code")
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
            timeout=15,
        )
        if resp.status_code in (400, 401, 403):
            detail = oauth_error_detail(resp)
            raise RuntimeError(f"Schwab authorization exchange rejected ({resp.status_code}): {detail}")
        resp.raise_for_status()
        tokens = resp.json()
        self.save_tokens(tokens)
        LOG.info("Schwab authorization completed; remove SCHWAB_AUTH_CALLBACK_URL from Railway")
        return tokens

    def _parse_side(self, symbol: str, exp_map: dict, side: OptionSide, underlying: float, now: datetime) -> list[OptionSnapshot]:
        out = []
        for exp_key, strikes in exp_map.items():
            expiration = parse_expiration(exp_key)
            if not expiration:
                continue
            dte = max((expiration - now.date()).days, 0)
            for strike_text, contracts in strikes.items():
                strike = num(strike_text)
                if strike is None:
                    continue
                for raw in contracts:
                    bid = num(raw.get("bid"))
                    ask = num(raw.get("ask"))
                    mark = num(raw.get("mark")) or midpoint(bid, ask) or num(raw.get("last")) or 0
                    contract = OptionContract(
                        symbol=symbol,
                        option_symbol=raw.get("symbol") or f"{symbol}_{expiration}_{strike}_{side.value}",
                        expiration=expiration,
                        strike=strike,
                        side=side,
                        dte=dte,
                    )
                    out.append(OptionSnapshot(
                        contract=contract,
                        volume=int(raw.get("totalVolume") or raw.get("volume") or 0),
                        open_interest=int(raw.get("openInterest") or 0),
                        mark=mark,
                        underlying_price=underlying,
                        timestamp=now,
                        bid=bid,
                        ask=ask,
                        delta=num(raw.get("delta")),
                        gamma=num(raw.get("gamma")),
                    ))
        return out

    def _filter_near_spot(self, snapshots: list[OptionSnapshot], underlying: float) -> list[OptionSnapshot]:
        lower = underlying * (1 - self.settings.strike_range_pct)
        upper = underlying * (1 + self.settings.strike_range_pct)
        kept = []
        for snap in snapshots:
            if snap.contract.dte > self.settings.max_dte:
                continue
            thresholds = self.settings.thresholds_for(snap.contract.symbol)
            premium = max(snap.mark or 0, 0) * snap.volume * 100
            exceptional = snap.volume >= thresholds.min_volume * 4
            whale_flow = premium >= thresholds.long_dte_min_premium
            if lower <= snap.contract.strike <= upper or exceptional or whale_flow:
                kept.append(snap)
        return kept


def expired(tokens: dict) -> bool:
    return time.time() > tokens.get("saved_at", 0) + tokens.get("expires_in", 1800) - 300


def oauth_error_detail(response) -> str:
    try:
        payload = response.json()
        return str(payload.get("error_description") or payload.get("error") or "authorization rejected")[:300]
    except (TypeError, ValueError):
        return "authorization rejected"


def parse_expiration(exp_key: str):
    try:
        return datetime.strptime(exp_key.split(":")[0], "%Y-%m-%d").date()
    except Exception:
        return None


def num(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def midpoint(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2


def extract_underlying_price(data: dict) -> float | None:
    for key in ("underlyingPrice", "lastPrice"):
        value = num(data.get(key))
        if value:
            return value
    underlying = data.get("underlying") or {}
    for key in ("last", "lastPrice", "mark", "close"):
        value = num(underlying.get(key))
        if value:
            return value
    return None
