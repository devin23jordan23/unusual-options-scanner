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
- Prioritizes 0DTE, then 1DTE-7DTE
- Focuses strikes near spot, with exceptional-volume escape hatch
- Detects unusual volume, Vol/OI, large estimated premium, and 5-minute acceleration
- Aggregates nearby abnormal strikes into ticker-level call/put surge alerts
- Suppresses duplicate alerts with cooldown and escalation rules
- Sends one Discord webhook embed destination
- Supports mock mode for weekends/off-market testing

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

## Tests

```bash
python -m unittest discover -s tests
```

## Schwab Limitation

V1 uses Schwab REST option-chain data. It does not reconstruct exchange sweeps and does not scan the entire US options universe. If Schwab streaming `LEVELONE_OPTIONS` or option screener access is added later, it can replace the data adapter without rewriting the scanner rules.
