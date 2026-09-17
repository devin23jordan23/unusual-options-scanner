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

## Schwab Authorization Without Telegram

Mount a persistent Railway volume at `/app/data` before authorizing. After
signing into Schwab, the browser redirects to `https://127.0.0.1/...` and may
show a connection error. Copy that full browser address into this temporary
Railway variable:

```text
SCHWAB_AUTH_CALLBACK_URL=https://127.0.0.1/?code=...
```

Deploy immediately. The scanner exchanges the one-time code and stores the
result in `/app/data/schwab_tokens.json`. When the logs say authorization
completed, delete `SCHWAB_AUTH_CALLBACK_URL` and redeploy. Never paste the
callback URL into Discord, source control, or chat.
