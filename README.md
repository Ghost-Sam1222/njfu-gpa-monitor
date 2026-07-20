# NJFU GPA Monitor

南京林业大学教务系统低频成绩监控。项目使用 GitHub Actions 定时登录 JWXT，发现新增或更正成绩后推送通知；达到邮件批量阈值或本学期成绩全部到齐时，发送一份可排序的简洁 HTML 成绩单。

## 零基础云端配置教程

https://github.com/user-attachments/assets/09fe3f6a-d11d-426c-9fc4-bf6398ec6ccd

部署个人监控时，请通过模板创建新仓库，不要使用普通 Fork。推荐选择 **Private**；若希望使用免费的公开仓库标准 Actions，也可以选择 **Public**，但 Variables 和运行日志会公开。账号、密码和通知密钥只写入 GitHub Secrets。

[打开网页，开始云端配置](https://ghost-sam1222.github.io/njfu-gpa-monitor/) · [先选适合你的通知渠道](https://ghost-sam1222.github.io/njfu-gpa-monitor/channels.html)

## 功能

- 只查询 `JW_SEMESTER` 指定学期，自动识别课程、课程编号、学分、课程属性、成绩和绩点。
- 支持 Bark、飞书、钉钉、企业微信、Telegram、ntfy、Slack、邮件和通用 Webhook。
- 实时渠道按“课程｜成绩、绩点、学分”推送，并附当前学分加权平均绩点；邮件可用 `EMAIL_BATCH_SIZE` 设置累计几项后发送。
- 成绩齐全时，实时渠道只发送完成状态和平均绩点；邮件额外使用简洁 HTML 成绩单，显示平均成绩、平均绩点和可排序课程明细。
- 每个渠道独立记录投递状态。一个渠道失败时，不会让其他成功渠道重复通知。
- 支持 2、3、6、12、24 小时频率预设；未选中的计划不会启动 GitHub Runner。
- 每月只做一次轻量保活提交，避免公开仓库因 60 天无活动被 GitHub 自动停用定时任务；它与手动程序更新互不影响。
- 上游程序更新只允许手动触发，避免静默替换能够接触 Secrets 的可执行代码；仓库默认工作流令牌保持只读，只有保活和手动更新任务单独申请内容写权限。
- 状态按学期隔离。新学期不会被上学期的“已完成”缓存拦住。

通知渠道设计参考了 [TrendRadar](https://github.com/sansan0/TrendRadar)，但本项目只保留成绩监控所需的轻量实现。

## 一键云端设置

打开[云端配置页](https://ghost-sam1222.github.io/njfu-gpa-monitor/)，输入 GitHub 用户名和新仓库名称，然后依次点击两个按钮。第一个按钮通过 GitHub 官方模板创建个人仓库，第二个按钮启动同名仓库的临时 Codespace，随后自动打开设置页。创建时可按页面说明选择 Private 或 Public。用户只需要：

1. 验证教务账号和指定学期是否能正常查询；首次部署未验证时不能显示成功。
2. 选择检查频率、停止日期和成绩完成条件。
3. 配置任意通知渠道。
4. 点击“完成配置”，写入 Secrets/Variables 并触发通知测试。

Codespaces 转发端口保持 Private，只有创建者登录 GitHub 后才能访问；配置完成后可以删除该 Codespace。设置页不使用浏览器 Cookie 或 LocalStorage 保存表单，也会关闭教务密码自动填充；账号密码不会经过 GitHub Pages，也不会发送给项目作者。空白 Secret 不会覆盖仓库中已有值，重复设置不会轮换已有的 `GRADE_STATE_SALT`。删除渠道时，设置页会拒绝保存“一个通知渠道都没有”的状态。

本地备用路径会自动准备隔离环境：macOS 双击 `setup-macos.command`，Linux 运行 `setup-linux.sh`，Windows 双击 `setup-windows.bat`。

## 登录方式

推荐把 `JW_USERNAME` 和 `JW_PASSWORD` 放入 GitHub Secrets。每次运行时 Playwright 会临时完成登录并建立会话，不需要长期维护 Cookie。登录凭据只允许发送到 `jwxt.njfu.edu.cn`、`uia.njfu.edu.cn` 和兼容旧入口的 `authserver.njfu.edu.cn`，其他地址会被拒绝。

也可以设置 `JW_COOKIE`，但学校会话会过期；若只设置 Cookie，过期后需要重新配置。账号密码与 Cookie 同时存在时，Cookie 失效会自动回退到账号密码登录。程序在填写密码前会验证当前页面属于 `njfu.edu.cn`，拒绝向其他域名发送凭据。

## 配置

核心 Variables：

| 名称 | 示例 | 说明 |
| --- | --- | --- |
| `JW_SEMESTER` | `2026-2027-1` | 当前学期 |
| `CHECK_INTERVAL_HOURS` | `6` | 只能为 `2/3/6/12/24` |
| `MONITOR_ENABLED` | `true` | 定时监控总开关 |
| `CHECK_START_DATE` | `2026-12-20` | 可选，开始日期 |
| `MONITOR_UNTIL` | `2027-01-20` | 启用监控时必填，超过该日期停止 |
| `COMPLETION_MODE` | `date` | `date`（默认，停止日期当天发最终成绩单）、`count` 或 `names` |
| `EXPECTED_GRADE_COUNT` | `9` | `count` 模式必填，至少为 1 |
| `EXPECTED_COURSE_NAMES` | `课程A,课程B` | `names` 模式必填，精确匹配全部课程 |
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

这个项目保证的是“个人数据不进入公开仓库和公开日志”，不是“数据只在个人设备本地处理”：

- GitHub Secrets 由 GitHub 加密保存，Actions Runner 在运行期间会读取账号并访问学校系统。
- 通知服务会收到通知正文；实时通知包含课程、成绩、绩点、学分和平均绩点，邮件会收到完整成绩单。
- 云端设置时，账号密码会通过 GitHub 的加密连接进入用户自己的私有 Codespace，再写入 GitHub Secrets；不会经过公开 Pages 或项目作者的服务器。
- HTML 成绩单只在 Runner 临时目录生成并作为邮件正文发送，不上传 GitHub Pages 或 Actions Artifact。
- Actions 缓存只保存学期、更新时间、完成状态、待发计数、渠道名称和加盐哈希，不保存课程名、成绩、绩点、密码、Cookie 或推送密钥。
- 公开日志只显示渠道名以及“是否变化/是否完成”，不输出成绩数量、课程名、成绩或远端响应正文。

若不信任 GitHub 托管 Runner 或第三方通知服务，请在自己的电脑或服务器运行本项目，并选择自托管通知端点。

## 工作流

`Check NJFU Grades` 根据频率预设定时执行，也可以手动运行。`MONITOR_ENABLED=false`、未到开始日期或超过停止日期时，会在安装依赖和登录之前结束。达到完成条件后只发送一次完成提醒，仍会低频检查到停止日期，以捕捉新增或更正成绩。

每次运行遇到临时教务或网络错误会先重试两次；仍失败才记录一次连续故障。连续每 3 次失败会发送一次不含成绩的健康提醒。所有日期判断统一使用北京时间，停止日也不会把空成绩列表误判为“成绩已齐”。

未设置完成方式时会安全地使用 `date`。为兼容早期设置页曾写入的错误组合，若仓库中是 `count`、数量为 `0`，但已有课程名单，程序会自动按 `names` 运行；真正缺少完成条件时仍会明确报错，不会静默误判成绩已齐。

如果成绩已齐后又增加了课程，手动运行 `Check NJFU Grades` 并勾选 `reset_state`。它只重建当前学期基线，不影响其他学期。

`Test Notifications` 只测试已配置的通知渠道，不登录教务系统。首次部署建议先运行它，再手动运行一次成绩检查建立基线。

`Apply Upstream Fixes` 只支持手动触发。运行前先查看源仓库最近更新；它会替换公开程序、工作流和文档，但不会读取或修改 Secrets/Variables。一个稳定学期内通常不需要运行。

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
