from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from notifications import NotificationError, NotificationSettings

DEFAULT_BASE_URL = "https://jwxt.njfu.edu.cn"


class ConfigError(RuntimeError):
    pass


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value.strip()


def parse_bool(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ConfigError("Dates must use YYYY-MM-DD format.") from exc


def parse_int(name: str, value: str, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc
    if parsed < minimum:
        raise ConfigError(f"{name} must be at least {minimum}.")
    return parsed


def parse_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in re.split(r"[,，\n]", value) if part.strip())


def infer_semester(today: date) -> str:
    if today.month >= 8:
        return f"{today.year}-{today.year + 1}-1"
    return f"{today.year - 1}-{today.year}-2"


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str
    password: str
    cookie: str
    semester: str
    enabled: bool
    monitor_until: date | None
    check_start_date: date | None
    expected_course_names: tuple[str, ...]
    expected_grade_count: int
    notify_on_first_run: bool
    email_batch_size: int
    final_report_enabled: bool
    state_salt: str
    state_path: Path
    report_path: Path
    notifications: NotificationSettings


def load_settings() -> Settings:
    load_dotenv()
    username = env("JW_USERNAME")
    password = env("JW_PASSWORD")
    cookie = env("JW_COOKIE")
    salt = env("GRADE_STATE_SALT")
    if not cookie and (not username or not password):
        raise ConfigError("Set JW_USERNAME and JW_PASSWORD, or provide JW_COOKIE.")
    if salt == "replace-with-long-random-secret" or len(salt) < 32:
        raise ConfigError("GRADE_STATE_SALT must be a random string of at least 32 characters.")
    expected_count = parse_int(
        "EXPECTED_GRADE_COUNT",
        env("EXPECTED_GRADE_COUNT", env("EXPECTED_NEW_COUNT", "0")),
    )
    email_batch_size = parse_int("EMAIL_BATCH_SIZE", env("EMAIL_BATCH_SIZE", "3"), 1)
    try:
        notifications = NotificationSettings.from_env()
    except NotificationError as exc:
        raise ConfigError(str(exc)) from exc
    notification_errors = notifications.configuration_errors()
    if notification_errors:
        raise ConfigError("; ".join(notification_errors))
    return Settings(
        base_url=env("JW_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        username=username,
        password=password,
        cookie=cookie,
        semester=env("JW_SEMESTER", infer_semester(date.today())),
        enabled=parse_bool(env("MONITOR_ENABLED", "true"), True),
        monitor_until=parse_date(env("MONITOR_UNTIL")),
        check_start_date=parse_date(env("CHECK_START_DATE")),
        expected_course_names=parse_csv(env("EXPECTED_COURSE_NAMES")),
        expected_grade_count=expected_count,
        notify_on_first_run=parse_bool(env("NOTIFY_ON_FIRST_RUN"), False),
        email_batch_size=email_batch_size,
        final_report_enabled=parse_bool(env("FINAL_REPORT_ENABLED", "true"), True),
        state_salt=salt,
        state_path=Path(env("GRADE_STATE_PATH", "data/grade_state.json")),
        report_path=Path(env("GRADE_REPORT_PATH", "reports/transcript.html")),
        notifications=notifications,
    )
