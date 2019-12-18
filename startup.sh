#!/bin/bash
set -e

if [ -n "$VIRTUAL_ENV" ]; then
  echo "Already in virtual environment $VIRTUAL_ENV"
else
  python3 -m venv venv
  source ./venv/bin/activate 2>/dev/null && echo "Virtual environment activated."
fi

python3 application.py
