"""Đồng bộ danh sách xưởng từ workbook được cung cấp, bảo toàn ID và lịch sử."""
import csv
import hashlib
import os
from pathlib import Path

import openpyxl

from . import auth, storage

ROSTER_PATH = Path(__file__).resolve().parent.parent / 'resources' / 'nhan-vien-xuong.xlsx'


def read_names(path):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        names = [str(row[0]).strip() for row in wb.active.iter_rows(values_only=True) if row and row[0]]
    finally:
        wb.close()
    if not names or len({storage.name_key(n) for n in names}) != len(names):
        raise ValueError('Danh sách nhân viên trống hoặc trùng tên')
    return names


def sync_if_changed(conn):
    if not ROSTER_PATH.is_file():
        raise FileNotFoundError(f'Thiếu danh sách nhân viên: {ROSTER_PATH}')
    digest = hashlib.sha256(ROSTER_PATH.read_bytes()).hexdigest()
    saved = conn.execute("SELECT value FROM app_settings WHERE key = 'roster_hash'").fetchone()
    if saved and saved['value'] == digest:
        return {'added': 0, 'new_credentials': []}
    names = read_names(ROSTER_PATH)
    existing = conn.execute('SELECT * FROM employees WHERE is_admin = 0').fetchall()
    by_name = {}
    for row in existing:
        by_name.setdefault(storage.name_key(row['name']), []).append(row)
    if any(len(by_name.get(storage.name_key(n), [])) > 1 for n in names):
        raise ValueError('Có nhiều tài khoản trùng tên; cần xử lý trước khi đồng bộ danh sách xưởng')
    next_code = max(63, conn.execute('SELECT COALESCE(MAX(pers_no), 0) FROM employees').fetchone()[0]) + 1
    credentials = []
    wanted_ids = []
    with conn:
        for name in names:
            matches = by_name.get(storage.name_key(name), [])
            if matches:
                emp = matches[0]
                conn.execute('UPDATE employees SET name = ?, active = 1 WHERE id = ?', (name, emp['id']))
                wanted_ids.append(emp['id'])
            else:
                code = next_code
                while conn.execute('SELECT 1 FROM employees WHERE username = ?', (f'nv{code:02d}',)).fetchone():
                    code += 1
                next_code = code + 1
                username, password = f'nv{code:02d}', f'vdl@{code:02d}'
                cp = '1060.01' if conn.execute("SELECT 1 FROM cost_centres WHERE code = '1060.01'").fetchone() else None
                row = conn.execute('''INSERT INTO employees(pers_no, name, emp_type, username, password_hash,
                                      cost_place_code, place, is_admin, active)
                                      VALUES (?, ?, 'P', ?, ?, ?, 'VDL WORKSHOP', 0, 1)''',
                                   (code, name, username, auth.hash_password(password), cp))
                wanted_ids.append(row.lastrowid)
                credentials.append([username, password, code, name, cp])
        placeholders = ','.join('?' for _ in wanted_ids)
        conn.execute(f'UPDATE employees SET active = 0 WHERE is_admin = 0 AND id NOT IN ({placeholders})', wanted_ids)
        conn.execute('DELETE FROM sessions WHERE employee_id IN (SELECT id FROM employees WHERE active = 0)')
        conn.execute("INSERT OR REPLACE INTO app_settings(key, value) VALUES ('roster_hash', ?)", (digest,))
    if credentials:
        from . import db
        path = os.path.join(os.path.dirname(db.DB_PATH), 'tai-khoan-nhan-vien-moi.csv')
        with open(path, 'w', encoding='utf-8-sig', newline='') as out:
            writer = csv.writer(out)
            writer.writerow(['username', 'password', 'pers_no', 'name', 'cost_place_code'])
            writer.writerows(credentials)
    return {'added': len(credentials), 'new_credentials': credentials}
