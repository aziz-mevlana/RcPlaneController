#!/bin/bash
# RC Plane Controller — Steam Deck baslatma
cd "$(dirname "$0")"
source venv/bin/activate

# evdev yoksa kur
python3 -c "import evdev" 2>/dev/null || pip install evdev

exec python3 control.py --tty "$@"
