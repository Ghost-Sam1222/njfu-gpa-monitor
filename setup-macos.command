#!/bin/zsh
cd "${0:A:h}" || exit 1
if [[ ! -x .setup-venv/bin/python ]]; then
  python3 -m venv .setup-venv || exit 1
fi
.setup-venv/bin/python -c "import playwright" 2>/dev/null || .setup-venv/bin/pip install -r requirements.txt || exit 1
.setup-venv/bin/python -m playwright install chromium || exit 1
.setup-venv/bin/python scripts/setup_wizard.py
