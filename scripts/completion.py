from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from config import env, parse_bool, parse_csv, parse_date, parse_int, resolve_completion_mode
from state import load_state


def completion_key(*, semester: str, mode: str, count: int, names: tuple[str, ...],
                   until: str, channels: tuple[str, ...], final_report: bool, salt: str,
                   username: str = "") -> str:
    policy = [semester, username, mode, count if mode == "count" else 0,
              sorted(set(names)) if mode == "names" else [], until,
              sorted(set(channels)), final_report]
    return hmac.new(salt.encode(), json.dumps(policy, ensure_ascii=False).encode(), hashlib.sha256).hexdigest()


def cached_completion() -> bool:
    semester = env("JW_SEMESTER")
    salt = env("GRADE_STATE_SALT")
    if not semester or len(salt) < 32:
        return False
    state = load_state(Path(env("GRADE_STATE_PATH", "data/grade_state.json")), semester)
    if not state.complete or not state.completion_key:
        return False
    count = parse_int("EXPECTED_GRADE_COUNT", env("EXPECTED_GRADE_COUNT", env("EXPECTED_NEW_COUNT", "0")))
    names = parse_csv(env("EXPECTED_COURSE_NAMES"))
    mode = resolve_completion_mode(env("COMPLETION_MODE", "date"), count, names)
    until = parse_date(env("MONITOR_UNTIL"))
    key = completion_key(semester=semester, mode=mode, count=count, names=names,
                         until=until.isoformat() if until else "",
                         channels=tuple(env("COMPLETION_CHANNELS").split()),
                         final_report=parse_bool(env("FINAL_REPORT_ENABLED", "true"), True), salt=salt,
                         username=env("JW_USERNAME"))
    return hmac.compare_digest(state.completion_key, key)


if __name__ == "__main__":
    from config import ConfigError

    try:
        finished = cached_completion()
    except ConfigError:
        finished = False
    raise SystemExit(0 if finished else 1)
