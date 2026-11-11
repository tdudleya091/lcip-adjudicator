@echo off
rem Windows: create the virtualenv on first run, then start the app. Extra args pass through (e.g. --browser).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
.venv\Scripts\python.exe main.py %*
