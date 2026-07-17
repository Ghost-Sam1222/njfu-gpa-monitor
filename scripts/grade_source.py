from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from config import Settings
from models import Grade


class GradeSourceError(RuntimeError):
    pass


ALLOWED_NJFU_HOSTS = {"jwxt.njfu.edu.cn", "authserver.njfu.edu.cn"}


def _is_njfu_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and hostname in ALLOWED_NJFU_HOSTS


def _require_njfu_url(url: str) -> None:
    if not _is_njfu_url(url):
        raise GradeSourceError("Refusing to send credentials outside approved NJFU HTTPS hosts.")


def _cookie_entries(cookie_header: str, base_url: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for item in cookie_header.split(";"):
        if "=" not in item:
            continue
        name, value = item.strip().split("=", 1)
        if name:
            entries.append({"name": name, "value": value, "url": base_url})
    return entries


async def fetch_grades(settings: Settings) -> list[Grade]:
    try:
        return await _fetch_grades(settings)
    except GradeSourceError:
        raise
    except Exception as exc:
        raise GradeSourceError(f"JWXT browser step failed: {type(exc).__name__}") from exc


async def _fetch_grades(settings: Settings) -> list[Grade]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise GradeSourceError("Playwright is not installed; run pip install -r requirements.txt.") from exc

    _require_njfu_url(settings.base_url)
    login_url = f"{settings.base_url}/jsxsd/framework/xsMainV.jsp"
    grade_url = f"{settings.base_url}/jsxsd/kscj/cjcx_list"
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
            cookies = _cookie_entries(settings.cookie, settings.base_url)
            if cookies:
                await context.add_cookies(cookies)
        page = await context.new_page()
        try:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            if "authserver/login" in page.url:
                if not settings.username or not settings.password:
                    raise GradeSourceError("JW_COOKIE expired; configure JW_USERNAME and JW_PASSWORD as fallback.")
                _require_njfu_url(page.url)
                await page.fill("#username", settings.username)
                await page.fill("#password", settings.password)
                await page.click('button[type="submit"]')
                await page.wait_for_load_state("domcontentloaded", timeout=60000)
                await page.wait_for_timeout(1200)
            _require_njfu_url(page.url)
            if "authserver/login" in page.url:
                raise GradeSourceError("Login did not complete; verify credentials or interactive verification requirements.")

            await page.goto(grade_url, wait_until="domcontentloaded", timeout=60000)
            _require_njfu_url(page.url)
            html = await post_grade_query(page, grade_url, settings.semester)
            if not has_grade_table(html):
                html = await page.content()
            if not has_grade_table(html):
                raise GradeSourceError("Could not parse the grade table.")
            grades = parse_grades_html(html)
            semester_rows = [grade for grade in grades if grade.semester == settings.semester]
            return semester_rows if any(grade.semester for grade in grades) else grades
        finally:
            await browser.close()


async def post_grade_query(page: Any, grade_url: str, semester: str) -> str:
    return await page.evaluate(
        """async ({url, semester}) => {
            const form = new URLSearchParams({kksj: semester, kcxz: '', kcsx: '', kcmc: '', xsfs: 'all'});
            const response = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: form.toString(),
                credentials: 'include'
            });
            if (!response.ok) throw new Error(`grade query failed: ${response.status}`);
            return await response.text();
        }""",
        {"url": grade_url, "semester": semester},
    )


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


HEADER_ALIASES = {
    "semester": {"学年学期", "开课学期", "学期"},
    "course_code": {"课程代码", "课程编号"},
    "course_name": {"课程名称", "课程"},
    "score": {"成绩", "总评成绩"},
    "credit": {"学分"},
    "gpa": {"绩点"},
    "course_type": {"课程属性", "课程性质", "课程类别"},
}


def _header_indexes(labels: list[str]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        for index, label in enumerate(labels):
            if label in aliases:
                indexes[field] = index
                break
    return indexes


class GradeTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.found_table = False
        self.in_row = False
        self.cell_tag = ""
        self.cell_text: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == "dataList":
            self.in_table = True
            self.found_table = True
        elif self.in_table and tag == "tr":
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
            self.current_row.append(normalize_text("".join(self.cell_text)))
            self.cell_tag = ""
            self.cell_text = []
        elif self.in_row and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False
        elif self.in_table and tag == "table":
            self.in_table = False


def parse_grades_html(html: str) -> list[Grade]:
    parser = GradeTableParser()
    parser.feed(html)
    if not parser.rows:
        return []
    indexes = _header_indexes(parser.rows[0])
    fallback = {
        "semester": 1,
        "course_code": 2,
        "course_name": 3,
        "score": 4,
        "credit": 6,
        "gpa": 8,
        "course_type": 13,
    }

    def value(columns: list[str], field: str) -> str:
        index = indexes.get(field, fallback[field])
        return columns[index] if index < len(columns) else ""

    grades: list[Grade] = []
    for columns in parser.rows[1:]:
        if not columns:
            continue
        grade = Grade(
            semester=value(columns, "semester"),
            course_code=value(columns, "course_code"),
            course_name=value(columns, "course_name"),
            score=value(columns, "score"),
            credit=value(columns, "credit"),
            gpa=value(columns, "gpa"),
            course_type=value(columns, "course_type"),
        )
        if grade.course_name and grade.score:
            grades.append(grade)
    return grades


def has_grade_table(html: str) -> bool:
    parser = GradeTableParser()
    parser.feed(html)
    return parser.found_table
