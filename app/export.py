"""Xuất timesheet tuần ra file Excel theo đúng mẫu FORM TIMESHEET 2026 VDL VN.xlsx."""
import io
import os
import unicodedata
from datetime import date, datetime, timedelta

import openpyxl

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, "data", "source")
TEMPLATE = os.path.join(TEMPLATE_DIR, "FORM TIMESHEET 2026 VDL VN.xlsx")
TIMESHEET_DIR = os.path.join(BASE_DIR, "data", "timesheets")

# (dòng bắt đầu, số dòng trống) cho từng thứ, khớp template: CN 4-6, T2 7-16, T3 17-26...
BLOCKS = {
    6: (4, 3),    # Sunday
    0: (7, 10),   # Monday
    1: (17, 10),  # Tuesday
    2: (27, 10),  # Wednesday
    3: (37, 10),  # Thursday
    4: (47, 10),  # Friday
    5: (57, 3),   # Saturday
}

# cột trong template
COL_PROJECT, COL_PANEL, COL_DESC, COL_PLACE = 2, 3, 4, 6
COL_NORMAL, COL_TRAVEL, COL_OTA, COL_OTB, COL_COSTPLACE = 7, 8, 9, 10, 15


def week_bounds(start: date):
    return start, start + timedelta(days=6)


def week_start(d: date) -> date:
    """Chuẩn hoá về Chủ nhật đầu tuần (timesheet bắt đầu từ Chủ nhật)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def week_number(start: date):
    """Số tuần theo cách đánh số của file mẫu: ISO week của ngày Thứ Hai trong tuần."""
    start = week_start(start)
    iso = (start + timedelta(days=1)).isocalendar()
    return iso[0], iso[1]


def _fill_week_sheet(ws, employee: dict, entries: list, start: date) -> int:
    """Điền dữ liệu một tuần vào sheet; trả về số dòng bị bỏ vì vượt chỗ trống."""
    start = week_start(start)
    start, end = week_bounds(start)
    year, week_no = week_number(start)

    ws["F1"] = start
    ws["H1"] = end
    ws["I1"] = year
    ws["M1"] = week_no
    ws["O1"] = employee["pers_no"] or 1
    ws["D1"] = employee["name"]

    by_day: dict[int, list] = {}
    for e in entries:
        d = date.fromisoformat(e["work_date"])
        by_day.setdefault(d.weekday(), []).append(e)

    # xoá sạch vùng nhập liệu trước khi điền
    for r in range(4, 60):
        for col in (COL_PROJECT, COL_PANEL, COL_DESC, COL_PLACE,
                    COL_NORMAL, COL_TRAVEL, COL_OTA, COL_OTB, 11, 12, 13, 14, COL_COSTPLACE):
            ws.cell(r, col).value = None

    skipped = 0
    for wd, rows in by_day.items():
        block_start, capacity = BLOCKS[wd]
        rows.sort(key=lambda r: r["id"])
        for idx, entry in enumerate(rows):
            if idx >= capacity:
                skipped += 1
                continue
            r = block_start + idx
            ws.cell(r, COL_PROJECT).value = entry["project_number"]
            ws.cell(r, COL_PANEL).value = entry["panel_number"] or None
            ws.cell(r, COL_DESC).value = entry["description"] or None
            ws.cell(r, COL_PLACE).value = employee.get("place") or None
            ws.cell(r, COL_NORMAL).value = entry["normal_hours"] or None
            ws.cell(r, COL_TRAVEL).value = entry["travel_hours"] or None
            ws.cell(r, COL_OTA).value = entry["ot_a"] or None
            ws.cell(r, COL_OTB).value = entry["ot_b"] or None
            ws.cell(r, COL_COSTPLACE).value = entry["cost_place"] or None
    return skipped


def build_week_file(employee: dict, entries: list, start: date) -> tuple[bytes, str, int]:
    """Tạo file timesheet tuần từ file mẫu (dùng khi chưa có file admin up lên)."""
    if not os.path.exists(TEMPLATE):
        raise FileNotFoundError(f"Không thấy file mẫu: {TEMPLATE}")

    start = week_start(start)
    year, week_no = week_number(start)

    wb = openpyxl.load_workbook(TEMPLATE)
    sheet_name = str(week_no)
    if sheet_name not in wb.sheetnames:
        sheet_name = "1"
    skipped = _fill_week_sheet(wb[sheet_name], employee, entries, start)

    buf = io.BytesIO()
    # chỉ giữ sheet tuần này để mở file là thấy ngay dữ liệu
    for other in list(wb.sheetnames):
        if other != sheet_name:
            del wb[other]
    wb.active = 0
    wb.save(buf)

    safe_name = "".join(
        ch for ch in unicodedata.normalize("NFKD", employee["name"]).encode("ascii", "ignore").decode()
        if ch.isalnum() or ch in " -_"
    ).strip().replace(" ", "-")
    filename = f"Timesheet_{year}-W{week_no:02d}_{safe_name or 'NV'}.xlsx"
    return buf.getvalue(), filename, skipped


def write_into_workbook(path: str, employee: dict, entries: list, start: date) -> str:
    """Ghi dữ liệu tuần vào chính file .xlsx mà admin đã up lên (giữ nguyên các sheet khác)."""
    wb = openpyxl.load_workbook(path)
    year, week_no = week_number(start)
    sheet_name = str(week_no)
    if sheet_name not in wb.sheetnames:
        # file up lên không có sheet của tuần này -> tạo file riêng từ mẫu
        return write_week_file(employee, entries, start)
    _fill_week_sheet(wb[sheet_name], employee, entries, start)
    wb.active = wb.sheetnames.index(sheet_name)
    wb.save(path)
    return path


def read_week_sheet(path: str):
    """Đọc file timesheet tuần do admin tải lên, trả về (ngày bắt đầu tuần, danh sách dòng giờ)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    # chọn sheet tuần: sheet không phải các sheet phụ
    aux = {"Name list", "Cost centre", "Panel list1", "Panel list 2018", "Panel list",
           "How to fill timesheet", "general fill"}
    candidates = [n for n in wb.sheetnames if n not in aux and str(n).isdigit()]
    if not candidates:
        candidates = [wb.sheetnames[0]]

    def _has_data(sheet):
        n = 0
        for wd, (block_start, capacity) in BLOCKS.items():
            for i in range(capacity):
                if sheet.cell(block_start + i, COL_PROJECT).value:
                    n += 1
        return n

    # ưu tiên sheet có nhiều dòng giờ nhất; nếu tất cả trống thì lấy tuần hiện tại
    best, best_n = None, -1
    for name in candidates:
        n = _has_data(wb[name])
        if n > best_n:
            best, best_n = name, n
    if best_n <= 0:
        cur_week = date.today().isocalendar()[1]
        best = str(cur_week) if str(cur_week) in wb.sheetnames else candidates[0]
    ws = wb[best]

    start = ws["F1"].value
    if isinstance(start, datetime):
        start = start.date()
    elif isinstance(start, str):
        start = date.fromisoformat(start[:10])
    if not isinstance(start, date):
        raise ValueError("Không đọc được ngày bắt đầu tuần ở ô F1")

    rows = []
    for wd, (block_start, capacity) in BLOCKS.items():
        for i in range(capacity):
            r = block_start + i
            proj = ws.cell(r, COL_PROJECT).value
            if not proj:
                continue
            work_date = start + timedelta(days=(wd + 1) % 7)
            rows.append({
                "work_date": work_date.isoformat(),
                "project_number": str(proj).strip(),
                "panel_number": (str(ws.cell(r, COL_PANEL).value).strip()
                                 if ws.cell(r, COL_PANEL).value else None),
                "description": (str(ws.cell(r, COL_DESC).value).strip()
                                if ws.cell(r, COL_DESC).value else None),
                "normal_hours": float(ws.cell(r, COL_NORMAL).value or 0),
                "travel_hours": float(ws.cell(r, COL_TRAVEL).value or 0),
                "ot_a": float(ws.cell(r, COL_OTA).value or 0),
                "ot_b": float(ws.cell(r, COL_OTB).value or 0),
                "cost_place": (str(ws.cell(r, COL_COSTPLACE).value).strip()
                               if ws.cell(r, COL_COSTPLACE).value else None),
            })
    return week_start(start), rows


def safe_person_dir(name: str) -> str:
    """Tên thư mục an toàn cho từng nhân viên, ví dụ CHU-HAI-MINH."""
    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    keep = "".join(ch for ch in plain if ch.isalnum() or ch in " -_").strip()
    return (keep.replace(" ", "-") or "NV").upper()


def write_week_file(employee: dict, entries: list, start: date) -> str:
    """Tạo file timesheet tuần riêng (dùng khi nhân viên chưa có file admin up lên)."""
    content, filename, _skipped = build_week_file(employee, entries, start)
    who = safe_person_dir(employee["name"])
    week_part = filename[len("Timesheet_"):].split("_")[0]          # 2026-W43
    person_dir = os.path.join(TIMESHEET_DIR, who)
    os.makedirs(person_dir, exist_ok=True)
    path = os.path.join(person_dir, f"Timesheet_{week_part}_{who}.xlsx")
    with open(path, "wb") as f:
        f.write(content)
    return path
