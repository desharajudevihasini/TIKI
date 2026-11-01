#!/bin/zsh
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if [[ ! -e .env ]]; then cp .env.example .env; fi
printf '\nTIKI is installed. Edit .env privately with your Gemini key and ESP IP.\n'
printf 'Then run ./start.command or: python -m uvicorn app.main:app --host 127.0.0.1 --port 8002\n'
