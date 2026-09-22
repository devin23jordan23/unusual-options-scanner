import argparse
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


LOG = logging.getLogger(__name__)
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DISCORD_MESSAGE_LIMIT = 1900
DEFAULT_WATCHLIST = (
    "NVDA,MU,TSLA,PLTR,AMZN,AMD,MSFT,GOOGL,AAPL,AVGO,CVX,CRCL,NBIS,"
    "SNDK,RKLB,AAOI,DELL,LITE,MRVL,XOM"
)


@dataclass(frozen=True)
class PremarketSettings:
    openai_api_key: str
    discord_webhook: str
    model: str = "gpt-6-astra"
    timezone: str = "America/New_York"
    report_hour: int = 8
    report_minute: int = 45
    open_report_hour: int = 9
    open_report_minute: int = 55
    schedule_window_minutes: int = 10
    watchlist: str = DEFAULT_WATCHLIST
    prompt_path: str = "prompts/premarket_brief.md"
    open_prompt_path: str = "prompts/opening_watch.md"
    max_output_tokens: int = 14000
    reasoning_effort: str = "high"
    log_level: str = "INFO"


def load_settings() -> PremarketSettings:
    return PremarketSettings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        discord_webhook=os.getenv(
            "DISCORD_PREMARKET_WEBHOOK",
            os.getenv("DISCORD_UNUSUAL_OPTIONS_WEBHOOK", ""),
        ),
        model=os.getenv("PREMARKET_OPENAI_MODEL", "gpt-6-astra"),
        timezone=os.getenv("PREMARKET_TIMEZONE", "America/New_York"),
        report_hour=int(os.getenv("PREMARKET_REPORT_HOUR", "8")),
        report_minute=int(os.getenv("PREMARKET_REPORT_MINUTE", "45")),
        open_report_hour=int(os.getenv("PREMARKET_OPEN_REPORT_HOUR", "9")),
        open_report_minute=int(os.getenv("PREMARKET_OPEN_REPORT_MINUTE", "55")),
        schedule_window_minutes=int(os.getenv("PREMARKET_SCHEDULE_WINDOW_MINUTES", "10")),
        watchlist=os.getenv("PREMARKET_WATCHLIST", DEFAULT_WATCHLIST),
        prompt_path=os.getenv("PREMARKET_PROMPT_PATH", "prompts/premarket_brief.md"),
        open_prompt_path=os.getenv("PREMARKET_OPEN_PROMPT_PATH", "prompts/opening_watch.md"),
        max_output_tokens=int(os.getenv("PREMARKET_MAX_OUTPUT_TOKENS", "14000")),
        reasoning_effort=os.getenv("PREMARKET_REASONING_EFFORT", "high"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def scheduled_report(settings: PremarketSettings, now: datetime | None = None) -> str | None:
    now = now or datetime.now(ZoneInfo(settings.timezone))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo(settings.timezone))
    else:
        now = now.astimezone(ZoneInfo(settings.timezone))
    if now.weekday() >= 5:
        return None
    current_minutes = now.hour * 60 + now.minute
    schedules = {
        "premarket": settings.report_hour * 60 + settings.report_minute,
        "opening": settings.open_report_hour * 60 + settings.open_report_minute,
    }
    for report_kind, target_minutes in schedules.items():
        if 0 <= current_minutes - target_minutes < settings.schedule_window_minutes:
            return report_kind
    return None


def scheduled_now(settings: PremarketSettings, now: datetime | None = None) -> bool:
    return scheduled_report(settings, now) is not None


def load_prompt(
    settings: PremarketSettings,
    now: datetime | None = None,
    report_kind: str = "premarket",
) -> str:
    now = now or datetime.now(ZoneInfo(settings.timezone))
    prompt_path = Path(settings.open_prompt_path if report_kind == "opening" else settings.prompt_path)
    if not prompt_path.is_absolute():
        prompt_path = Path(__file__).resolve().parents[1] / prompt_path
    template = prompt_path.read_text(encoding="utf-8")
    return template.format(
        current_datetime=now.strftime("%A, %B %-d, %Y | %-I:%M %p %Z"),
        watchlist=settings.watchlist,
    )


def extract_output_text(response: dict) -> str:
    parts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    text = "\n".join(parts).strip()
    if not text:
        detail = response.get("incomplete_details") or response.get("error") or response.get("status")
        raise RuntimeError(f"OpenAI returned no report text: {detail}")
    return text


def generate_report(settings: PremarketSettings, prompt: str) -> str:
    import requests

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    payload = {
        "model": settings.model,
        "tools": [{"type": "web_search"}],
        "input": prompt,
        "reasoning": {"effort": settings.reasoning_effort},
        "max_output_tokens": settings.max_output_tokens,
        "store": False,
    }
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=900,
    )
    if not response.ok:
        raise RuntimeError(f"OpenAI request failed ({response.status_code}): {response.text[:1000]}")
    return extract_output_text(response.json())


def split_report(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in text.strip().splitlines():
        pieces = [line[i : i + limit] for i in range(0, len(line), limit)] or [""]
        for piece in pieces:
            candidate = piece if not current else f"{current}\n{piece}"
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def post_discord_message(webhook_url: str, content: str, label: str) -> None:
    import requests

    for attempt in range(5):
        response = requests.post(
            webhook_url,
            params={"wait": "true"},
            json={"username": "Andre's Pre-Market Brief", "content": content},
            timeout=30,
        )
        if response.status_code == 429:
            retry_after = float(response.json().get("retry_after", 1))
            time.sleep(min(retry_after, 30))
            continue
        if response.ok:
            return
        LOG.warning("Discord send failed for %s attempt %s: %s", label, attempt + 1, response.text[:500])
        time.sleep(2**attempt)
    raise RuntimeError(f"Discord delivery failed after retries: {label}")


def publish_report(settings: PremarketSettings, report: str) -> int:
    if not settings.discord_webhook:
        raise RuntimeError("DISCORD_PREMARKET_WEBHOOK is required")
    chunks = split_report(report)
    for index, chunk in enumerate(chunks, start=1):
        post_discord_message(settings.discord_webhook, chunk, f"part {index}/{len(chunks)}")
        if index < len(chunks):
            time.sleep(0.4)
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and publish Andre's pre-market brief")
    parser.add_argument("--force", action="store_true", help="ignore the weekday and schedule guard")
    parser.add_argument("--report", choices=("premarket", "opening"), default=None)
    parser.add_argument("--dry-run", action="store_true", help="generate and print without posting to Discord")
    args = parser.parse_args()

    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    now = datetime.now(ZoneInfo(settings.timezone))
    report_kind = args.report or scheduled_report(settings, now)
    if not args.force and report_kind is None:
        LOG.info("Outside the configured premarket window; nothing to send (%s)", now.isoformat())
        return
    report_kind = report_kind or "premarket"

    LOG.info("Generating %s report with %s", report_kind, settings.model)
    report = generate_report(settings, load_prompt(settings, now, report_kind))
    if args.dry_run:
        print(report)
        return
    parts = publish_report(settings, report)
    LOG.info("Premarket brief delivered to Discord in %s message(s)", parts)


if __name__ == "__main__":
    main()
