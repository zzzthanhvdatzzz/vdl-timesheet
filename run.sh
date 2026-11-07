#!/usr/bin/env bash
# Khởi động web chấm công VDL VN
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
if [ ! -x "$HOME/.venv-timesheet/bin/uvicorn" ]; then
  echo "Thiếu venv ~/.venv-timesheet — chạy: uv venv ~/.venv-timesheet --python 3.11 && uv pip install --python ~/.venv-timesheet/bin/python fastapi 'uvicorn[standard]' openpyxl"
  exit 1
fi
if [ ! -f data/app.db ]; then
  echo "Chưa có DB, đang seed từ Excel..."
  ~/.venv-timesheet/bin/python -m app.seed --reset
fi
exec ~/.venv-timesheet/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
