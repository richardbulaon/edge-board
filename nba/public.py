"""Public bettors: who the public is on, whether the line followed them, and a running
fade-the-public record that grades itself after each game.

The books (Logic of Sports Betting, Sharp Sports Betting) say "fade the public" is mostly a myth
in big markets. This tracker tests it on real games instead of trusting it.
"""
import json, os
from datetime import datetime, timedelta, timezone

HEAVY = 60       # "public side" = 60%+ of bets
FADE = 70        # tracked fade spots = 70%+ of bets on one side
SIDES = {"spread": ("away", "home"), "moneyline": ("away", "home"), "total": ("over", "under")}


def public_view(game):
    """Per market: public side, % of bets/money, and whether the line moved with or against them."""
    sp = game.get("splits") or {}
    m = sp.get("market") or {}
    names = {"away": game["away"]["short"], "home": game["home"]["short"], "over": "Over", "under": "Under"}
    out = []
    for k, (a, b) in SIDES.items():
        x = sp.get(k) or {}
        if x.get(a, {}).get("bets") is None:
            continue
        side = a if x[a]["bets"] >= x.get(b, {}).get("bets", 0) else b
        pct, money = x[side]["bets"], x[side].get("money")
        mk = m.get(k) or {}
        toward = None
        if k == "spread" and mk.get("move"):
            toward = "home" if mk["move"] > 0 else "away"      # away line went up = market moved to home
        elif k == "total" and mk.get("move"):
            toward = "over" if mk["move"] > 0 else "under"
        elif k == "moneyline" and abs(mk.get("move_pct") or 0) >= 1.5:
            toward = "away" if mk["move_pct"] > 0 else "home"
        if toward is None:
            verdict = "no move"
        else:
            verdict = "with public" if toward == side else "against public"
        if toward is None:
            move_txt = "line hasn't moved since open"
        elif k == "moneyline":
            move_txt = f"moved {abs(mk['move_pct']):.1f}% toward {names[toward]}"
        else:
            move_txt = f"moved {abs(mk['move']):g} pt{'s' if abs(mk['move']) != 1 else ''} toward {names[toward]}"
        out.append({"market": k, "side": side, "name": names[side], "bets": pct, "money": money,
                    "heavy": pct >= HEAVY, "fade_spot": pct >= FADE and k in ("spread", "total"),
                    "move": move_txt, "verdict": verdict,
                    "line": (mk.get("line") if k != "spread" else (mk.get("line") if side == "away" else (-mk["line"] if mk.get("line") is not None else None)))})
    return out


def _load(path):
    try:
        return json.load(open(path))
    except Exception:
        return {"spots": {}}


def update_tracker(path, games, fetch_final):
    """Record fade spots until kickoff (the last pre-game snapshot = closing split/line), grade after the game.

    fetch_final(event_id) -> (away_pts, home_pts) or None if not final.
    """
    t = _load(path)
    spots = t["spots"]
    now = datetime.now(timezone.utc)
    for g in games:
        if g.get("state") != "pre":
            continue
        for p in g.get("public") or []:
            if not p["fade_spot"] or p["line"] is None:
                continue
            key = f"{g['id']}-{p['market']}"
            spots[key] = {"id": g["id"], "market": p["market"], "public_side": p["side"], "public_name": p["name"],
                          "pct": p["bets"], "money": p["money"], "line": p["line"], "start": g["start_utc"],
                          "matchup": f"{g['away']['abbr']} @ {g['home']['abbr']}", "date": g.get("date_key"),
                          "result": None}
    # grade anything that started 3+ hours ago
    for key, s in spots.items():
        if s["result"] is not None:
            continue
        try:
            start = datetime.strptime(s["start"].replace("Z", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if now - start < timedelta(hours=3):
            continue
        fin = fetch_final(s["id"])
        if not fin:
            continue
        away, home = fin
        if s["market"] == "spread":
            mine, theirs = (away, home) if s["public_side"] == "away" else (home, away)
            res = mine + s["line"] - theirs
        else:
            res = (away + home - s["line"]) * (1 if s["public_side"] == "over" else -1)
        s["final"] = f"{away}-{home}"
        s["result"] = "push" if res == 0 else ("public" if res > 0 else "fade")
    json.dump(t, open(path, "w"), indent=1)
    return summarize(t)


def summarize(t):
    done = [s for s in t["spots"].values() if s["result"] in ("public", "fade")]
    def rec(rows):
        w = sum(r["result"] == "fade" for r in rows)
        l = len(rows) - w
        units = w * (100 / 110) - l          # fading at -110
        return {"w": w, "l": l, "n": len(rows), "pct": round(w / len(rows) * 100, 1) if rows else None,
                "units": round(units, 2)}
    return {"all": rec(done), "80": rec([s for s in done if s["pct"] >= 80]),
            "spread": rec([s for s in done if s["market"] == "spread"]),
            "total": rec([s for s in done if s["market"] == "total"]),
            "pending": sum(s["result"] is None for s in t["spots"].values()),
            "recent": sorted([s for s in t["spots"].values() if s["result"]], key=lambda s: s["start"], reverse=True)[:10],
            "since": min((s["date"] for s in t["spots"].values() if s.get("date")), default=None)}
