#!/usr/bin/env python3
"""NBA game edge sheet: spreads, rest, travel, last-game flags, stars, prime time.

Usage:  python3 nba.py [days]        -> writes dashboard.html + data.json next to this file
Odds come from The Odds API if ~/.odds_api_key exists (ODDS_API_KEY=...), else ESPN/DraftKings.
"""
import defense as dfn
import market as mkt
import public as pub
import live as lv
import json, math, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
HERE = os.path.dirname(os.path.abspath(__file__))

# Home arena lat, lon, UTC offset (standard time)
ARENAS = {
    "ATL": (33.757, -84.396, -5), "BOS": (42.366, -71.062, -5), "BKN": (40.683, -73.975, -5),
    "CHA": (35.225, -80.839, -5), "CHI": (41.881, -87.674, -6), "CLE": (41.497, -81.688, -5),
    "DAL": (32.790, -96.810, -6), "DEN": (39.749, -105.008, -7), "DET": (42.341, -83.055, -5),
    "GS": (37.768, -122.388, -8), "HOU": (29.751, -95.362, -6), "IND": (39.764, -86.156, -5),
    "LAC": (33.945, -118.343, -8), "LAL": (34.043, -118.267, -8), "MEM": (35.138, -90.051, -6),
    "MIA": (25.781, -80.188, -5), "MIL": (43.045, -87.917, -6), "MIN": (44.980, -93.276, -6),
    "NO": (29.949, -90.082, -6), "NY": (40.751, -73.993, -5), "OKC": (35.463, -97.515, -6),
    "ORL": (28.539, -81.384, -5), "PHI": (39.901, -75.172, -5), "PHX": (33.446, -112.071, -7),
    "POR": (45.532, -122.667, -8), "SAC": (38.580, -121.500, -8), "SA": (29.427, -98.438, -6),
    "TOR": (43.643, -79.379, -5), "UTAH": (40.768, -111.901, -7), "WSH": (38.898, -77.021, -5),
}
NATIONAL_TV = ("ESPN", "ABC", "NBC", "Peacock", "Prime Video", "Amazon", "TNT", "NBA TV")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return round(3959 * 2 * math.asin(math.sqrt(h)))


def parse_dt(s):
    return datetime.strptime(s.replace("Z", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)


# ---------- team history ----------
_sched = {}
CURRENT_SEASON = [9999]


def completed_games(team_id, season_year):
    """All finished games for a team in a season (regular + playoffs), oldest first."""
    key = (team_id, season_year)
    disk = os.path.join(HERE, "cache", f"sched_{team_id}_{season_year}.json")
    if key not in _sched and os.path.exists(disk):
        _sched[key] = json.load(open(disk))  # finished seasons never change
    if key not in _sched:
        out = []
        for st in (2, 3):
            try:
                j = get(f"{ESPN}/teams/{team_id}/schedule?season={season_year}&seasontype={st}")
            except Exception:
                continue
            for e in j.get("events", []):
                c = e["competitions"][0]
                if not c.get("status", {}).get("type", {}).get("completed"):
                    continue
                out.append(e)
        out.sort(key=lambda e: e["date"])
        _sched[key] = out
        if season_year < CURRENT_SEASON[0] and out:
            os.makedirs(os.path.dirname(disk), exist_ok=True)
            json.dump(out, open(disk, "w"))
    return _sched[key]


def last_game(team_id, before, season_year):
    for yr in (season_year, season_year - 1):
        prior = [e for e in completed_games(team_id, yr) if parse_dt(e["date"]) < before]
        if prior:
            return prior[-1]
    return None


def score(comp):
    s = comp.get("score")
    if isinstance(s, dict):
        return float(s.get("value") or 0)
    return float(s or 0)


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


def situation(team_id, abbr, game_dt, game_venue_abbr, season_year):
    lg = last_game(team_id, game_dt, season_year)
    if not lg:
        return {"note": "No previous game found"}
    c = lg["competitions"][0]
    me = next(x for x in c["competitors"] if str(x["id"]) == str(team_id))
    opp = next(x for x in c["competitors"] if str(x["id"]) != str(team_id))
    home_of_last = next(x for x in c["competitors"] if x["homeAway"] == "home")["team"]["abbreviation"]
    my_pts, opp_pts = score(me), score(opp)
    lost = my_pts < opp_pts
    margin = int(abs(my_pts - opp_pts))
    last_dt = parse_dt(lg["date"])
    rest = (game_dt.astimezone(ET).date() - last_dt.astimezone(ET).date()).days - 1
    fav, line = was_favorite(lg["id"], team_id)

    out = {
        "last_date": last_dt.astimezone(ET).strftime("%b %d"),
        "last_result": f"{'L' if lost else 'W'} {int(my_pts)}-{int(opp_pts)} {'vs' if me['homeAway']=='home' else '@'} {opp['team']['abbreviation']}",
        "rest_days": rest,
        "lost": lost,
        "margin": margin,
        "blowout_loss": lost and margin > 10,
        "upset_loss": bool(lost and fav),
        "last_line": line,
        "season_opener": rest > 30,
    }
    if rest <= 0:
        out["rest_tag"] = "BACK-TO-BACK"
    if rest <= 7 and home_of_last in ARENAS and game_venue_abbr in ARENAS:
        a, b = ARENAS[home_of_last], ARENAS[game_venue_abbr]
        out["travel_miles"] = miles(a, b)
        out["tz_change"] = b[2] - a[2]
        out["travel_from"] = home_of_last
    return out


def game_row(e, team_id):
    """One finished game from a team's point of view."""
    c = e["competitions"][0]
    me = next(x for x in c["competitors"] if str(x["id"]) == str(team_id))
    opp = next(x for x in c["competitors"] if str(x["id"]) != str(team_id))
    a, b = int(score(me)), int(score(opp))
    note = (c.get("notes") or [{}])[0].get("headline", "")
    return {"date": parse_dt(e["date"]).astimezone(ET).strftime("%b %d, %Y"),
            "result": "W" if a > b else "L", "score": f"{a}-{b}", "margin": a - b,
            "where": "vs" if me["homeAway"] == "home" else "@", "opp": opp["team"]["abbreviation"],
            "playoff": "Playoff" if e.get("seasonType", {}).get("type") == 3 or "Game" in note else "", "note": note}


def recent_games(team_id, before, season_year, n=5):
    games = []
    for yr in (season_year, season_year - 1):
        games = [e for e in completed_games(team_id, yr) if parse_dt(e["date"]) < before] + games
        if len(games) >= n:
            break
    return [game_row(e, team_id) for e in games[-n:]][::-1]


def head_to_head(team_id, opp_id, before, season_year, n=5):
    """Last n meetings, searching back up to 4 seasons."""
    found = []
    for yr in range(season_year, season_year - 4, -1):
        for e in completed_games(team_id, yr):
            ids = {str(x["id"]) for x in e["competitions"][0]["competitors"]}
            if str(opp_id) in ids and parse_dt(e["date"]) < before:
                found.append(e)
        if len(found) >= n:
            break
    found.sort(key=lambda e: e["date"])
    return [game_row(e, team_id) for e in found[-n:]][::-1]


def games_in_last(team_id, game_dt, days, season_year):
    start = game_dt - timedelta(days=days)
    return sum(1 for e in completed_games(team_id, season_year) if start <= parse_dt(e["date"]) < game_dt)


# ---------- stars & injuries ----------
def load_stars(season_year):
    """Top scorers by team. Uses current season once enough games are played, else last season."""
    def fetch(yr):
        url = ("https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete"
               f"?region=us&lang=en&isqualified=false&limit=300&sort=offensive.avgPoints%3Adesc&season={yr}&seasontype=2")
        j = get(url)
        cats = {c["name"]: c["names"] for c in j["categories"]}
        rows = []
        for a in j["athletes"]:
            vals = {c["name"]: dict(zip(cats[c["name"]], c["totals"])) for c in a["categories"]}
            gp = int(float(vals["general"]["gamesPlayed"] or 0))
            rows.append({
                "name": a["athlete"]["displayName"], "id": a["athlete"]["id"],
                "team": a["athlete"].get("teamShortName"), "gp": gp,
                "ppg": float(vals["offensive"]["avgPoints"] or 0),
                "rpg": float(vals["general"]["avgRebounds"] or 0),
                "apg": float(vals["offensive"]["avgAssists"] or 0),
                "tpm": float(vals["offensive"]["avgThreePointFieldGoalsMade"] or 0),
                "tpa": float(vals["offensive"]["avgThreePointFieldGoalsAttempted"] or 0),
                "tp_pct": float(vals["offensive"]["threePointFieldGoalPct"] or 0),
            })
        return rows

    rows = fetch(season_year)
    label = f"{season_year - 1}-{str(season_year)[2:]}"
    if not rows or max(r["gp"] for r in rows) < 5:
        rows = [r for r in fetch(season_year - 1) if r["gp"] >= 10]
        label = f"{season_year - 2}-{str(season_year - 1)[2:]} (last season)"
    return rows, label


def shooters_by_team(rows, roster_team):
    """Best 3-point shooters per team: volume (1.5+ makes/game) and accuracy."""
    by_team = {}
    for r in rows:
        if r["tpm"] < 1.5 or r["gp"] < 10:
            continue
        team = roster_team.get(dfn.norm(r["name"])) if roster_team else r["team"]
        if team:
            by_team.setdefault(team, []).append({k: r[k] for k in ("name", "tpm", "tpa", "tp_pct")})
    for t in by_team:
        by_team[t] = sorted(by_team[t], key=lambda r: -(r["tpm"] * r["tp_pct"]))[:3]
    return by_team


def stars_by_team(rows, roster_team):
    """Top 3 scorers per team, using CURRENT rosters (handles trades/free agency)."""
    by_team = {}
    for r in sorted(rows, key=lambda r: -r["ppg"]):
        r = {**r, "team": roster_team.get(dfn.norm(r["name"]), r["team"] if not roster_team else None)}
        if not r["team"]:
            continue
        by_team.setdefault(r["team"], [])
        if len(by_team[r["team"]]) < 3:
            by_team[r["team"]].append(r)
    return by_team


def load_injuries():
    out = {}
    try:
        j = get(f"{ESPN}/injuries")
    except Exception:
        return out
    for team in j.get("injuries", []):
        for i in team.get("injuries", []):
            ath = i.get("athlete", {})
            name = ath.get("displayName") or f"{ath.get('firstName','')} {ath.get('lastName','')}".strip()
            out[name] = {"status": i.get("status"), "note": i.get("shortComment", "")}
    return out


def load_live_coaches(season_year):
    """Current head coach per ESPN team id, so a firing/hire gets flagged."""
    def one(tid):
        try:
            items = get(f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{season_year}/teams/{tid}/coaches").get("items", [])
            c = get(items[0]["$ref"].replace("http:", "https:"))
            return str(tid), f"{c['firstName']} {c['lastName']}"
        except Exception:
            return str(tid), None
    with ThreadPoolExecutor(10) as ex:
        return dict(ex.map(one, range(1, 31)))


# ---------- public betting splits ----------
def load_splits(dates):
    """% of bets (tickets) and % of money per side, Action Network consensus (book 15)."""
    out = {}
    for d in dates:
        try:
            ids = ",".join(str(i) for i in [mkt.CONSENSUS, mkt.OPEN, *mkt.BOOKS])
            j = get(f"https://api.actionnetwork.com/web/v2/scoreboard/nba?bookIds={ids}&date={d}&periods=event,live")
        except Exception as e:
            print("splits unavailable:", e, file=sys.stderr)
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
                    row.setdefault(market, {})[o["side"]] = {
                        "line": o.get("value"), "odds": o.get("odds"),
                        "bets": (bi.get("tickets") or {}).get("percent"),
                        "money": (bi.get("money") or {}).get("percent")}
            raw = {}
            for bid, mk in g.get("markets", {}).items():
                for market, outs in (mk.get("event") or {}).items():
                    for o in outs:
                        raw.setdefault(market, {}).setdefault(int(bid), {})[o["side"]] = {"line": o.get("value"), "odds": o.get("odds")}
            row["market"] = mkt.analyze(raw, row)
            lt = [o.get("value") for mk in g.get("markets", {}).values() for o in (mk.get("live") or {}).get("total", []) if o.get("side") == "over"]
            row["live_total"] = lt[0] if lt else None
            out[(away["full_name"].split()[-1], home["full_name"].split()[-1])] = row
    return out


# ---------- odds ----------
def load_odds_api():
    path = os.path.expanduser("~/.odds_api_key")
    if not os.path.exists(path):
        return None
    key = open(path).read().strip().split("=", 1)[-1].strip()
    url = ("https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
           f"?apiKey={key}&regions=us&markets=spreads,totals&oddsFormat=american"
           "&bookmakers=draftkings,fanduel,betmgm,caesars")
    try:
        data = get(url)
    except Exception as e:
        print("Odds API error:", e, file=sys.stderr)
        return None
    out = {}
    for g in data:
        books = {}
        for b in g.get("bookmakers", []):
            row = {"updated": b.get("last_update")}
            for m in b.get("markets", []):
                if m["key"] == "spreads":
                    for o in m["outcomes"]:
                        row[o["name"]] = o.get("point")
                if m["key"] == "totals":
                    row["total"] = m["outcomes"][0].get("point")
            books[b["title"]] = row
        out[(g["away_team"], g["home_team"])] = books
    return out


# ---------- main ----------
def build(days=3):
    now = datetime.now(ET)
    dates = [(now + timedelta(days=d)).strftime("%Y%m%d") for d in range(days)]
    events = []
    for d in dates:
        events += get(f"{ESPN}/scoreboard?dates={d}").get("events", [])
    if not events:
        return {"generated": now.isoformat(), "games": []}
    season_year = events[0]["season"]["year"]
    CURRENT_SEASON[0] = season_year

    star_rows, stars_label = load_stars(season_year)
    injuries = load_injuries()
    odds_api = load_odds_api()
    splits = load_splits(dates)
    coaches = json.load(open(os.path.join(HERE, "coaches.json")))
    live_coach = load_live_coaches(season_year)
    try:
        defense = dfn.load(season_year, injuries)
    except Exception as ex:
        print("defense data unavailable:", ex, file=sys.stderr)
        defense = None
    roster_team = {dfn.norm(p["name"]): abbr for abbr, pl in (defense or {}).get("roster", {}).items() for p in pl}
    stars = stars_by_team(star_rows, roster_team)
    shooters = shooters_by_team(star_rows, roster_team)

    def one(e):
        c = e["competitions"][0]
        dt = parse_dt(e["date"])
        home = next(x for x in c["competitors"] if x["homeAway"] == "home")
        away = next(x for x in c["competitors"] if x["homeAway"] == "away")
        venue_abbr = home["team"]["abbreviation"]
        tv = [n for b in c.get("broadcasts", []) for n in b.get("names", [])]
        national = [n for n in tv if any(n.startswith(k) for k in NATIONAL_TV)]
        o = (c.get("odds") or [{}])[0]

        teams = {}
        for side, t in (("away", away), ("home", home)):
            abbr = t["team"]["abbreviation"]
            sit = situation(t["id"], abbr, dt, venue_abbr, season_year)
            sit["games_last_4"] = games_in_last(t["id"], dt, 4, season_year)
            sit["games_last_6"] = games_in_last(t["id"], dt, 6, season_year)
            sit["last5"] = recent_games(t["id"], dt, season_year)
            s = []
            for p in stars.get(abbr, []):
                inj = injuries.get(p["name"])
                s.append({**p, "status": inj["status"] if inj else "Active", "inj_note": inj["note"] if inj else ""})
            rec = (t.get("records") or [{}])[0].get("summary", "")
            coach = dict(coaches.get(abbr, {}))
            live = live_coach.get(str(t["id"]))
            if live and coach.get("name") != live:
                coach = {"name": live, "rating": None, "accolades": [], "good": [], "bad": ["Coach changed — notes not written yet"]}
            teams[side] = {"shooters": shooters.get(abbr, []), "coach": coach, "abbr": abbr, "name": t["team"]["displayName"], "short": t["team"]["shortDisplayName"],
                           "logo": t["team"].get("logo"), "record": rec, "score": t.get("score"),
                           "situation": sit, "stars": s}

        h2h = head_to_head(home["id"], away["id"], dt, season_year)
        if defense:
            for side, opp in (("away", "home"), ("home", "away")):
                teams[side]["defense"] = dfn.matchups(defense, teams[side]["abbr"], teams[opp]["abbr"], teams[opp]["stars"])
        live_info = None
        if e["status"]["type"]["state"] == "in":
            try:
                summ = get(f"{ESPN}/summary?event={e['id']}")
                sp = splits.get((away["team"]["displayName"].split()[-1], home["team"]["displayName"].split()[-1])) or {}
                pre = (sp.get("market", {}).get("total") or {}).get("line") or o.get("overUnder")
                star_names = [p["name"] for side in ("away", "home") for p in teams[side]["stars"]]
                live_info = lv.analyze(summ, pre, sp.get("live_total"), star_names)
            except Exception as ex:
                print("live error", e["id"], ex, file=sys.stderr)
        books = None
        if odds_api:
            books = odds_api.get((away["team"]["displayName"], home["team"]["displayName"]))
        return {
            "id": e["id"], "start_utc": e["date"],
            "start_et": dt.astimezone(ET).strftime("%a %b %d, %-I:%M %p ET"),
            "date_key": dt.astimezone(ET).strftime("%Y-%m-%d"),
            "status": e["status"]["type"]["shortDetail"], "state": e["status"]["type"]["state"],
            "tv": tv, "national_tv": national, "prime_time": bool(national),
            "spread": o.get("details"), "total": o.get("overUnder"),
            "odds_source": o.get("provider", {}).get("name", "ESPN"),
            "books": books, "h2h": h2h, "live": live_info,
            "splits": splits.get((away["team"]["displayName"].split()[-1], home["team"]["displayName"].split()[-1])), "away": teams["away"], "home": teams["home"],
        }

    with ThreadPoolExecutor(8) as ex:
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

    return {"generated": now.isoformat(), "generated_label": now.strftime("%a %b %d, %-I:%M %p ET"),
            "stars_season": stars_label, "defense_season": defense["label"] if defense else None, "odds_api": bool(odds_api), "games": games, "public_tracker": tracker}


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    data = build(days)
    with open(os.path.join(HERE, "data.json"), "w") as f:
        json.dump(data, f, indent=1)
    tpl = open(os.path.join(HERE, "template.html")).read()
    with open(os.path.join(HERE, "dashboard.html"), "w") as f:
        f.write(tpl.replace("/*DATA*/null", json.dumps(data)))
    print(f"{len(data['games'])} games written · {data.get('generated_label')}")
