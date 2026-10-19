#!/usr/bin/env python3
"""Serves the board at http://localhost:8765 and keeps every stat fresh.

- Background refresh: every 2 min from noon to 2 AM ET (game windows), every 15 min otherwise.
- POST /refresh rebuilds everything right now (the Refresh button on the page).
"""
import json, os, subprocess, sys, threading, time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = [os.path.join(ROOT, "nba", "nba.py"), os.path.join(ROOT, "nfl", "nfl.py")]
lock = threading.Lock()
state = {"last": None, "error": None}


def rebuild(force=False):
    if not lock.acquire(blocking=False):
        with lock:  # a rebuild is already running; wait for it
            return state
    try:
        env = dict(os.environ, NBA_FORCE="1" if force else "")
        errs = []
        for script in SCRIPTS:
            if not os.path.exists(script):
                continue
            r = subprocess.run([sys.executable, script] + (["4"] if script.endswith("nba.py") else []), cwd=os.path.dirname(script),
                               env=env, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                errs.append(os.path.basename(script) + ": " + (r.stderr.strip().splitlines() or ["failed"])[-1])
        state["last"] = datetime.now(ZoneInfo("America/New_York")).strftime("%-I:%M:%S %p ET")
        state["error"] = "; ".join(errs) or None
    except Exception as e:
        state["error"] = str(e)
    finally:
        lock.release()
    return state


seen_alerts = set()


def notify(msg):
    """Mac notification for new in-game alerts."""
    safe = msg.replace('"', "'")
    subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "NBA Edge Board" sound name "Ping"'], capture_output=True)


def live_alerts():
    """Returns True if any game is live; pings once per new alert."""
    games = []
    for sport in ("nba", "nfl"):
        try:
            games += json.load(open(os.path.join(ROOT, sport, "data.json"))).get("games", [])
        except Exception:
            pass
    any_live = False
    for g in games:
        lv = g.get("live")
        if g.get("state") != "in" or not lv:
            continue
        any_live = True
        tag = f"{g['away']['abbr']} @ {g['home']['abbr']}"
        alerts = []
        if lv.get("pace_flag"):
            alerts.append((f"{g['id']}-pace-{lv['pace_flag']}-{lv['period']}", f"{tag}: {lv['pace_note']}"))
        for t in lv.get("foul_trouble") or []:
            alerts.append((f"{g['id']}-foul-{t['name']}-{t['fouls']}", f"{tag}: {t['name']} {t['level']} ({t['fouls']} fouls, Q{lv['period']})"))
        for key, msg in alerts:
            if key not in seen_alerts:
                seen_alerts.add(key)
                notify(msg)
    return any_live


def loop():
    while True:
        rebuild()
        live_now = live_alerts()
        h = datetime.now(ZoneInfo("America/New_York")).hour
        time.sleep(45 if live_now else 120 if (h >= 12 or h < 2) else 900)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html", "/dashboard.html"):
            self.path = "/nba/dashboard.html"
        elif self.path in ("/nfl", "/nfl/"):
            self.path = "/nfl/dashboard.html"
        elif self.path in ("/nba", "/nba/"):
            self.path = "/nba/dashboard.html"
        super().do_GET()

    def do_POST(self):
        if not self.path.endswith("/refresh"):
            return self.send_error(404)
        body = json.dumps(rebuild(force=True)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    print("Boards on http://localhost:8765  (NBA: /nba  ·  NFL: /nfl)")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
