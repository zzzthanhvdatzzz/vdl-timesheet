"""Kết nối SQLite + tạo schema cho hệ thống chấm công VDL."""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_centres (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pers_no INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL,
    emp_type TEXT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    cost_place_code TEXT REFERENCES cost_centres(code),
    place TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS projects (
    project_number TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_number TEXT NOT NULL,
    panel_number TEXT NOT NULL,
    description TEXT,
    desc_vi TEXT,
    remark TEXT,
    UNIQUE(project_number, panel_number)
);
CREATE INDEX IF NOT EXISTS idx_panels_project ON panels(project_number);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    work_date TEXT NOT NULL,
    project_number TEXT NOT NULL,
    panel_number TEXT,
    description TEXT,
    normal_hours REAL NOT NULL DEFAULT 0,
    travel_hours REAL NOT NULL DEFAULT 0,
    ot_a REAL NOT NULL DEFAULT 0,
    ot_b REAL NOT NULL DEFAULT 0,
    cost_place TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    approved_by INTEGER,
    approved_at TEXT,
    review_note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_emp_date ON entries(employee_id, work_date);

CREATE TABLE IF NOT EXISTS password_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER REFERENCES employees(id),
    username TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    temp_password TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS weekly_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL UNIQUE,
    week_no INTEGER NOT NULL,
    year INTEGER NOT NULL,
    required_hours REAL NOT NULL,
    total_employees INTEGER NOT NULL,
    short_count INTEGER NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL,
    week_start TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    UNIQUE(employee_id, kind, week_start)
);

CREATE TABLE IF NOT EXISTS email_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    to_addr TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    error TEXT,
    tries INTEGER NOT NULL DEFAULT 0
);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        # migration cho DB cũ: thêm cột duyệt nếu chưa có
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(entries)")}
        for name, ddl in (
            ("status", "ALTER TABLE entries ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"),
            ("approved_by", "ALTER TABLE entries ADD COLUMN approved_by INTEGER"),
            ("approved_at", "ALTER TABLE entries ADD COLUMN approved_at TEXT"),
            ("review_note", "ALTER TABLE entries ADD COLUMN review_note TEXT"),
        ):
            if name not in cols:
                conn.execute(ddl)
        emp_cols = {r["name"] for r in conn.execute("PRAGMA table_info(employees)")}
        if "timesheet_file" not in emp_cols:
            conn.execute("ALTER TABLE employees ADD COLUMN timesheet_file TEXT")
    conn.close()
