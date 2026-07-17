# NJFU GPA Monitor

南京林业大学教务系统低频成绩监控。项目使用 GitHub Actions 定时登录 JWXT，发现新增或更正成绩后推送通知；达到邮件批量阈值或本学期成绩全部到齐时，发送一份可排序的简洁 HTML 成绩单。

## 功能

- 只查询 `JW_SEMESTER` 指定学期，自动识别课程、课程编号、学分、课程属性、成绩和绩点。
- 支持 Bark、飞书、钉钉、企业微信、Telegram、ntfy、Slack、邮件和通用 Webhook。
- 实时渠道按批次推送新成绩；邮件可用 `EMAIL_BATCH_SIZE` 设置累计几项后发送。
- 完成时向实时渠道发送文字版成绩单；邮件额外使用 Apple 风格 HTML，显示学分加权平均成绩、平均绩点和可排序课程明细。
- 每个渠道独立记录投递状态。一个渠道失败时，不会让其他成功渠道重复通知。
- 支持 2、3、6、12、24 小时频率预设；未选中的计划不会启动 GitHub Runner。
- 状态按学期隔离。新学期不会被上学期的“已完成”缓存拦住。

通知渠道设计参考了 [TrendRadar](https://github.com/sansan0/TrendRadar)，但本项目只保留成绩监控所需的轻量实现。

## 快速设置

先从本仓库创建自己的仓库并下载到电脑。安装 [GitHub CLI](https://cli.github.com/)，完成一次登录：

```bash
gh auth login -h github.com
```

macOS 可双击 `setup-macos.command`，Windows 可双击 `setup-windows.bat`。首次启动会在 `.setup-venv` 中安装依赖和专用 Chromium，全部留在项目目录内。也可手动运行：

```bash
python3 scripts/setup_wizard.py
```

本地设置页可以：

1. 验证教务账号和指定学期是否能正常查询。
2. 选择检查频率、停止日期和成绩完成条件。
3. 配置任意通知渠道。
4. 通过本机 GitHub CLI 写入仓库 Secrets/Variables，并触发通知测试。

设置页只监听 `127.0.0.1`，不使用浏览器 Cookie 或 LocalStorage 保存表单。空白 Secret 不会覆盖仓库中已经存在的值，重复运行向导也不会轮换已有的 `GRADE_STATE_SALT`。

## 登录方式

推荐把 `JW_USERNAME` 和 `JW_PASSWORD` 放入 GitHub Secrets。每次运行时 Playwright 会临时完成登录并建立会话，不需要长期维护 Cookie。

也可以设置 `JW_COOKIE`，但学校会话会过期；若只设置 Cookie，过期后需要重新配置。账号密码与 Cookie 同时存在时，Cookie 失效会自动回退到账号密码登录。程序在填写密码前会验证当前页面属于 `njfu.edu.cn`，拒绝向其他域名发送凭据。

## 配置

核心 Variables：

| 名称 | 示例 | 说明 |
| --- | --- | --- |
| `JW_SEMESTER` | `2026-2027-1` | 当前学期 |
| `CHECK_INTERVAL_HOURS` | `6` | 只能为 `2/3/6/12/24` |
| `MONITOR_ENABLED` | `true` | 定时监控总开关 |
| `CHECK_START_DATE` | `2026-12-20` | 可选，开始日期 |
| `MONITOR_UNTIL` | `2027-01-20` | 可选，硬停止日期 |
| `EXPECTED_GRADE_COUNT` | `9` | 可选，达到数量后完成 |
| `EXPECTED_COURSE_NAMES` | `课程A,课程B` | 可选，精确匹配全部课程后完成；优先于数量 |
| `EMAIL_BATCH_SIZE` | `3` | 累计几项新成绩后发邮件 |
| `FINAL_REPORT_ENABLED` | `true` | 完成时强制发送最终成绩单 |

必需 Secrets：

- `JW_USERNAME` 与 `JW_PASSWORD`，或短期使用 `JW_COOKIE`
- `GRADE_STATE_SALT`：至少 32 位随机字符串
- 至少一套通知渠道凭据

渠道 Secrets：

| 渠道 | Secrets |
| --- | --- |
| Bark | `BARK_DEVICE_KEY`，可选 `BARK_SERVER` |
| 飞书 | `FEISHU_WEBHOOK_URL` |
| 钉钉 | `DINGTALK_WEBHOOK_URL` |
| 企业微信 | `WEWORK_WEBHOOK_URL` |
| Telegram | `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` |
| ntfy | `NTFY_TOPIC`，可选 `NTFY_SERVER_URL`、`NTFY_TOKEN` |
| Slack | `SLACK_WEBHOOK_URL` |
| 通用 Webhook | `GENERIC_WEBHOOK_URL`，可选 `GENERIC_WEBHOOK_TEMPLATE` |
| 邮件 | `EMAIL_FROM`、`EMAIL_PASSWORD`、`EMAIL_TO`，可选 SMTP 地址与端口 |

通用 Webhook 模板必须是 JSON，可在任意字符串值中使用 `{title}` 和 `{content}`。不配置模板时发送：

```json
{"title": "通知标题", "content": "通知正文"}
```

## 隐私边界

这个项目保证的是“个人数据不进入公开仓库和公开日志”，不是“数据完全不离开本机”：

- GitHub Secrets 由 GitHub 加密保存，Actions Runner 在运行期间会读取账号并访问学校系统。
- 通知服务会收到通知正文；实时通知包含课程名和成绩，邮件会收到完整成绩单。
- HTML 成绩单只在 Runner 临时目录生成并作为邮件正文发送，不上传 GitHub Pages 或 Actions Artifact。
- Actions 缓存只保存学期、更新时间、完成状态、待发计数、渠道名称和加盐哈希，不保存课程名、成绩、绩点、密码、Cookie 或推送密钥。
- 公开日志只显示渠道名以及“是否变化/是否完成”，不输出成绩数量、课程名、成绩或远端响应正文。

若不信任 GitHub 托管 Runner 或第三方通知服务，请在自己的电脑或服务器运行本项目，并选择自托管通知端点。

## 工作流

`Check NJFU Grades` 根据频率预设定时执行，也可以手动运行。`MONITOR_ENABLED=false`、未到开始日期、超过停止日期或已完成时，会在安装依赖和登录之前结束。

如果成绩已齐后又增加了课程，手动运行 `Check NJFU Grades` 并勾选 `reset_state`。它只重建当前学期基线，不影响其他学期。

`Test Notifications` 只测试已配置的通知渠道，不登录教务系统。首次部署建议先运行它，再手动运行一次成绩检查建立基线。

## 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python scripts/check_grades.py
```

测试与静态检查：

```bash
PYTHONPATH=scripts python -m unittest discover -s tests -v
python -m py_compile scripts/*.py
```

## License

[MIT](LICENSE)
