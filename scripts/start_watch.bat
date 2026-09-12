@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
rem 전체 경로로 띄워야 stop_watch.ps1 이 이 프로세스를 찾아낼 수 있다
pythonw.exe "%~dp0..\watch.py"
