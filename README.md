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
- Lets 30DTE-60DTE whale flow through when premium/Vol-OI is meaningful
- Ranks individual contracts without emitting multi-strike cluster alerts
- Suppresses duplicate alerts with cooldown and escalation rules
- Warms up on the first snapshot, ranks candidates, and sends at most three distinct tickers per cycle
- Compresses grouped strikes into one summary and applies a 15-minute ticker-wide cooldown
- Sends a persistent top-calls/top-puts Discord report at 4:05 PM Eastern
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

## Tests

```bash
python -m unittest discover -s tests
```

## Pre-Market Brief Service

The 8:45 AM ET pre-market brief is a separate Railway cron service. It uses OpenAI web
search to generate the report and posts the finished Markdown to Discord. It
does not use Schwab.

Use `railway.premarket.json` as the service's Railway config file and set:

```text
OPENAI_API_KEY=
DISCORD_PREMARKET_WEBHOOK=
PREMARKET_TIMEZONE=America/New_York
```

The service runs at both possible UTC equivalents of 8:45 AM Eastern and the
application's timezone guard allows only the correct run to publish. To test a
deployment manually, override the start command temporarily or run:

```bash
python -m app.premarket --force
```

## Schwab Limitation

V1 uses Schwab REST option-chain data. It does not reconstruct exchange sweeps and does not scan the entire US options universe. If Schwab streaming `LEVELONE_OPTIONS` or option screener access is added later, it can replace the data adapter without rewriting the scanner rules.
