# Repository Guidelines

## Project Structure & Module Organization

This repository contains a small Python monitor plus one GitHub Actions workflow. Main logic lives in `scripts/check_grades.py`. Runtime state is written to `data/grade_state.json` by the workflow; keep `data/.gitkeep` so the directory exists. Notification artwork lives in `assets/`. Automation is configured in `.github/workflows/check-grades.yml`. Use `.env.example` as the local configuration template; never commit a real `.env`.

## Build, Test, and Development Commands

Create a local environment before editing:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Run the monitor locally with test credentials in `.env`:

```bash
python scripts/check_grades.py
```

Run a quick syntax check:

```bash
python -m py_compile scripts/check_grades.py
```

## Coding Style & Naming Conventions

Use Python 3.12-compatible syntax, 4-space indentation, type hints for public helpers, and concise function names such as `load_settings`, `fetch_grades`, and `save_state`. Keep secrets in environment variables only. Do not print course scores, passwords, Bark keys, or raw HTTP URLs containing credentials.

## Testing Guidelines

There is no formal test suite yet. For every change, run `python -m py_compile scripts/check_grades.py`. For behavior changes, test with `MONITOR_ENABLED=false` first, then use GitHub Actions `workflow_dispatch` after Secrets and Variables are configured. Avoid committing generated local caches.

## Commit & Pull Request Guidelines

Use short, imperative commit messages, for example `add grade monitor` or `update workflow schedule`. Pull requests should describe the behavior change, list any new configuration variables, and mention whether notification text, state format, or schedule changed.

## Security & Configuration Tips

Required private values belong in GitHub Actions Secrets: `JW_USERNAME`, `JW_PASSWORD`, `BARK_DEVICE_KEY`, and `GRADE_STATE_SALT`. Public Variables may contain term dates, expected course names, and Bark display settings. The state file must store only salted hashes and counts, not raw grades.
