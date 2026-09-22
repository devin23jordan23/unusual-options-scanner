# Railway Setup

Configure the existing scanner service's Railway start command as:

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

## Separate Pre-Market Brief Cron Service

Create two services from this same GitHub repository. Configure the premarket
service to run `python -m app.premarket --report premarket` on
`45 12,13 * * 1-5`. Configure the opening-watch service to run
`python -m app.premarket --report opening` on `55 13,14 * * 1-5`. Set both
restart policies to `Never`. The application checks Eastern time and exits
without sending on the extra daylight-saving-time run.

Required variables for only this service:

```text
OPENAI_API_KEY=
DISCORD_PREMARKET_WEBHOOK=
PREMARKET_TIMEZONE=America/New_York
```

The Discord variable may use the same webhook as the options scanner. Keep the
OpenAI key in Railway variables and never commit it to the repository.

## Schwab Authorization Without Telegram

Mount a persistent Railway volume at `/app/data` before authorizing. Generate a
public Railway domain for the service, set a temporary strong
`SCHWAB_AUTH_SETUP_KEY`, and deploy before starting the Schwab login. Then open:

```text
https://YOUR-RAILWAY-DOMAIN/schwab-auth
```

Use the page's Schwab login link. After Schwab redirects to
`https://127.0.0.1/?code=...`, immediately paste that complete address and the
setup key into the already-running authorization page. No deployment occurs
while the short-lived code is active. The scanner stores tokens in
`/app/data/schwab_tokens.json`. Delete `SCHWAB_AUTH_SETUP_KEY` and any old
`SCHWAB_AUTH_CALLBACK_URL` after success. Never paste the callback URL into
Discord, source control, or chat.
