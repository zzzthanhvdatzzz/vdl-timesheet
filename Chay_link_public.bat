@echo off
chcp 65001 >nul
title LocalTunnel - Cham cong VDL VN
cd /d "%~dp0"
echo Giu cua so nay mo de giu nguyen phien tunnel.
echo Chay Chay_web.bat o cua so rieng. Ban co the tat/mo lai web ma khong tat tunnel.
echo Ten link duoc doc tu TEN_LINK_PUBLIC.txt.
echo.
"vendor\node\node.exe" tunnel.js
echo.
echo LocalTunnel da dung. Bam phim bat ky de dong cua so.
pause >nul
