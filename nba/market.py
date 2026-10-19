"""Market math from the betting books, applied to live multi-book lines.

- Break-even % and hold           (Sharp Sports Betting; The Logic of Sports Betting)
- No-vig fair probability / line  (all four)
- Best price per side + best-price combined hold (Logic of Sports Betting: "synthetic market")
- Edge % = best price vs consensus fair price   (Kaunitz et al., Beating the Bookies)
- Opening -> current movement, reverse line movement
- Spread vs moneyline consistency (spread -> win prob via normal, NBA sd ~ 12)
"""
import math

BOOKS = {68: "DraftKings", 69: "FanDuel", 75: "BetMGM", 123: "Caesars", 79: "bet365", 71: "BetRivers", 2988: "Fanatics"}
OPEN, CONSENSUS = 30, 15
NBA_SD = 13.5   # final margin vs closing spread, NBA
MIN_BOOKS = 4       # don't trust an "edge" built on fewer books
EDGE_FLAG = 0.02    # 2% EV threshold (paper used a bigger cushion before de-vigging)


def be(odds):
    """Break-even probability for American odds."""
    if odds is None:
        return None
    return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)


def dec(odds):
    return 1 + (odds / 100 if odds > 0 else 100 / abs(odds))


def american(p):
    if not p or p <= 0 or p >= 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def two_way(market, a, b):
    """market: {book_id: {side: {"line":..,"odds":..}}}. Returns fair/edge analysis for sides a/b."""
    out = {"books": {}}
    # group by line so we only compare identical numbers
    lines = {}
    for bid, sides in market.items():
        if bid not in BOOKS or a not in sides or b not in sides:
            continue
        sa, sb = sides[a], sides[b]
        if sa.get("odds") is None or sb.get("odds") is None:
            continue
        out["books"][BOOKS[bid]] = {a: sa, b: sb, "hold": round((be(sa["odds"]) + be(sb["odds"]) - 1) * 100, 1)}
        lines.setdefault(sa.get("line"), []).append((BOOKS[bid], sa["odds"], sb["odds"]))
    if not lines:
        return None
    main_line, rows = max(lines.items(), key=lambda kv: len(kv[1]))
    # de-vig per book, average (paper: consensus of books)
    pa = sum(be(x) / (be(x) + be(y)) for _, x, y in rows) / len(rows)
    best_a = max(rows, key=lambda r: dec(r[1]))
    best_b = max(rows, key=lambda r: dec(r[2]))
    edge_a = dec(best_a[1]) * pa - 1
    edge_b = dec(best_b[2]) * (1 - pa) - 1
    out.update({
        "line": main_line, "n_books": len(rows),
        "fair": {a: round(pa * 100, 1), b: round((1 - pa) * 100, 1)},
        "fair_odds": {a: american(pa), b: american(1 - pa)},
        "best": {a: {"book": best_a[0], "odds": best_a[1], "edge": round(edge_a * 100, 1)},
                 b: {"book": best_b[0], "odds": best_b[2], "edge": round(edge_b * 100, 1)}},
        "best_hold": round((be(best_a[1]) + be(best_b[2]) - 1) * 100, 1),
        "avg_hold": round(sum(be(x) + be(y) - 1 for _, x, y in rows) / len(rows) * 100, 1),
        "reliable": len(rows) >= MIN_BOOKS,
    })
    out["value"] = [s for s in (a, b) if out["reliable"] and out["best"][s]["edge"] >= EDGE_FLAG * 100]
    # best NUMBER (points) for spreads/totals regardless of price
    out["line_range"] = [min(lines), max(lines)] if all(isinstance(k, (int, float)) for k in lines) else None
    return out


def analyze(raw, splits, sd=None):
    """raw: {market: {book_id: {side: {...}}}} from Action Network."""
    res = {}
    for m, (a, b) in (("moneyline", ("away", "home")), ("spread", ("away", "home")), ("total", ("over", "under"))):
        r = two_way(raw.get(m, {}), a, b)
        if not r:
            continue
        op = raw.get(m, {}).get(OPEN, {})
        if op.get(a):
            r["open"] = {a: op[a], b: op.get(b)}
            if m in ("spread", "total") and op[a].get("line") is not None and r["line"] is not None:
                r["move"] = round(r["line"] - op[a]["line"], 1)
            elif m == "moneyline" and op[a].get("odds") is not None:
                r["move_pct"] = round((r["fair"][a] - be(op[a]["odds"]) / (be(op[a]["odds"]) + be(op[b]["odds"])) * 100), 1)
        # reverse line movement: majority of bets on one side, line moved toward the other
        sp = (splits or {}).get(m, {})
        if sp.get(a, {}).get("bets") is not None and ("move" in r or "move_pct" in r):
            pub = a if sp[a]["bets"] >= 60 else b if sp.get(b, {}).get("bets", 0) >= 60 else None
            mv = r.get("move", 0) if m != "moneyline" else -r.get("move_pct", 0)
            # spread line is from side a's view: positive move = a getting more points = market moved to b
            toward = None
            if m == "spread" and mv:
                toward = b if mv > 0 else a
            elif m == "total" and mv:
                toward = a if mv > 0 else b
            elif m == "moneyline" and abs(r.get("move_pct") or 0) >= 1.5:
                toward = a if r["move_pct"] > 0 else b
            if pub and toward and toward != pub:
                r["rlm"] = {"public": pub, "public_pct": sp[pub]["bets"], "moved_toward": toward}
        res[m] = r
    # spread vs moneyline consistency (home perspective)
    if "spread" in res and "moneyline" in res and res["spread"]["line"] is not None:
        # away line +x means home favored by x: P(home wins) = Phi(x/sd)
        p_spread = ncdf(res["spread"]["line"] / (sd or NBA_SD))
        p_ml = res["moneyline"]["fair"]["home"] / 100
        res["consistency"] = {"home_from_spread": round(p_spread * 100, 1), "home_from_ml": round(p_ml * 100, 1),
                              "gap": round((p_ml - p_spread) * 100, 1)}
    return res


def best_bet(game):
    """One pick per game, only when the numbers clear a bar; otherwise 'no bet'.

    Ranked by expected value. Pregame: best price beats the vig-free consensus by 2%+ (4+ books).
    Live: projection beats the LIVE total by 6+ pts with a pace flag (pregame-total comparisons
    are shown but never picked, since the live line has already moved).
    Supporting signals (reverse line move toward the side, spread/ML disagreement) add confidence.
    """
    sp = game.get("splits") or {}
    m = sp.get("market") or {}
    names = {"away": game["away"]["short"], "home": game["home"]["short"], "over": "Over", "under": "Under"}
    cands = []
    for k in ("moneyline", "spread", "total"):
        x = m.get(k)
        if not x or not x.get("reliable"):
            continue
        for s in x.get("value", []):
            b = x["best"][s]
            line = ""
            if k == "spread" and x.get("line") is not None:
                v = x["line"] if s == "away" else -x["line"]
                line = f" {'+' if v > 0 else ''}{v}"
            elif k == "total":
                line = f" {x.get('line')}"
            why = [f"{b['book']} pays {'+' if b['odds'] > 0 else ''}{b['odds']}; fair is {'+' if x['fair_odds'][s] > 0 else ''}{x['fair_odds'][s]} ({x['fair'][s]}%)"]
            score = b["edge"]
            if x.get("rlm") and x["rlm"]["moved_toward"] == s:
                score += 0.5
                why.append("line is moving this way against the public")
            cands.append({"kind": "pregame", "market": k, "side": s,
                          "label": f"{names[s]}{' ML' if k == 'moneyline' else line}",
                          "odds": b["odds"], "book": b["book"], "edge": b["edge"], "score": round(score, 2), "why": why})
    lv = game.get("live")
    if lv and lv.get("live_total") and lv.get("pace_flag") and abs(lv.get("vs_line") or 0) >= 6 and lv.get("elapsed", 0) < 44:
        s = "over" if lv["vs_line"] > 0 else "under"
        cands.append({"kind": "live", "market": "total", "side": s, "label": f"LIVE {names[s]} {lv['live_total']}",
                      "odds": None, "book": None, "edge": None, "score": round(abs(lv["vs_line"]) / 3, 2),
                      "why": [lv["pace_note"]] + [f"{t['name']} {t['level']}" for t in lv.get("foul_trouble", []) if t.get("star")]})
    if not cands:
        return None
    return max(cands, key=lambda c: c["score"])


def lean(game):
    """Strongest side on the board even when it misses the 2% bar: the best price vs fair across
    reliable markets. Shown as a lighter 'lean', never as a best bet."""
    m = ((game.get("splits") or {}).get("market")) or {}
    names = {"away": game["away"]["short"], "home": game["home"]["short"], "over": "Over", "under": "Under"}
    best = None
    for k in ("moneyline", "spread", "total"):
        x = m.get(k)
        if not x or not x.get("reliable"):
            continue
        for s, b in x["best"].items():
            if best is None or b["edge"] > best["edge"]:
                line = ""
                if k == "spread" and x.get("line") is not None:
                    v = x["line"] if s == "away" else -x["line"]
                    line = f" {'+' if v > 0 else ''}{v:g}"
                elif k == "total":
                    line = f" {x.get('line')}"
                best = {"market": k, "side": s, "label": f"{names[s]}{' ML' if k == 'moneyline' else line}",
                        "odds": b["odds"], "book": b["book"], "edge": b["edge"],
                        "why": [f"closest to fair of every price on this game ({x['fair'][s]}% fair chance)"]}
    return best
