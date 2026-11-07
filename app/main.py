"""Hệ thống chấm công VDL VN - FastAPI + SQLite.

Chạy:  uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
import os
import secrets
from datetime import date, datetime, timedelta

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, db, export

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "app", "static")

COOKIE = "sid"
MAX_DAY_HOURS = 24.0
MAX_NORMAL_DAY = 8.0
WEEK_TARGET_HOURS = 40.0

# Danh sách mô tả công việc cho ô "Description of proceedings"
DESCRIPTION_OPTIONS = [
    "Take leave of Holiday",
    "Unpaid leave of absence (nghỉ không lương)",
    "Read document",
    "Mechanical works",
    "Equipment installation and Wiring",
    "Make wooden box and Packing",
    "Mods work relate",
    "Indirect (support store, clean workshop, meeting,…)",
]

app = FastAPI(title="VDL Timesheet", docs_url="/api/docs")
_scheduler_started = False


@app.on_event("startup")
def _startup():
    db.init_db()
    # Bỏ cơ chế duyệt: mọi dòng đang chờ duyệt chuyển thành đã ghi nhận
    conn = db.connect()
    with conn:
        conn.execute("UPDATE entries SET status = 'approved' WHERE status != 'approved'")
    conn.close()
    import threading
    global _scheduler_started
    if not _scheduler_started:
        _scheduler_started = True
        threading.Thread(target=_weekly_report_scheduler, daemon=True).start()


# ---------------------------------------------------------------- helpers
def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(conn=Depends(get_conn), sid: str | None = Cookie(default=None, alias=COOKIE)):
    if not sid:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    row = conn.execute(
        """SELECT e.* FROM sessions s JOIN employees e ON e.id = s.employee_id
           WHERE s.token = ? AND e.active = 1""",
        (sid,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ")
    return dict(row)


def require_admin(user=Depends(current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Chỉ admin được phép")
    return user


def user_payload(user: dict, conn) -> dict:
    cc = None
    if user.get("cost_place_code"):
        row = conn.execute(
            "SELECT code, name FROM cost_centres WHERE code = ?", (user["cost_place_code"],)
        ).fetchone()
        if row:
            cc = {"code": row["code"], "name": row["name"]}
    return {
        "id": user["id"],
        "name": user["name"],
        "username": user["username"],
        "pers_no": user["pers_no"],
        "emp_type": user["emp_type"],
        "is_admin": bool(user["is_admin"]),
        "cost_place": cc,
        "place": user.get("place"),
    }


# ---------------------------------------------------------------- models
class LoginIn(BaseModel):
    username: str
    password: str


class EntryIn(BaseModel):
    work_date: date
    project_number: str
    panel_number: str | None = None
    description: str | None = None
    normal_hours: float = Field(default=0, ge=0, le=24)
    travel_hours: float = Field(default=0, ge=0, le=24)
    ot_a: float = Field(default=0, ge=0, le=24)
    ot_b: float = Field(default=0, ge=0, le=24)


class EmployeePatch(BaseModel):
    cost_place_code: str | None = None
    name: str | None = None
    place: str | None = None
    active: bool | None = None


class EmployeeNew(BaseModel):
    pers_no: int = Field(ge=1, le=9999)
    name: str = Field(min_length=2)
    emp_type: str = "P"
    username: str | None = None
    password: str | None = None
    cost_place_code: str | None = None


class PanelIn(BaseModel):
    project_number: str
    panel_number: str
    description: str | None = None
    desc_vi: str | None = None


class PasswordIn(BaseModel):
    new_password: str = Field(min_length=6)


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class PasswordRequestIn(BaseModel):
    username: str
    note: str | None = None


TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def gen_temp_password(n: int = 10) -> str:
    return "".join(secrets.choice(TEMP_ALPHABET) for _ in range(n))


def notify_admin(conn, text: str) -> None:
    """Báo cho admin: lưu vào bảng yêu cầu + thử bắn thông báo desktop (best effort)."""
    try:
        import subprocess
        subprocess.run(["notify-send", "Chấm công VDL", text], timeout=5, check=False)
    except Exception:
        pass


# ---------------------------------------------------------------- auth api
@app.post("/api/login")
def login(body: LoginIn, response: Response, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT * FROM employees WHERE username = ? AND active = 1", (body.username.strip(),)
    ).fetchone()
    if not row or not auth.verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu")
    token = auth.new_token()
    with conn:
        conn.execute(
            "INSERT INTO sessions(token, employee_id, created_at) VALUES (?, ?, ?)",
            (token, row["id"], datetime.now().isoformat(timespec="seconds")),
        )
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 12)
    return {"ok": True, "is_admin": bool(row["is_admin"])}


@app.post("/api/logout")
def logout(response: Response, sid: str | None = Cookie(default=None, alias=COOKIE), conn=Depends(get_conn)):
    if sid:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (sid,))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user), conn=Depends(get_conn)):
    return user_payload(user, conn)


# ---------------------------------------------------------------- worker api
@app.get("/api/projects")
def projects(q: str = "", limit: int = 20, user=Depends(current_user), conn=Depends(get_conn)):
    q = q.strip()
    if not q:
        rows = conn.execute(
            "SELECT project_number FROM projects ORDER BY project_number LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT project_number FROM projects WHERE project_number LIKE ? ORDER BY project_number LIMIT ?",
            (f"%{q}%", limit),
        ).fetchall()
    return [r["project_number"] for r in rows]


@app.get("/api/descriptions")
def descriptions(user=Depends(current_user)):
    """Danh sách mô tả công việc cho ô Description of proceedings."""
    return {"items": DESCRIPTION_OPTIONS}


@app.get("/api/panel-search")
def panel_search(q: str = "", limit: int = 15, user=Depends(current_user), conn=Depends(get_conn)):
    q = q.strip()
    if len(q) < 2:
        return []
    rows = conn.execute(
        """SELECT panel_number, project_number, description FROM panels
           WHERE panel_number LIKE ? ORDER BY panel_number LIMIT ?""",
        (f"{q}%", limit),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            """SELECT panel_number, project_number, description FROM panels
               WHERE panel_number LIKE ? ORDER BY panel_number LIMIT ?""",
            (f"%{q}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/panel-lookup")
def panel_lookup(panel: str, user=Depends(current_user), conn=Depends(get_conn)):
    """Nhập panel number -> trả về project number tương ứng (kèm mô tả)."""
    panel = panel.strip()
    if not panel:
        raise HTTPException(status_code=400, detail="Chưa nhập panel number")
    rows = conn.execute(
        """SELECT panel_number, project_number, description, desc_vi FROM panels
           WHERE panel_number = ? ORDER BY project_number""",
        (panel,),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy panel {panel}")
    return [dict(r) for r in rows]


@app.get("/api/panels")
def panels(project: str, user=Depends(current_user), conn=Depends(get_conn)):
    project = project.strip()
    rows = conn.execute(
        """SELECT panel_number, description, desc_vi, remark FROM panels
           WHERE project_number = ? ORDER BY panel_number""",
        (project,),
    ).fetchall()
    if not rows:
        exists = conn.execute(
            "SELECT 1 FROM projects WHERE project_number = ?", (project,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Không có project number này")
    return [
        {
            "panel_number": r["panel_number"],
            "description": r["description"],
            "desc_vi": r["desc_vi"],
        }
        for r in rows
    ]


def _sync_employee_week(conn, employee_id: int, work_date: date) -> str | None:
    """Ghi dữ liệu tuần vào file timesheet của nhân viên trên máy chủ.

    Ưu tiên ghi vào chính file .xlsx mà admin đã up lên; nếu chưa có thì tạo file tuần riêng.
    """
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        return None
    start = export.week_start(work_date)
    end = start + timedelta(days=6)
    rows = conn.execute(
        """SELECT * FROM entries WHERE employee_id = ? AND work_date BETWEEN ? AND ?
           ORDER BY work_date, id""",
        (employee_id, start.isoformat(), end.isoformat()),
    ).fetchall()
    entries = [dict(r) for r in rows]
    try:
        master = emp["timesheet_file"] if "timesheet_file" in emp.keys() else None
        if master and os.path.isfile(master):
            return export.write_into_workbook(master, dict(emp), entries, start)
        return export.write_week_file(dict(emp), entries, start)
    except Exception as exc:  # ghi file lỗi thì vẫn không chặn việc lưu giờ
        print("Lỗi ghi timesheet:", exc)
        return None


def _entry_dict(r):
    return {
        "id": r["id"],
        "work_date": r["work_date"],
        "project_number": r["project_number"],
        "panel_number": r["panel_number"],
        "description": r["description"],
        "normal_hours": r["normal_hours"],
        "travel_hours": r["travel_hours"],
        "ot_a": r["ot_a"],
        "ot_b": r["ot_b"],
        "cost_place": r["cost_place"],
        "status": r["status"] if "status" in r.keys() else "pending",
        "review_note": r["review_note"] if "review_note" in r.keys() else None,
        "approved_at": r["approved_at"] if "approved_at" in r.keys() else None,
    }


@app.get("/api/entries")
def list_entries(
    start: date | None = None,
    end: date | None = None,
    user=Depends(current_user),
    conn=Depends(get_conn),
):
    if start is None:
        today = date.today()
        start = today - timedelta(days=today.weekday() + 1 if today.weekday() != 6 else 0)
    if end is None:
        end = start + timedelta(days=6)
    rows = conn.execute(
        """SELECT * FROM entries WHERE employee_id = ? AND work_date BETWEEN ? AND ?
           ORDER BY work_date, id""",
        (user["id"], start.isoformat(), end.isoformat()),
    ).fetchall()
    return {"start": start, "end": end, "week_target": WEEK_TARGET_HOURS,
            "items": [_entry_dict(r) for r in rows]}


def _check_entry_rules(conn, employee_id: int, work_date: date, normal: float, travel: float,
                       ot_a: float, ot_b: float, project_number: str,
                       panel_number: str | None, exclude_id: int | None = None):
    """Kiểm tra quy tắc giờ và panel; trả về (project, panel) đã chuẩn hoá."""
    total = normal + travel + ot_a + ot_b
    if total <= 0:
        raise HTTPException(status_code=400, detail="Phải nhập ít nhất một loại giờ > 0")

    # Thứ Bảy (5), Chủ nhật (6) chỉ ghi Overtime B; ngày thường chỉ ghi Overtime A
    weekend = work_date.weekday() >= 5
    if weekend and ot_a > 0:
        raise HTTPException(status_code=400,
                            detail="Thứ Bảy và Chủ nhật chỉ được ghi Overtime B, không ghi Overtime A")
    if not weekend and ot_b > 0:
        raise HTTPException(status_code=400,
                            detail="Ngày thường chỉ ghi Overtime A. Overtime B chỉ dùng cho Thứ Bảy và Chủ nhật")

    # Giờ hành chính tối đa 8h/ngày (không tính overtime)
    extra = "" if exclude_id is None else " AND id != ?"
    params = [employee_id, work_date.isoformat()] + ([] if exclude_id is None else [exclude_id])
    day_normal = conn.execute(
        "SELECT COALESCE(SUM(normal_hours), 0) s FROM entries WHERE employee_id = ? AND work_date = ?" + extra,
        params,
    ).fetchone()["s"]
    if normal > MAX_NORMAL_DAY:
        raise HTTPException(status_code=400, detail=f"Normal hours tối đa {MAX_NORMAL_DAY:g}h/ngày")
    if day_normal + normal > MAX_NORMAL_DAY:
        con_lai = max(0.0, MAX_NORMAL_DAY - day_normal)
        raise HTTPException(
            status_code=400,
            detail=f"Ngày {work_date.isoformat()} đã ghi {day_normal:g}h hành chính,"
                   f" chỉ còn {con_lai:g}h. Overtime phải nhập ở ô riêng.",
        )

    day_total = conn.execute(
        "SELECT COALESCE(SUM(normal_hours + travel_hours + ot_a + ot_b), 0) s FROM entries"
        " WHERE employee_id = ? AND work_date = ?" + extra,
        params,
    ).fetchone()["s"]
    if day_total + total > MAX_DAY_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f"Tổng giờ ngày {work_date.isoformat()} vượt {MAX_DAY_HOURS:g}h"
                   f" (đã có {day_total:g}h)",
        )

    proj = (project_number or "").strip()
    if not proj:
        raise HTTPException(status_code=400, detail="Chưa có project number")
    if not conn.execute("SELECT 1 FROM projects WHERE project_number = ?", (proj,)).fetchone():
        raise HTTPException(status_code=400, detail=f"Project number {proj} không tồn tại")

    panel = (panel_number or "").strip() or None
    if panel:
        ok = conn.execute(
            "SELECT 1 FROM panels WHERE project_number = ? AND panel_number = ?", (proj, panel)
        ).fetchone()
        if not ok:
            raise HTTPException(status_code=400, detail=f"Panel {panel} không thuộc project {proj}")
    return proj, panel


@app.post("/api/entries")
def create_entry(body: EntryIn, user=Depends(current_user), conn=Depends(get_conn)):
    if user["is_admin"]:
        raise HTTPException(
            status_code=403,
            detail="Tài khoản admin không chấm công. Hãy đăng xuất và đăng nhập bằng tài khoản nhân viên.",
        )
    if not user.get("cost_place_code"):
        raise HTTPException(status_code=400, detail="Tài khoản chưa được gán cost place, liên hệ admin")

    proj, panel = _check_entry_rules(
        conn, user["id"], body.work_date, body.normal_hours, body.travel_hours,
        body.ot_a, body.ot_b, body.project_number, body.panel_number,
    )

    with conn:
        cur = conn.execute(
            """INSERT INTO entries(employee_id, work_date, project_number, panel_number, description,
                                   normal_hours, travel_hours, ot_a, ot_b, cost_place,
                                   status, approved_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)""",
            (user["id"], body.work_date.isoformat(), proj, panel, body.description,
             body.normal_hours, body.travel_hours, body.ot_a, body.ot_b,
             user["cost_place_code"], datetime.now().isoformat(timespec="seconds"),
             datetime.now().isoformat(timespec="seconds")),
        )
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (cur.lastrowid,)).fetchone()
    path = _sync_employee_week(conn, user["id"], body.work_date)
    d = _entry_dict(row)
    d["file_path"] = path
    return d


@app.put("/api/entries/{entry_id}")
def update_entry(entry_id: int, body: EntryIn, user=Depends(current_user), conn=Depends(get_conn)):
    """Sửa lại dòng giờ đã lưu (nhập sai thì sửa), file timesheet được ghi lại ngay."""
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không thấy dòng giờ")
    if row["employee_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Chỉ sửa được dòng của mình")

    proj, panel = _check_entry_rules(
        conn, row["employee_id"], body.work_date, body.normal_hours, body.travel_hours,
        body.ot_a, body.ot_b, body.project_number, body.panel_number, exclude_id=entry_id,
    )

    with conn:
        conn.execute(
            """UPDATE entries SET work_date = ?, project_number = ?, panel_number = ?, description = ?,
                   normal_hours = ?, travel_hours = ?, ot_a = ?, ot_b = ?
               WHERE id = ?""",
            (body.work_date.isoformat(), proj, panel, body.description,
             body.normal_hours, body.travel_hours, body.ot_a, body.ot_b, entry_id),
        )
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()

    # ghi lại file của tuần chứa ngày mới và ngày cũ (nếu đổi sang tuần khác)
    paths = []
    for d in {body.work_date, date.fromisoformat(body.work_date.isoformat())}:
        paths.append(_sync_employee_week(conn, row["employee_id"], d))
    out = _entry_dict(row)
    out["file_path"] = paths[-1] if paths else None
    return out


@app.delete("/api/entries/{entry_id}")
def delete_entry(entry_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không thấy dòng giờ")
    if row["employee_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Chỉ xoá được dòng của mình")
    with conn:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    _sync_employee_week(conn, row["employee_id"], date.fromisoformat(row["work_date"]))
    return {"ok": True}


# ---------------------------------------------------------------- duyệt giờ
class ReviewIn(BaseModel):
    note: str | None = None


class ApproveWeekIn(BaseModel):
    start: date
    employee_id: int | None = None


@app.get("/api/admin/review")
def admin_review_list(
    status: str = "pending",
    start: date | None = None,
    end: date | None = None,
    q: str = "",
    admin=Depends(require_admin),
    conn=Depends(get_conn),
):
    params = []
    sql = """SELECT en.*, e.name AS employee_name, e.pers_no FROM entries en
             JOIN employees e ON e.id = en.employee_id WHERE 1 = 1"""
    if status in ("pending", "approved", "rejected"):
        sql += " AND en.status = ?"
        params.append(status)
    if start:
        sql += " AND en.work_date >= ?"
        params.append(start.isoformat())
    if end:
        sql += " AND en.work_date <= ?"
        params.append(end.isoformat())
    if q.strip():
        sql += " AND (e.name LIKE ? OR en.project_number LIKE ?)"
        params += [f"%{q.strip()}%", f"%{q.strip()}%"]
    sql += " ORDER BY en.work_date, e.pers_no, en.id LIMIT 500"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = _entry_dict(r)
        d.update({"employee_name": r["employee_name"], "pers_no": r["pers_no"]})
        out.append(d)
    return out


@app.post("/api/admin/entries/{entry_id}/approve")
def approve_entry(entry_id: int, admin=Depends(require_admin), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không thấy dòng giờ")
    if row["status"] == "approved":
        return {"ok": True, "already": True}
    with conn:
        conn.execute(
            "UPDATE entries SET status = 'approved', approved_by = ?, approved_at = ?, review_note = NULL"
            " WHERE id = ?",
            (admin["id"], datetime.now().isoformat(timespec="seconds"), entry_id),
        )
    return {"ok": True}


@app.post("/api/admin/entries/{entry_id}/reject")
def reject_entry(entry_id: int, body: ReviewIn, admin=Depends(require_admin), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không thấy dòng giờ")
    with conn:
        conn.execute(
            "UPDATE entries SET status = 'rejected', approved_by = ?, approved_at = ?, review_note = ?"
            " WHERE id = ?",
            (admin["id"], datetime.now().isoformat(timespec="seconds"),
             (body.note or "").strip() or None, entry_id),
        )
    return {"ok": True}


@app.post("/api/admin/entries/approve-week")
def approve_week(body: ApproveWeekIn, admin=Depends(require_admin), conn=Depends(get_conn)):
    start = export.week_start(body.start)
    end = start + timedelta(days=6)
    sql = ("UPDATE entries SET status = 'approved', approved_by = ?, approved_at = ?, review_note = NULL"
           " WHERE status = 'pending' AND work_date BETWEEN ? AND ?")
    params = [admin["id"], datetime.now().isoformat(timespec="seconds"),
              start.isoformat(), end.isoformat()]
    if body.employee_id:
        sql += " AND employee_id = ?"
        params.append(body.employee_id)
    with conn:
        cur = conn.execute(sql, params)
    return {"ok": True, "approved": cur.rowcount}


# ---------------------------------------------------------------- admin api
@app.get("/api/admin/employees")
def admin_employees(admin=Depends(require_admin), conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT e.id, e.pers_no, e.name, e.emp_type, e.username, e.cost_place_code,
                  e.place, e.active, e.is_admin, c.name AS cost_place_name
           FROM employees e LEFT JOIN cost_centres c ON c.code = e.cost_place_code
           ORDER BY e.is_admin DESC, e.pers_no"""
    ).fetchall()
    return [dict(r) for r in rows]


@app.patch("/api/admin/employees/{emp_id}")
def admin_patch_employee(emp_id: int, body: EmployeePatch, admin=Depends(require_admin), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không thấy nhân viên")

    sets, vals = [], []
    if body.cost_place_code is not None:
        code = body.cost_place_code.strip()
        if not conn.execute("SELECT 1 FROM cost_centres WHERE code = ?", (code,)).fetchone():
            raise HTTPException(status_code=400, detail=f"Cost place {code} không tồn tại")
        sets.append("cost_place_code = ?")
        vals.append(code)
    if body.name is not None:
        sets.append("name = ?")
        vals.append(body.name.strip())
    if body.place is not None:
        sets.append("place = ?")
        vals.append(body.place.strip())
    if body.active is not None:
        sets.append("active = ?")
        vals.append(1 if body.active else 0)
    if not sets:
        return {"ok": True, "changed": 0}
    vals.append(emp_id)
    with conn:
        conn.execute(f"UPDATE employees SET {', '.join(sets)} WHERE id = ?", vals)
    row = conn.execute(
        """SELECT e.id, e.pers_no, e.name, e.cost_place_code, e.place, e.active, c.name AS cost_place_name
           FROM employees e LEFT JOIN cost_centres c ON c.code = e.cost_place_code WHERE e.id = ?""",
        (emp_id,),
    ).fetchone()
    return dict(row)


@app.post("/api/admin/employees")
def admin_create_employee(body: EmployeeNew, admin=Depends(require_admin), conn=Depends(get_conn)):
    """Thêm nhân viên mới. Không nhập username/mật khẩu thì hệ thống tự đặt nvXX / vdl@XX."""
    name = body.name.strip().upper()
    if conn.execute("SELECT 1 FROM employees WHERE pers_no = ?", (body.pers_no,)).fetchone():
        raise HTTPException(status_code=400, detail=f"Pers.no {body.pers_no} đã có người dùng")
    username = (body.username or f"nv{body.pers_no:02d}").strip().lower()
    if conn.execute("SELECT 1 FROM employees WHERE username = ?", (username,)).fetchone():
        raise HTTPException(status_code=400, detail=f"Tên đăng nhập {username} đã tồn tại")
    password = body.password or f"vdl@{body.pers_no:02d}"
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu tối thiểu 6 ký tự")
    code = (body.cost_place_code or "").strip() or None
    if code and not conn.execute("SELECT 1 FROM cost_centres WHERE code = ?", (code,)).fetchone():
        raise HTTPException(status_code=400, detail=f"Cost place {code} không tồn tại")
    emp_type = (body.emp_type or "P").strip().upper()[:1]
    with conn:
        cur = conn.execute(
            """INSERT INTO employees(pers_no, name, emp_type, username, password_hash,
                   cost_place_code, is_admin, active)
               VALUES (?, ?, ?, ?, ?, ?, 0, 1)""",
            (body.pers_no, name, emp_type, username, auth.hash_password(password), code),
        )
        emp_id = cur.lastrowid
    return {"ok": True, "id": emp_id, "username": username, "password": password,
            "pers_no": body.pers_no, "name": name}


@app.post("/api/admin/employees/{emp_id}/password")
def admin_reset_password(emp_id: int, body: PasswordIn, admin=Depends(require_admin), conn=Depends(get_conn)):
    if not conn.execute("SELECT 1 FROM employees WHERE id = ?", (emp_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Không thấy nhân viên")
    with conn:
        conn.execute("UPDATE employees SET password_hash = ? WHERE id = ?",
                     (auth.hash_password(body.new_password), emp_id))
        conn.execute("DELETE FROM sessions WHERE employee_id = ?", (emp_id,))
    return {"ok": True}


@app.get("/api/admin/cost-centres")
def admin_cost_centres(admin=Depends(require_admin), conn=Depends(get_conn)):
    rows = conn.execute("SELECT code, name FROM cost_centres ORDER BY code").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/admin/projects")
def admin_projects(q: str = "", admin=Depends(require_admin), conn=Depends(get_conn)):
    q = q.strip()
    if q:
        rows = conn.execute(
            """SELECT p.project_number, (SELECT COUNT(*) FROM panels WHERE project_number = p.project_number) n
               FROM projects p WHERE p.project_number LIKE ? ORDER BY p.project_number LIMIT 50""",
            (f"%{q}%",),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT p.project_number, (SELECT COUNT(*) FROM panels WHERE project_number = p.project_number) n
               FROM projects p ORDER BY p.project_number LIMIT 50"""
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/admin/panels")
def admin_add_panel(body: PanelIn, admin=Depends(require_admin), conn=Depends(get_conn)):
    proj = body.project_number.strip()
    panel = body.panel_number.strip()
    if not proj or not panel:
        raise HTTPException(status_code=400, detail="Thiếu project number hoặc panel number")
    with conn:
        conn.execute("INSERT OR IGNORE INTO projects(project_number) VALUES (?)", (proj,))
        conn.execute(
            """INSERT INTO panels(project_number, panel_number, description, desc_vi)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(project_number, panel_number)
               DO UPDATE SET description = excluded.description, desc_vi = excluded.desc_vi""",
            (proj, panel, body.description, body.desc_vi),
        )
    return {"ok": True}


@app.get("/api/admin/entries")
def admin_entries(
    admin=Depends(require_admin),
    conn=Depends(get_conn),
    start: date | None = None,
    end: date | None = None,
    q: str = "",
    include_pending: bool = False,
):
    if start is None:
        today = date.today()
        start = today - timedelta(days=6)
    if end is None:
        end = date.today()
    params = [start.isoformat(), end.isoformat()]
    sql = """SELECT en.*, e.name AS employee_name, e.pers_no FROM entries en
             JOIN employees e ON e.id = en.employee_id
             WHERE en.work_date BETWEEN ? AND ?"""
    if q.strip():
        sql += " AND (e.name LIKE ? OR en.project_number LIKE ?)"
        params += [f"%{q.strip()}%", f"%{q.strip()}%"]
    sql += " ORDER BY en.work_date DESC, e.pers_no LIMIT 500"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = _entry_dict(r)
        d.update({"employee_name": r["employee_name"], "pers_no": r["pers_no"]})
        out.append(d)
    return out


# ---------------------------------------------------------------- đổi / quên mật khẩu
@app.post("/api/me/password")
def change_own_password(
    body: PasswordChangeIn,
    response: Response,
    user=Depends(current_user),
    conn=Depends(get_conn),
):
    if not auth.verify_password(body.old_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không đúng")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải khác mật khẩu cũ")
    token = auth.new_token()
    with conn:
        conn.execute("UPDATE employees SET password_hash = ? WHERE id = ?",
                     (auth.hash_password(body.new_password), user["id"]))
        conn.execute("DELETE FROM sessions WHERE employee_id = ?", (user["id"],))
        conn.execute("INSERT INTO sessions(token, employee_id, created_at) VALUES (?, ?, ?)",
                     (token, user["id"], datetime.now().isoformat(timespec="seconds")))
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 12)
    return {"ok": True}


@app.post("/api/password-request")
def create_password_request(body: PasswordRequestIn, conn=Depends(get_conn)):
    username = body.username.strip()
    emp = conn.execute("SELECT * FROM employees WHERE username = ?", (username,)).fetchone()
    if not emp:
        # không tiết lộ username có tồn tại hay không
        return {"ok": True}
    pending = conn.execute(
        "SELECT id FROM password_requests WHERE employee_id = ? AND status = 'pending'",
        (emp["id"],),
    ).fetchone()
    if pending:
        return {"ok": True, "already": True}
    with conn:
        conn.execute(
            """INSERT INTO password_requests(employee_id, username, note, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (emp["id"], username, (body.note or "").strip() or None,
             datetime.now().isoformat(timespec="seconds")),
        )
    notify_admin(conn, f"Yêu cầu cấp lại mật khẩu: {emp['name']} ({username})")
    return {"ok": True}


@app.get("/api/admin/password-requests")
def list_password_requests(admin=Depends(require_admin), conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT r.*, e.name AS employee_name, e.pers_no
           FROM password_requests r LEFT JOIN employees e ON e.id = r.employee_id
           ORDER BY CASE r.status WHEN 'pending' THEN 0 ELSE 1 END, r.id DESC LIMIT 100"""
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/admin/password-requests/{req_id}/issue")
def issue_password(req_id: int, admin=Depends(require_admin), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM password_requests WHERE id = ?", (req_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không thấy yêu cầu")
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="Yêu cầu này đã xử lý rồi")
    if not row["employee_id"]:
        raise HTTPException(status_code=400, detail="Không xác định được nhân viên")
    new_pw = gen_temp_password()
    with conn:
        conn.execute("UPDATE employees SET password_hash = ? WHERE id = ?",
                     (auth.hash_password(new_pw), row["employee_id"]))
        conn.execute("DELETE FROM sessions WHERE employee_id = ?", (row["employee_id"],))
        conn.execute(
            """UPDATE password_requests SET status = 'issued', temp_password = ?, resolved_at = ?
               WHERE id = ?""",
            (new_pw, datetime.now().isoformat(timespec="seconds"), req_id),
        )
    return {"ok": True, "username": row["username"], "temp_password": new_pw}


@app.post("/api/admin/password-requests/{req_id}/reject")
def reject_password_request(req_id: int, admin=Depends(require_admin), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM password_requests WHERE id = ?", (req_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không thấy yêu cầu")
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="Yêu cầu này đã xử lý rồi")
    with conn:
        conn.execute(
            "UPDATE password_requests SET status = 'rejected', resolved_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), req_id),
        )
    return {"ok": True}


@app.delete("/api/admin/password-requests/{req_id}")
def delete_password_request(req_id: int, admin=Depends(require_admin), conn=Depends(get_conn)):
    with conn:
        cur = conn.execute("DELETE FROM password_requests WHERE id = ?", (req_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Không thấy yêu cầu")
    return {"ok": True}


# ---------------------------------------------------------------- xuất Excel theo mẫu
def _xlsx_response(employee: dict, entries: list, start: date):
    content, filename, skipped = export.build_week_file(employee, entries, start)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "X-Skipped-Rows": str(skipped),
    }
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


def _week_entries(conn, employee_id: int, start: date) -> list:
    """Lấy toàn bộ dòng giờ của tuần (không cần duyệt nữa)."""
    start = export.week_start(start)
    end = start + timedelta(days=6)
    rows = conn.execute(
        """SELECT * FROM entries WHERE employee_id = ? AND work_date BETWEEN ? AND ?
           ORDER BY work_date, id""",
        (employee_id, start.isoformat(), end.isoformat()),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/export/week")
def export_own_week(start: date, user=Depends(current_user), conn=Depends(get_conn)):
    entries = _week_entries(conn, user["id"], start)
    return _xlsx_response(user, entries, start)


@app.get("/api/admin/export")
def admin_export(
    employee_id: int,
    start: date,
    admin=Depends(require_admin),
    conn=Depends(get_conn),
):
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        raise HTTPException(status_code=404, detail="Không thấy nhân viên")
    entries = _week_entries(conn, employee_id, start)
    return _xlsx_response(dict(emp), entries, start)


@app.get("/api/admin/timesheet-files")
def admin_timesheet_files(employee_id: int, admin=Depends(require_admin), conn=Depends(get_conn)):
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        raise HTTPException(status_code=404, detail="Không thấy nhân viên")
    safe = export.safe_person_dir(emp["name"])
    person_dir = os.path.join(export.TIMESHEET_DIR, safe)
    files = []
    if os.path.isdir(person_dir):
        for name in sorted(os.listdir(person_dir), reverse=True):
            if not name.endswith(".xlsx"):
                continue
            full = os.path.join(person_dir, name)
            st = os.stat(full)
            files.append({
                "name": name,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "url": f"/api/admin/timesheet-file?employee_id={employee_id}&name={name}",
                "is_master": bool(emp["timesheet_file"]) and os.path.abspath(emp["timesheet_file"]) == os.path.abspath(full),
            })
    return {
        "employee": emp["name"],
        "folder": person_dir,
        "exists": os.path.isdir(person_dir),
        "master": emp["timesheet_file"] if "timesheet_file" in emp.keys() else None,
        "files": files,
    }


@app.get("/api/admin/timesheet-file")
def admin_timesheet_file(employee_id: int, name: str, admin=Depends(require_admin), conn=Depends(get_conn)):
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        raise HTTPException(status_code=404, detail="Không thấy nhân viên")
    safe_name = os.path.basename(name)
    path = os.path.join(export.TIMESHEET_DIR, export.safe_person_dir(emp["name"]), safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Không thấy file timesheet")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=safe_name,
    )


@app.post("/api/admin/timesheet-upload")
def admin_timesheet_upload(
    employee_id: int,
    file: UploadFile = File(...),
    admin=Depends(require_admin),
    conn=Depends(get_conn),
):
    """Admin up file timesheet từ máy mình lên: đọc dữ liệu trong file rồi ghi vào hệ thống
    và tạo lại file chuẩn của tuần đó cho nhân viên."""
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        raise HTTPException(status_code=404, detail="Không thấy nhân viên")
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Chỉ nhận file Excel .xlsx")

    tmp_dir = os.path.join(export.TIMESHEET_DIR, "_uploads")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"{emp['id']}-{int(datetime.now().timestamp())}.xlsx")
    with open(tmp_path, "wb") as f:
        f.write(file.file.read())

    try:
        week_start, rows = export.read_week_sheet(tmp_path)
    except Exception as exc:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=f"Không đọc được file: {exc}") from exc

    if not rows:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise HTTPException(
            status_code=400,
            detail="File này không có dòng giờ nào nên Mao không ghi đè dữ liệu. "
                   "Hãy chọn file timesheet đã có giờ.",
        )

    # lưu file admin up lên làm file chính thức của nhân viên này
    person_dir = os.path.join(export.TIMESHEET_DIR, export.safe_person_dir(emp["name"]))
    os.makedirs(person_dir, exist_ok=True)
    safe_file_name = os.path.basename(file.filename or "timesheet.xlsx")
    master_path = os.path.join(person_dir, safe_file_name)
    os.replace(tmp_path, master_path)
    with conn:
        conn.execute("UPDATE employees SET timesheet_file = ? WHERE id = ?", (master_path, emp["id"]))

    week_end = week_start + timedelta(days=6)
    inserted = 0
    with conn:
        # thay thế toàn bộ dữ liệu tuần đó của nhân viên bằng dữ liệu trong file
        conn.execute(
            "DELETE FROM entries WHERE employee_id = ? AND work_date BETWEEN ? AND ?",
            (emp["id"], week_start.isoformat(), week_end.isoformat()),
        )
        for row in rows:
            proj = row["project_number"]
            conn.execute("INSERT OR IGNORE INTO projects(project_number) VALUES (?)", (proj,))
            conn.execute(
                """INSERT INTO entries(employee_id, work_date, project_number, panel_number, description,
                       normal_hours, travel_hours, ot_a, ot_b, cost_place, status, approved_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)""",
                (emp["id"], row["work_date"], proj, row["panel_number"], row["description"],
                 row["normal_hours"], row["travel_hours"], row["ot_a"], row["ot_b"],
                 row["cost_place"] or emp["cost_place_code"],
                 datetime.now().isoformat(timespec="seconds"),
                 datetime.now().isoformat(timespec="seconds")),
            )
            inserted += 1

    path = _sync_employee_week(conn, emp["id"], week_start)
    return {
        "ok": True,
        "employee": emp["name"],
        "week_start": week_start.isoformat(),
        "imported": inserted,
        "file_path": path,
    }


@app.post("/api/admin/timesheet-use")
def admin_timesheet_use(employee_id: int, name: str, admin=Depends(require_admin), conn=Depends(get_conn)):
    """Chọn file có sẵn làm file chính thức để hệ thống ghi dữ liệu vào."""
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        raise HTTPException(status_code=404, detail="Không thấy nhân viên")
    path = os.path.join(export.TIMESHEET_DIR, export.safe_person_dir(emp["name"]), os.path.basename(name))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Không thấy file timesheet")
    with conn:
        conn.execute("UPDATE employees SET timesheet_file = ? WHERE id = ?", (path, emp["id"]))
    return {"ok": True, "master": path}


@app.delete("/api/admin/timesheet-file")
def admin_timesheet_delete(employee_id: int, name: str, admin=Depends(require_admin), conn=Depends(get_conn)):
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        raise HTTPException(status_code=404, detail="Không thấy nhân viên")
    safe_name = os.path.basename(name)
    path = os.path.join(export.TIMESHEET_DIR, export.safe_person_dir(emp["name"]), safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Không thấy file timesheet")
    os.remove(path)
    if emp["timesheet_file"] and os.path.abspath(emp["timesheet_file"]) == os.path.abspath(path):
        with conn:
            conn.execute("UPDATE employees SET timesheet_file = NULL WHERE id = ?", (emp["id"],))
    return {"ok": True, "deleted": safe_name}


@app.get("/api/admin/timesheet-zip")
def admin_timesheet_zip(employee_id: int | None = None, admin=Depends(require_admin), conn=Depends(get_conn)):
    """Tải về một gói .zip toàn bộ file timesheet (của 1 người hoặc tất cả) để đồng bộ về máy admin."""
    import io as _io
    import zipfile

    buf = _io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if employee_id:
            emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
            if not emp:
                raise HTTPException(status_code=404, detail="Không thấy nhân viên")
            person = export.safe_person_dir(emp["name"])
            folder = os.path.join(export.TIMESHEET_DIR, person)
            if os.path.isdir(folder):
                for name in sorted(os.listdir(folder)):
                    if name.endswith(".xlsx"):
                        zf.write(os.path.join(folder, name), arcname=f"{person}/{name}")
                        added += 1
            zip_name = f"Timesheet_{person}.zip"
        else:
            if os.path.isdir(export.TIMESHEET_DIR):
                for person in sorted(os.listdir(export.TIMESHEET_DIR)):
                    folder = os.path.join(export.TIMESHEET_DIR, person)
                    if person.startswith("_") or not os.path.isdir(folder):
                        continue
                    for name in sorted(os.listdir(folder)):
                        if name.endswith(".xlsx"):
                            zf.write(os.path.join(folder, name), arcname=f"{person}/{name}")
                            added += 1
            zip_name = "Timesheet_VDL_tat_ca.zip"

    if added == 0:
        raise HTTPException(status_code=404, detail="Chưa có file timesheet nào để tải")
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@app.get("/api/my-timesheet")
def my_timesheet(user=Depends(current_user), conn=Depends(get_conn), start: date | None = None, week: int | None = None):
    """Tải về file timesheet của chính mình, tạo mới từ dữ liệu hiện có (luôn mới nhất)."""
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (user["id"],)).fetchone()
    day = start or date.today()
    entries = _week_entries(conn, emp["id"], day)
    content, filename, _skipped = export.build_week_file(dict(emp), entries, day)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# ---------------------------------------------------------------- báo cáo tuần
def _compute_week_report(conn, week_start_date: date) -> dict:
    """Tổng hợp giờ hành chính của cả tuần cho mọi nhân viên."""
    start = export.week_start(week_start_date)
    end = start + timedelta(days=6)
    year, week_no = export.week_number(start)
    emps = conn.execute(
        "SELECT id, pers_no, name FROM employees WHERE is_admin = 0 AND active = 1 ORDER BY pers_no"
    ).fetchall()
    rows = []
    for e in emps:
        hours = conn.execute(
            "SELECT COALESCE(SUM(normal_hours), 0) s FROM entries"
            " WHERE employee_id = ? AND work_date BETWEEN ? AND ?",
            (e["id"], start.isoformat(), end.isoformat()),
        ).fetchone()["s"] or 0.0
        ot = conn.execute(
            "SELECT COALESCE(SUM(ot_a + ot_b), 0) s FROM entries"
            " WHERE employee_id = ? AND work_date BETWEEN ? AND ?",
            (e["id"], start.isoformat(), end.isoformat()),
        ).fetchone()["s"] or 0.0
        missing = max(0.0, WEEK_TARGET_HOURS - hours)
        rows.append({
            "employee_id": e["id"],
            "pers_no": e["pers_no"],
            "name": e["name"],
            "hours": round(hours, 2),
            "ot_hours": round(ot, 2),
            "missing": round(missing, 2),
            "ok": hours >= WEEK_TARGET_HOURS,
        })
    short = [r for r in rows if not r["ok"]]
    short.sort(key=lambda r: r["hours"])
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "week_no": week_no,
        "year": year,
        "required_hours": WEEK_TARGET_HOURS,
        "total_employees": len(rows),
        "short_count": len(short),
        "short_list": short,
        "all": rows,
    }


def _save_week_report(conn, week_start_date: date) -> dict:
    import json as _json
    report = _compute_week_report(conn, week_start_date)
    with conn:
        conn.execute(
            """INSERT INTO weekly_reports(week_start, week_no, year, required_hours,
                   total_employees, short_count, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(week_start) DO UPDATE SET
                   short_count = excluded.short_count,
                   total_employees = excluded.total_employees,
                   detail_json = excluded.detail_json""",
            (report["week_start"], report["week_no"], report["year"], report["required_hours"],
             report["total_employees"], report["short_count"],
             _json.dumps(report, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )
    return report


def _previous_week_start() -> date:
    today = date.today()
    this_week = export.week_start(today)
    return this_week - timedelta(days=7)




@app.get("/api/admin/week-summary")
def admin_week_summary(start: date | None = None, admin=Depends(require_admin), conn=Depends(get_conn)):
    """Tổng hợp tuần: mặc định là tuần vừa rồi."""
    target = start or _previous_week_start()
    return _compute_week_report(conn, target)


def _add_notification(conn, employee_id: int, kind: str, week_start: str, title: str, body: str) -> None:
    """Thêm thông báo (bỏ qua nếu đã có cùng loại cho cùng tuần)."""
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO notifications(employee_id, kind, week_start, title, body, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (employee_id, kind, week_start, title, body, datetime.now().isoformat(timespec="seconds")),
        )


def _week_hours(conn, employee_id: int, start: date) -> float:
    end = start + timedelta(days=6)
    return conn.execute(
        "SELECT COALESCE(SUM(normal_hours), 0) s FROM entries"
        " WHERE employee_id = ? AND work_date BETWEEN ? AND ?",
        (employee_id, start.isoformat(), end.isoformat()),
    ).fetchone()["s"] or 0.0


def _weekly_report_scheduler():
    """07:00 Thứ Hai: chốt báo cáo tuần và báo cho admin.
    07:00 Thứ Bảy: báo cho từng nhân viên đã làm bao nhiêu giờ, còn thiếu bao nhiêu.
    Nếu lúc đó máy tắt thì lần bật sau sẽ chạy bù."""
    import time
    while True:
        try:
            conn = db.connect()
            now = datetime.now()
            prev = _previous_week_start()
            this_week = export.week_start(date.today())

            # --- Thứ Hai 07:00: chốt báo cáo tuần trước, thông báo admin
            monday_deadline = datetime.combine(prev + timedelta(days=8),
                                               datetime.min.time()).replace(hour=7)
            if now >= monday_deadline:
                report = _save_week_report(conn, prev)
                _add_notification(
                    conn, 0, "weekly_report", report["week_start"],
                    f"Đã tổng hợp báo cáo tuần {report['week_no']}/{report['year']}",
                    f"Chốt lúc 07:00 Thứ Hai. {report['short_count']}/{report['total_employees']} "
                    f"người chưa đủ {WEEK_TARGET_HOURS:g}h hành chính.",
                )
                # gửi email cho admin nếu đã cấu hình Gmail
                lines = [f"Báo cáo tuần {report['week_no']}/{report['year']} "
                         f"({report['week_start']} → {report['week_end']})",
                         f"Tổng: {report['total_employees']} nhân viên, "
                         f"{report['short_count']} người chưa đủ {WEEK_TARGET_HOURS:g}h.", ""]
                for r in report["short_list"]:
                    lines.append(f"- {r['pers_no']:>3} {r['name']}: {r['hours']:g}h "
                                 f"(thiếu {r['missing']:g}h)")
                _enqueue_email(conn, f"[Chấm công VDL] Báo cáo tuần "
                                     f"{report['week_no']}/{report['year']}",
                               "\n".join(lines))
            _send_pending_emails(conn)

            # --- Thứ Bảy 07:00: báo tiến độ cho từng nhân viên (tuần hiện tại)
            saturday_deadline = datetime.combine(this_week + timedelta(days=6),
                                                 datetime.min.time()).replace(hour=7)
            if now >= saturday_deadline:
                year, week_no = export.week_number(this_week)
                emps = conn.execute(
                    "SELECT id, name FROM employees WHERE is_admin = 0 AND active = 1"
                ).fetchall()
                for e in emps:
                    hours = _week_hours(conn, e["id"], this_week)
                    missing = max(0.0, WEEK_TARGET_HOURS - hours)
                    body = (f"Tuần này bạn đã làm {hours:g}h hành chính, còn thiếu {missing:g}h."
                            if missing else
                            f"Tuần này bạn đã làm {hours:g}h, đã đủ mức {WEEK_TARGET_HOURS:g}h.")
                    _add_notification(
                        conn, e["id"], "week_progress", this_week.isoformat(),
                        f"Tiến độ tuần {week_no}/{year}", body,
                    )
            conn.close()
        except Exception as exc:
            print("Lỗi scheduler:", exc)
        time.sleep(600)


@app.get("/api/notifications")
def my_notifications(user=Depends(current_user), conn=Depends(get_conn)):
    target = 0 if user["is_admin"] else user["id"]
    rows = conn.execute(
        """SELECT id, kind, week_start, title, body, created_at, read_at FROM notifications
           WHERE employee_id = ? ORDER BY created_at DESC, id DESC LIMIT 100""",
        (target,),
    ).fetchall()
    unread = sum(1 for r in rows if not r["read_at"])
    return {"unread": unread, "items": [dict(r) for r in rows]}


@app.post("/api/notifications/read")
def read_notifications(user=Depends(current_user), conn=Depends(get_conn)):
    target = 0 if user["is_admin"] else user["id"]
    with conn:
        conn.execute(
            "UPDATE notifications SET read_at = ? WHERE employee_id = ? AND read_at IS NULL",
            (datetime.now().isoformat(timespec="seconds"), target),
        )
    return {"ok": True}


def _mail_config() -> dict:
    """Đọc cấu hình gửi mail từ biến môi trường hoặc file ~/.config/vdl-timesheet/email.env"""
    conf = {
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "465")),
        "user": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASS", ""),
        "to": os.environ.get("MAIL_TO", ""),
    }
    env_path = os.path.expanduser("~/.config/vdl-timesheet/email.env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                key = {"SMTP_HOST": "host", "SMTP_PORT": "port", "SMTP_USER": "user",
                       "SMTP_PASS": "password", "MAIL_TO": "to"}.get(k)
                if key:
                    conf[key] = int(v) if key == "port" else v
    if not conf["to"]:
        conf["to"] = conf["user"]
    return conf


def _enqueue_email(conn, subject: str, body: str, to_addr: str | None = None) -> None:
    conf = _mail_config()
    to_addr = to_addr or conf["to"]
    if not to_addr:
        return
    with conn:
        conn.execute(
            "INSERT INTO email_queue(to_addr, subject, body, created_at) VALUES (?, ?, ?, ?)",
            (to_addr, subject, body, datetime.now().isoformat(timespec="seconds")),
        )


def _send_pending_emails(conn) -> int:
    """Gửi các email còn trong hàng đợi. Trả về số email gửi thành công."""
    import smtplib
    from email.mime.text import MIMEText
    from email.utils import formataddr

    conf = _mail_config()
    if not (conf["user"] and conf["password"]):
        return 0

    rows = conn.execute(
        "SELECT * FROM email_queue WHERE sent_at IS NULL AND tries < 5 ORDER BY id LIMIT 20"
    ).fetchall()
    if not rows:
        return 0

    sent = 0
    try:
        if conf["port"] == 465:
            server = smtplib.SMTP_SSL(conf["host"], conf["port"], timeout=20)
        else:
            server = smtplib.SMTP(conf["host"], conf["port"], timeout=20)
            server.starttls()
        server.login(conf["user"], conf["password"])
    except Exception as exc:
        with conn:
            conn.execute("UPDATE email_queue SET error = ?, tries = tries + 1 WHERE sent_at IS NULL",
                         (f"login: {exc}",))
        return 0

    for r in rows:
        try:
            msg = MIMEText(r["body"], "plain", "utf-8")
            msg["Subject"] = r["subject"]
            msg["From"] = formataddr(("Chấm công VDL", conf["user"]))
            msg["To"] = r["to_addr"]
            server.sendmail(conf["user"], [r["to_addr"]], msg.as_string())
            with conn:
                conn.execute("UPDATE email_queue SET sent_at = ?, error = NULL WHERE id = ?",
                             (datetime.now().isoformat(timespec="seconds"), r["id"]))
            sent += 1
        except Exception as exc:
            with conn:
                conn.execute("UPDATE email_queue SET error = ?, tries = tries + 1 WHERE id = ?",
                             (str(exc)[:300], r["id"]))
    try:
        server.quit()
    except Exception:
        pass
    return sent


@app.get("/api/admin/email-status")
def admin_email_status(admin=Depends(require_admin), conn=Depends(get_conn)):
    conf = _mail_config()
    queued = conn.execute(
        "SELECT COUNT(*) c FROM email_queue WHERE sent_at IS NULL"
    ).fetchone()["c"]
    last = conn.execute(
        "SELECT * FROM email_queue ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "configured": bool(conf["user"] and conf["password"]),
        "host": conf["host"],
        "port": conf["port"],
        "user": conf["user"],
        "to": conf["to"],
        "queued": queued,
        "last": dict(last) if last else None,
    }


@app.post("/api/admin/email-test")
def admin_email_test(admin=Depends(require_admin), conn=Depends(get_conn)):
    conf = _mail_config()
    if not (conf["user"] and conf["password"]):
        raise HTTPException(
            status_code=400,
            detail="Chưa cấu hình email. Tạo file ~/.config/vdl-timesheet/email.env với SMTP_USER và SMTP_PASS.",
        )
    _enqueue_email(conn, "Chấm công VDL — thử gửi email",
                   "Đây là email thử từ hệ thống chấm công VDL.\nNếu bạn nhận được, cấu hình đã đúng.")
    sent = _send_pending_emails(conn)
    return {"ok": True, "sent": sent, "to": conf["to"]}


@app.get("/api/admin/week-reports")
def admin_week_reports(admin=Depends(require_admin), conn=Depends(get_conn)):
    """Danh sách các báo cáo tuần đã chốt."""
    rows = conn.execute(
        """SELECT week_start, week_no, year, total_employees, short_count, created_at
           FROM weekly_reports ORDER BY week_start DESC LIMIT 52"""
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- pages
@app.get("/")
def index(sid: str | None = Cookie(default=None, alias=COOKIE)):
    return RedirectResponse("/login" if not sid else "/worker")


@app.get("/login")
def page_login():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.get("/worker")
def page_worker():
    return FileResponse(os.path.join(STATIC_DIR, "worker.html"))


@app.get("/admin")
def page_admin():
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))


@app.get("/account")
def page_account():
    return FileResponse(os.path.join(STATIC_DIR, "account.html"))


@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.now().isoformat(timespec="seconds")}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
