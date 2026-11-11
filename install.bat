@echo off
rem LCIP installer (Windows): sets up Python packages and adds Desktop and Start menu shortcuts.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python.exe -m pip install -q -r requirements.txt || exit /b 1
rem pythonw.exe starts the app without a console window
powershell -NoProfile -Command ^
  "$s = New-Object -ComObject WScript.Shell;" ^
  "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {" ^
  "  $l = $s.CreateShortcut((Join-Path $dir 'LCIP Adjudicator.lnk'));" ^
  "  $l.TargetPath = '%~dp0.venv\Scripts\pythonw.exe'; $l.Arguments = '\"%~dp0main.py\"';" ^
  "  $l.WorkingDirectory = '%~dp0'; $l.Description = 'Littoral Commander adjudicator (offline)'; $l.Save() }"
echo Installed. Open "LCIP Adjudicator" from your Desktop or Start menu.
