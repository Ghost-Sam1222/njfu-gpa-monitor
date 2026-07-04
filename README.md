# NJFU GPA Monitor

Low-frequency GitHub Actions monitor for 南京林业大学教务系统出分提醒. It logs in to JWXT, checks the grade table, compares a privacy-preserving state file, and sends Bark notifications only when new grades appear.

This repository is designed to be reusable: fork it, set your own GitHub Secrets and Variables, then enable the workflow during exam week.

## How It Works

- GitHub Actions runs on a schedule or by manual dispatch.
- Playwright logs in to `jwxt.njfu.edu.cn` with credentials stored in GitHub Secrets.
- The script reads the grade table from `jsxsd/kscj/cjcx_list`.
- New grade rows are detected by salted SHA-256 hashes.
- Bark receives the actual course name and score; GitHub state stores only hashes and counts.
- Monitoring stops after `MONITOR_UNTIL`, `MONITOR_ENABLED=false`, or completion rules are satisfied.

## Privacy Model

Never commit `.env`, passwords, Bark keys, or screenshots with personal data. The committed state file contains:

- update time
- semester
- known grade count
- salted hashes
- completion flag

It does not store course names, scores, GPA values, credentials, or Bark device keys. It can still reveal metadata such as check time, semester, known grade count, and whether all expected grades have arrived. Code templates can be public, but a real monitor repository is safer as private.

Bark receives the notification content, including course names and scores. Use a Bark server you trust.

## Setup

1. Fork or create a repository from this project.
2. Go to `Settings -> Secrets and variables -> Actions`.
3. Add the required Secrets:

| Name | Example | Notes |
| --- | --- | --- |
| `JW_USERNAME` | `2450...` | Student ID |
| `JW_PASSWORD` | `********` | JWXT password |
| `BARK_DEVICE_KEY` | `********` | Bark device key |
| `GRADE_STATE_SALT` | random 32+ chars | Required; generate with `openssl rand -hex 32` |
| `BARK_SERVER` | `https://api.day.app` | Optional |

4. Add Variables for the current exam season:

| Name | Example | Notes |
| --- | --- | --- |
| `JW_BASE_URL` | `https://jwxt.njfu.edu.cn` | Usually unchanged |
| `JW_SEMESTER` | `2025-2026-2` | Academic term |
| `MONITOR_ENABLED` | `true` | Set `false` after use |
| `CHECK_START_DATE` | `2026-06-22` | First day to start checking |
| `MONITOR_UNTIL` | `2026-07-15` | Hard stop date |
| `EXPECTED_COURSE_NAMES` | `课程A,课程B` | Optional completion rule |
| `EXPECTED_NEW_COUNT` | `9` | Optional completion rule |
| `BARK_GROUP` | `njfu GPA` | Bark category |
| `BARK_SOUND` | `alarm` | Bark sound |
| `BARK_ICON` | raw image URL | Optional notification icon |
| `NOTIFY_ON_FIRST_RUN` | `false` | Avoid noisy first baseline |

## Schedule

The default workflow checks three times per day:

```yaml
cron: "30 2,8,14 * * *"
```

That is 10:30, 16:30, and 22:30 in Asia/Shanghai. Edit `.github/workflows/check-grades.yml` if you want lower frequency.

The workflow has a preflight guard. If `MONITOR_ENABLED=false`, today is before `CHECK_START_DATE`, today is after `MONITOR_UNTIL`, or `data/grade_state.json` is already complete, it exits before installing Python dependencies and Playwright.

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python scripts/check_grades.py
```

Syntax check:

```bash
python -m py_compile scripts/check_grades.py
```

## Bark Icon

This repository includes `assets/njfu-gpa-icon.png`. After pushing, set `BARK_ICON` to a raw GitHub URL like:

```text
https://raw.githubusercontent.com/<owner>/<repo>/main/assets/njfu-gpa-icon.png
```
