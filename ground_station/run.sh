#!/bin/bash
# RC Ucak Yer Istasyonu Baslatma

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

python main.py "$@"
