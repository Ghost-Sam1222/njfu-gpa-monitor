# Repository Guidelines

## Project Structure & Module Organization

This repository is a small Python monitor driven by GitHub Actions. `scripts/check_grades.py` orchestrates each run. Configuration, JWXT access, state, notifications, and transcript rendering live in focused modules under `scripts/`. The setup UI is `setup/index.html`, served locally or in a private Codespace by `scripts/setup_wizard.py`; `.devcontainer/` boots the cloud path, and `docs/` is the public GitHub Pages entry. Workflows are in `.github/workflows/`; tests are in `tests/`; notification artwork is in `assets/`. Runtime files under `data/` and `reports/` must stay untracked.

## Build, Test, and Development Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
PYTHONPATH=scripts python -m unittest discover -s tests -v
python -m py_compile scripts/*.py
```

Copy `.env.example` to `.env` for local runs, then execute `python scripts/check_grades.py`. Start the local configuration UI with `python scripts/setup_wizard.py`.

## Coding Style & Naming Conventions

Use Python 3.12-compatible syntax, 4-space indentation, type hints, dataclasses for structured values, and standard-library APIs when they keep the project lighter. Modules and functions use `snake_case`; classes use `PascalCase`. Keep channel-specific HTTP payloads in `notifications.py`, parsing in `grade_source.py`, and orchestration in `check_grades.py`.

## Testing Guidelines

Use `unittest`; name files `tests/test_*.py` and methods `test_*`. Cover parser column changes, semester isolation, zero-grade initialization, per-channel retries, threshold behavior, HTML escaping, and weighted averages. Never use live credentials in automated tests.

## Commit & Pull Request Guidelines

Use short imperative commits such as `add email transcript reports`. Pull requests must list new Secrets/Variables, state-schema changes, notification behavior, and verification commands.

## Security & Configuration

Credentials, Cookies, webhook URLs, email authorization codes, and device keys belong in GitHub Secrets or an ignored local `.env`. Never log notification bodies, remote response bodies, course data, or full URLs containing tokens. The public Pages entry must never collect Secrets; sensitive configuration is allowed only through the localhost wizard or its private Codespaces port.
