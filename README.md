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

打开[云端配置页](https://ghost-sam1222.github.io/njfu-gpa-monitor/)，输入仓库所有者和新仓库名称，然后依次点击两个按钮。第一个按钮通过 GitHub 官方模板创建个人仓库；创建完成后回到入口页，确认所有者和名称与仓库首页完全一致，再用第二个按钮启动该仓库的临时 Codespace。GitHub 不允许公开网页替用户创建私有仓库或写入 Secrets，因此这两个确认步骤不能安全合并。创建时可按页面说明选择 Private 或 Public。用户只需要：

1. 验证教务账号和指定学期是否能正常查询；首次部署未验证时不能显示成功。
2. 选择频率和完成条件。首次部署默认不启用定时监控；考试安排未发布时可先留空日期。准备开启时再填写停止日期。
3. 配置任意通知渠道。
4. 点击“完成配置”，写入 Secrets/Variables 并触发通知测试。

“停止日期”旁的“读取考试安排”会调用项目内置考试 API，按所选学期读取教务系统发布的全部考试项目，包括不同校区、机考和纸笔考试。页面会区分“尚未发布项目”“项目已发布但没有当前账号的考试”“部分项目读取失败”和“登录失效”。只有每个项目都成功解析且至少取得一场有日期的考试时，页面才允许采用“最后一场考试 + 30 天”；不完整结果不会覆盖人工日期，已有的更晚日期也会保留。考试安排只在用户点击时查询，不会增加每次成绩检查的请求量。

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
| `MONITOR_UNTIL` | `2027-02-10` | 启用监控时必填；这是硬截止，建议设为最后一场考试后 30 天 |
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

`Check NJFU Grades` 根据频率预设定时执行，也可以手动运行。定时任务在 `MONITOR_ENABLED=false`、未到开始日期、超过停止日期或当前完成条件已经收尾时，会在安装依赖和登录之前结束，并在 Actions 摘要中显示原因。按名单或数量确认完成、且通知全部送达后停止查询；邮件未满批量阈值的剩余更新也会在收尾时发送。按日期模式只是时间兜底，不声称课程已全部出分。

完成标记绑定学期、完成条件、停止日期和渠道集合，缓存只记录加盐摘要。改变这些设置会恢复检查；旧版没有配置摘要的完成缓存不会直接拦住查询。GitHub 缓存若被清除或过期，下次可能重新检查，因此这里是尽量节省请求，不承诺调度永久不启动 Runner。手动运行默认勾选 `force_check`，可绕过完成状态、监控开关和日期范围查询一次，继续发现新增或更正成绩；不需要清空已送达状态。

每次运行遇到临时教务或网络错误会先重试两次；仍失败才记录一次连续故障。连续每 3 次失败会发送一次不含成绩的健康提醒。所有日期判断统一使用北京时间，停止日也不会把空成绩列表误判为“成绩已齐”。

未设置完成方式时会安全地使用 `date`。为兼容早期设置页曾写入的错误组合，若仓库中是 `count`、数量为 `0`，但已有课程名单，程序会自动按 `names` 运行；真正缺少完成条件时仍会明确报错，不会静默误判成绩已齐。

如果停止日期后又公布了成绩，直接手动运行 `Check NJFU Grades`，保留默认的 `force_check`，不要勾选 `reset_state`。这样会保留上次状态，只通知真正新增或更正的成绩。`reset_state` 仅用于状态损坏或准备重新建立基线；默认不会把重置时已经存在的成绩重新通知。

`Verify NJFU Login` 只手动运行，允许临时选择学期，只确认真实登录与成绩表读取，不输出课程、分数或数量，不读取推送密钥、不更新基线、不发通知。尚未公布成绩的有效空表也可通过验证。`Test Notifications` 单独测试已配置渠道，不登录教务系统。这两项都通过后，再按需要手动运行一次成绩检查建立基线。

### 当前验收边界

课表摘要的合成数据导入、拒绝分支与实体 iPhone 布局已经验收。真实考试安排需等学校发布后，再核对所选学期的各校区、机考和纸笔项目；在此之前不把接口返回空项目当成“没有考试”，也不自动生成截止日期。课表摘要不属于部署必经步骤。

本轮新增的收尾行为已通过离线回归、独立代码审查和云端 Tests；“先保存配置、不开定时监控”的网页行为也已验证。2026-10-26 的真实验收中，[独立通知测试](https://github.com/Ghost-Sam1222/njfu-gpa-monitor/actions/runs/40314330863)成功，表示 Bark 服务接受请求，设备实际收取仍需使用者确认。首次登录失败后，使用者确认学校密码修改后未同步 GitHub Secret；仅更新 Secret、未修改登录代码，[再次独立验证](https://github.com/Ghost-Sam1222/njfu-gpa-monitor/actions/runs/40332754904)即通过，所选学期返回有效空成绩表。本次未查询考试安排、未更改成绩基线、未重发通知。真实考试安排和全新模板仓库的完整云端部署仍待验收，这些结果不代表未来接口永不变化。

`Apply Upstream Fixes` 只支持手动触发。运行前先查看源仓库最近更新；它会替换公开程序、工作流和文档，但不会读取或修改 Secrets/Variables。一个稳定学期内通常不需要运行。

## 考试安排 API 与 CLI

### 可选的课表摘要

配置页支持选择课表项目导出的 `term-summary.json`，在私有 Codespace 或本地设置页中校验；不会自动寻找公开地址、读取其他仓库的密钥或保存上传文件。不导入、导入失败均不影响现有监控。

消费方只接受版本 `1`、与当前选择一致的学期、最近 14 天内的 UTC 生成时间及 `school_web` / `school_app_api` 来源。测试来源、未知来源、未来时间、过期摘要和不一致的日期依据会被拒绝。人工配置学期和人工调课会单独标注。来源只是文件声明，不是加密认证；只导入自己可信课表项目的文件。

结课日来自最后一个生成的课程事件，只用于辅助判断何时关注成绩，**不等于最后考试日**。它不会填写或覆盖开始日期、最终截止或成绩完成条件；完整考试安排和用户明确设置的日期始终优先。若没有课程日期，页面会明确显示缺失，不会猜测。

程序接口为 `term_summary.inspect_term_summary(payload, semester)`，也可显式检查本地文件（不联网）：

```bash
python scripts/term_summary.py /path/to/term-summary.json --semester 2026-2027-1
```

退出码 `0` 表示可作参考，`2` 表示缺失、不可信或不可用；输出仅包含校验状态、日期及依据，不包含课程或成绩。

### 考试安排

考试安排的核心实现位于 `scripts/exam_source.py`。它使用南林强智教务系统当前接口动态读取指定学期的考试项目，再逐项查询安排；配置网页只调用这套实现，不维护第二份抓取逻辑。

本地或 Codespace 中可直接使用 CLI。账号密码只从环境变量读取，不接受命令行参数，避免出现在终端历史和进程列表中：

```bash
export JW_USERNAME='你的学号'
export JW_PASSWORD='你的密码'
python scripts/exam_source.py --semester 2026-2027-1 --format summary
python scripts/exam_source.py --semester 2026-2027-1 --format suggested
```

`summary` 只输出考试数量、项目数量、最晚日期和建议停止日期，适合日志；`latest` 只输出最后考试日，`suggested` 输出最后考试日加 30 天。`json` 会输出课程、时间和考场明细，仅应在自己的设备或私有 Codespace 中使用，不要复制到公开 Actions 日志。

退出码：`0` 表示全部项目查询完成，`2` 表示存在未能解析的项目，`3` 表示缺少凭据或登录失败，`4` 表示响应格式无法解析，`5` 表示其他查询故障。项目列表为空或考试尚未发布时可能正常返回 `0`，但不会产生建议日期。

不使用终端时，可以在 Actions 中手动运行 `Query NJFU Exams`，留空学期会读取 `JW_SEMESTER`。该工作流只把不含课程、考场和座位的摘要写入运行总结，不会定时执行，也不会修改 `MONITOR_UNTIL`。

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
