#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from grade_source import GradeSourceError, fetch_grades
from config import infer_semester

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "setup" / "index.html"
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
DEFAULT_REPOSITORY = "Ghost-Sam1222/njfu-gpa-monitor"
SECRET_NAMES = {
    "JW_USERNAME",
    "JW_PASSWORD",
    "JW_COOKIE",
    "GRADE_STATE_SALT",
    "BARK_SERVER",
    "BARK_DEVICE_KEY",
    "FEISHU_WEBHOOK_URL",
    "DINGTALK_WEBHOOK_URL",
    "WEWORK_WEBHOOK_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "NTFY_SERVER_URL",
    "NTFY_TOPIC",
    "NTFY_TOKEN",
    "SLACK_WEBHOOK_URL",
    "GENERIC_WEBHOOK_URL",
    "GENERIC_WEBHOOK_TEMPLATE",
    "EMAIL_FROM",
    "EMAIL_PASSWORD",
    "EMAIL_TO",
    "EMAIL_SMTP_SERVER",
    "EMAIL_SMTP_PORT",
}
VARIABLE_NAMES = {
    "JW_SEMESTER",
    "CHECK_INTERVAL_HOURS",
    "MONITOR_ENABLED",
    "CHECK_START_DATE",
    "MONITOR_UNTIL",
    "EXPECTED_COURSE_NAMES",
    "EXPECTED_GRADE_COUNT",
    "COMPLETION_MODE",
    "NOTIFY_ON_FIRST_RUN",
    "EMAIL_BATCH_SIZE",
    "FINAL_REPORT_ENABLED",
    "BARK_GROUP",
    "BARK_SOUND",
    "BARK_ICON",
}


def repository_variables(repository: str) -> dict[str, str]:
    result = gh("variable", "list", "--repo", repository, "--json", "name,value")
    if result.returncode != 0:
        return {}
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return {
        str(item["name"]): str(item.get("value", ""))
        for item in items
        if isinstance(item, dict) and item.get("name") in VARIABLE_NAMES
    }


def restrict_default_workflow_permissions(repository: str) -> bool:
    """Keep the repository token read-only unless a job explicitly requests writes."""
    result = gh(
        "api",
        "--method",
        "PUT",
        f"repos/{repository}/actions/permissions/workflow",
        "-f",
        "default_workflow_permissions=read",
        "-F",
        "can_approve_pull_request_reviews=false",
    )
    return result.returncode == 0


def login_digest(username: str, password: str, cookie: str, semester: str) -> str:
    payload = json.dumps(
        [username.strip(), password.strip(), cookie.strip(), semester.strip()],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def login_configuration_error(
    existing_names: set[str],
    submitted: dict[object, object],
    semester: str,
    verified_digest: str,
    existing_semester: str = "",
) -> str:
    username = str(submitted.get("JW_USERNAME", "")).strip()
    password = str(submitted.get("JW_PASSWORD", "")).strip()
    cookie = str(submitted.get("JW_COOKIE", "")).strip()
    submitted_any = bool(username or password or cookie)
    submitted_complete = bool(cookie or (username and password))
    existing_complete = "JW_COOKIE" in existing_names or {
        "JW_USERNAME",
        "JW_PASSWORD",
    }.issubset(existing_names)
    if submitted_any and not submitted_complete:
        return "请完整填写账号和密码，或填写 Cookie。"
    if not submitted_complete and not existing_complete:
        return "请填写教务登录信息并先点击“验证教务登录”。"
    if existing_semester and semester != existing_semester and not submitted_complete:
        return "学期已变更，请重新填写教务登录信息并验证新学期。"
    if submitted_complete and not hmac.compare_digest(
        login_digest(username, password, cookie, semester),
        verified_digest,
    ):
        return "教务登录信息或学期尚未验证，请先点击“验证教务登录”。"
    return ""


def telegram_chat_ids(token: str) -> list[dict[str, str]]:
    if not re.fullmatch(r"[0-9]{5,}:[A-Za-z0-9_-]{20,}", token.strip()):
        raise ValueError("Telegram Bot Token 格式不正确。")
    request = Request(
        f"https://api.telegram.org/bot{token.strip()}/getUpdates",
        headers={"User-Agent": "njfu-gpa-monitor/1.0"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 Telegram 消息：{type(exc).__name__}") from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise ValueError("Telegram 拒绝了请求，请检查 Bot Token。")
    chats: dict[str, str] = {}
    for update in payload.get("result", []):
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") if isinstance(message, dict) else None
        if not isinstance(chat, dict) or "id" not in chat:
            continue
        chat_id = str(chat["id"])
        label = str(chat.get("title") or chat.get("username") or chat.get("first_name") or chat_id)
        chats[chat_id] = label
    return [{"id": chat_id, "label": label} for chat_id, label in chats.items()]


def latest_workflow_run(repository: str, workflow: str) -> dict[str, object] | None:
    result = gh(
        "run",
        "list",
        "--repo",
        repository,
        "--workflow",
        workflow,
        "--event",
        "workflow_dispatch",
        "--limit",
        "1",
        "--json",
        "databaseId,status,conclusion,url",
    )
    if result.returncode != 0:
        return None
    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return runs[0] if isinstance(runs, list) and runs and isinstance(runs[0], dict) else None


def wait_for_workflow(
    repository: str,
    workflow: str,
    previous_id: object,
    attempts: int = 35,
    delay: float = 2.0,
) -> dict[str, object] | None:
    latest: dict[str, object] | None = None
    for _ in range(attempts):
        candidate = latest_workflow_run(repository, workflow)
        if candidate and candidate.get("databaseId") != previous_id:
            latest = candidate
            if candidate.get("status") == "completed":
                return candidate
        time.sleep(delay)
    return latest


def incomplete_secret_groups(names: set[str]) -> tuple[str, ...]:
    errors: list[str] = []
    telegram = {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}
    email = {"EMAIL_FROM", "EMAIL_PASSWORD", "EMAIL_TO"}
    if names & telegram and not telegram.issubset(names):
        errors.append("Telegram requires both Bot Token and Chat ID")
    if names & email and not email.issubset(names):
        errors.append("Email requires sender, authorization code, and recipient")
    if "NTFY_TOKEN" in names and "NTFY_TOPIC" not in names:
        errors.append("ntfy Token requires a Topic")
    if "GENERIC_WEBHOOK_TEMPLATE" in names and "GENERIC_WEBHOOK_URL" not in names:
        errors.append("Generic Webhook template requires a URL")
    return tuple(errors)


def has_notification_channel(names: set[str]) -> bool:
    complete_groups = (
        {"BARK_DEVICE_KEY"},
        {"FEISHU_WEBHOOK_URL"},
        {"DINGTALK_WEBHOOK_URL"},
        {"WEWORK_WEBHOOK_URL"},
        {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"},
        {"NTFY_TOPIC"},
        {"SLACK_WEBHOOK_URL"},
        {"GENERIC_WEBHOOK_URL"},
        {"EMAIL_FROM", "EMAIL_PASSWORD", "EMAIL_TO"},
    )
    return any(group.issubset(names) for group in complete_groups)


def normalize_completion_variables(variables: dict[object, object]) -> tuple[str, str, str]:
    mode = str(variables.get("COMPLETION_MODE", "date")).strip()
    expected_count = str(variables.get("EXPECTED_GRADE_COUNT", "")).strip()
    expected_names = str(variables.get("EXPECTED_COURSE_NAMES", "")).strip()
    if mode == "count" and (not expected_count.isdigit() or int(expected_count) < 1) and expected_names:
        mode = "names"
        variables["COMPLETION_MODE"] = mode
    return mode, expected_count, expected_names


def detect_repository() -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    remote = result.stdout.strip()
    match = re.search(r"github\.com(?::\d+)?[/:]([^/]+/[^/]+?)(?:\.git)?$", remote)
    return match.group(1) if match else ""


def cloud_mode() -> bool:
    return os.environ.get("SETUP_CLOUD") == "1" or os.environ.get("CODESPACES") == "true"


def source_repository() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "").strip() or detect_repository() or DEFAULT_REPOSITORY


def suggested_repository() -> str:
    return source_repository()


def cloud_target_allowed(repository: str) -> bool:
    return not cloud_mode() or repository.casefold() == source_repository().casefold()


def codespace_host(port: int) -> str:
    name = os.environ.get("CODESPACE_NAME", "").strip()
    domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev").strip()
    return f"{name}-{port}.{domain}" if name and domain else ""


def gh(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        input=stdin,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )


class SetupServer(ThreadingHTTPServer):
    csrf_token: str
    cloud: bool
    trusted_cloud_host: str
    verified_login_digest: str


class Handler(BaseHTTPRequestHandler):
    server: SetupServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: int, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _is_trusted_request(self) -> bool:
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.server.trusted_cloud_host:
            allowed_hosts.add(self.server.trusted_cloud_host.lower())
        host = self.headers.get("Host", "").lower()
        if host not in allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        local_origin = (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and parsed.port == port
        )
        cloud_origin = (
            bool(self.server.trusted_cloud_host)
            and parsed.scheme == "https"
            and parsed.netloc.lower() == self.server.trusted_cloud_host.lower()
        )
        return local_origin or cloud_origin

    def do_GET(self) -> None:
        if not self._is_trusted_request():
            self.send_error(403)
            return
        if self.path == "/":
            context = (
                "本页运行在你的私有 GitHub Codespace 中。表单不会写入浏览器存储，也不会发送给项目作者。"
                if self.server.cloud
                else "本页只运行在 127.0.0.1，不保存表单或写入浏览器存储。"
            )
            content = (
                PAGE.read_text(encoding="utf-8")
                .replace("__CSRF_TOKEN__", self.server.csrf_token)
                .replace("__SETUP_CONTEXT__", context)
            )
            encoded = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(encoded)
            return
        if self.path == "/api/status":
            installed = shutil.which("gh") is not None
            authenticated = installed and gh("auth", "status", "--hostname", "github.com").returncode == 0
            repository = suggested_repository()
            self._json(
                200,
                {
                    "gh_installed": installed,
                    "gh_authenticated": authenticated,
                    "repository": repository,
                    "cloud": self.server.cloud,
                    "semester": infer_semester(date.today()),
                    "variables": repository_variables(repository) if authenticated else {},
                },
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not self._is_trusted_request():
            self.send_error(403)
            return
        if self.path not in {"/api/apply", "/api/verify-jw", "/api/telegram-chat-id"}:
            self.send_error(404)
            return
        if self.headers.get("X-CSRF-Token") != self.server.csrf_token:
            self._json(403, {"ok": False, "error": "Invalid local setup token."})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 65536:
            self._json(400, {"ok": False, "error": "Invalid request size."})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "Invalid JSON."})
            return
        if not isinstance(payload, dict):
            self._json(400, {"ok": False, "error": "Invalid configuration payload."})
            return
        if self.path == "/api/telegram-chat-id":
            try:
                chats = telegram_chat_ids(str(payload.get("token", "")))
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            if not chats:
                self._json(400, {"ok": False, "error": "请先给机器人发送一条消息，再点击获取。"})
                return
            self._json(200, {"ok": True, "chats": chats})
            return
        if self.path == "/api/verify-jw":
            username = str(payload.get("username", "")).strip()
            password = str(payload.get("password", "")).strip()
            cookie = str(payload.get("cookie", "")).strip()
            semester = str(payload.get("semester", "")).strip()
            if not semester or (not cookie and (not username or not password)):
                self._json(400, {"ok": False, "error": "请填写学期和账号密码，或填写 Cookie。"})
                return
            try:
                asyncio.run(
                    fetch_grades(
                        SimpleNamespace(
                            base_url="https://jwxt.njfu.edu.cn",
                            username=username,
                            password=password,
                            cookie=cookie,
                            semester=semester,
                        )
                    )
                )
            except GradeSourceError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            self.server.verified_login_digest = login_digest(username, password, cookie, semester)
            self._json(200, {"ok": True})
            return
        repository = str(payload.get("repository", "")).strip()
        if not REPOSITORY_PATTERN.fullmatch(repository):
            self._json(400, {"ok": False, "error": "Repository must use owner/name format."})
            return
        if not cloud_target_allowed(repository):
            self._json(400, {"ok": False, "error": "云端设置只能配置当前 Codespace 对应的仓库。"})
            return
        if shutil.which("gh") is None:
            self._json(400, {"ok": False, "error": "GitHub CLI is not installed."})
            return
        if gh("auth", "status", "--hostname", "github.com").returncode != 0:
            self._json(400, {"ok": False, "error": "Run gh auth login -h github.com first."})
            return

        existing_repository = gh("repo", "view", repository, "--json", "nameWithOwner")
        if existing_repository.returncode != 0:
            self._json(400, {"ok": False, "error": "监控仓库不存在或当前 Codespace 无权配置它，请从云端入口重新进入。"})
            return

        secrets_payload = payload.get("secrets") or {}
        variables_payload = payload.get("variables") or {}
        delete_secrets_payload = payload.get("delete_secrets") or []
        if (
            not isinstance(secrets_payload, dict)
            or not isinstance(variables_payload, dict)
            or not isinstance(delete_secrets_payload, list)
        ):
            self._json(400, {"ok": False, "error": "Invalid configuration payload."})
            return
        monitor_enabled = str(variables_payload.get("MONITOR_ENABLED", "false")) == "true"
        monitor_until = str(variables_payload.get("MONITOR_UNTIL", "")).strip()
        completion_mode, expected_count, expected_names = normalize_completion_variables(variables_payload)
        if monitor_enabled and not monitor_until:
            self._json(400, {"ok": False, "error": "启用监控时必须填写停止日期。"})
            return
        if completion_mode not in {"count", "names", "date"}:
            self._json(400, {"ok": False, "error": "请选择一种成绩完成方式。"})
            return
        if completion_mode == "count" and (not expected_count.isdigit() or int(expected_count) < 1):
            self._json(400, {"ok": False, "error": "按数量判断时，预期成绩数量至少为 1。"})
            return
        if completion_mode == "names" and not expected_names:
            self._json(400, {"ok": False, "error": "按课程判断时，请填写预期课程名称。"})
            return
        existing = gh(
            "secret",
            "list",
            "--repo",
            repository,
            "--json",
            "name",
            "--jq",
            ".[].name",
        )
        if existing.returncode != 0:
            self._json(400, {"ok": False, "error": "Failed to inspect existing Secrets."})
            return
        existing_names = set(existing.stdout.splitlines())
        existing_variables = repository_variables(repository)
        login_error = login_configuration_error(
            existing_names,
            secrets_payload,
            str(variables_payload.get("JW_SEMESTER", "")),
            self.server.verified_login_digest,
            existing_variables.get("JW_SEMESTER", ""),
        )
        if login_error:
            self._json(400, {"ok": False, "error": login_error})
            return
        submitted_names = {
            name
            for name, value in secrets_payload.items()
            if name in SECRET_NAMES and str(value).strip()
        }
        requested_deletions = {str(name) for name in delete_secrets_payload} & SECRET_NAMES
        deleted_names = (requested_deletions - submitted_names) & existing_names
        group_errors = incomplete_secret_groups((existing_names - deleted_names) | submitted_names)
        if group_errors:
            self._json(400, {"ok": False, "error": "; ".join(group_errors)})
            return
        if not has_notification_channel((existing_names - deleted_names) | submitted_names):
            self._json(400, {"ok": False, "error": "请至少配置一种完整的通知渠道。"})
            return
        if not secrets_payload.get("GRADE_STATE_SALT") and "GRADE_STATE_SALT" not in existing_names:
            secrets_payload["GRADE_STATE_SALT"] = secrets.token_hex(32)

        updated_secrets: list[str] = []
        deleted_secrets: list[str] = []
        updated_variables: list[str] = []
        deleted_variables: list[str] = []
        for name in sorted(deleted_names):
            result = gh("secret", "delete", name, "--repo", repository)
            if result.returncode != 0:
                self._json(400, {"ok": False, "error": f"Failed to delete Secret {name}."})
                return
            deleted_secrets.append(name)
        for name, raw_value in secrets_payload.items():
            value = str(raw_value).strip()
            if name not in SECRET_NAMES or not value:
                continue
            result = gh("secret", "set", name, "--repo", repository, stdin=value)
            if result.returncode != 0:
                self._json(400, {"ok": False, "error": f"Failed to set Secret {name}."})
                return
            updated_secrets.append(name)

        for name, raw_value in variables_payload.items():
            value = str(raw_value).strip()
            if name not in VARIABLE_NAMES:
                continue
            if value == "":
                if name in existing_variables:
                    result = gh("variable", "delete", name, "--repo", repository)
                    if result.returncode != 0:
                        self._json(400, {"ok": False, "error": f"Failed to delete Variable {name}."})
                        return
                    deleted_variables.append(name)
                continue
            result = gh("variable", "set", name, "--repo", repository, "--body", value)
            if result.returncode != 0:
                self._json(400, {"ok": False, "error": f"Failed to set Variable {name}."})
                return
            updated_variables.append(name)

        if not restrict_default_workflow_permissions(repository):
            self._json(
                400,
                {"ok": False, "error": "配置已保存，但无法把仓库默认工作流权限限制为只读。请检查仓库 Actions 设置后重试。"},
            )
            return

        for workflow in ("check-grades.yml", "test-notifications.yml", "sync-upstream.yml"):
            result = gh("workflow", "enable", workflow, "--repo", repository)
            if result.returncode != 0:
                self._json(400, {"ok": False, "error": f"配置已保存，但无法启用工作流 {workflow}。"})
                return

        test_started = False
        test_status = "not_requested"
        test_url = ""
        if payload.get("run_test"):
            previous_run = latest_workflow_run(repository, "test-notifications.yml")
            result = gh("workflow", "run", "test-notifications.yml", "--repo", repository)
            test_started = result.returncode == 0
            if not test_started:
                self._json(400, {"ok": False, "error": "配置已保存，但通知测试未能启动，请再次点击完成配置。"})
                return
            completed_run = wait_for_workflow(
                repository,
                "test-notifications.yml",
                previous_run.get("databaseId") if previous_run else None,
            )
            if completed_run:
                test_url = str(completed_run.get("url", ""))
                test_status = (
                    "success"
                    if completed_run.get("status") == "completed"
                    and completed_run.get("conclusion") == "success"
                    else "failure"
                    if completed_run.get("status") == "completed"
                    else "pending"
                )
            else:
                test_status = "pending"
        self._json(
            200,
            {
                "ok": True,
                "secrets_updated": updated_secrets,
                "secrets_deleted": deleted_secrets,
                "variables_updated": updated_variables,
                "variables_deleted": deleted_variables,
                "test_started": test_started,
                "test_status": test_status,
                "test_url": test_url,
                "repository_url": f"https://github.com/{repository}",
                "actions_url": f"https://github.com/{repository}/actions",
            },
        )


def main() -> None:
    if not PAGE.exists():
        raise SystemExit("setup/index.html is missing")
    port = int(os.environ.get("SETUP_PORT", "0"))
    is_cloud = cloud_mode()
    server = SetupServer(("0.0.0.0" if is_cloud else "127.0.0.1", port), Handler)
    server.csrf_token = secrets.token_urlsafe(32)
    server.cloud = is_cloud
    server.trusted_cloud_host = codespace_host(server.server_port) if is_cloud else ""
    server.verified_login_digest = ""
    url = (
        f"https://{server.trusted_cloud_host}/"
        if server.trusted_cloud_host
        else f"http://127.0.0.1:{server.server_port}/"
    )
    print(f"Setup wizard: {url}")
    print("Press Ctrl+C to stop it.")
    if os.environ.get("SETUP_NO_BROWSER") != "1":
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
