from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Any, Protocol
from urllib.parse import urlparse

from config import DEFAULT_BASE_URL, infer_semester
from models import Exam


class ExamSourceError(RuntimeError):
    pass


class ExamAuthenticationError(ExamSourceError):
    pass


class ExamParseError(ExamSourceError):
    pass


class ExamSettings(Protocol):
    base_url: str
    username: str
    password: str
    cookie: str
    semester: str


@dataclass(frozen=True)
class ExamProject:
    project_id: str
    name: str


@dataclass(frozen=True)
class ExamFetchResult:
    exams: tuple[Exam, ...]
    projects: tuple[ExamProject, ...]
    failed_projects: tuple[ExamProject, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.failed_projects


ALLOWED_NJFU_HOSTS = {
    "jwxt.njfu.edu.cn",
    "authserver.njfu.edu.cn",
    "uia.njfu.edu.cn",
}
EXAM_QUERY_PATH = "/jsxsd/xsks/xsksap_query"
EXAM_PROJECTS_PATH = "/jsxsd/xsks/xsksap_ksmc"
EXAM_LIST_PATH = "/jsxsd/xsks/xsksap_list"


def _is_njfu_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in ALLOWED_NJFU_HOSTS


def _require_njfu_url(url: str) -> None:
    if not _is_njfu_url(url):
        raise ExamSourceError("Refusing to send credentials outside approved NJFU HTTPS hosts.")


def _is_login_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host in {"authserver.njfu.edu.cn", "uia.njfu.edu.cn"} and "login" in parsed.path.lower()


def _cookie_entries(cookie_header: str, base_url: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for item in cookie_header.split(";"):
        if "=" not in item:
            continue
        name, value = item.strip().split("=", 1)
        if name:
            entries.append({"name": name, "value": value, "url": base_url})
    return entries


def parse_exam_projects(data: Any) -> list[ExamProject]:
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        raise ExamParseError("The exam project response is not a JSON list.")

    projects: list[ExamProject] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            raise ExamParseError("The exam project response contains an invalid item.")
        project_id = str(item.get("kw0401id") or "").strip()
        name = str(item.get("ksmc") or "").strip()
        if not project_id or not name:
            raise ExamParseError("The exam project response is missing kw0401id or ksmc.")
        if project_id not in seen:
            seen.add(project_id)
            projects.append(ExamProject(project_id, name))
    return projects


async def fetch_exams(settings: ExamSettings) -> ExamFetchResult:
    try:
        return await _fetch_exams(settings)
    except ExamSourceError:
        raise
    except Exception as exc:
        raise ExamSourceError(f"Exam browser step failed: {type(exc).__name__}") from exc


async def _fetch_exams(settings: ExamSettings) -> ExamFetchResult:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ExamSourceError("Playwright is not installed; run pip install -r requirements.txt.") from exc

    base_url = settings.base_url.rstrip("/")
    _require_njfu_url(base_url)
    login_url = f"{base_url}/jsxsd/framework/xsMainV.jsp"
    query_url = f"{base_url}{EXAM_QUERY_PATH}"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        if settings.cookie:
            cookies = _cookie_entries(settings.cookie, base_url)
            if cookies:
                await context.add_cookies(cookies)
        page = await context.new_page()
        try:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            if _is_login_url(page.url):
                if not settings.username or not settings.password:
                    raise ExamAuthenticationError(
                        "JW_COOKIE expired; configure JW_USERNAME and JW_PASSWORD as fallback."
                    )
                _require_njfu_url(page.url)
                await page.fill("#username", settings.username)
                await page.fill("#password", settings.password)
                await page.click('button[type="submit"]')
                await page.wait_for_load_state("domcontentloaded", timeout=60000)
                await page.wait_for_timeout(1200)
            _require_njfu_url(page.url)
            if _is_login_url(page.url):
                raise ExamAuthenticationError(
                    "Login did not complete; verify credentials or interactive verification requirements."
                )

            await page.goto(query_url, wait_until="domcontentloaded", timeout=60000)
            _require_njfu_url(page.url)
            if _is_login_url(page.url):
                raise ExamAuthenticationError("The NJFU login session expired before the exam query.")

            projects_text = await _fetch_exam_projects(page, base_url, settings.semester)
            projects = parse_exam_projects_text(projects_text)
            exams: list[Exam] = []
            failed: list[ExamProject] = []
            seen_keys: set[str] = set()

            for project in projects:
                try:
                    html = await _query_exam_project(page, base_url, settings.semester, project)
                    parsed, recognized = parse_exam_html(
                        html,
                        settings.semester,
                        project.project_id,
                        project.name,
                    )
                    if not recognized:
                        raise ExamParseError("The exam result table was not recognized.")
                    for exam in parsed:
                        key = exam.stable_key()
                        if key not in seen_keys:
                            seen_keys.add(key)
                            exams.append(exam)
                except ExamAuthenticationError:
                    raise
                except Exception:
                    failed.append(project)

            exams.sort(key=lambda item: (item.start_time, item.course_name, item.location))
            return ExamFetchResult(tuple(exams), tuple(projects), tuple(failed))
        finally:
            await browser.close()


async def _fetch_exam_projects(page: Any, base_url: str, semester: str) -> str:
    return await page.evaluate(
        """async ({url, semester}) => {
            const response = await fetch(`${url}?xnxqid=${encodeURIComponent(semester)}`, {
                method: 'GET',
                credentials: 'include'
            });
            if (!response.ok) throw new Error(`exam project query failed: ${response.status}`);
            return await response.text();
        }""",
        {"url": f"{base_url}{EXAM_PROJECTS_PATH}", "semester": semester},
    )


def parse_exam_projects_text(text: str) -> list[ExamProject]:
    text = text.lstrip("\ufeff")
    if _looks_like_login_page(text):
        raise ExamAuthenticationError("The NJFU login session expired during project discovery.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExamParseError("The exam project response is not valid JSON.") from exc
    return parse_exam_projects(data)


async def _query_exam_project(
    page: Any,
    base_url: str,
    semester: str,
    project: ExamProject,
) -> str:
    query_category = _infer_query_category(project.name)
    return await page.evaluate(
        """async ({url, semester, projectId, queryCategory}) => {
            const form = new URLSearchParams({
                xqlbmc: '',
                xnxqid: semester,
                kw0401id: projectId,
                xqlb: queryCategory
            });
            const response = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: form.toString(),
                credentials: 'include'
            });
            if (!response.ok) throw new Error(`exam query failed: ${response.status}`);
            return await response.text();
        }""",
        {
            "url": f"{base_url}{EXAM_LIST_PATH}",
            "semester": semester,
            "projectId": project.project_id,
            "queryCategory": query_category,
        },
    )


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_header(value: str) -> str:
    return re.sub(r"[\s:：()（）\[\]【】]", "", _normalize_text(value))


class _ExamTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.in_row = False
        self.cell_tag = ""
        self.cell_text: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.table_depth += 1
        elif self.table_depth and tag == "tr":
            self.in_row = True
            self.current_row = []
        elif self.in_row and tag in {"th", "td"}:
            self.cell_tag = tag
            self.cell_text = []
        elif self.cell_tag and tag == "br":
            self.cell_text.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell_tag:
            self.cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.cell_tag and tag == self.cell_tag:
            self.current_row.append(_normalize_text("".join(self.cell_text)))
            self.cell_tag = ""
            self.cell_text = []
        elif self.in_row and tag == "tr":
            if self.current_row and any(self.current_row):
                self.rows.append(self.current_row)
            self.in_row = False
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1


_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "campus": ("考试校区", "校区"),
    "course_code": ("课程编号", "课程代码"),
    "course_name": ("课程名称", "考试科目", "科目"),
    "exam_time": ("考试时间", "考试日期", "时间", "日期"),
    "location": ("考场", "考试地点", "地点", "教室"),
    "exam_type": ("考试类型", "考试方式"),
}


def _header_indexes(headers: list[str]) -> dict[str, int]:
    normalized = [_normalize_header(item) for item in headers]
    indexes: dict[str, int] = {}
    for field, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            target = _normalize_header(alias)
            if target in normalized:
                indexes[field] = normalized.index(target)
                break
    return indexes


def parse_exam_html(
    html: str,
    semester: str,
    project_id: str,
    project_name: str,
) -> tuple[list[Exam], bool]:
    if _looks_like_login_page(html):
        raise ExamAuthenticationError("The NJFU login session expired during the exam query.")

    parser = _ExamTableParser()
    parser.feed(html)
    rows = parser.rows
    for header_index, row in enumerate(rows):
        indexes = _header_indexes(row)
        if "course_name" not in indexes or "exam_time" not in indexes:
            continue
        exams = _parse_exam_rows(rows[header_index + 1 :], indexes, semester, project_id, project_name)
        return exams, True
    if "未查询到数据" in html or "暂无数据" in html:
        return [], True
    return [], False


def _looks_like_login_page(html: str) -> bool:
    lower = html.lower()
    return (
        (re.search(r"(?:name|id)\s*=\s*['\"]?username\b", lower) is not None)
        and (re.search(r"(?:name|id)\s*=\s*['\"]?password\b", lower) is not None)
    ) or (
        ("统一身份认证" in html or "unified identity authentication" in lower)
        and "login" in lower
    )


def _parse_exam_rows(
    rows: list[list[str]],
    indexes: dict[str, int],
    semester: str,
    project_id: str,
    project_name: str,
) -> list[Exam]:
    def value(row: list[str], field: str) -> str:
        index = indexes.get(field, -1)
        return row[index] if 0 <= index < len(row) else ""

    exams: list[Exam] = []
    for row in rows:
        course_name = value(row, "course_name")
        if not course_name or "未查询到数据" in course_name:
            continue
        start_time, end_time = _parse_datetime_range(value(row, "exam_time"), semester)
        if start_time is None or end_time is None:
            raise ExamParseError("An exam row has no parseable date and time.")
        exams.append(
            Exam(
                semester=semester,
                exam_project_id=project_id,
                exam_project_name=project_name,
                exam_type=value(row, "exam_type") or _infer_exam_type(project_name),
                campus=value(row, "campus") or _infer_campus(project_name),
                course_code=value(row, "course_code"),
                course_name=course_name,
                start_time=start_time,
                end_time=end_time,
                location=value(row, "location"),
            )
        )
    return exams


_DATE_PATTERNS = (
    re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"),
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"),
)
_MONTH_DAY_PATTERN = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?")
_TIME_RANGE_PATTERN = re.compile(
    r"(\d{1,2}:\d{2})\s*(?:-|~|－|—|至|到)\s*(\d{1,2}:\d{2})"
)
_SINGLE_TIME_PATTERN = re.compile(r"\b(\d{1,2}:\d{2})\b")
_SEMESTER_PATTERN = re.compile(r"(\d{4})-(\d{4})-([12])")


def _infer_year_from_semester(semester: str, month: int) -> int:
    match = _SEMESTER_PATTERN.fullmatch(semester)
    if not match:
        return date.today().year
    start_year, end_year, term = match.groups()
    if term == "1":
        return int(start_year if month >= 8 else end_year)
    return int(end_year)


def _parse_date(text: str, semester: str) -> date | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return date(*(int(part) for part in match.groups()))
            except ValueError:
                return None
    match = _MONTH_DAY_PATTERN.search(text)
    if not match:
        return None
    month, day = (int(part) for part in match.groups())
    try:
        return date(_infer_year_from_semester(semester, month), month, day)
    except ValueError:
        return None


def _parse_clock(value: str) -> time | None:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def _parse_datetime_range(text: str, semester: str = "") -> tuple[datetime | None, datetime | None]:
    normalized = _normalize_text(text)
    exam_date = _parse_date(normalized, semester)
    if exam_date is None:
        return None, None
    range_match = _TIME_RANGE_PATTERN.search(normalized)
    if range_match:
        start_clock = _parse_clock(range_match.group(1))
        end_clock = _parse_clock(range_match.group(2))
    else:
        single = _SINGLE_TIME_PATTERN.search(normalized)
        start_clock = _parse_clock(single.group(1)) if single else None
        end_clock = start_clock
    if start_clock is None or end_clock is None:
        return None, None
    return datetime.combine(exam_date, start_clock), datetime.combine(exam_date, end_clock)


def _infer_exam_type(project_name: str) -> str:
    if "机考" in project_name or "上机" in project_name:
        return "机考"
    if "补考" in project_name or "重修" in project_name:
        return "补考"
    if "期中" in project_name:
        return "期中考试"
    if "期末" in project_name:
        return "期末考试"
    return ""


def _infer_query_category(project_name: str) -> str:
    """Map the visible NJFU project name to the xsksap_list category field."""
    if "补考" in project_name or "期初" in project_name:
        return "1"
    if "期中" in project_name:
        return "2"
    return "3"


def _infer_campus(project_name: str) -> str:
    match = re.search(r"[（(]([^）)]*校区)[）)]", project_name)
    return match.group(1) if match else ""


def suggested_monitor_until(exams: tuple[Exam, ...] | list[Exam]) -> date | None:
    if not exams:
        return None
    return max(exam.end_time.date() for exam in exams) + timedelta(days=30)


def describe_result(result: ExamFetchResult) -> dict[str, Any]:
    latest = max((exam.end_time.date() for exam in result.exams), default=None)
    suggested = suggested_monitor_until(result.exams)
    return {
        "exam_count": len(result.exams),
        "project_count": len(result.projects),
        "latest_exam_date": latest.isoformat() if latest else None,
        "suggested_monitor_until": suggested.isoformat() if suggested else None,
        "complete": result.complete,
        "failed_project_count": len(result.failed_projects),
    }


async def suggestion_for_setup(settings: ExamSettings) -> dict[str, Any]:
    try:
        result = await fetch_exams(settings)
    except ExamSourceError:
        return {
            "exam_count": 0,
            "project_count": 0,
            "latest_exam_date": None,
            "suggested_monitor_until": None,
            "complete": False,
            "failed_project_count": 0,
            "error": "无法读取考试安排，请检查教务登录状态后重试。",
        }
    payload = describe_result(result)
    if not result.complete:
        payload["error"] = "部分考试项目查询失败，不能自动采用建议日期。"
    elif not result.exams:
        payload["error"] = "该学期暂未查询到考试安排，请稍后重试或手动填写停止日期。"
    return payload


def _exam_to_json(exam: Exam) -> dict[str, str]:
    return {
        "semester": exam.semester,
        "project_id": exam.exam_project_id,
        "project_name": exam.exam_project_name,
        "exam_type": exam.exam_type,
        "campus": exam.campus,
        "course_code": exam.course_code,
        "course_name": exam.course_name,
        "start_time": exam.start_time.isoformat(),
        "end_time": exam.end_time.isoformat(),
        "location": exam.location,
    }


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query NJFU exam arrangements.")
    parser.add_argument("--semester", default=os.environ.get("JW_SEMESTER") or infer_semester(date.today()))
    parser.add_argument("--base-url", default=os.environ.get("JW_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument(
        "--format",
        choices=("json", "summary", "latest", "suggested"),
        default="summary",
        help="Output full JSON, a private-safe summary, the latest exam date, or latest + 30 days.",
    )
    return parser


def _run_cli(argv: list[str] | None = None) -> int:
    args = _build_cli_parser().parse_args(argv)
    settings = SimpleNamespace(
        base_url=args.base_url,
        username=os.environ.get("JW_USERNAME", ""),
        password=os.environ.get("JW_PASSWORD", ""),
        cookie=os.environ.get("JW_COOKIE", ""),
        semester=args.semester,
    )
    if not settings.cookie and (not settings.username or not settings.password):
        print("error: set JW_USERNAME and JW_PASSWORD, or provide JW_COOKIE", file=sys.stderr)
        return 3
    try:
        result = asyncio.run(fetch_exams(settings))
    except ExamAuthenticationError:
        print("error: NJFU authentication failed", file=sys.stderr)
        return 3
    except ExamParseError as exc:
        print(f"error: NJFU exam response could not be parsed: {exc}", file=sys.stderr)
        return 4
    except ExamSourceError:
        print("error: NJFU exam query failed", file=sys.stderr)
        return 5

    summary = describe_result(result)
    if args.format == "json":
        print(json.dumps({
            **summary,
            "projects": [asdict(project) for project in result.projects],
            "exams": [_exam_to_json(item) for item in result.exams],
        }, ensure_ascii=False, indent=2))
    elif args.format == "latest":
        print(summary["latest_exam_date"] or "")
    elif args.format == "suggested":
        print(summary["suggested_monitor_until"] or "")
    else:
        print(json.dumps(summary, ensure_ascii=False))
    return 0 if result.complete else 2


if __name__ == "__main__":
    raise SystemExit(_run_cli())
