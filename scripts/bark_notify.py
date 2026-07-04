#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class BarkError(RuntimeError):
    pass


@dataclass(frozen=True)
class BarkConfig:
    server: str
    device_key: str
    group: str = ""
    sound: str = ""
    icon: str = ""
    level: str = "timeSensitive"
    archive: bool = True


def describe_config(config: BarkConfig) -> str:
    parsed = urlparse(config.server)
    host = parsed.hostname or "set"
    return (
        f"server={host} "
        f"group={config.group or 'unset'} "
        f"sound={config.sound or 'unset'} "
        f"icon={'set' if config.icon else 'unset'}"
    )


def send_bark(config: BarkConfig, title: str, body: str) -> None:
    payload = {
        "device_key": config.device_key,
        "title": title,
        "body": body,
        "level": config.level,
    }
    if config.group:
        payload["group"] = config.group
    if config.sound:
        payload["sound"] = config.sound
    if config.icon:
        payload["icon"] = config.icon
    if config.archive:
        payload["isArchive"] = "1"

    request = Request(
        f"{config.server.rstrip('/')}/push",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "njfu-gpa-monitor/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise BarkError(f"HTTP {response.status}")
    except HTTPError as exc:
        raise BarkError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise BarkError(str(exc.reason)) from exc

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError:
        raise BarkError("Bark returned a non-JSON response")
    if str(result.get("code", "200")) != "200":
        message = result.get("message") or result.get("error") or "Bark rejected the push"
        raise BarkError(str(message)[:120])
