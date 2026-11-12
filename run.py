#!/usr/bin/env python3
"""Chạy web chấm công VDL mà không cần bash.

Cài đặt (một lần):
    python -m venv .venv
    .venv\\Scripts\\activate        (Windows)   |  source .venv/bin/activate   (macOS/Linux)
    pip install -r requirements.txt

Chạy:
    python run.py                  -> http://127.0.0.1:8000
    set PORT=9000 && python run.py   (Windows)
    PORT=9000 python run.py          (macOS/Linux)

Cho máy khác trong LAN truy cập: set HOST=0.0.0.0 && python run.py
Lỗi chi tiết được ghi vào log.txt cạnh file này.
"""
import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "log.txt")


def write_log(text: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


def main() -> int:
    try:
        import uvicorn
    except ImportError:
        msg = ("Chưa cài thư viện. Chạy: python -m pip install -r requirements.txt")
        print(msg)
        write_log(msg)
        return 1

    host = os.environ.get("HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        print("PORT phải là số, ví dụ: PORT=9000 python run.py")
        return 1

    if not os.path.exists(os.path.join(BASE_DIR, "data", "app.db")):
        print("Chưa có database, đang khởi tạo...")
        try:
            sys.path.insert(0, BASE_DIR)
            from app import seed
            seed.main(reset=False)
        except Exception:
            err = "Không khởi tạo được database:\n" + traceback.format_exc()
            print(err)
            write_log(err)

    for candidate in range(port, port + 6):
        print(f"Đang chạy tại http://{host}:{candidate}  (Ctrl+C để dừng)")
        print(f"Mở trên máy này: http://127.0.0.1:{candidate}")
        try:
            uvicorn.run("app.main:app", host=host, port=candidate, log_level="info")
            return 0
        except OSError as exc:
            print(f"Cổng {candidate} không dùng được ({exc}), thử cổng khác...")
        except Exception:
            err = traceback.format_exc()
            print("Ứng dụng dừng do lỗi:\n" + err)
            write_log(err)
            return 1

    msg = f"Không mở được cổng nào từ {port} đến {port + 5}."
    print(msg)
    write_log(msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
