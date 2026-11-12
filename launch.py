"""Khởi động server và (tùy chọn) LocalTunnel portable, không cần cài môi trường."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def main():
    os.chdir(ROOT)
    public = '--public' in sys.argv
    port = int(os.environ.get('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('Cổng phải nằm trong khoảng 1–65535')
    try:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    except OSError:
        print(f'Cổng {port} đang được sử dụng. Hãy tắt cửa sổ chạy web cũ trước khi mở bản này.')
        return 1
    server = tunnel = None
    link_file = ROOT / 'data' / 'public-link.txt'
    if public:
        link_file.unlink(missing_ok=True)
    try:
        server = subprocess.Popen([sys.executable, '-X', 'utf8', '-u', str(ROOT / 'run.py')])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = f'http://127.0.0.1:{port}'
        for _ in range(180):
            if server.poll() is not None:
                print('Server chưa khởi động được. Xem lỗi ở phía trên.')
                return 1
            try:
                with opener.open(url + '/login', timeout=1) as response:
                    ready = response.status == 200
                if ready:
                    break
            except OSError:
                time.sleep(0.5)
        else:
            print('Server khởi động quá lâu. Chưa tạo link public; kiểm tra lỗi ở phía trên.')
            return 1
        webbrowser.open(url)
        if public:
            node = ROOT / 'vendor' / 'node' / 'node.exe'
            if not node.is_file():
                print('Thiếu vendor/node/node.exe. Hãy giải nén lại đầy đủ bộ Windows.')
                return 1
            tunnel = subprocess.Popen([str(node), str(ROOT / 'tunnel.js'), str(port)])
            print('Đang tạo link LocalTunnel. Link sẽ hiện bên dưới và được lưu tại data/public-link.txt.', flush=True)
        print('Giữ cửa sổ này mở. Bấm Ctrl+C để tắt web và link public.', flush=True)
        while server.poll() is None:
            if tunnel is not None and tunnel.poll() is not None:
                print('LocalTunnel đã dừng. Web nội bộ vẫn chạy; xem lỗi ở phía trên. Tắt cửa sổ và chạy lại Chay_web_public.bat để yêu cầu lại đúng tên link đã cấu hình.', flush=True)
                tunnel = None
            time.sleep(0.5)
        return server.returncode
    except KeyboardInterrupt:
        return 0
    finally:
        for process in (tunnel, server):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if public:
            link_file.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Không khởi động được: {exc}')
        sys.exit(1)
