"""Kho timesheet phẳng: mọi file Excel nằm trực tiếp trong data/timesheets."""
import ntpath
import os
import re
import unicodedata
from datetime import datetime


def name_key(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold().replace('đ', 'd')
    return ''.join(ch for ch in text if ch.isalnum())


def safe_filename(name):
    name = ntpath.basename(name or 'timesheet.xlsx')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')
    if not name or name.rsplit('.', 1)[-1].lower() not in {'xlsx', 'xlsm'}:
        raise ValueError('Chỉ nhận file Excel .xlsx hoặc .xlsm')
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        name = '_' + name
    return name


def target_name(conn, employee_id, name):
    from .export import TIMESHEET_DIR
    name = safe_filename(name)
    stem, ext = os.path.splitext(name)
    candidate = name
    index = 0
    while True:
        owner = conn.execute('SELECT employee_id FROM timesheet_files WHERE filename = ? COLLATE NOCASE', (candidate,)).fetchone()
        if owner and owner['employee_id'] == employee_id:
            return candidate
        if not owner and not os.path.exists(os.path.join(TIMESHEET_DIR, candidate)):
            return candidate
        index += 1
        candidate = f'{stem}__nv{employee_id}' + (f'_{index}' if index > 1 else '') + ext


def register(conn, employee_id, filename, weeks):
    conn.execute('''INSERT INTO timesheet_files(employee_id, filename, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(filename) DO UPDATE SET updated_at = excluded.updated_at''',
                 (employee_id, filename, datetime.now().isoformat(timespec='seconds')))
    row = conn.execute('SELECT id, employee_id FROM timesheet_files WHERE filename = ?', (filename,)).fetchone()
    if row['employee_id'] != employee_id:
        raise ValueError('Tên file đang thuộc nhân viên khác')
    conn.execute('DELETE FROM timesheet_file_weeks WHERE file_id = ?', (row['id'],))
    for week in weeks:
        conn.execute('INSERT INTO timesheet_file_weeks(file_id, week_start, sheet_name) VALUES (?, ?, ?)',
                     (row['id'], week['start'].isoformat(), week['sheet']))


def files_for(conn, employee_id=None):
    sql = 'SELECT * FROM timesheet_files'
    params = ()
    if employee_id is not None:
        sql += ' WHERE employee_id = ?'
        params = (employee_id,)
    return conn.execute(sql + ' ORDER BY filename', params).fetchall()


def owned_path(conn, employee_id, name):
    from .export import TIMESHEET_DIR
    name = safe_filename(name)
    row = conn.execute('SELECT * FROM timesheet_files WHERE filename = ? AND employee_id = ?', (name, employee_id)).fetchone()
    if row is None:
        raise FileNotFoundError('File không thuộc nhân viên này')
    path = os.path.join(TIMESHEET_DIR, row['filename'])
    if not os.path.isfile(path):
        raise FileNotFoundError('Không thấy file timesheet')
    return path


def migrate_legacy(conn):
    """Di chuyển file từ thư mục từng người của bản cũ; cập nhật đường dẫn khi đổi máy."""
    from . import export
    os.makedirs(export.TIMESHEET_DIR, exist_ok=True)
    for emp in conn.execute('SELECT * FROM employees').fetchall():
        folder = os.path.join(export.TIMESHEET_DIR, export.safe_person_dir(emp['name']))
        master = emp['timesheet_file']
        legacy_name = ntpath.basename(master) if master else None
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if not name.lower().endswith(('.xlsx', '.xlsm')):
                    continue
                old_path = os.path.join(folder, name)
                new_name = target_name(conn, emp['id'], name)
                new_path = os.path.join(export.TIMESHEET_DIR, new_name)
                try:
                    weeks = export.read_timesheet(old_path)
                except Exception:
                    weeks = []  # giữ lại file cũ kể cả khi chưa đọc được nội dung
                os.replace(old_path, new_path)
                try:
                    with conn:
                        register(conn, emp['id'], new_name, weeks)
                        if name == legacy_name:
                            conn.execute('UPDATE employees SET timesheet_file = ? WHERE id = ?', (new_path, emp['id']))
                except Exception:
                    os.replace(new_path, old_path)
                    raise
            try:
                os.rmdir(folder)
            except OSError:
                pass
        # File đã đăng ký vẫn tìm thấy khi chép cả thư mục data sang máy khác.
        if master:
            current = conn.execute('SELECT timesheet_file FROM employees WHERE id = ?', (emp['id'],)).fetchone()[0]
            if current and not os.path.isfile(current):
                row = conn.execute('SELECT filename FROM timesheet_files WHERE employee_id = ? AND filename = ?', (emp['id'], legacy_name)).fetchone()
                if row:
                    with conn:
                        conn.execute('UPDATE employees SET timesheet_file = ? WHERE id = ?', (os.path.join(export.TIMESHEET_DIR, row['filename']), emp['id']))
