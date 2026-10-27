#!/usr/bin/env bash
# Starts Bank Statement Analyzer. The first run sets up a private Python environment (.venv)
# and installs what the app needs; later runs start straight away.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Setting up (first run only)..."
  python3 -m venv .venv
fi
if [ ! -f .venv-installed ] || [ requirements.txt -nt .venv-installed ]; then
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv-installed
fi
exec .venv/bin/python -m streamlit run app.py
