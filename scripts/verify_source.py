from __future__ import annotations

import asyncio
import re
import sys
from types import SimpleNamespace

from config import DEFAULT_BASE_URL, env
from grade_source import GradeAuthenticationError, GradeSourceError, fetch_grades


async def verify_source() -> str:
    semester = env("VERIFY_SEMESTER", env("JW_SEMESTER"))
    if not re.fullmatch(r"\d{4}-\d{4}-[12]", semester):
        raise ValueError("请选择有效学期，例如 2026-2027-1。")
    username, password, cookie = env("JW_USERNAME"), env("JW_PASSWORD"), env("JW_COOKIE")
    if not cookie and (not username or not password):
        raise ValueError("尚未配置教务登录信息，请从云端设置页完成配置。")
    grades = await fetch_grades(SimpleNamespace(
        base_url=DEFAULT_BASE_URL, username=username, password=password, cookie=cookie, semester=semester,
    ))
    return "ready" if grades else "empty"


def main() -> int:
    try:
        status = asyncio.run(verify_source())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except GradeAuthenticationError:
        print("教务登录未完成，请在云端设置页重新验证；可能需要学校的交互验证。", file=sys.stderr)
        return 1
    except GradeSourceError:
        print("教务成绩接口暂时不可用或响应不兼容，请稍后重试。", file=sys.stderr)
        return 1
    print("教务登录和成绩接口验证通过。" if status == "ready" else "教务登录和成绩接口验证通过；所选学期当前暂无已公布成绩。")
    print("本次未输出课程或成绩、未修改监控状态、未发送通知。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
