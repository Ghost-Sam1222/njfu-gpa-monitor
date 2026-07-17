#!/usr/bin/env bash
set -euo pipefail

pid_file="/tmp/njfu-gpa-setup.pid"
if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  exit 0
fi

SETUP_CLOUD=1 SETUP_PORT=8765 SETUP_NO_BROWSER=1 \
  nohup python scripts/setup_wizard.py >/tmp/njfu-gpa-setup.log 2>&1 &
echo "$!" >"$pid_file"
