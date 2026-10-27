@echo off
rem Starts Bank Statement Analyzer. The first run sets up a private Python environment (.venv)
rem and installs what the app needs; later runs start straight away.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Setting up - first run only...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist .venv\Scripts\python.exe (
    echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
  )
)
if not exist .venv-installed (
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt || (pause & exit /b 1)
  type nul > .venv-installed
)
.venv\Scripts\python.exe -m streamlit run app.py
