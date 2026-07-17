#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import re
import sys
from datetime import date

from config import ConfigError, Settings, load_settings
from grade_source import GradeSourceError, fetch_grades
from models import Grade
from notifications import NotificationError, send_channel, send_email
from report import weighted_average, write_transcript
from state import MonitorState, load_state, save_state


class MonitorError(RuntimeError):
    pass


def normalized_name(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def is_complete(settings: Settings, grades: list[Grade]) -> bool:
    if settings.expected_course_names:
        names = {normalized_name(grade.course_name) for grade in grades}
        expected = {normalized_name(name) for name in settings.expected_course_names}
        return expected.issubset(names)
    if settings.expected_grade_count > 0:
        return len(grades) >= settings.expected_grade_count
    return False


def should_skip(settings: Settings, state: MonitorState) -> bool:
    today = date.today()
    if not settings.enabled:
        print("Monitor disabled.")
        return True
    if settings.check_start_date and today < settings.check_start_date:
        print("Monitor has not reached its start date.")
        return True
    if settings.monitor_until and today > settings.monitor_until:
        print("Monitor has passed its stop date.")
        return True
    if state.complete:
        print("Expected grades are complete; login skipped.")
        return True
    return False


def format_grades(grades: list[Grade], complete: bool = False) -> str:
    lines = []
    for grade in grades:
        details = [f"成绩 {grade.score}"]
        if grade.gpa:
            details.append(f"绩点 {grade.gpa}")
        if grade.credit:
            details.append(f"学分 {grade.credit}")
        lines.append(f"{grade.course_name}：{'，'.join(details)}")
    if complete:
        lines.append("本学期预期成绩已全部到齐。")
    return "\n".join(lines)


def completion_summary(grades: list[Grade]) -> str:
    average_score = weighted_average(grades, "score")
    average_gpa = weighted_average(grades, "gpa")
    parts = ["本学期预期成绩已全部到齐，监控将在投递成功后停止。"]
    if average_score is not None:
        parts.append(f"学分加权平均成绩 {average_score:.2f}")
    if average_gpa is not None:
        parts.append(f"学分加权平均绩点 {average_gpa:.2f}")
    parts.append("课程明细：")
    for grade in grades:
        fields = [grade.course_name]
        if grade.course_code:
            fields.append(grade.course_code)
        fields.append(f"成绩 {grade.score}")
        if grade.credit:
            fields.append(f"学分 {grade.credit}")
        if grade.gpa:
            fields.append(f"绩点 {grade.gpa}")
        if grade.course_type:
            fields.append(grade.course_type)
        parts.append("｜".join(fields))
    return "\n".join(parts)


def initialize_channel_baselines(state: MonitorState, channels: tuple[str, ...], current_hashes: set[str]) -> None:
    for channel in channels:
        if channel not in state.delivered_by_channel:
            state.delivered_by_channel[channel] = set(current_hashes)
            print(f"Initialized notification channel: channel={channel}.")


def deliver_realtime(
    settings: Settings,
    state: MonitorState,
    grades_by_hash: dict[str, Grade],
    detected_complete: bool,
) -> list[str]:
    failures: list[str] = []
    completion_marker = f"completion:{settings.semester}"
    for channel in settings.notifications.realtime_channels():
        delivered = state.delivered(channel)
        pending_hashes = [item for item in grades_by_hash if item not in delivered]
        pending_grades = [grades_by_hash[item] for item in pending_hashes]
        if pending_grades:
            try:
                send_channel(
                    settings.notifications,
                    channel,
                    "NJFU GPA 新成绩",
                    format_grades(pending_grades, complete=detected_complete),
                )
                delivered.update(pending_hashes)
            except NotificationError as exc:
                failures.append(f"{channel}: {exc}")

        if detected_complete and completion_marker not in delivered:
            try:
                send_channel(
                    settings.notifications,
                    channel,
                    "NJFU GPA 成绩已齐",
                    completion_summary(list(grades_by_hash.values())),
                )
                delivered.add(completion_marker)
            except NotificationError as exc:
                failures.append(f"{channel}: {exc}")
    return failures


def deliver_email(
    settings: Settings,
    state: MonitorState,
    grades: list[Grade],
    detected_complete: bool,
    new_count: int,
) -> list[str]:
    if not settings.notifications.email_enabled():
        return []
    completion_marker = f"completion:{settings.semester}"
    delivered = state.delivered("email")
    state.email_pending_count += new_count
    threshold_reached = state.email_pending_count >= settings.email_batch_size
    final_due = (
        detected_complete
        and settings.final_report_enabled
        and completion_marker not in delivered
    )
    if not threshold_reached and not final_due:
        return []

    subject = f"NJFU {settings.semester} {'最终成绩单' if final_due else '成绩更新'}"
    try:
        html = write_transcript(settings.report_path, grades, settings.semester, settings.username)
        send_email(settings.notifications, subject, completion_summary(grades), html)
    except NotificationError as exc:
        return [f"email: {exc}"]
    except OSError as exc:
        return [f"email: report generation failed: {type(exc).__name__}"]
    state.email_pending_count = 0
    if final_due:
        delivered.add(completion_marker)
    return []


def run() -> None:
    settings = load_settings()
    state = load_state(settings.state_path, settings.semester)
    if should_skip(settings, state):
        return
    channels = settings.notifications.realtime_channels()
    if not channels and not settings.notifications.email_enabled():
        raise MonitorError("Configure at least one notification channel.")

    grades = asyncio.run(fetch_grades(settings))
    grades_by_hash = {grade.identity(settings.state_salt): grade for grade in grades}
    current_hashes = set(grades_by_hash)
    detected_complete = is_complete(settings, grades)

    if not state.initialized:
        state.initialized = True
        state.observed_hashes = set(current_hashes)
        if not settings.notify_on_first_run:
            initialize_channel_baselines(state, channels, current_hashes)
        new_count = len(current_hashes) if settings.notify_on_first_run else 0
    else:
        new_count = len(current_hashes - state.observed_hashes)
        initialize_channel_baselines(state, channels, current_hashes)

    failures = deliver_realtime(settings, state, grades_by_hash, detected_complete)
    failures.extend(deliver_email(settings, state, grades, detected_complete, new_count))
    state.observed_hashes.update(current_hashes)
    state.complete = detected_complete and not failures
    save_state(settings.state_path, state)
    print(f"Grade check finished: changed={new_count > 0} complete={state.complete}.")
    if failures:
        raise MonitorError("Notification delivery failed: " + "; ".join(failures))


def main() -> int:
    try:
        run()
        return 0
    except (ConfigError, GradeSourceError, MonitorError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
