#!/usr/bin/env python3
"""NFL edge board: spreads, market/fair price, key numbers, teasers, weather, rest/bye,
travel, last-game flags, QB/skill stars + injuries, offense/defense ranks, coaches, live projection.

Usage:  python3 nfl.py      -> writes dashboard.html + data.json next to this file
"""
import json, math, os, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "nba"))
import market as mkt
import public as pub                                          # shared market math
from nba import get, miles, parse_dt, score                   # shared helpers

ET = ZoneInfo("America/New_York")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
NFL_SD = 13.5
KEY_NUMBERS = (3, 7, 10, 6, 14)
NATIONAL = ("ESPN", "ABC", "NBC", "Prime Video", "Netflix", "NFL Net", "YouTube")

# Stadium lat, lon, UTC offset (standard time)
STADIUMS = {
    "ARI": (33.528, -112.263, -7), "ATL": (33.755, -84.401, -5), "BAL": (39.278, -76.623, -5), "BUF": (42.774, -78.787, -5),
    "CAR": (35.226, -80.853, -5), "CHI": (41.862, -87.617, -6), "CIN": (39.095, -84.516, -5), "CLE": (41.506, -81.700, -5),
    "DAL": (32.748, -97.093, -6), "DEN": (39.744, -105.020, -7), "DET": (42.340, -83.046, -5), "GB": (44.501, -88.062, -6),
    "HOU": (29.685, -95.411, -6), "IND": (39.760, -86.164, -5), "JAX": (30.324, -81.637, -5), "KC": (39.049, -94.484, -6),
    "LV": (36.091, -115.184, -8), "LAC": (33.953, -118.339, -8), "LAR": (33.953, -118.339, -8), "MIA": (25.958, -80.239, -5),
    "MIN": (44.974, -93.258, -6), "NE": (42.091, -71.264, -5), "NO": (29.951, -90.081, -6), "NYG": (40.813, -74.074, -5),
    "NYJ": (40.813, -74.074, -5), "PHI": (39.901, -75.168, -5), "PIT": (40.447, -80.016, -5), "SF": (37.403, -121.970, -8),
    "SEA": (47.595, -122.332, -8), "TB": (27.976, -82.503, -5), "TEN": (36.166, -86.771, -6), "WSH": (38.908, -76.864, -5),
}
# International / neutral venues by city
NEUTRAL = {"Saint-Denis": (48.924, 2.360, 1), "Paris": (48.924, 2.360, 1), "London": (51.556, -0.280, 0), "Munich": (48.219, 11.625, 1), "Berlin": (52.515, 13.239, 1), "Madrid": (40.453, -3.688, 1),
           "Dublin": (53.336, -6.229, 0), "Sao Paulo": (-23.545, -46.474, -3), "Mexico City": (19.303, -99.150, -6), "Melbourne": (-37.820, 144.983, 10)}


# ---------- history ----------
_sched = {}


def all_games(team_id, season):
    key = (team_id, season)
    if key not in _sched:
        out = []
        for st in (2, 3):
            try:
                out += get(f"{ESPN}/teams/{team_id}/schedule?season={season}&seasontype={st}").get("events", [])
            except Exception:
                continue
        out.sort(key=lambda e: e["date"])
        _sched[key] = out
    return _sched[key]


def completed_games(team_id, season):
    return [e for e in all_games(team_id, season) if e["competitions"][0].get("status", {}).get("type", {}).get("completed")]


def venue_point(comp):
    """Coordinates of where a game is played (handles London etc.)."""
    city = (comp.get("venue") or {}).get("address", {}).get("city", "")
    for k, v in NEUTRAL.items():
        if k.lower() in city.lower():
            return v, city
    home = next(x for x in comp["competitors"] if x["homeAway"] == "home")["team"]["abbreviation"]
    return STADIUMS.get(home), home


def game_row(e, team_id):
    c = e["competitions"][0]
    me = next(x for x in c["competitors"] if str(x["id"]) == str(team_id))
    opp = next(x for x in c["competitors"] if str(x["id"]) != str(team_id))
    a, b = int(score(me)), int(score(opp))
    note = (c.get("notes") or [{}])[0].get("headline", "")
    return {"date": parse_dt(e["date"]).astimezone(ET).strftime("%b %d, %Y"), "result": "W" if a > b else "L" if a < b else "T",
            "score": f"{a}-{b}", "margin": a - b, "where": "vs" if me["homeAway"] == "home" else "@",
            "opp": opp["team"]["abbreviation"], "playoff": "P" if e.get("seasonType", {}).get("type") == 3 else "", "note": note}


def was_favorite(event_id, team_id):
    try:
        pc = get(f"{ESPN}/summary?event={event_id}").get("pickcenter") or []
    except Exception:
        return None, None
    for p in pc:
        for side in ("homeTeamOdds", "awayTeamOdds"):
            o = p.get(side) or {}
            if str(o.get("teamId")) == str(team_id):
                return bool(o.get("favorite")), p.get("details")
    return None, None


def situation(team_id, game_dt, here, season, week):
    prior = [e for e in completed_games(team_id, season) + completed_games(team_id, season - 1) if parse_dt(e["date"]) < game_dt]
    prior.sort(key=lambda e: e["date"])
    out = {"last5": [game_row(e, team_id) for e in prior[-5:]][::-1]}
    if not prior:
        return out
    lg = prior[-1]
    r = game_row(lg, team_id)
    # rest/travel use the most recent game on the schedule, even if it hasn't finished yet (e.g. Monday night)
    sched = [e for e in all_games(team_id, season) if parse_dt(e["date"]) < game_dt]
    prev = sched[-1] if sched else lg
    last_dt = parse_dt(prev["date"])
    days = (game_dt.astimezone(ET).date() - last_dt.astimezone(ET).date()).days
    fav, line = was_favorite(lg["id"], team_id)
    out.update({"last_result": f"{r['result']} {r['score']} {r['where']} {r['opp']}", "last_date": r["date"][:6],
                "days_rest": days, "lost": r["result"] == "L", "margin": abs(r["margin"]),
                "blowout_loss": r["result"] == "L" and abs(r["margin"]) > 10,
                "upset_loss": bool(r["result"] == "L" and fav), "last_line": line,
                "season_opener": days > 60})
    out["rest_tag"] = ("Short week" if days <= 5 else "Off Monday game" if days == 6 else "Off bye" if days >= 12 else "Mini-bye" if days >= 9 else None) if days <= 60 else None
    pt, _ = venue_point(prev["competitions"][0])
    if days <= 30 and pt and here:
        out["travel_miles"] = miles(pt, here)
        out["tz_change"] = here[2] - pt[2]
    return out


def head_to_head(team_id, opp_id, before, season):
    found = []
    for yr in range(season, season - 6, -1):
        found += [e for e in completed_games(team_id, yr)
                  if str(opp_id) in {str(x["id"]) for x in e["competitions"][0]["competitors"]} and parse_dt(e["date"]) < before]
        if len(found) >= 5:
            break
    found.sort(key=lambda e: e["date"])
    return [game_row(e, team_id) for e in found[-5:]][::-1]


# ---------- players, injuries, team ranks ----------
def load_players(season):
    """QB, top rusher, top receivers per team (ESPN season stats)."""
    def fetch(cat, sort):
        url = ("https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/statistics/byathlete"
               f"?region=us&lang=en&isqualified=false&limit=200&category=offense%3A{cat}&sort={sort}%3Adesc&season={season}&seasontype=2")
        j = get(url)
        names = {c["name"]: c["names"] for c in j["categories"]}
        rows = []
        for a in j["athletes"]:
            v = {c["name"]: dict(zip(names[c["name"]], c["totals"])) for c in a["categories"]}
            rows.append((a["athlete"]["displayName"], a["athlete"].get("teamShortName"), a["athlete"].get("position", {}).get("abbreviation"), v))
        return rows
    num = lambda x: float(str(x).replace(",", "") or 0) if x not in ("-", None, "") else 0.0
    out = {}
    try:
        for n, t, pos, v in fetch("passing", "passing.passingYards"):
            if pos == "QB" and t and not any(p["role"] == "QB" for p in out.get(t, [])):
                p = v["passing"]
                out.setdefault(t, []).append({"name": n, "role": "QB", "line": f"{p['passingYardsPerGame']} yds/g · {p['passingTouchdowns']} TD · {p['interceptions']} INT · QBR {p.get('QBR','-')}"})
        for n, t, pos, v in fetch("rushing", "rushing.rushingYards"):
            if t and not any(p["role"] == "RB" for p in out.get(t, [])) and pos in ("RB", "FB", "QB") and pos != "QB":
                p = v["rushing"]
                out.setdefault(t, []).append({"name": n, "role": "RB", "line": f"{p['rushingYardsPerGame']} yds/g · {p['yardsPerRushAttempt']} ypc · {p['rushingTouchdowns']} TD"})
        for n, t, pos, v in fetch("receiving", "receiving.receivingYards"):
            if t and sum(p["role"] in ("WR", "TE") for p in out.get(t, [])) < 2 and pos in ("WR", "TE"):
                p = v["receiving"]
                out.setdefault(t, []).append({"name": n, "role": pos, "line": f"{p['receivingYardsPerGame']} yds/g · {p['receptions']} rec · {p['receivingTouchdowns']} TD"})
    except Exception as ex:
        print("player stats unavailable:", ex, file=sys.stderr)
    return out


def load_injuries():
    out = {}
    try:
        for team in get(f"{ESPN}/injuries").get("injuries", []):
            for i in team.get("injuries", []):
                a = i.get("athlete", {})
                out[a.get("displayName", "")] = {"status": i.get("status"), "note": i.get("shortComment", "")}
    except Exception:
        pass
    return out


def team_ranks(league, season):
    """Points and yards for/against per game, ranked 1-32 (1 = best)."""
    def one(t):
        tid, ab = t["team"]["id"], t["team"]["abbreviation"]
        games = [e for e in completed_games(tid, season) if e.get("seasonType", {}).get("type", 2) == 2] or completed_games(tid, season)
        pf = pa = 0
        for e in games:
            c = e["competitions"][0]
            me = next(x for x in c["competitors"] if str(x["id"]) == str(tid))
            op = next(x for x in c["competitors"] if str(x["id"]) != str(tid))
            pf += score(me); pa += score(op)
        n = max(1, len(games))
        row = {"g": len(games), "ppg": round(pf / n, 1), "papg": round(pa / n, 1)}
        try:
            r = get(f"{ESPN}/teams/{tid}/statistics?season={season}")["results"]
            def stat(block, cat, name):
                cats = block["categories"] if isinstance(block, dict) else block
                for c in cats:
                    if c["name"] == cat:
                        for s in c["stats"]:
                            if s["name"] == name:
                                return s.get("value")
            row["pass_y"] = stat(r["stats"], "passing", "netPassingYardsPerGame")
            row["rush_y"] = stat(r["stats"], "rushing", "rushingYardsPerGame")
            row["pass_y_allowed"] = stat(r["opponent"], "passing", "netPassingYardsPerGame")
            row["rush_y_allowed"] = stat(r["opponent"], "rushing", "rushingYardsPerGame")
            row["sacks"] = stat(r["stats"], "defensive", "sacks")
            row["takeaways"] = stat(r["stats"], "miscellaneous", "totalTakeaways")
        except Exception:
            pass
        return ab, row
    with ThreadPoolExecutor(8) as ex:
        rows = dict(ex.map(one, league))
    for key, best_low in (("ppg", False), ("papg", True), ("pass_y", False), ("rush_y", False), ("pass_y_allowed", True), ("rush_y_allowed", True)):
        have = [t for t in rows if rows[t].get(key) is not None]
        for i, t in enumerate(sorted(have, key=lambda t: rows[t][key] if best_low else -rows[t][key]), 1):
            rows[t][key + "_rank"] = i
    return rows


# ---------- market ----------
def load_market(weeks, stype):
    out = {}
    ids = ",".join(str(i) for i in [mkt.CONSENSUS, mkt.OPEN, *mkt.BOOKS])
    st = {2: "reg", 3: "post", 1: "pre"}.get(stype, "reg")
    for wk in weeks:
        try:
            j = get(f"https://api.actionnetwork.com/web/v2/scoreboard/nfl?bookIds={ids}&week={wk}&seasonType={st}&periods=event,live")
        except Exception as ex:
            print("market unavailable:", ex, file=sys.stderr)
            continue
        for g in j.get("games", []):
            teams = {t["id"]: t for t in g.get("teams", [])}
            away, home = teams.get(g["away_team_id"]), teams.get(g["home_team_id"])
            if not away or not home:
                continue
            ev = (g.get("markets", {}).get("15") or {}).get("event", {})
            row = {"num_bets": g.get("num_bets")}
            for market in ("spread", "moneyline", "total"):
                for o in ev.get(market, []):
                    bi = o.get("bet_info") or {}
                    row.setdefault(market, {})[o["side"]] = {"line": o.get("value"), "odds": o.get("odds"),
                                                             "bets": (bi.get("tickets") or {}).get("percent"), "money": (bi.get("money") or {}).get("percent")}
            raw = {}
            for bid, mk in g.get("markets", {}).items():
                for market, outs in (mk.get("event") or {}).items():
                    for o in outs:
                        raw.setdefault(market, {}).setdefault(int(bid), {})[o["side"]] = {"line": o.get("value"), "odds": o.get("odds")}
            row["market"] = mkt.analyze(raw, row, sd=NFL_SD)
            row["market"].pop("consistency", None)  # NFL margins cluster on 3/7, so the smooth model misleads
            lt = [o.get("value") for mk in g.get("markets", {}).values() for o in (mk.get("live") or {}).get("total", []) if o.get("side") == "over"]
            row["live_total"] = lt[0] if lt else None
            out[(away["full_name"].split()[-1], home["full_name"].split()[-1])] = row
    return out


def key_number_notes(m):
    """Wong: key numbers 3 and 7 matter; teaser legs that cross both (fav -7.5..-8.5, dog +1.5..+2.5)."""
    notes, teaser = [], []
    sp = (m or {}).get("spread")
    if not sp or sp.get("line") is None:
        return notes, teaser
    line = sp["line"]  # away perspective
    a = abs(line)
    for k in (3, 7):
        if a in (k - 0.5, k + 0.5):
            notes.append(f"Spread of {a:g} sits right next to key number {k}: about 1 in {7 if k == 3 else 11} NFL games ends on a {k}-point margin, so half a point here is worth extra.")
    for side, v in (("away", line), ("home", -line)):
        a = abs(v)
        if v < 0 and 7.5 <= a <= 8.5:
            teaser.append({"side": side, "from": v, "to": v + 6})
        if v > 0 and 1.5 <= a <= 2.5:
            teaser.append({"side": side, "from": v, "to": v + 6})
    rng = sp.get("line_range")
    if rng and rng[0] != rng[1]:
        lo, hi = rng
        for k in (3, 7):
            if lo < k < hi or lo < -k < hi or (abs(lo) < k < abs(hi)) or (abs(hi) < k < abs(lo)):
                notes.append(f"Books split around {k}: lines range {lo:+g} to {hi:+g}. Shop for the side of the key number you want.")
    return notes, teaser


def weather_note(e, comp):
    if (comp.get("venue") or {}).get("indoor"):
        return {"indoor": True, "text": "Indoors"}
    w = e.get("weather") or comp.get("weather")
    if not w:
        return {"indoor": False, "text": "Outdoors, no forecast yet"}
    t = w.get("temperature")
    txt = f"{w.get('displayValue','')}, {t}°F" if t is not None else w.get("displayValue", "")
    flag = None
    low = (w.get("displayValue") or "").lower()
    if any(k in low for k in ("rain", "snow", "storm", "shower", "wind")):
        flag = "Weather could lower scoring and passing"
    if t is not None and t <= 25:
        flag = "Very cold: kicking and passing can suffer"
    return {"indoor": False, "text": txt, "flag": flag}


def live_projection(e, pre_total, live_total):
    """NFL in-game: blend live scoring rate with the pregame total (60-minute game)."""
    st = e["status"]
    per, clk = st.get("period", 1), st.get("displayClock", "15:00")
    m, s = (clk.split(":") + ["0"])[:2] if ":" in clk else (clk, "0")
    left = float(m) + float(s) / 60
    el = (per - 1) * 15 + (15 - left) if per <= 4 else 60 + (10 - left)
    if el <= 0 or not pre_total:
        return None
    c = e["competitions"][0]
    pts = sum(score(x) for x in c["competitors"])
    rem = max(0.0, 60 - el)
    w = min(1, el / 60)
    rate = w * (pts / el) + (1 - w) * (pre_total / 60)
    proj = pts + rate * rem
    speed = (pts / el) / (pre_total / 60) - 1
    line = live_total or pre_total
    out = {"period": per, "clock": clk, "elapsed": round(el, 1), "points": int(pts), "projected": round(proj, 1),
           "speed_pct": round(speed * 100, 1), "pregame_total": pre_total, "live_total": live_total, "vs_line": round(proj - line, 1),
           "foul_trouble": []}
    if el >= 10 and abs(speed) >= 0.15:
        out["pace_flag"] = "fast" if speed > 0 else "slow"
        out["pace_note"] = f"Scoring {abs(speed)*100:.0f}% {'faster' if speed > 0 else 'slower'} than the {pre_total} total expected. Projection {proj:.1f} vs line {line}."
    return out


# ---------- main ----------
def build():
    now = datetime.now(ET)
    j = get(f"{ESPN}/scoreboard")
    season, week, stype = j["season"]["year"], j["week"]["number"], j["season"]["type"]
    events = [e for e in j["events"] if e["status"]["type"]["state"] != "post"]
    try:
        events += get(f"{ESPN}/scoreboard?seasontype={stype}&week={week + 1}").get("events", [])
    except Exception:
        pass
    league = get(f"{ESPN}/teams")["sports"][0]["leagues"][0]["teams"]
    dates = sorted({parse_dt(e["date"]).astimezone(ET).strftime("%Y%m%d") for e in events})
    with ThreadPoolExecutor(4) as ex:
        f_players = ex.submit(load_players, season)
        f_inj = ex.submit(load_injuries)
        f_ranks = ex.submit(team_ranks, league, season)
        f_mkt = ex.submit(load_market, [week, week + 1], stype)
    players, injuries, ranks, markets = f_players.result(), f_inj.result(), f_ranks.result(), f_mkt.result()
    coaches = json.load(open(os.path.join(HERE, "coaches.json")))

    def one(e):
        c = e["competitions"][0]
        dt = parse_dt(e["date"])
        home = next(x for x in c["competitors"] if x["homeAway"] == "home")
        away = next(x for x in c["competitors"] if x["homeAway"] == "away")
        here, where = venue_point(c)
        tv = [n for b in c.get("broadcasts", []) for n in b.get("names", [])]
        local = dt.astimezone(ET)
        prime = any(any(n.startswith(k) for k in NATIONAL) for n in tv) or local.hour >= 20 or (local.weekday() in (0, 3))
        o = (c.get("odds") or [{}])[0]
        key = (away["team"]["displayName"].split()[-1], home["team"]["displayName"].split()[-1])
        sp = markets.get(key)
        teams = {}
        for side, t in (("away", away), ("home", home)):
            ab = t["team"]["abbreviation"]
            stars = [{**p, "status": (injuries.get(p["name"]) or {}).get("status", "Active"),
                      "inj_note": (injuries.get(p["name"]) or {}).get("note", "")} for p in players.get(ab, [])]
            teams[side] = {"abbr": ab, "name": t["team"]["displayName"], "short": t["team"]["shortDisplayName"],
                           "logo": t["team"].get("logo"), "record": (t.get("records") or [{}])[0].get("summary", ""),
                           "score": t.get("score"), "situation": situation(t["id"], dt, here, season, week),
                           "stars": stars, "ranks": ranks.get(ab, {}), "coach": coaches.get(ab, {})}
        notes, teaser = key_number_notes((sp or {}).get("market"))
        live = None
        if e["status"]["type"]["state"] == "in":
            pre = ((sp or {}).get("market", {}).get("total") or {}).get("line") or o.get("overUnder")
            live = live_projection(e, pre, (sp or {}).get("live_total"))
        return {"id": e["id"], "start_utc": e["date"], "start_et": local.strftime("%a %b %d, %-I:%M %p ET"),
                "date_key": local.strftime("%Y-%m-%d"), "status": e["status"]["type"]["shortDetail"], "state": e["status"]["type"]["state"],
                "week": e.get("week", {}).get("number"), "tv": tv, "national_tv": tv, "prime_time": prime,
                "venue": (c.get("venue") or {}).get("fullName", ""), "neutral": c.get("neutralSite", False), "where": where,
                "weather": weather_note(e, c), "spread": o.get("details"), "total": o.get("overUnder"),
                "odds_source": o.get("provider", {}).get("name", "ESPN"), "splits": sp, "key_notes": notes, "teasers": teaser,
                "h2h": head_to_head(home["id"], away["id"], dt, season), "live": live, "away": teams["away"], "home": teams["home"]}

    with ThreadPoolExecutor(6) as ex:
        games = list(ex.map(one, events))
    for g in games:
        g["best_bet"] = mkt.best_bet(g) if g["state"] != "post" else None
        g["lean"] = mkt.lean(g) if g["state"] != "post" and not g["best_bet"] else None
        g["public"] = pub.public_view(g)

    def fetch_final(eid):
        try:
            comp = get(f"{ESPN}/summary?event={eid}")["header"]["competitions"][0]
        except Exception:
            return None
        if not comp.get("status", {}).get("type", {}).get("completed"):
            return None
        sc = {c["homeAway"]: int(float(c.get("score") or 0)) for c in comp["competitors"]}
        return sc.get("away", 0), sc.get("home", 0)
    tracker = pub.update_tracker(os.path.join(HERE, "fade_tracker.json"), games, fetch_final)
    games.sort(key=lambda g: g["start_utc"])
    return {"generated": now.isoformat(), "generated_label": now.strftime("%a %b %d, %-I:%M %p ET"),
            "season": season, "week": week, "games": games, "public_tracker": tracker}


if __name__ == "__main__":
    data = build()
    json.dump(data, open(os.path.join(HERE, "data.json"), "w"), indent=1)
    tpl = open(os.path.join(HERE, "template.html")).read()
    open(os.path.join(HERE, "dashboard.html"), "w").write(tpl.replace("/*DATA*/null", json.dumps(data)))
    print(f"{len(data['games'])} games written · {data['generated_label']}")
