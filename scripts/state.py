from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 3


@dataclass
class MonitorState:
    semester: str
    initialized: bool = False
    observed_hashes: set[str] = field(default_factory=set)
    delivered_by_channel: dict[str, set[str]] = field(default_factory=dict)
    email_pending_count: int = 0
    complete: bool = False
    consecutive_failures: int = 0

    def delivered(self, channel: str) -> set[str]:
        return self.delivered_by_channel.setdefault(channel, set())


def load_state(path: Path, semester: str) -> MonitorState:
    if not path.exists():
        return MonitorState(semester=semester)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return MonitorState(semester=semester)
    if not isinstance(raw, dict) or raw.get("semester") != semester:
        return MonitorState(semester=semester)

    observed = raw.get("observed_hashes", raw.get("hashes", []))
    deliveries = raw.get("delivered_by_channel", {})
    counters = [raw.get(name, 0) for name in ("email_pending_count", "consecutive_failures")]
    if (
        not isinstance(observed, list)
        or not all(isinstance(item, str) for item in observed)
        or not isinstance(deliveries, dict)
        or not all(isinstance(items, list) and all(isinstance(item, str) for item in items)
                   for items in deliveries.values())
        or not all(type(value) is int and value >= 0 for value in counters)
        or not all(type(raw[name]) is bool for name in ("initialized", "complete") if name in raw)
    ):
        return MonitorState(semester=semester)
    delivered = {channel: set(items) for channel, items in deliveries.items()}
    initialized = bool(raw.get("initialized", bool(observed)))
    return MonitorState(
        semester=semester,
        initialized=initialized,
        observed_hashes=set(observed or []),
        delivered_by_channel=delivered,
        email_pending_count=int(raw.get("email_pending_count", 0)),
        complete=bool(raw.get("complete", False)),
        consecutive_failures=int(raw.get("consecutive_failures", 0)),
    )


def save_state(path: Path, state: MonitorState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "semester": state.semester,
        "initialized": state.initialized,
        "observed_hashes": sorted(state.observed_hashes),
        "delivered_by_channel": {
            channel: sorted(items) for channel, items in sorted(state.delivered_by_channel.items())
        },
        "email_pending_count": state.email_pending_count,
        "complete": state.complete,
        "consecutive_failures": state.consecutive_failures,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
