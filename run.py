#!/usr/bin/env python3
"""Chạy web chấm công VDL mà không cần bash.

Cách dùng:
    python run.py                # cổng 8000, chỉ máy này truy cập
    PORT=9000 python run.py      # đổi cổng (Mac/Linux)
    set PORT=9000 && python run.py   # đổi cổng (Windows cmd)

Muốn máy khác trong mạng LAN truy cập được:
    HOST=0.0.0.0 python run.py
"""
import os
import sys


def main() -> int:
    try:
        import uvicorn
    except ImportError:
        print("Chưa cài uvicorn. Chạy: python -m pip install -r requirements.txt")
        return 1

    host = os.environ.get("HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        print("PORT phải là số, ví dụ: PORT=9000 python run.py")
        return 1

    # tạo database + dữ liệu mẫu nếu chưa có
    if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db")):
        print("Chưa có database, đang nạp dữ liệu từ file Excel mẫu...")
        try:
            from app import seed
            seed.main(reset=False)
        except Exception as exc:
            print(f"Không nạp được dữ liệu mẫu: {exc}")
            print("Kiểm tra file data/source/FORM TIMESHEET 2026 VDL VN.xlsx")

    print(f"Đang chạy tại http://{host}:{port}  (Ctrl+C để dừng)")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
