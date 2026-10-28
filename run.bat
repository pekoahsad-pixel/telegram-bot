@echo off
chcp 65001 > nul
echo Запуск Telegram бота...
py main.py
if %ERRORLEVEL% NEQ 0 (
    python main.py
)
pause
