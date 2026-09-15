# Railway Setup

Deploy command is configured to run:

```bash
python -m app.main
```

Required Railway variables:

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

Optional tuning variables are listed in `.env.example`.

Runtime state is stored under `data/`:

```text
data/schwab_tokens.json
data/alert_state.json
```

Those JSON files are ignored by git. On Railway, set `SCHWAB_REFRESH_TOKEN`
so the scanner can refresh its access token and pull Schwab market data after
deploys or restarts.
