#!/usr/bin/env python3
from __future__ import annotations

import sys

from notifications import NotificationError, NotificationSettings, send_email, send_realtime


def main() -> int:
    try:
        settings = NotificationSettings.from_env()
        configuration_errors = settings.configuration_errors()
        if configuration_errors:
            raise NotificationError("; ".join(configuration_errors))
        channels = settings.realtime_channels()
        if not channels and not settings.email_enabled():
            raise NotificationError("Configure at least one notification channel.")
        if channels:
            send_realtime(settings, "NJFU GPA 测试通知", "推送链路正常，后续出分会发送到这里。")
        if settings.email_enabled():
            send_email(
                settings,
                "NJFU GPA 测试通知",
                "邮件链路正常。",
                "<h1>NJFU GPA</h1><p>邮件链路正常，达到批量阈值或成绩全部到齐时会收到成绩单。</p>",
            )
    except NotificationError as exc:
        print(f"error: Notification test failed: {exc}", file=sys.stderr)
        return 1
    print("Configured notification channels passed the test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
