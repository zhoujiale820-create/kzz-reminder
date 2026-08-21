@echo off
chcp 65001 >nul
title 新债申购提醒
echo 正在启动新债申购微信/飞书提醒工具...
echo.
python "%~dp0新债申购微信提醒.py"
pause
