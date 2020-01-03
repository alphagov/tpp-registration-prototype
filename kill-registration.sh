#!/bin/bash
set -e


  if [ -f "./tmp/pids/registration.pid" ]; then
    echo "Killing registration"
    kill "$(< ./tmp/pids/registration.pid)" || true
    rm -f ./tmp/pids/registration.pid
  fi