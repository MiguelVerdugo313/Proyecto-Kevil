#!/usr/bin/env bash
# Arranca Kevil Studio en macOS y Linux.
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "No se encuentra Python. Instálalo desde https://www.python.org/downloads/"
  exit 1
fi

exec "$PY" run.py "$@"
