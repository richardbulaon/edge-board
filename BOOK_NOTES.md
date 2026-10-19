# What the betting books say, and what the board does about it

Written Oct 19, 2026 from the 6 files in `betting books/`. Ideas are paraphrased.

## The books, in one line each
| Book | Worth it? | Big idea |
|---|---|---|
| **The Logic of Sports Betting** (Miller & Davidow) | ⭐⭐⭐ Best of the set | Lines are a market. A few "market maker" books set the price and retail books copy it. Beat the **closing line** and the **house cut**; most trends and public-% splits are noise. |
| **Beating the Bookies With Their Own Numbers** (Kaunitz et al.) | ⭐⭐⭐ Concrete method | Average many books' odds into a fair price, then bet any single book that beats it by a cushion. It made money and got the authors limited by books within months. |
| **Sharp Sports Betting** (Wong), summary version | ⭐⭐ | Know your break-even (52.4% at -110), shop lines, compare spread against moneyline, and test any "system" on fresh data before trusting it. NFL-heavy. |
| **The Art of Live Sports Betting** | ⭐ | Qualitative. Live markets overreact to runs; watch pace, fouls and injuries; keep a bet log and set limits. |
| **7 Secrets of Sports Betting Success** | ⭐ | Value is all that matters. The vig is the enemy. Don't buy picks or systems. Winners are rare. |
| **sports betting.pdf** | ❌ | A 2007 sales page with "never lose" claims. These are the traps the other books warn about. |

## What I added to the board because of them
1. **💲 Market & fair price panel** on every game:
   - 7 books: DraftKings, FanDuel, BetMGM, Caesars, bet365, BetRivers and Fanatics
   - Fair chance for each side, with the vig removed
   - The best available price and which book has it
   - **Edge %** of the best price vs. fair, marked ✅ at +2% or more when 4+ books are available (the Kaunitz method)
   - **House cut**, both the average and the cut you'd pay at the best prices
   - **Line movement** since the open
2. **🔄 Reverse line move** flag: most bets are on one side, but the line moved toward the other.
3. **⚖️ Spread vs. moneyline check**: flags when the two imply win chances 4+ points apart.
4. **🎯 Best spots right now**: one list at the top of the board.
5. **Honest labels**: public splits and situational stats (rest, travel, streaks, H2H, coach, prime time) are marked as *context*. Logic of Sports Betting argues these are already priced into the main NBA lines.
6. **🧮 Tools page** (`nba/tools.html`):
   - Break-even, fair-odds, EV and Kelly-stake calculator
   - Vig remover
   - **Bet log with closing line value (CLV)**. Every book says to track your bets, and CLV is the fastest honest scorecard.

## Rules worth keeping on a sticky note
- At -110 you need **52.4%** just to break even.
- Judge a bet by **price vs. fair**, not by whether it won.
- **Shop every bet.** The gap between books is often worth more than any trend.
- Beating the closing line over hundreds of bets is the real proof of skill. Win rate needs 1,000+ bets.
- Main NBA spreads and totals are the **toughest** markets. Softer spots are props, slow-moving books and live overreactions.
- Bet sizes: small and flat, or ¼ Kelly. Never chase losses.
- Books limit winners. If you find real edges, expect it.

## Next ideas (not built yet)
- ~~Live pace → projected total~~ and ~~star foul trouble~~: built (live panel, Mac notifications, 45-second refresh during games).
- **Closing-line snapshots**: save each game's final lines automatically so the bet log can fill CLV itself, and so we can backtest which flags actually win.
- **Prop pricing** for 3-pointers (Poisson model on the 3PT shooters list).
- ~~NFL version~~: built at /nfl (key numbers, Wong teaser legs, weather, byes/short weeks, QB & skill-player injuries, offense/defense ranks).
