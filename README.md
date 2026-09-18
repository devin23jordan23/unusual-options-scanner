# Unusual Options Activity Scanner

Separate Railway-ready repo for a read-only Schwab unusual options activity scanner.

Production command:

```bash
python -m app.main
```

This is not the old stock scanner and does not import it at runtime. Schwab auth/token logic was copied and refactored from the existing Trading Scanner folder into `app/schwab.py`.

## What It Does

- Watches `CORE_UNIVERSE | UOA_IN_PLAY`
- Loads near-term Schwab option chains
- Scans 0DTE through 60DTE with stricter requirements for noisy ETFs and longer-dated flow
- Focuses strikes near spot, with exceptional-volume escape hatch
- Detects unusual volume, Vol/OI, large estimated premium, and 5-minute acceleration
- Detects underlying stock-volume surges with price movement, intraday range expansion, and 5-minute burst ratios
- Lets 30DTE-60DTE whale flow through when premium/Vol-OI is meaningful
- Ranks individual contracts without emitting multi-strike cluster alerts
- Suppresses duplicate alerts with cooldown and escalation rules
- Warms up on the first snapshot, ranks candidates, and sends at most three distinct tickers per cycle
- Compresses grouped strikes into one summary and applies a 15-minute ticker-wide cooldown
- Sends one Discord webhook embed destination
- Supports mock mode for weekends/off-market testing

See [`docs/UNDERLYING_VOLUME_SCANNER.md`](docs/UNDERLYING_VOLUME_SCANNER.md) for the underlying-volume model and tuning plan.

## Required Railway Variables

```text
SCHWAB_CLIENT_ID=
SCHWAB_CLIENT_SECRET=
SCHWAB_REFRESH_TOKEN=
DISCORD_UNUSUAL_OPTIONS_WEBHOOK=
SCANNER_MODE=live
SCANNER_TIMEZONE=America/New_York
DATA_DIR=/app/data
LOG_LEVEL=INFO
```

For initial authorization without Telegram, follow
[`docs/RAILWAY_SETUP.md`](docs/RAILWAY_SETUP.md). The scanner accepts the full
Schwab redirect URL through a temporary `SCHWAB_AUTH_CALLBACK_URL` variable.

## Mock Mode

```bash
SCANNER_MODE=mock UOA_MOCK_CYCLES=5 UOA_POLL_SECONDS=1 python -m app.main
```

If `DISCORD_UNUSUAL_OPTIONS_WEBHOOK` is blank, mock alerts are logged and not sent.

## Tune Tickers

Permanent universe:

```text
UOA_CORE_UNIVERSE=SPY,QQQ,IWM,TSLA,NVDA,...
```

Temporary in-play names:

```text
UOA_IN_PLAY=CRWD,SMCI
```

Underlying volume scanner knobs:

```text
UVS_ENABLED=true
UVS_MIN_5M_VOLUME=100000
UVS_MIN_5M_DOLLAR_VOLUME=15000000
UVS_MIN_BURST_RATIO=2.0
UVS_MIN_CHANGE_FROM_CLOSE_PCT=1.5
UVS_MIN_CHANGE_FROM_OPEN_PCT=0.8
UVS_MIN_5M_PRICE_CHANGE_PCT=0.45
UVS_MIN_DAY_RANGE_PCT=1.2
```

## Tests

```bash
python -m unittest discover -s tests
```

## Schwab Limitation

V1 uses Schwab REST option-chain data. It does not reconstruct exchange sweeps and does not scan the entire US options universe. If Schwab streaming `LEVELONE_OPTIONS` or option screener access is added later, it can replace the data adapter without rewriting the scanner rules.
