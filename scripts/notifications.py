#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from bark_notify import BarkConfig, BarkError, send_bark


class NotificationError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value.strip()


@dataclass(frozen=True)
class NotificationSettings:
    bark_server: str = ""
    bark_device_key: str = ""
    bark_group: str = "NJFU-GPA"
    bark_sound: str = "telegraph"
    bark_icon: str = ""
    feishu_webhook_url: str = ""
    dingtalk_webhook_url: str = ""
    wework_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    ntfy_server_url: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    ntfy_token: str = ""
    slack_webhook_url: str = ""
    generic_webhook_url: str = ""
    generic_webhook_template: str = ""
    email_from: str = ""
    email_password: str = ""
    email_to: str = ""
    email_smtp_server: str = ""
    email_smtp_port: int = 0

    @classmethod
    def from_env(cls) -> "NotificationSettings":
        port = _env("EMAIL_SMTP_PORT")
        try:
            email_smtp_port = int(port) if port else 0
        except ValueError as exc:
            raise NotificationError("EMAIL_SMTP_PORT must be an integer") from exc
        return cls(
            bark_server=_env("BARK_SERVER", "https://api.day.app").rstrip("/"),
            bark_device_key=_env("BARK_DEVICE_KEY"),
            bark_group=_env("BARK_GROUP", "NJFU-GPA"),
            bark_sound=_env("BARK_SOUND", "telegraph"),
            bark_icon=_env("BARK_ICON"),
            feishu_webhook_url=_env("FEISHU_WEBHOOK_URL"),
            dingtalk_webhook_url=_env("DINGTALK_WEBHOOK_URL"),
            wework_webhook_url=_env("WEWORK_WEBHOOK_URL"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            ntfy_server_url=_env("NTFY_SERVER_URL", "https://ntfy.sh").rstrip("/"),
            ntfy_topic=_env("NTFY_TOPIC"),
            ntfy_token=_env("NTFY_TOKEN"),
            slack_webhook_url=_env("SLACK_WEBHOOK_URL"),
            generic_webhook_url=_env("GENERIC_WEBHOOK_URL"),
            generic_webhook_template=_env("GENERIC_WEBHOOK_TEMPLATE"),
            email_from=_env("EMAIL_FROM"),
            email_password=_env("EMAIL_PASSWORD"),
            email_to=_env("EMAIL_TO"),
            email_smtp_server=_env("EMAIL_SMTP_SERVER"),
            email_smtp_port=email_smtp_port,
        )

    def realtime_channels(self) -> tuple[str, ...]:
        channels: list[str] = []
        if self.bark_device_key:
            channels.append("bark")
        if self.feishu_webhook_url:
            channels.append("feishu")
        if self.dingtalk_webhook_url:
            channels.append("dingtalk")
        if self.wework_webhook_url:
            channels.append("wework")
        if self.telegram_bot_token and self.telegram_chat_id:
            channels.append("telegram")
        if self.ntfy_topic:
            channels.append("ntfy")
        if self.slack_webhook_url:
            channels.append("slack")
        if self.generic_webhook_url:
            channels.append("generic_webhook")
        return tuple(channels)

    def email_enabled(self) -> bool:
        return bool(self.email_from and self.email_password and self.email_to)

    def configuration_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if bool(self.telegram_bot_token) != bool(self.telegram_chat_id):
            errors.append("Telegram requires both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        email_core = (self.email_from, self.email_password, self.email_to)
        if any(email_core) and not all(email_core):
            errors.append("Email requires EMAIL_FROM, EMAIL_PASSWORD, and EMAIL_TO")
        if self.ntfy_token and not self.ntfy_topic:
            errors.append("NTFY_TOKEN requires NTFY_TOPIC")
        if self.generic_webhook_template and not self.generic_webhook_url:
            errors.append("GENERIC_WEBHOOK_TEMPLATE requires GENERIC_WEBHOOK_URL")
        endpoints = {
            "BARK_SERVER": self.bark_server if self.bark_device_key else "",
            "FEISHU_WEBHOOK_URL": self.feishu_webhook_url,
            "DINGTALK_WEBHOOK_URL": self.dingtalk_webhook_url,
            "WEWORK_WEBHOOK_URL": self.wework_webhook_url,
            "NTFY_SERVER_URL": self.ntfy_server_url if self.ntfy_topic else "",
            "SLACK_WEBHOOK_URL": self.slack_webhook_url,
            "GENERIC_WEBHOOK_URL": self.generic_webhook_url,
        }
        for name, value in endpoints.items():
            if value and urlparse(value).scheme.lower() != "https":
                errors.append(f"{name} must use HTTPS")
        return tuple(errors)


def _request(url: str, *, payload: Any = None, body: bytes | None = None, headers: dict[str, str] | None = None) -> str:
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json; charset=utf-8")
    request = Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urlopen(request, timeout=25) as response:
            text = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise NotificationError(f"HTTP {response.status}")
            return text
    except HTTPError as exc:
        raise NotificationError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise NotificationError(f"network request failed: {type(exc.reason).__name__}") from exc
    except (OSError, TimeoutError, TypeError, ValueError) as exc:
        raise NotificationError(f"network request failed: {type(exc).__name__}") from exc


def _json_response(text: str) -> dict[str, Any]:
    try:
        result = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise NotificationError("remote service returned a non-JSON response") from exc
    if not isinstance(result, dict):
        raise NotificationError("remote service returned an unexpected response")
    return result


def _replace_placeholders(value: Any, title: str, content: str) -> Any:
    if isinstance(value, str):
        return value.replace("{title}", title).replace("{content}", content)
    if isinstance(value, list):
        return [_replace_placeholders(item, title, content) for item in value]
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, title, content) for key, item in value.items()}
    return value


def _send_channel(settings: NotificationSettings, channel: str, title: str, content: str) -> None:
    if channel == "bark":
        try:
            send_bark(
                BarkConfig(
                    server=settings.bark_server,
                    device_key=settings.bark_device_key,
                    group=settings.bark_group,
                    sound=settings.bark_sound,
                    icon=settings.bark_icon,
                ),
                title,
                content,
            )
        except BarkError as exc:
            raise NotificationError(str(exc)) from exc
        return

    if channel == "feishu":
        result = _json_response(_request(settings.feishu_webhook_url, payload={"msg_type": "text", "content": {"text": f"{title}\n{content}"}}))
        if str(result.get("code", result.get("StatusCode", ""))) != "0":
            raise NotificationError("Feishu rejected the message")
        return

    if channel == "dingtalk":
        result = _json_response(_request(settings.dingtalk_webhook_url, payload={"msgtype": "text", "text": {"content": f"{title}\n{content}"}}))
        if str(result.get("errcode", "")) != "0":
            raise NotificationError("DingTalk rejected the message")
        return

    if channel == "wework":
        result = _json_response(_request(settings.wework_webhook_url, payload={"msgtype": "text", "text": {"content": f"{title}\n{content}"}}))
        if str(result.get("errcode", "")) != "0":
            raise NotificationError("WeCom rejected the message")
        return

    if channel == "telegram":
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        result = _json_response(_request(url, payload={"chat_id": settings.telegram_chat_id, "text": f"{title}\n{content}", "disable_web_page_preview": True}))
        if not result.get("ok"):
            raise NotificationError("Telegram rejected the message")
        return

    if channel == "ntfy":
        headers = {"Title": Header(title, "utf-8").encode()}
        if settings.ntfy_token:
            headers["Authorization"] = f"Bearer {settings.ntfy_token}"
        _request(f"{settings.ntfy_server_url}/{quote(settings.ntfy_topic, safe='')}", body=content.encode("utf-8"), headers=headers)
        return

    if channel == "slack":
        response = _request(settings.slack_webhook_url, payload={"text": f"*{title}*\n{content}"})
        if response.strip().lower() not in {"", "ok"}:
            raise NotificationError("Slack rejected the message")
        return

    if channel == "generic_webhook":
        payload: Any = {"title": title, "content": content}
        if settings.generic_webhook_template:
            try:
                payload = _replace_placeholders(json.loads(settings.generic_webhook_template), title, content)
            except json.JSONDecodeError as exc:
                raise NotificationError("GENERIC_WEBHOOK_TEMPLATE is not valid JSON") from exc
        _request(settings.generic_webhook_url, payload=payload)
        return

    raise NotificationError(f"unsupported channel: {channel}")


def send_channel(settings: NotificationSettings, channel: str, title: str, content: str) -> None:
    _send_channel(settings, channel, title, content)
    print(f"Notification sent: channel={channel}.")


def send_realtime(settings: NotificationSettings, title: str, content: str) -> tuple[str, ...]:
    channels = settings.realtime_channels()
    failures: list[str] = []
    for channel in channels:
        try:
            send_channel(settings, channel, title, content)
        except NotificationError as exc:
            failures.append(f"{channel}: {exc}")
    if failures:
        raise NotificationError("; ".join(failures))
    return channels


SMTP_DEFAULTS: dict[str, tuple[str, int]] = {
    "gmail.com": ("smtp.gmail.com", 465),
    "icloud.com": ("smtp.mail.me.com", 587),
    "me.com": ("smtp.mail.me.com", 587),
    "outlook.com": ("smtp-mail.outlook.com", 587),
    "hotmail.com": ("smtp-mail.outlook.com", 587),
    "qq.com": ("smtp.qq.com", 465),
    "163.com": ("smtp.163.com", 465),
    "126.com": ("smtp.126.com", 465),
}


def send_email(settings: NotificationSettings, subject: str, text: str, html: str) -> None:
    if not settings.email_enabled():
        raise NotificationError("email channel is incomplete")
    domain = settings.email_from.rsplit("@", 1)[-1].lower()
    default_server, default_port = SMTP_DEFAULTS.get(domain, ("", 0))
    server_name = settings.email_smtp_server or default_server
    port = settings.email_smtp_port or default_port
    if not server_name or not port:
        raise NotificationError("EMAIL_SMTP_SERVER and EMAIL_SMTP_PORT are required for this provider")

    message = MIMEMultipart("alternative")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = formataddr((str(Header("NJFU GPA Monitor", "utf-8")), settings.email_from))
    recipients = [item.strip() for item in settings.email_to.split(",") if item.strip()]
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(text, "plain", "utf-8"))
    message.attach(MIMEText(html, "html", "utf-8"))

    try:
        if port == 465:
            with smtplib.SMTP_SSL(server_name, port, timeout=30, context=ssl.create_default_context()) as smtp:
                smtp.login(settings.email_from, settings.email_password)
                smtp.sendmail(settings.email_from, recipients, message.as_string())
        else:
            with smtplib.SMTP(server_name, port, timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(settings.email_from, settings.email_password)
                smtp.sendmail(settings.email_from, recipients, message.as_string())
    except (OSError, smtplib.SMTPException) as exc:
        raise NotificationError(f"email delivery failed: {type(exc).__name__}") from exc
    print("Notification sent: channel=email.")
