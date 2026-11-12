#!/bin/bash
# Chạy web chấm công với HTTPS (chứng chỉ tự ký) trên cổng 8443
cd "$(dirname "$0")" || exit 1

CERT_DIR="$HOME/.config/vdl-timesheet/certs"
CERT="$CERT_DIR/cert.pem"
KEY="$CERT_DIR/key.pem"
IP=$(hostname -I 2>/dev/null | awk '{print $1}')

if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
  echo "Chưa có chứng chỉ, đang tạo..."
  mkdir -p "$CERT_DIR"
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$KEY" -out "$CERT" -days 825 \
    -subj "/CN=chamcong-vdl.local" \
    -addext "subjectAltName=DNS:chamcong-vdl.local,DNS:localhost,IP:127.0.0.1,IP:${IP:-127.0.0.1}" >/dev/null 2>&1
fi

PY="./python/bin/python3"
[ -x "$PY" ] || PY=$(command -v python3)
[ -x "./.venv/bin/python" ] && PY="./.venv/bin/python"

echo "=========================================="
echo "  CHAM CONG VDL VN - HTTPS"
echo "=========================================="
echo "Mở: https://${IP:-127.0.0.1}:8443"
echo "Lần đầu trình duyệt cảnh báo chứng chỉ: bấm Nâng cao -> Tiếp tục."
echo "Dừng: Ctrl+C"
echo

exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8443 \
  --ssl-keyfile "$KEY" --ssl-certfile "$CERT"
