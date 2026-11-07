"""Seed dữ liệu từ file Excel FORM TIMESHEET 2026 VDL VN.xlsx vào SQLite.

Chạy:  python -m app.seed [--reset]
Xuất kèm file credentials.csv chứa tài khoản khởi tạo cho từng nhân viên.
"""
import csv
import os
import sys
from datetime import datetime

import openpyxl

from . import auth, db

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_XLSX = os.path.join(BASE_DIR, "data", "source", "FORM TIMESHEET 2026 VDL VN.xlsx")
CREDENTIALS_CSV = os.path.join(BASE_DIR, "data", "credentials.csv")


def read_cost_centres(ws):
    """Cột D = mã cost centre, cột E = tên."""
    out = {}
    for r in range(2, ws.max_row + 1):
        code = ws.cell(r, 4).value
        name = ws.cell(r, 5).value
        if not code:
            continue
        code = str(code).strip()
        name = (str(name).strip() if name else "")
        if code in out:
            if name and name not in out[code]:
                out[code] += " / " + name
        else:
            out[code] = name
    return out


def read_places(ws):
    """Cột K = tên place (VDL WORKSHOP, ...)."""
    out = []
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, 11).value
        if v:
            out.append(str(v).strip())
    return out


def read_name_list(ws):
    """A = pers.no, B = tên, C = loại (E/P)."""
    out = []
    for row in ws.iter_rows(min_row=1, values_only=True):
        if row[0] is None or row[1] is None:
            continue
        try:
            pers_no = int(row[0])
        except (TypeError, ValueError):
            continue
        out.append((pers_no, str(row[1]).strip(), (str(row[2]).strip().upper() if row[2] else "")))
    return out


def read_panels(ws):
    """A = project number, B = panel number, C = description, D = remark, E = miêu tả."""
    projects = set()
    panels = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        proj = row[0]
        if not proj:
            continue
        proj = str(proj).strip()
        projects.add(proj)
        panel = row[1]
        if panel is None or str(panel).strip() == "":
            continue
        panel = str(panel).strip()
        desc = (str(row[2]).strip() if len(row) > 2 and row[2] else "")
        remark = (str(row[3]).strip() if len(row) > 3 and row[3] else "")
        desc_vi = (str(row[4]).strip() if len(row) > 4 and row[4] else "")
        panels[(proj, panel)] = (desc, desc_vi, remark)
    return projects, panels


def default_cost_place(emp_type: str, places: list) -> str:
    """Tạm gán: Engineer -> 1074.01, Worker -> 1060.01. Admin sửa lại sau."""
    return "1074.01" if emp_type == "E" else "1060.01"


def main(reset: bool = False) -> None:
    if not os.path.exists(SOURCE_XLSX):
        sys.exit(f"Không thấy file nguồn: {SOURCE_XLSX}")

    if reset and os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
        print("đã xoá DB cũ")

    db.init_db()

    wb = openpyxl.load_workbook(SOURCE_XLSX, data_only=True)
    cost_centres = read_cost_centres(wb["Cost centre"])
    places = read_places(wb["Cost centre"])
    names = read_name_list(wb["Name list"])
    projects, panels = read_panels(wb["Panel list"])

    conn = db.connect()
    now = datetime.now().isoformat(timespec="seconds")
    creds = []

    with conn:
        for code, name in cost_centres.items():
            conn.execute(
                "INSERT OR REPLACE INTO cost_centres(code, name) VALUES (?, ?)", (code, name)
            )

        for proj in sorted(projects):
            conn.execute("INSERT OR IGNORE INTO projects(project_number) VALUES (?)", (proj,))

        for (proj, panel), (desc, desc_vi, remark) in panels.items():
            conn.execute(
                "INSERT OR IGNORE INTO panels(project_number, panel_number, description, desc_vi, remark)"
                " VALUES (?, ?, ?, ?, ?)",
                (proj, panel, desc, desc_vi, remark),
            )

        existing = {r["pers_no"] for r in conn.execute("SELECT pers_no FROM employees")}
        for pers_no, name, emp_type in names:
            if pers_no in existing:
                continue
            username = f"nv{pers_no:02d}"
            password = f"vdl@{pers_no:02d}"
            place = places[0] if places else None
            conn.execute(
                """INSERT INTO employees(pers_no, name, emp_type, username, password_hash,
                                        cost_place_code, place, is_admin)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (pers_no, name, emp_type, username, auth.hash_password(password),
                 default_cost_place(emp_type, places), place),
            )
            creds.append([username, password, pers_no, name, default_cost_place(emp_type, places)])

        admin = conn.execute("SELECT id FROM employees WHERE is_admin = 1").fetchone()
        if not admin:
            admin_pw = "admin@2026"
            conn.execute(
                """INSERT INTO employees(pers_no, name, emp_type, username, password_hash,
                                        cost_place_code, place, is_admin)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (0, "ADMIN", "A", "admin", auth.hash_password(admin_pw), "1079.01", None),
            )
            creds.insert(0, ["admin", admin_pw, 0, "ADMIN", "1079.01"])

    counts = {
        "cost_centres": conn.execute("SELECT COUNT(*) c FROM cost_centres").fetchone()["c"],
        "projects": conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"],
        "panels": conn.execute("SELECT COUNT(*) c FROM panels").fetchone()["c"],
        "employees": conn.execute("SELECT COUNT(*) c FROM employees").fetchone()["c"],
    }
    conn.close()

    if creds:
        os.makedirs(os.path.dirname(CREDENTIALS_CSV), exist_ok=True)
        with open(CREDENTIALS_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["username", "password", "pers_no", "name", "cost_place_code"])
            w.writerows(creds)

    print("seed xong:", counts)
    print("credentials:", CREDENTIALS_CSV)


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
