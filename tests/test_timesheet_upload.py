"""Kiểm tra nhập nhiều tuần bằng workbook và database tạm, không đụng dữ liệu thật."""
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import openpyxl
from fastapi import HTTPException, UploadFile

from app import db, export, main, storage, roster


class TimesheetUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_patch = patch.object(db, 'DB_PATH', str(self.root / 'app.db'))
        self.dir_patch = patch.object(export, 'TIMESHEET_DIR', str(self.root / 'timesheets'))
        self.base_patch = patch.object(main, 'BASE_DIR', str(self.root))
        self.base_patch.start()
        self.db_patch.start()
        self.dir_patch.start()
        db.init_db()
        self.conn = db.connect()
        with self.conn:
            self.conn.execute("INSERT INTO employees(id, pers_no, name, username, password_hash) VALUES (1, 1, 'TEST', 'test', 'unused')")
            self.conn.execute("INSERT INTO employees(id, pers_no, name, username, password_hash) VALUES (2, 2, 'OTHER', 'other', 'unused')")
            for employee, day in [(1, '2026-01-05'), (1, '2026-01-19'), (1, '2026-01-26'), (2, '2026-01-05')]:
                self.conn.execute("INSERT INTO entries(employee_id, work_date, project_number, normal_hours, created_at) VALUES (?, ?, 'OLD', 3, 'test')", (employee, day))

    def tearDown(self):
        self.conn.close()
        self.dir_patch.stop()
        self.base_patch.stop()
        self.db_patch.stop()
        self.tmp.cleanup()

    def workbook(self, bad=False, duplicate=False, empty=False, formula=False):
        wb = openpyxl.Workbook()
        wb.active.title = 'Name list'
        # Nhiều dòng nhất ở tuần đầu: vẫn phải nhập cả tuần thứ hai.
        for name, start, hours in [('2', date(2026, 1, 4), [8, 2]), ('3', date(2026, 1, 11), [6]), ('4', date(2026, 1, 18), [])]:
            ws = wb.create_sheet(name)
            ws['F1'] = start
            for i, hour in enumerate([] if empty else hours):
                ws.cell(7 + i, 2, 'NEW')
                ws.cell(7 + i, 7, hour)
            ws['Q70'] = '=SUM(G7:G16)'
        if bad:
            wb['3']['F1'] = 'invalid date'
        if duplicate:
            wb['3']['F1'] = wb['2']['F1'].value
        if formula:
            wb['3']['G7'] = '=2+4'
        out = io.BytesIO()
        wb.save(out)
        wb.close()
        return out.getvalue()

    def upload(self, content):
        return main.admin_timesheet_upload(employee_id=1, file=UploadFile(filename='employee.xlsx', file=io.BytesIO(content)), admin={}, conn=self.conn)

    def snapshot(self):
        return [tuple(r) for r in self.conn.execute('SELECT * FROM entries ORDER BY id')]

    def test_import_all_weeks_and_reupload_without_duplicates(self):
        content = self.workbook()
        for _ in range(2):
            result = self.upload(content)
            self.assertEqual(result['weeks_imported'], 2)
            self.assertEqual(result['imported'], 3)
            rows = self.conn.execute('SELECT * FROM entries WHERE employee_id=1').fetchall()
            self.assertEqual(len(rows), 5)
            self.assertEqual(sum(r['normal_hours'] for r in rows), 22)
            self.assertEqual({r['work_date'] for r in rows}, {'2026-01-05', '2026-01-12', '2026-01-19', '2026-01-26'})
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM entries WHERE employee_id=2').fetchone()[0], 1)
        wb = openpyxl.load_workbook(result['file_path'])
        self.assertEqual(wb['2']['Q70'].value, '=SUM(G7:G16)')
        self.assertIn('Name list', wb.sheetnames)
        wb.close()

    def test_invalid_or_duplicate_or_empty_file_keeps_existing_data(self):
        for kwargs in [{'bad': True}, {'duplicate': True}, {'empty': True}, {'formula': True}]:
            before = self.snapshot()
            with self.assertRaises(HTTPException) as err:
                self.upload(self.workbook(**kwargs))
            self.assertEqual(err.exception.status_code, 400)
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(list((self.root / 'data' / '_uploads').iterdir()))

    def test_database_failure_rolls_back_every_week_and_preserves_file(self):
        first = self.upload(self.workbook())
        master = Path(first['file_path'])
        before_file = master.read_bytes()
        before = self.snapshot()
        self.conn.execute("CREATE TRIGGER fail_import BEFORE INSERT ON entries WHEN NEW.work_date = '2026-01-12' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(Exception):
            self.upload(self.workbook())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(master.read_bytes(), before_file)
        self.assertFalse(list((self.root / 'data' / '_uploads').iterdir()))

    def test_flat_files_ownership_collision_and_zip(self):
        self.upload(self.workbook())
        result = main.admin_timesheet_upload(employee_id=2,
            file=UploadFile(filename='employee.xlsx', file=io.BytesIO(self.workbook())), admin={}, conn=self.conn)
        self.assertEqual(Path(result['file_path']).parent, self.root / 'timesheets')
        self.assertNotEqual(Path(result['file_path']).name, 'employee.xlsx')
        self.assertEqual(len(main.admin_timesheet_files(1, {}, self.conn)['files']), 1)
        with self.assertRaises(HTTPException):
            main.admin_timesheet_file(2, 'employee.xlsx', {}, self.conn)
        import zipfile
        response = main.admin_timesheet_zip(admin={}, conn=self.conn)
        with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
            self.assertEqual(len(archive.namelist()), 2)
            self.assertTrue(all('/' not in n for n in archive.namelist()))

    def test_edit_updates_all_uploaded_workbooks_for_same_week(self):
        self.upload(self.workbook())
        main.admin_timesheet_upload(employee_id=1,
            file=UploadFile(filename='second.xlsx', file=io.BytesIO(self.workbook())), admin={}, conn=self.conn)
        with self.conn:
            self.conn.execute("UPDATE entries SET normal_hours=4 WHERE employee_id=1 AND project_number='NEW'")
        main._sync_employee_week(self.conn, 1, date(2026, 1, 5))
        for filename in ['employee.xlsx', 'second.xlsx']:
            wb = openpyxl.load_workbook(self.root / 'timesheets' / filename)
            self.assertEqual(wb['2']['G7'].value, 4)
            self.assertEqual(wb['2']['D1'].value, 'TEST')
            wb.close()

    def test_batch_matches_names_and_reports_bad_files(self):
        data = self.workbook()
        wb = openpyxl.load_workbook(io.BytesIO(data))
        for sheet in ['2', '3']:
            wb[sheet]['D1'] = 'TEST'
        content = io.BytesIO()
        wb.save(content)
        wb.close()
        result = main.admin_timesheet_upload_batch(files=[
            UploadFile(filename='ok.xlsx', file=io.BytesIO(content.getvalue())),
            UploadFile(filename='bad.xlsx', file=io.BytesIO(b'not xlsx'))], employee_id=None, admin={}, conn=self.conn)
        self.assertEqual(result['succeeded'], 1)
        self.assertEqual(result['results'][0]['employee_id'], 1)
        self.assertFalse(result['results'][1]['ok'])

    def test_legacy_folder_migrates_without_losing_data(self):
        folder = self.root / 'timesheets' / 'TEST'
        folder.mkdir(parents=True)
        source = folder / 'old.xlsx'
        source.write_bytes(self.workbook())
        with self.conn:
            self.conn.execute('UPDATE employees SET timesheet_file=? WHERE id=1', (str(source),))
        storage.migrate_legacy(self.conn)
        storage.migrate_legacy(self.conn)
        self.assertFalse(folder.exists())
        self.assertEqual(len(storage.files_for(self.conn, 1)), 1)
        self.assertTrue((self.root / 'timesheets' / 'old.xlsx').is_file())
        self.assertEqual(len(self.snapshot()), 4)

    def test_description_fixed_and_other(self):
        self.assertEqual(len(main.DESCRIPTION_OPTIONS), 10)
        body = main.EntryIn(work_date='2026-01-05', project_number='P',
                            description_choice='Other', description='Custom work')
        self.assertEqual(main._entry_description(body), 'Custom work')
        body.description_choice = main.DESCRIPTION_OPTIONS[3]
        with self.assertRaises(HTTPException):
            main._entry_description(body)
        body.description = body.description_choice
        self.assertEqual(main._entry_description(body), body.description)

    def test_roster_exactly_matches_supplied_names_and_keeps_history(self):
        before = self.snapshot()
        original_hash = self.conn.execute('SELECT password_hash FROM employees WHERE id=1').fetchone()[0]
        with patch.object(roster, 'read_names', return_value=['TEST', 'New Person']):
            result = roster.sync_if_changed(self.conn)
            self.assertEqual(result['added'], 1)
            self.assertEqual({r[0] for r in self.conn.execute('SELECT name FROM employees WHERE active=1')}, {'TEST', 'New Person'})
            self.assertEqual(self.conn.execute('SELECT password_hash FROM employees WHERE id=1').fetchone()[0], original_hash)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(roster.sync_if_changed(self.conn)['added'], 0)

    def test_template_header_formulas_without_excel_cache(self):
        wb = openpyxl.load_workbook(io.BytesIO(self.workbook()))
        wb['2']['H1'] = date(2026, 1, 10)
        wb['2']['D1'] = 'TEST'
        wb['3']['F1'] = "='2'!H1+1"
        wb['3']['D1'] = "='2'!D1"
        stream = io.BytesIO()
        wb.save(stream)
        wb.close()
        result = main.admin_timesheet_upload(employee_id=None,
            file=UploadFile(filename='formulas.xlsx', file=io.BytesIO(stream.getvalue())), admin={}, conn=self.conn)
        self.assertEqual(result['weeks_imported'], 2)
        self.assertEqual(result['employee_id'], 1)

    def test_resync_restores_all_weeks_from_existing_files(self):
        self.upload(self.workbook())
        with self.conn:
            self.conn.execute("DELETE FROM entries WHERE employee_id=1 AND work_date='2026-01-12'")
        result = main.admin_timesheet_resync(admin={}, conn=self.conn)
        self.assertEqual(result['succeeded'], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entries WHERE employee_id=1 AND work_date='2026-01-12'").fetchone()[0], 1)

    def test_import_includes_renamed_week_alongside_numbered_sheets(self):
        wb = openpyxl.load_workbook(io.BytesIO(self.workbook()))
        wb['3'].title = 'Week 3'
        stream = io.BytesIO()
        wb.save(stream)
        wb.close()
        result = self.upload(stream.getvalue())
        self.assertEqual(result['weeks_imported'], 2)
        self.assertEqual(result['imported'], 3)


if __name__ == '__main__':
    unittest.main()
