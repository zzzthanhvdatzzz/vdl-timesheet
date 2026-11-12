# Bản Windows portable cập nhật

Đọc `HUONG_DAN.txt` để chạy và nâng cấp. Cách chạy mặc định: bấm đúp **`BAT_DAU.bat`**.
Chương trình tự chạy server, đợi web sẵn sàng, mở trình duyệt và kết nối LocalTunnel
portable theo tên link đã lưu. Không cần cài IDE/Python/Node.
`Chay_web.bat` chỉ chạy nội bộ; `Chay_web_public.bat` là cách chạy gộp cũ vẫn được hỗ trợ.
Link public và Tunnel Password được ghi vào `data/public-link.txt` khi kết nối thành công.
Tên yêu cầu được lưu trong `TEN_LINK_PUBLIC.txt` (mặc định `chamcong-vdl-vn`).
Mỗi lần khởi động đều yêu cầu đúng tên đó; nếu không được cấp đúng tên thì báo lỗi,
không tự dùng URL ngẫu nhiên. LocalTunnel công cộng không đảm bảo giữ chỗ tên lâu dài.
Để khởi động lại web trong khi giữ phiên tunnel, chạy `Chay_web.bat` và
`Chay_link_public.bat` ở hai cửa sổ riêng, giữ cửa sổ tunnel mở.
Xem `HUONG_DAN_LINK_PUBLIC.txt` để áp dụng bản vá cho bộ Windows đã tải trước đó.

- Nhập nhiều file Excel, nhập toàn bộ tuần có dữ liệu; có nút đồng bộ lại mọi file đã lưu.
- Kho file phẳng `data/timesheets/`, có chỉ mục file theo nhân viên/tuần trong SQLite.
- Khi sửa giờ, cập nhật mọi file đã đăng ký chứa tuần đó; báo lỗi nếu Windows khóa file.
- Chuyển file từ cấu trúc thư mục từng người của bản cũ khi khởi động.
- Danh sách xưởng từ `resources/nhan-vien-xuong.xlsx`: bảo toàn ID và mật khẩu cũ,
  cấp mã mới nếu cần, khóa tài khoản ngoài danh sách và giữ lịch sử.
- Description: 10 mục cố định và Other cho phép nhập tự do; kiểm tra cả trên server.
- Chạy kiểm tra: `python -m unittest discover -s tests -v` trong môi trường phát triển.

Phần bên dưới mô tả kiến trúc gốc; cách chạy Windows dùng hướng dẫn ở trên.

# Chấm công VDL VN

Hệ thống chấm công nội bộ cho xưởng: nhân viên nhập giờ theo Project/Panel, hệ thống tự sinh
file timesheet `.xlsx` đúng form gốc của công ty, admin quản lý nhân viên, cost place và báo cáo tuần.

## Tính năng

**Nhân viên**
- Đăng nhập bằng tài khoản riêng (mỗi người một tài khoản).
- Nhập **panel number** → hệ thống tự điền **project number** (kèm mô tả panel).
- Chọn **Description of proceedings** từ 10 mục cố định; chọn **Other** để nhập tự do.
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
  timesheets/     mọi file Excel nằm trực tiếp ở đây, không chia thư mục người
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
