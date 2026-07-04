#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from bark_notify import BarkConfig, BarkError, describe_config, send_bark


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
    config = BarkConfig(
        server=server,
        device_key=device_key,
        group=env("BARK_GROUP", "NJFU-GPA"),
        sound=env("BARK_SOUND", "telegraph"),
        icon=env("BARK_ICON"),
    )

    print(f"Bark options: {describe_config(config)}")
    try:
        send_bark(config, title, body)
    except BarkError as exc:
        print(f"error: Bark push failed: {exc}", file=sys.stderr)
        return 1
    print("Bark test notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
