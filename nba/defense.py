"""Defensive breakdown: team defensive rating + projected 'who guards who'.

Data: Basketball-Reference (team DRtg, player DBPM / minutes), cached once a day,
mapped onto ESPN's current rosters so offseason moves are handled.
Matchups are projections (position fit + best defender on best scorer), not tracking data.
"""
import html, json, os, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
POS = {"PG": 1, "G": 1.5, "SG": 2, "GF": 2.5, "SF": 3, "F": 3.5, "PF": 4, "FC": 4.5, "C": 5}
# Basketball-Reference team names -> ESPN abbreviations
BBREF = {"Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
         "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
         "Detroit Pistons": "DET", "Golden State Warriors": "GS", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
         "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
         "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NO", "New York Knicks": "NY",
         "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
         "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SA", "Toronto Raptors": "TOR",
         "Utah Jazz": "UTAH", "Washington Wizards": "WSH"}


def norm(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", n))


def fetch(url, name, max_age=6 * 3600):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if os.environ.get("NBA_FORCE"):
        max_age = min(max_age, 1800)  # Refresh button: re-pull, but at most every 30 min (site rate limits)
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > max_age:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            open(path, "wb").write(r.read())
        time.sleep(3)  # be polite to Basketball-Reference
    return open(path, encoding="utf-8", errors="ignore").read()


def rows(page, table_id):
    page = page.replace("<!--", "").replace("-->", "")  # bbref hides tables in comments
    m = re.search(rf'<table[^>]*id="{table_id}".*?</table>', page, re.S)
    if not m:
        return []
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S):
        cells = dict((k, html.unescape(re.sub("<[^>]+>", "", v)).strip())
                     for k, v in re.findall(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', tr, re.S))
        if cells:
            out.append(cells)
    return out


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def team_ratings(year):
    page = fetch(f"https://www.basketball-reference.com/leagues/NBA_{year}.html", f"lg_{year}.html")
    teams = {}
    for r in rows(page, "advanced-team"):
        name = r.get("team", "").rstrip("*")
        if name in BBREF and num(r.get("def_rtg")):
            teams[BBREF[name]] = {"drtg": num(r["def_rtg"]), "ortg": num(r.get("off_rtg")), "net": num(r.get("net_rtg"))}
    for r in rows(page, "per_game-opponent"):
        name = r.get("team", "").rstrip("*")
        if BBREF.get(name) in teams:
            teams[BBREF[name]].update(opp3_pct=num(r.get("opp_fg3_pct")), opp3a=num(r.get("opp_fg3a")))
    for i, t in enumerate(sorted([t for t in teams if teams[t].get("opp3_pct")], key=lambda t: teams[t]["opp3_pct"]), 1):
        teams[t]["opp3_rank"] = i
    ranked = sorted(teams, key=lambda t: teams[t]["drtg"])
    for i, t in enumerate(ranked, 1):
        teams[t]["drtg_rank"] = i
    return teams


def player_defense(year):
    page = fetch(f"https://www.basketball-reference.com/leagues/NBA_{year}_advanced.html", f"adv_{year}.html")
    out = {}
    for r in rows(page, "advanced"):
        name = r.get("name_display") or r.get("player")
        mp = num(r.get("mp"))
        if not name or not mp:
            continue
        key = norm(name)
        if key in out and out[key]["mp"] >= mp:  # traded players: keep combined (largest) row
            continue
        out[key] = {"mp": mp, "dbpm": num(r.get("dbpm")) or 0.0, "dws": num(r.get("dws")) or 0.0,
                    "pos": r.get("pos", ""), "g": num(r.get("games")) or 0}
    return out


def rosters():
    def one(t):
        try:
            j = json.load(urllib.request.urlopen(f"{ESPN}/teams/{t['id']}/roster", timeout=20))
        except Exception:
            return t["abbreviation"], []
        return t["abbreviation"], [{"name": a["displayName"], "pos": a.get("position", {}).get("abbreviation", "")}
                                   for a in j.get("athletes", [])]
    teams = json.load(urllib.request.urlopen(f"{ESPN}/teams", timeout=20))["sports"][0]["leagues"][0]["teams"]
    with ThreadPoolExecutor(10) as ex:
        return dict(ex.map(one, [t["team"] for t in teams]))


def load(season_year, injuries):
    """season_year = ESPN season year (2027 for 2026-27). Falls back to last season early on."""
    yr, label = season_year, f"{season_year-1}-{str(season_year)[2:]}"
    try:
        teams, players = team_ratings(yr), player_defense(yr)
        if len(teams) < 30 or max((p["g"] for p in players.values()), default=0) < 5:
            raise ValueError
    except Exception:
        yr -= 1
        label = f"{yr-1}-{str(yr)[2:]} (last season)"
        teams, players = team_ratings(yr), player_defense(yr)
    rost = rosters()
    lineups = {}
    for abbr, plist in rost.items():
        rotation = []
        for p in plist:
            st = (injuries.get(p["name"]) or {}).get("status", "Active")
            if st == "Out":
                continue
            d = players.get(norm(p["name"]), {"mp": 0, "dbpm": -1.0, "dws": 0, "pos": p["pos"]})
            rotation.append({"name": p["name"], "pos": p["pos"] or d["pos"], "dbpm": d["dbpm"], "mp": d["mp"]})
        rotation.sort(key=lambda p: -p["mp"])
        lineups[abbr] = rotation[:8]
    return {"teams": teams, "lineups": lineups, "label": label, "roster": rost}


def grade(dbpm):
    return "Elite" if dbpm >= 2 else "Good" if dbpm >= 0.8 else "Average" if dbpm >= -0.5 else "Weak"


def matchups(defense, def_abbr, off_abbr, off_stars):
    """Who on def_abbr guards whom on off_abbr. Best defenders go to the best scorers."""
    D = defense["lineups"].get(def_abbr, [])[:5]
    O = defense["lineups"].get(off_abbr, [])[:5]
    star_rank = {norm(s["name"]): i for i, s in enumerate(off_stars)}
    O = sorted(O, key=lambda p: star_rank.get(norm(p["name"]), 10 + O.index(p)))
    used, out = set(), []
    for o in O:
        best = None
        for d in D:
            if d["name"] in used:
                continue
            gap = abs(POS.get(d["pos"], 3) - POS.get(o["pos"], 3))
            score = d["dbpm"] - gap * 1.2
            if best is None or score > best[0]:
                best = (score, d)
        if best:
            d = best[1]
            used.add(d["name"])
            out.append({"defender": d["name"], "def_pos": d["pos"], "dbpm": round(d["dbpm"], 1),
                        "grade": grade(d["dbpm"]), "guarding": o["name"], "off_pos": o["pos"]})
    t = defense["teams"].get(def_abbr, {})
    # Perimeter stoppers: best defensive guards/wings in the rotation (no free per-player 3PT-defense tracking data)
    perim = sorted([p for p in defense["lineups"].get(def_abbr, []) if POS.get(p["pos"], 3) <= 3.5 and p["mp"] > 300],
                   key=lambda p: -p["dbpm"])[:2]
    return {"drtg": t.get("drtg"), "drtg_rank": t.get("drtg_rank"), "matchups": out,
            "opp3_pct": t.get("opp3_pct"), "opp3a": t.get("opp3a"), "opp3_rank": t.get("opp3_rank"),
            "perimeter": [{"name": p["name"], "pos": p["pos"], "dbpm": round(p["dbpm"], 1)} for p in perim]}
