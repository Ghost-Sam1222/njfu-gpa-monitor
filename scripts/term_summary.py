from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MAX_AGE = timedelta(days=14)


def inspect_term_summary(
    payload: Any, semester: str, *, now: datetime | None = None
) -> dict[str, Any]:
    """Validate declared provenance, not authenticity; never derive an exam deadline."""
    def rejected(status: str, message: str) -> dict[str, Any]:
        return {"status": status, "message": message}

    if payload is None:
        return rejected("missing", "未提供课表摘要；仍可按考试安排或人工日期配置监控。")
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int:
        return rejected("invalid", "课表摘要格式无效。")
    if payload["schema_version"] != 1:
        return rejected("unsupported_version", "不支持该课表摘要版本，请重新导出。")
    if not re.fullmatch(r"\d{4}-\d{4}-[12]", semester) or payload.get("semester") != semester:
        return rejected("semester_mismatch", "摘要与当前选择的学期不符，请核对学期后重新导入。")
    term_source = payload.get("term_source")
    timetable_source = payload.get("timetable_source")
    expected_confidence = {
        "term": "reported" if term_source == "school_reported" else "configured",
        "last_class_date": "derived",
    }
    if (
        term_source not in ("school_reported", "manual")
        or timetable_source not in ("school_web", "school_app_api")
        or payload.get("confidence") != expected_confidence
        or payload.get("last_class_date_basis") != "latest_generated_course_event"
        or type(payload.get("has_manual_adjustments")) is not bool
    ):
        return rejected("untrusted_source", "摘要来源或日期依据不受支持；测试数据不能用于实际配置。")
    try:
        generated_at = datetime.fromisoformat(payload["generated_at"].replace("Z", "+00:00"))
        first_monday = date.fromisoformat(payload["first_monday"])
        last_class = payload["last_class_date"]
        last_class_date = date.fromisoformat(last_class) if last_class is not None else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return rejected("invalid", "课表摘要日期格式无效，请重新导出。")
    if (
        generated_at.utcoffset() != timedelta(0)
        or first_monday.weekday() != 0
        or (last_class_date is not None and last_class_date < first_monday)
    ):
        return rejected("invalid", "课表摘要的时区或日期范围无效。")
    now = now or datetime.now(timezone.utc)
    if generated_at > now:
        return rejected("future_timestamp", "摘要生成时间在未来，请检查时钟并重新导出。")
    if now - generated_at > MAX_AGE:
        return rejected("stale", "课表摘要已超过 14 天，请先更新课表再导入。")
    return {
        "status": "ready",
        "semester": semester,
        "generated_at": generated_at.isoformat(),
        "first_monday": first_monday.isoformat(),
        "last_class_date": last_class_date.isoformat() if last_class_date else None,
        "term_source": term_source,
        "timetable_source": timetable_source,
        "has_manual_adjustments": payload["has_manual_adjustments"],
        "message": "课表摘要可作关注期参考；结课日不是考试日，不会自动设置开始或停止日期。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a local course-calendar term summary.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--semester", required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(json.dumps({"status": "invalid", "message": "Cannot read term summary JSON."}))
        return 2
    result = inspect_term_summary(payload, args.semester)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
