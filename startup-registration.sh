#!/bin/bash
set -e

if [ -n "$VIRTUAL_ENV" ]; then
  echo "Already in virtual environment $VIRTUAL_ENV"
else
  python3 -m venv venv
  source ./venv/bin/activate 2>/dev/null && echo "Virtual environment activated."
fi

PID_DIR=./tmp/pids
if [ ! -d $PID_DIR ]; then
    echo -e 'Creating PIDs directory\n'
    mkdir -p $PID_DIR
fi

pip3 install -r requirements.txt

nohup python3 application.py  &
  echo $! > ./tmp/pids/registration.pid
