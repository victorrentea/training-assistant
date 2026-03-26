#!/bin/bash
# Start Wispr Addons menu bar app (kills any existing instance first)
cd "$(dirname "$0")"
pkill -f "wispr-addons/app.py" 2>/dev/null
sleep 0.3
python3 wispr-addons/app.py &
echo "Wispr Addons started (PID $!)"
