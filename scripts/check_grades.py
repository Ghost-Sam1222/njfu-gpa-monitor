#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

DEFAULT_BASE_URL = "https://jwxt.njfu.edu.cn"
DEFAULT_STATE_PATH = Path("data/grade_state.json")


class MonitorError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str
    password: str
    semester: str
    bark_server: str
    bark_device_key: str
    bark_group: str
    bark_sound: str
    bark_icon: str
    enabled: bool
    monitor_until: Optional[date]
    check_start_date: Optional[date]
    expected_course_names: tuple[str, ...]
    expected_new_count: int
    notify_on_first_run: bool
    state_salt: str
    state_path: Path


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def parse_bool(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


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


def load_settings() -> Settings:
    load_dotenv()
    today = date.today()
    username = env("JW_USERNAME")
    password = env("JW_PASSWORD")
    device_key = env("BARK_DEVICE_KEY")
    salt = env("GRADE_STATE_SALT")
    if not username or not password:
        raise MonitorError("Missing JW_USERNAME or JW_PASSWORD.")
    if not device_key:
        raise MonitorError("Missing BARK_DEVICE_KEY.")
    if not salt:
        raise MonitorError("Missing GRADE_STATE_SALT.")
    if salt == "replace-with-long-random-secret" or len(salt) < 32:
        raise MonitorError("GRADE_STATE_SALT must be a random string of at least 32 characters.")
    return Settings(
        base_url=env("JW_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        username=username,
        password=password,
        semester=env("JW_SEMESTER", infer_semester(today)),
        bark_server=env("BARK_SERVER", "https://api.day.app").rstrip("/"),
        bark_device_key=device_key,
        bark_group=env("BARK_GROUP", "NJFU-GPA"),
        bark_sound=env("BARK_SOUND", "telegraph"),
        bark_icon=env("BARK_ICON"),
        enabled=parse_bool(env("MONITOR_ENABLED", "true"), default=True),
        monitor_until=parse_date(env("MONITOR_UNTIL")),
        check_start_date=parse_date(env("CHECK_START_DATE")),
        expected_course_names=parse_csv(env("EXPECTED_COURSE_NAMES")),
        expected_new_count=int(env("EXPECTED_NEW_COUNT", "0")),
        notify_on_first_run=parse_bool(env("NOTIFY_ON_FIRST_RUN"), default=False),
        state_salt=salt,
        state_path=Path(env("GRADE_STATE_PATH", str(DEFAULT_STATE_PATH))),
    )


async def fetch_grades(settings: Settings) -> list[dict[str, str]]:
    from playwright.async_api import async_playwright

    login_url = f"{settings.base_url}/jsxsd/framework/xsMainV.jsp"
    grade_url = f"{settings.base_url}/jsxsd/kscj/cjcx_list"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        try:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            if "authserver/login" in page.url:
                await page.fill("#username", settings.username)
                await page.fill("#password", settings.password)
                await page.click('button[type="submit"]')
                await page.wait_for_load_state("domcontentloaded", timeout=60000)
                await page.wait_for_timeout(1500)
            if "authserver/login" in page.url:
                raise MonitorError("Browser login stayed on the unified-auth login page.")
            await page.goto(grade_url, wait_until="domcontentloaded", timeout=60000)
            html = await page.content()
            grades = parse_grades_html(html)
            if grades:
                return grades
            grades = await post_grade_query(page, grade_url)
            if not grades:
                raise MonitorError("Could not parse grade table from the grade page.")
            return grades
        finally:
            await browser.close()


async def post_grade_query(page: Any, grade_url: str) -> list[dict[str, str]]:
    html = await page.evaluate(
        """async (url) => {
            const form = new URLSearchParams({kksj: '', kcxz: '', kcsx: '', kcmc: '', xsfs: 'all'});
            const res = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: form.toString(),
                credentials: 'include'
            });
            return await res.text();
        }""",
        grade_url,
    )
    return parse_grades_html(html)


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_grades_html(html: str) -> list[dict[str, str]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "dataList"})
    if table is None:
        return []
    grades: list[dict[str, str]] = []
    for row in table.find_all("tr")[1:]:
        cols = [normalize_text(col.get_text(" ", strip=True)) for col in row.find_all("td")]
        if len(cols) < 9:
            continue
        grades.append(
            {
                "semester": cols[1] if len(cols) > 1 else "",
                "course_code": cols[2] if len(cols) > 2 else "",
                "course_name": cols[3] if len(cols) > 3 else "",
                "score": cols[4] if len(cols) > 4 else "",
                "credit": cols[6] if len(cols) > 6 else "",
                "gpa": cols[8] if len(cols) > 8 else "",
                "course_type": cols[13] if len(cols) > 13 else "",
            }
        )
    return [grade for grade in grades if grade["course_name"] and grade["score"]]


def grade_identity(settings: Settings, grade: dict[str, str]) -> str:
    payload = "|".join(
        [
            settings.state_salt,
            grade.get("semester", ""),
            grade.get("course_code", ""),
            grade.get("course_name", ""),
            grade.get("score", ""),
            grade.get("credit", ""),
            grade.get("gpa", ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"hashes": [], "complete": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"hashes": [], "complete": False}


def save_state(settings: Settings, grades: list[dict[str, str]], complete: bool) -> None:
    settings.state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "semester": settings.semester,
        "known_count": len(grades),
        "hashes": sorted(grade_identity(settings, grade) for grade in grades),
        "complete": complete,
    }
    settings.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def matches_expected(name: str, expected: str) -> bool:
    compact_name = re.sub(r"\s+", "", name)
    compact_expected = re.sub(r"\s+", "", expected)
    return compact_expected in compact_name or compact_name in compact_expected


def is_complete(settings: Settings, grades: list[dict[str, str]]) -> bool:
    if settings.expected_course_names:
        names = [grade["course_name"] for grade in grades]
        return all(any(matches_expected(name, expected) for name in names) for expected in settings.expected_course_names)
    if settings.expected_new_count > 0:
        return len(grades) >= settings.expected_new_count
    return False


def bark_push(settings: Settings, title: str, body: str) -> None:
    import requests

    url = f"{settings.bark_server}/{quote(settings.bark_device_key)}/{quote(title)}/{quote(body)}"
    params = {
        "group": settings.bark_group,
        "sound": settings.bark_sound,
        "level": "timeSensitive",
    }
    if settings.bark_icon:
        params["icon"] = settings.bark_icon
    response = requests.get(url, params=params, timeout=20)
    if response.status_code >= 400:
        raise MonitorError(f"Bark push failed: HTTP {response.status_code} {response.text[:200]}")


def format_grade(grade: dict[str, str]) -> str:
    parts = [
        f"成绩：{grade.get('score', '')}",
        f"绩点：{grade.get('gpa', '')}",
        f"学分：{grade.get('credit', '')}",
    ]
    return f"{grade.get('course_name', '新成绩')}｜" + "，".join(part for part in parts if not part.endswith("："))


def should_skip(settings: Settings, state: dict[str, Any]) -> bool:
    today = date.today()
    if not settings.enabled:
        print("Monitor disabled by MONITOR_ENABLED=false.")
        return True
    if settings.check_start_date and today < settings.check_start_date:
        print(f"Before CHECK_START_DATE={settings.check_start_date}; skipping.")
        return True
    if settings.monitor_until and today > settings.monitor_until:
        print(f"After MONITOR_UNTIL={settings.monitor_until}; skipping.")
        return True
    if state.get("complete"):
        print("Expected courses are already complete; skipping login.")
        return True
    return False


def run() -> None:
    settings = load_settings()
    state = load_state(settings.state_path)
    if should_skip(settings, state):
        return

    grades = asyncio.run(fetch_grades(settings))
    known_hashes = set(state.get("hashes") or [])
    first_run = not known_hashes
    new_grades = [
        grade
        for grade in grades
        if grade_identity(settings, grade) not in known_hashes
    ]
    complete = is_complete(settings, grades)

    if first_run and not settings.notify_on_first_run:
        print(f"Initialized baseline with {len(grades)} grades; no push on first run.")
        save_state(settings, grades, complete)
        return

    for grade in new_grades:
        bark_push(settings, "NJFU GPA 新成绩", format_grade(grade))
        print("Pushed one new grade notification.")

    if complete and not state.get("complete"):
        bark_push(settings, "NJFU GPA 监控完成", f"已检测到 {len(grades)} 门成绩，监控将自动停止重登录。")

    save_state(settings, grades, complete)
    print(f"Checked {len(grades)} grades; new={len(new_grades)} complete={complete}.")


def main() -> int:
    try:
        run()
        return 0
    except MonitorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
