@echo off
rem Windows: run the tests, then build dist\LCIP\LCIP.exe. Must be run on Windows (PyInstaller cannot cross-compile).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
.venv\Scripts\python.exe -m pytest -q tests || exit /b 1
.venv\Scripts\pyinstaller.exe --noconfirm lcip.spec || exit /b 1
echo Built: dist\LCIP\LCIP.exe
