# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.12 grade monitor run by GitHub Actions. `scripts/check_grades.py` coordinates fetching, state comparison, and delivery. Keep focused logic in the existing modules: JWXT parsing in `grade_source.py`, configuration in `config.py`, notification payloads in `notifications.py`, reports in `report.py`, and persisted state in `state.py`. The guided setup UI is `setup/index.html`, served by `scripts/setup_wizard.py`; `.devcontainer/` starts its private Codespaces version. `docs/` contains the public GitHub Pages launcher. Tests live in `tests/`, workflows in `.github/workflows/`, and notification artwork in `assets/`. Do not track generated files under `data/` or `reports/`.

## Build, Test, and Development Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python scripts/check_grades.py
PYTHONPATH=scripts python -m unittest discover -s tests -v
python -m py_compile scripts/*.py
```

The first four commands prepare a local environment. Run `scripts/setup_wizard.py` to test the browser setup flow. The final two commands are the required test and syntax checks before submission.

## Coding Style & Naming Conventions

Use 4-space indentation, type hints, and small functions. Prefer standard-library APIs and dataclasses to new dependencies. Use `snake_case` for modules, functions, and variables; use `PascalCase` for classes. No formatter or linter is enforced, so match nearby code and run `py_compile`. Keep comments brief and limited to non-obvious behavior.

## Testing Guidelines

Tests use `unittest`. Name files `test_*.py` and methods `test_*`. Add focused coverage for parser changes, semester isolation, first-run behavior, per-channel retries, batching, weighted averages, HTML escaping, and setup security. Never call live JWXT or notification services from automated tests.

## Commit & Pull Request Guidelines

History favors short imperative subjects, such as `add cloud setup flow` or `Harden Bark push diagnostics`. Keep each commit scoped. Pull requests should explain behavior changes, list new Secrets or Variables, note workflow/state-schema effects, and include verification output. Add desktop and mobile screenshots when changing `setup/`, `docs/`, or report HTML.

## Security & Configuration

Store passwords, cookies, device keys, email authorization codes, and webhook URLs only in GitHub Secrets or an ignored `.env`. Never log grades, notification bodies, token-bearing URLs, or remote response bodies. Public Pages must not collect secrets; sensitive setup is allowed only through localhost or the authenticated private Codespaces port.
