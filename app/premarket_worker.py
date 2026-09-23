import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .premarket import PremarketSettings, generate_report, load_prompt, load_settings, publish_report


LOG = logging.getLogger(__name__)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"sent": {}, "last_attempt": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("sent", {})
        data.setdefault("last_attempt", {})
        return data
    except (OSError, ValueError, TypeError):
        LOG.exception("Could not read premarket worker state; starting with empty state")
        return {"sent": {}, "last_attempt": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def target_minutes(settings: PremarketSettings, report_kind: str) -> int:
    if report_kind == "opening":
        return settings.open_report_hour * 60 + settings.open_report_minute
    return settings.report_hour * 60 + settings.report_minute


def is_due(
    settings: PremarketSettings,
    state: dict,
    report_kind: str,
    now: datetime,
    retry_seconds: int,
) -> bool:
    if now.weekday() >= 5:
        return False
    today = now.date().isoformat()
    if state.get("sent", {}).get(report_kind) == today:
        return False
    if now.hour * 60 + now.minute < target_minutes(settings, report_kind):
        return False
    attempted_at = state.get("last_attempt", {}).get(report_kind)
    if attempted_at:
        try:
            previous = datetime.fromisoformat(attempted_at)
            if (now - previous).total_seconds() < retry_seconds:
                return False
        except ValueError:
            pass
    return True


class PremarketWorker:
    def __init__(self, settings: PremarketSettings, state_path: Path, retry_seconds: int = 300):
        self.settings = settings
        self.state_path = state_path
        self.retry_seconds = retry_seconds
        self.state = load_state(state_path)

    def run_once(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(ZoneInfo(self.settings.timezone))
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo(self.settings.timezone))
        else:
            now = now.astimezone(ZoneInfo(self.settings.timezone))

        sent: list[str] = []
        for report_kind in ("premarket", "opening"):
            if not is_due(self.settings, self.state, report_kind, now, self.retry_seconds):
                continue
            self.state["last_attempt"][report_kind] = now.isoformat()
            save_state(self.state_path, self.state)
            try:
                LOG.info("Generating overdue-or-due %s report", report_kind)
                report = generate_report(self.settings, load_prompt(self.settings, now, report_kind))
                parts = publish_report(self.settings, report)
            except Exception:
                LOG.exception(
                    "%s report failed; retrying in %s seconds",
                    report_kind,
                    self.retry_seconds,
                )
                continue
            self.state["sent"][report_kind] = now.date().isoformat()
            save_state(self.state_path, self.state)
            sent.append(report_kind)
            LOG.info("%s report delivered in %s Discord message(s)", report_kind, parts)
        return sent


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    data_dir = Path(os.getenv("PREMARKET_DATA_DIR", os.getenv("DATA_DIR", "/app/data")))
    poll_seconds = max(15, int(os.getenv("PREMARKET_WORKER_POLL_SECONDS", "60")))
    retry_seconds = max(60, int(os.getenv("PREMARKET_RETRY_SECONDS", "300")))
    worker = PremarketWorker(settings, data_dir / "premarket_worker_state.json", retry_seconds)
    LOG.info(
        "Premarket worker started; targets %02d:%02d and %02d:%02d %s",
        settings.report_hour,
        settings.report_minute,
        settings.open_report_hour,
        settings.open_report_minute,
        settings.timezone,
    )
    while True:
        worker.run_once()
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
