@echo off
chcp 65001 >nul
echo Installing VK Admin Notifier dependencies...
echo:
pip install -r requirements.txt
echo:
echo Done! Run: python main.py
pause
