#!/bin/zsh
# Keeps the dashboard fresh: every 2 min during game windows, every 15 min otherwise.
cd "$(dirname "$0")"
while true; do
  python3 nba.py 4 || echo "refresh failed $(date)"
  h=$(date +%H)
  if (( h >= 12 || h < 2 )); then sleep 120; else sleep 900; fi
done
