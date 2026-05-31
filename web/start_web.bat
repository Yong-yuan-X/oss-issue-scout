@echo off
setlocal

cd /d "%~dp0"

python -c "import flask, flask_cors" >nul 2>nul
if errorlevel 1 (
    echo Missing web dependencies.
    echo Run this from the project root first:
    echo python -m pip install -e ".[web]"
    pause
    exit /b 1
)

start "oss-issue-scout api" cmd /k python api.py
start "oss-issue-scout web" cmd /k python -m http.server 8000

timeout /t 2 /nobreak >nul
start http://localhost:8000
