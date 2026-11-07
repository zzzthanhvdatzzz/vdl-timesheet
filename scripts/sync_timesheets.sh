#!/usr/bin/env bash
# Kéo toàn bộ file timesheet từ máy chủ về máy admin.
#
# Dùng:
#   VDL_ADMIN_PASS='mật khẩu admin' bash scripts/sync_timesheets.sh
# hoặc đặt biến môi trường trong ~/.config/vdl-timesheet.env rồi thêm dòng
#   */15 * * * * set -a; . $HOME/.config/vdl-timesheet.env; set +a; bash $HOME/timesheet-app/scripts/sync_timesheets.sh >> $HOME/.local/share/vdl-sync.log 2>&1
# vào crontab -e để 15 phút đồng bộ một lần.
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
ADMIN_USER="${VDL_ADMIN_USER:-admin}"
ADMIN_PASS="${VDL_ADMIN_PASS:-}"
DEST="${DEST:-$HOME/Timesheet-VDL}"

if [ -z "$ADMIN_PASS" ]; then
  echo "Thiếu VDL_ADMIN_PASS. Ví dụ: VDL_ADMIN_PASS='admin@2026' bash scripts/sync_timesheets.sh" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

code=$(curl -s -o "$TMP/login.json" -w '%{http_code}' \
  -c "$TMP/cookies" -X POST "$BASE_URL/api/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}")
if [ "$code" != "200" ]; then
  echo "Đăng nhập thất bại (HTTP $code): $(cat "$TMP/login.json")" >&2
  exit 2
fi

code=$(curl -s -b "$TMP/cookies" -o "$TMP/all.zip" -w '%{http_code}' "$BASE_URL/api/admin/timesheet-zip")
if [ "$code" != "200" ]; then
  echo "Không tải được gói zip (HTTP $code)" >&2
  exit 3
fi

mkdir -p "$DEST"
if command -v unzip >/dev/null 2>&1; then
  unzip -o -q "$TMP/all.zip" -d "$DEST"
  unzip -Z1 "$TMP/all.zip" > "$TMP/list.txt"
else
  python3 - "$TMP/all.zip" "$DEST" <<'PY'
import sys, zipfile
zf = zipfile.ZipFile(sys.argv[1])
zf.extractall(sys.argv[2])
print("\n".join(zf.namelist()))
PY
  python3 -c "import sys,zipfile;print('\n'.join(zipfile.ZipFile(sys.argv[1]).namelist()))" "$TMP/all.zip" > "$TMP/list.txt"
fi

# Dọn file cũ ở máy: file nào không còn trên máy chủ thì xoá khỏi thư mục đồng bộ
if [ "${MIRROR:-1}" = "1" ]; then
  while IFS= read -r -d '' local; do
    rel="${local#$DEST/}"
    if ! grep -qxF "$rel" "$TMP/list.txt"; then
      rm -f "$local"
      echo "đã xoá file không còn trên máy chủ: $rel"
    fi
  done < <(find "$DEST" -type f -name 'Timesheet_*.xlsx' -print0)
fi

count=$(find "$DEST" -name '*.xlsx' | wc -l)
echo "$(date '+%Y-%m-%d %H:%M:%S') đã đồng bộ $count file vào $DEST"
