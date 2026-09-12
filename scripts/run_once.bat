@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
pythonw.exe "%~dp0..\run_once.py" %1
