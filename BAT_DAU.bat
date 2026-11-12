@echo off
setlocal
chcp 65001 >nul
title Cham cong VDL VN - Web + LocalTunnel
cd /d "%~dp0"
set "VDL_EXIT_CODE=1"

if not exist "python\python.exe" (
    echo Thieu Python di kem. Hay giai nen day du bo ung dung truoc khi chay.
    goto :finish
)
if not exist "vendor\node\node.exe" (
    echo Thieu Node.js di kem. Hay dung goi Windows day du co LocalTunnel.
    goto :finish
)
if not exist "TEN_LINK_PUBLIC.txt" (
    >"TEN_LINK_PUBLIC.txt" echo chamcong-vdl-vn
)

echo Dang khoi dong web va LocalTunnel...
echo Link va Tunnel Password se hien o cua so nay sau khi ket noi thanh cong.
echo Giu cua so nay mo trong khi su dung. Bam Ctrl+C de tat.
echo.
"python\python.exe" -X utf8 -u launch.py --public
set "VDL_EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
echo Chuong trinh da dung. Bam phim bat ky de dong cua so.
pause >nul
exit /b %VDL_EXIT_CODE%
