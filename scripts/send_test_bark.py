#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def main() -> int:
    server = env("BARK_SERVER", "https://api.day.app").rstrip("/")
    device_key = env("BARK_DEVICE_KEY")
    if not device_key:
        print("error: Missing BARK_DEVICE_KEY.", file=sys.stderr)
        return 1

    title = env("BARK_TEST_TITLE", "NJFU GPA 测试通知")
    body = env("BARK_TEST_BODY", "Bark 推送链路正常，后续出分会发送到这个分组。")
    params = {
        "group": env("BARK_GROUP", "njfu GPA"),
        "sound": env("BARK_SOUND", "alarm"),
        "level": "timeSensitive",
    }
    icon = env("BARK_ICON")
    if icon:
        params["icon"] = icon

    url = f"{server}/{quote(device_key)}/{quote(title)}/{quote(body)}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "njfu-gpa-monitor/1.0"})
    with urlopen(request, timeout=20) as response:
        if response.status >= 400:
            print(f"error: Bark returned HTTP {response.status}.", file=sys.stderr)
            return 1
        response.read()
    print("Bark test notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
