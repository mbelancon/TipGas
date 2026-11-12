@echo off
REM ---------------------------------------------------------------------------
REM  TipGas - launcher for Windows (running from source)
REM  Finds Python (Miniconda, Anaconda or PATH), installs missing libraries
REM  and opens the interface. The portable release does not need this file.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "PY="
for %%P in (
  "%USERPROFILE%\miniconda3\python.exe"
  "%USERPROFILE%\anaconda3\python.exe"
  "%LOCALAPPDATA%\miniconda3\python.exe"
  "%LOCALAPPDATA%\anaconda3\python.exe"
  "%ProgramData%\miniconda3\python.exe"
  "%ProgramData%\anaconda3\python.exe"
  "C:\miniconda3\python.exe"
  "C:\anaconda3\python.exe"
) do (
  if not defined PY if exist %%P set "PY=%%~P"
)
REM Last resort: python on the PATH (ignoring the Microsoft Store alias)
if not defined PY (
  for /f "delims=" %%I in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do (
    if not defined PY set "PY=%%I"
  )
)
if not defined PY (
  echo Python not found. Install Miniconda, or use the portable release (TipGas.exe).
  pause
  exit /b 1
)
echo Using Python: %PY%

REM Miniconda: DLLs live in Library\bin; without this Qt/numpy may fail to load
for %%D in ("%PY%") do set "PYDIR=%%~dpD"
set "PATH=%PYDIR%;%PYDIR%Library\bin;%PYDIR%Scripts;%PATH%"

"%PY%" -c "import PySide6, pyqtgraph, serial, numpy" 2>nul
if errorlevel 1 (
  echo Installing required libraries ^(first run only^)...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Failed to install the libraries.
    pause
    exit /b 1
  )
)

"%PY%" TipGas.py %*
if errorlevel 1 pause
