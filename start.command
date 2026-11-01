#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'First run ./setup.command (or install with requirements.txt in VS Code).'
  exit 1
fi
if [[ ! -f .env ]]; then cp .env.example .env; fi
source .venv/bin/activate
printf '\nTIKI started. Open http://localhost:8002 in your Mac browser.\n'
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8002
