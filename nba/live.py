"""In-game engine: live pace -> projected total, and star foul trouble.

Everything is computed from ESPN play-by-play, so the same code can replay any past game
at any moment (`python3 live.py <event_id> <period> <clock>`) to test it.

Ideas from the books: compare live pace to what the pregame total expected and look for
overreaction (Art of Live Sports Betting, Logic of Sports Betting: "overs are likely good when
live pace runs 8%+ above the pace implied by the total"); star availability swings games.
"""
import json, sys, urllib.request

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
PACE_FLAG = 0.08      # 8% faster/slower than the pregame total implied
MIN_ELAPSED = 6.0     # don't flag before 6 minutes have been played
FOUL_LIMIT = {1: 2, 2: 3, 3: 4, 4: 5}   # "in trouble" thresholds by quarter (OT: 5)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def clock_secs(s):
    s = str(s or "0")
    if ":" in s:
        m, sec = s.split(":")
        return int(m) * 60 + float(sec)
    return float(s)


def elapsed_min(period, clock):
    """Minutes played so far (12-min quarters, 5-min OTs)."""
    left = clock_secs(clock) / 60
    if period <= 4:
        return (period - 1) * 12 + (12 - left)
    return 48 + (period - 5) * 5 + (5 - left)


def game_length(period):
    return 48 if period <= 4 else 48 + (period - 4) * 5


def players(summary):
    out = {}
    for team in summary.get("boxscore", {}).get("players", []):
        tid = team["team"]["id"]
        for a in team["statistics"][0]["athletes"]:
            out[a["athlete"]["id"]] = {"name": a["athlete"]["displayName"], "team": tid, "starter": a.get("starter", False)}
    return out


def state(summary, upto=None):
    """Replay plays (optionally only up to period/clock) -> score, possessions, fouls."""
    upto_min = elapsed_min(*upto) if upto else None
    comp = summary["header"]["competitions"][0]
    teams = {c["id"]: c["homeAway"] for c in comp["competitors"]}
    s = {side: {"pts": 0, "fga": 0, "fta": 0, "oreb": 0, "to": 0} for side in ("home", "away")}
    fouls, period, clock = {}, 1, "12:00"
    for p in summary.get("plays", []):
        per, clk = p["period"]["number"], p["clock"]["displayValue"]
        if upto_min is not None and elapsed_min(per, clk) > upto_min + 1e-6:
            break
        period, clock = per, clk
        s["home"]["pts"], s["away"]["pts"] = p.get("homeScore", 0), p.get("awayScore", 0)
        side = teams.get((p.get("team") or {}).get("id"))
        typ = p["type"]["text"]
        if side:
            if typ.startswith("Free Throw"):
                s[side]["fta"] += 1
            elif p.get("shootingPlay"):
                s[side]["fga"] += 1
            if typ == "Offensive Rebound":
                s[side]["oreb"] += 1
            if "Turnover" in typ or typ == "Traveling":
                s[side]["to"] += 1
        if "Foul" in typ and "Turnover" not in typ and "Technical" not in typ and p.get("participants"):
            pid = p["participants"][0]["athlete"]["id"]
            fouls[pid] = fouls.get(pid, 0) + 1
    for side in s:
        t = s[side]
        t["poss"] = t["fga"] + 0.44 * t["fta"] - t["oreb"] + t["to"]
    return {"stats": s, "fouls": fouls, "period": period, "clock": clock}


def analyze(summary, pregame_total, live_total=None, stars=None, upto=None):
    st = state(summary, upto)
    per, clk = st["period"], st["clock"]
    el = elapsed_min(per, clk)
    if el <= 0:
        return None
    total_len = max(48, game_length(per))
    rem = max(0.0, total_len - el)
    pts = st["stats"]["home"]["pts"] + st["stats"]["away"]["pts"]
    poss = (st["stats"]["home"]["poss"] + st["stats"]["away"]["poss"]) / 2
    pace = poss / el * 48
    live_ppm = pts / el
    out = {"period": per, "clock": clk, "elapsed": round(el, 1), "points": pts,
           "pace": round(pace, 1), "pts_per48": round(live_ppm * 48, 1)}
    if pregame_total:
        pre_ppm = pregame_total / 48
        w = min(1.0, el / 48)
        rate = w * live_ppm + (1 - w) * pre_ppm              # trust the live rate more as the game goes on
        proj = pts + rate * rem
        speed = live_ppm / pre_ppm - 1                         # scoring rate vs what the total implied
        line = live_total or pregame_total
        out.update({"pregame_total": pregame_total, "live_total": live_total, "projected": round(proj, 1),
                    "vs_line": round(proj - line, 1), "speed_pct": round(speed * 100, 1),
                    "naive_projection": round(live_ppm * total_len, 1)})
        if el >= MIN_ELAPSED and abs(speed) >= PACE_FLAG:
            out["pace_flag"] = "fast" if speed > 0 else "slow"
            out["pace_note"] = (f"Scoring {abs(speed)*100:.0f}% {'faster' if speed > 0 else 'slower'} than the "
                                f"{pregame_total} total expected. Projection {proj:.1f} vs line {line}.")
    # foul trouble
    people = players(summary)
    star_names = {n for n in (stars or [])}
    limit = FOUL_LIMIT.get(per, 5)
    trouble = []
    for pid, n in st["fouls"].items():
        p = people.get(pid)
        if not p:
            continue
        important = p["name"] in star_names or p["starter"]
        if n >= 6:
            level = "FOULED OUT"
        elif n >= limit:
            level = "in foul trouble"
        else:
            continue
        if important:
            trouble.append({"name": p["name"], "fouls": n, "level": level, "star": p["name"] in star_names,
                            "side": next((c["homeAway"] for c in summary["header"]["competitions"][0]["competitors"] if c["id"] == p["team"]), "")})
    trouble.sort(key=lambda t: (-t["star"], -t["fouls"]))
    out["foul_trouble"] = trouble
    return out


if __name__ == "__main__":
    # Replay test: python3 live.py <event_id> <period> <clock> [pregame_total]
    eid, per, clk = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    summ = get(f"{ESPN}/summary?event={eid}")
    total = float(sys.argv[4]) if len(sys.argv) > 4 else (summ.get("pickcenter") or [{}])[0].get("overUnder")
    print(json.dumps(analyze(summ, total, upto=(per, clk)), indent=1))
    final = state(summ)["stats"]
    print("Actual final total:", final["home"]["pts"] + final["away"]["pts"])
