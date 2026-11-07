# Chấm công VDL VN

Hệ thống chấm công nội bộ cho xưởng: nhân viên nhập giờ theo Project/Panel, hệ thống tự sinh
file timesheet `.xlsx` đúng form gốc của công ty, admin quản lý nhân viên, cost place và báo cáo tuần.

## Tính năng

**Nhân viên**
- Đăng nhập bằng tài khoản riêng (mỗi người một tài khoản).
- Nhập **panel number** → hệ thống tự điền **project number** (kèm mô tả panel).
- Chọn **Description of proceedings** từ danh sách gợi ý, hoặc gõ tay nếu chưa có trong danh sách.
- Nhập giờ: Normal (tối đa 8h/ngày), Traveling, Overtime A (ngày thường), Overtime B (Thứ Bảy/Chủ nhật).
- Sửa lại hoặc xoá dòng giờ đã lưu; dữ liệu ghi thẳng vào file timesheet trên máy chủ.
- Thanh tiến trình tuần: mục tiêu 40h hành chính, có cờ đích, tự chuyển xanh khi đủ.
- Tải file timesheet của mình về máy; xem thông báo tiến độ.

**Admin**
- Quản lý nhân viên: thêm nhân viên, gán cost place (chỉ admin sửa được), đặt lại mật khẩu.
- Quản lý Project/Panel: thêm hoặc sửa panel.
- Tab "Giờ đã chấm": xem toàn bộ giờ theo ngày/tuần, xuất Excel theo tuần.
- Nút hộp thư: up file timesheet từ máy admin lên, chọn file đang dùng để ghi dữ liệu,
  tải về, xoá file, tải tất cả dạng `.zip`.
- Nút "Báo cáo tuần": danh sách nhân viên chưa đủ 40h của tuần vừa rồi.
- Nút "Thông báo": thông báo hệ thống (đã tổng hợp báo cáo tuần lúc 07:00 Thứ Hai).

**Tự động (chạy nền trong ứng dụng)**
- 07:00 Thứ Hai: chốt báo cáo tuần trước, lưu vào database, báo cho admin.
- 07:00 Thứ Bảy: thông báo cho từng nhân viên đã làm bao nhiêu giờ, còn thiếu bao nhiêu.
- Nếu máy tắt đúng lúc đó, lần khởi động sau sẽ chạy bù.

## Công nghệ

- Python 3.11, FastAPI, Uvicorn
- SQLite (chế độ mặc định của Python, không cần cài server riêng)
- openpyxl để đọc/ghi file Excel theo đúng form mẫu
- Giao diện HTML/CSS/JS thuần, không phụ thuộc CDN, responsive cho cả điện thoại và máy tính

## Cài đặt

```bash
# 1. Môi trường ảo
uv venv ~/.venv-timesheet --python 3.11
uv pip install --python ~/.venv-timesheet/bin/python fastapi "uvicorn[standard]" openpyxl python-multipart

# 2. File mẫu timesheet của công ty (không nằm trong repo)
mkdir -p data/source
# đặt file "FORM TIMESHEET 2026 VDL VN.xlsx" vào data/source/

# 3. Tạo database và nạp dữ liệu từ file mẫu
~/.venv-timesheet/bin/python -m app.seed --reset

# 4. Chạy
bash run.sh          # mặc định http://127.0.0.1:8000
PORT=9000 bash run.sh
```

Tài khoản khởi tạo được ghi ra `data/credentials.csv` (admin mặc định `admin` / `admin@2026`,
nhân viên `nvXX` / `vdl@XX`). **Đổi mật khẩu trước khi dùng thật.**

## Cấu trúc

```
app/
  main.py         API FastAPI, phân quyền, scheduler báo cáo tuần
  db.py           schema SQLite + migration nhẹ
  auth.py         băm mật khẩu PBKDF2, token phiên
  seed.py         đọc Excel mẫu, nạp nhân viên / project / panel / cost centre
  export.py       ghi file timesheet theo form mẫu, đọc file admin up lên
  static/         login.html, worker.html, admin.html, account.html, style.css
data/
  source/         file mẫu timesheet (tự đặt, không commit)
  timesheets/     file .xlsx của từng nhân viên (tự sinh, không commit)
  app.db          database (tự sinh, không commit)
scripts/
  sync_timesheets.sh   kéo toàn bộ file timesheet từ máy chủ về máy admin
```

## Quy tắc nghiệp vụ

- Giờ hành chính (Normal) tối đa **8h/ngày**, overtime nhập ở ô riêng và không tính vào 8h này.
- **Thứ Bảy và Chủ nhật chỉ ghi Overtime B**; ngày thường chỉ ghi Overtime A. Server chặn cả hai chiều.
- Mục tiêu tuần là **40h hành chính**; overtime không tính vào mức này.
- Số tuần đánh theo cách của file mẫu: lấy ISO week của ngày Thứ Hai trong tuần đó.
- Mỗi nhân viên có một file timesheet "đang dùng" trên máy chủ. Nhân viên lưu/sửa/xoá giờ thì
  file được ghi lại ngay. Admin có thể up file khác lên để thay thế.
- Cost place của nhân viên chỉ admin sửa được; giá trị được chụp lại tại thời điểm ghi giờ.

## API chính

| Method | Đường dẫn | Việc |
|---|---|---|
| POST | `/api/login`, `/api/logout` | đăng nhập / đăng xuất |
| GET | `/api/me` | thông tin người đang đăng nhập |
| POST | `/api/me/password` | tự đổi mật khẩu |
| POST | `/api/password-request` | gửi yêu cầu cấp lại mật khẩu cho admin |
| GET | `/api/panel-search`, `/api/panel-lookup` | gợi ý panel, tra panel → project |
| GET | `/api/entries` | giờ của mình theo tuần |
| POST/PUT/DELETE | `/api/entries` | thêm / sửa / xoá dòng giờ |
| GET | `/api/my-timesheet` | tải file timesheet của mình |
| GET/POST | `/api/notifications` | thông báo của mình |
| GET | `/api/admin/employees` | danh sách nhân viên |
| POST | `/api/admin/employees` | thêm nhân viên |
| PATCH | `/api/admin/employees/{id}` | đổi cost place / trạng thái |
| POST | `/api/admin/employees/{id}/password` | đặt lại mật khẩu |
| GET | `/api/admin/week-summary` | tổng hợp tuần (ai chưa đủ 40h) |
| GET | `/api/admin/week-reports` | các báo cáo tuần đã chốt |
| POST | `/api/admin/timesheet-upload` | up file timesheet lên |
| GET/DELETE | `/api/admin/timesheet-file` | tải / xoá file timesheet |
| GET | `/api/admin/timesheet-zip` | tải tất cả file dạng zip |
| GET | `/api/admin/export` | xuất Excel tuần của một nhân viên |

## Ghi chú triển khai

- Ứng dụng mặc định chỉ nghe `127.0.0.1`. Khi đưa lên máy chủ thật cần đặt sau reverse proxy
  có HTTPS (Caddy/Nginx) hoặc Cloudflare Tunnel, và đổi toàn bộ mật khẩu mặc định.
- File timesheet nằm trên máy chạy server. Muốn đồng bộ về máy admin, dùng `scripts/sync_timesheets.sh`
  (chạy được trên Linux và macOS).
- Gửi email báo cáo qua Gmail là tuỳ chọn: tạo `~/.config/vdl-timesheet/email.env` với `SMTP_USER`
  và `SMTP_PASS` (App Password). Không cấu hình thì hệ thống không gửi gì.
