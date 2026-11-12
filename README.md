# Chấm công VDL VN

Web chấm công nội bộ: nhân viên tự nhập giờ theo ngày, dữ liệu tự ghi vào file Excel
timesheet của từng người, admin quản lý nhân viên / project / panel / cost place và
xem báo cáo tuần.

## Yêu cầu

- Python 3.10 trở lên (Windows, macOS, Linux đều được)
- Không cần Node.js, không cần database server (dùng SQLite)

## Cài đặt (làm một lần)

```bash
# 1. Tải mã nguồn
git clone https://github.com/zzzthanhvdatzzz/vdl-timesheet.git
cd vdl-timesheet

# 2. Tạo môi trường ảo
python -m venv .venv

# 3. Kích hoạt môi trường ảo
.venv\Scripts\activate          # Windows (cmd hoặc PowerShell)
source .venv/bin/activate       # macOS / Linux

# 4. Cài thư viện
pip install -r requirements.txt
```

## Chạy web

```bash
python run.py
```

Mở http://127.0.0.1:8000

- Đăng nhập quản trị mặc định: `admin` / `admin@2026`
- Đổi cổng: `PORT=9000 python run.py` (macOS/Linux) hoặc `set PORT=9000 && python run.py` (Windows)
- Cho máy khác trong LAN vào: `HOST=0.0.0.0 python run.py`, rồi máy kia mở `http://<IP-máy-chủ>:8000`

Dừng web: Ctrl+C.

## Cách đưa nhân viên vào hệ thống (quan trọng)

Repo **không kèm** file Excel mẫu của công ty. Luồng đúng như sau:

1. Admin đăng nhập (`admin` / `admin@2026`)
2. Vào tab **Nhân viên** → nút **…** hoặc ô upload → chọn file timesheet `.xlsx` của nhân viên đó
3. Hệ thống đọc tên ở ô D1, mã Pers.no ở ô O1, tự tạo nhân viên và hiện tài khoản mới,
   ví dụ `Lê Văn Khải → nv10 / vdl@10`. Cost place lấy luôn từ file.
4. Đưa tài khoản đó cho nhân viên. Từ lần này, họ tự chấm công và dữ liệu
   được ghi thẳng vào chính file Excel đã upload trên máy admin.

Chỉ mất bước upload này một lần cho mỗi người. Nhân viên chưa được upload file thì
chưa đăng nhập được.

Muốn nạp sẵn toàn bộ danh sách nhân viên / 346 project / 3315 panel từ file mẫu của
công ty thì copy `FORM TIMESHEET 2026 VDL VN.xlsx` vào `data/source/` rồi chạy
`python -m app.seed`.

## Dữ liệu nằm ở đâu

| Đường dẫn | Nội dung |
|---|---|
| `data/app.db` | database: nhân viên, giờ công, tài khoản |
| `data/timesheets/` | file Excel timesheet từng người, tự cập nhật khi lưu giờ |
| `data/source/` | file Excel mẫu (không commit) |
| `data/backups/` | bản sao database tự tạo hằng ngày, giữ 7 bản |
| `data/credentials.csv` | danh sách tài khoản khởi tạo (sau lần seed đầu) |

Sao lưu: copy cả thư mục `data/`. Chuyển máy: copy cả thư mục `data/` sang máy mới.

## Tính năng

- Nhân viên nhập giờ theo ngày: Normal / Travel / Overtime A / Overtime B
- Ngày thường chỉ ghi Overtime A, Thứ Bảy & Chủ nhật chỉ ghi Overtime B
- Normal tối đa 8h/ngày, thanh tiến trình mục tiêu 40h/tuần
- Nhập Panel number trước, Project number tự điền và khoá lại
- Cost place (mã cost centre) do admin gán, nhân viên không sửa được
- Lưu giờ là ghi thẳng vào file Excel timesheet của người đó (không cần tải về)
- Admin: upload nhiều file timesheet một lúc, tải về, xoá, chọn file làm chuẩn
- Báo cáo tuần: ai chưa đủ 40h; tự chốt 7h sáng Thứ Hai, thông báo nhân viên 7h sáng Thứ Bảy
- Đổi mật khẩu, quên mật khẩu (gửi yêu cầu cho admin), gửi email báo cáo nếu cấu hình SMTP
- Tự sao lưu database mỗi ngày

## Kiểm thử

```bash
python -m unittest tests.test_timesheet_upload -v
```

12 test: nhập nhiều tuần, upload lại không trùng, rollback khi lỗi, resync, kho file phẳng,
danh sách nhân viên, công thức header.

## Cấu hình email (tùy chọn)

Tạo file `~/.config/vdl-timesheet/email.env`:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=your@gmail.com
SMTP_PASS=app-password
MAIL_TO=admin@congty.com
```

Không cấu hình thì báo cáo chỉ hiện trong web, không gửi mail.

## Lưu ý bảo mật

- Đổi mật khẩu admin mặc định trước khi dùng thật
- Không đưa link public cho người ngoài: dữ liệu chấm công là dữ liệu cá nhân
- Chạy liên tục 24/7 cần máy chủ/VPS, không dùng được Vercel (serverless không giữ được file)

## Bản đóng gói sẵn cho Windows

Nếu chỉ cần chạy trên máy Windows không có Python, dùng bản zip có kèm sẵn Python và
Node.js: bấm `BAT_DAU.bat` là chạy, không cần cài gì. Bản này lấy từ người phát hành,
không có trong repo.
