@echo off
chcp 65001 >nul
title Cham cong VDL VN
cd /d "%~dp0"
python\python.exe -X utf8 -u launch.py --public
echo.
echo Chuong trinh da dung. Bam phim bat ky de dong cua so.
pause >nul
