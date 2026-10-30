# chess-trainer

A local-only web app for a daily chess routine: review your latest chess.com game,
play a new one, review that, and drill openings as spaced-repetition cards.

Runs entirely on `localhost`. Stockfish does the analysis, the Lichess masters
database supplies the opening lines, and all frontend libraries are vendored into
the repo so the app works offline.

**Status: complete** — all four steps work: review your last chess.com game, play
a new one, review that, and drill openings as spaced-repetition cards.

---

## Setup

Requires the conda env `chess` (Python 3.15) and Stockfish.

```bash
# Stockfish (if not already installed)
brew install stockfish

# Python dependencies, into the existing `chess` env
conda run -n chess pip install -e .
```

The opening cards need a Lichess token (the explorer returns 401 without one):

```bash
cp .env.example .env
# then edit .env and set LICHESS_TOKEN=lip_...
```

Create the token at <https://lichess.org/account/oauth/token/create>. **Leave every
scope unchecked** — the explorer only needs an authenticated identity, not
permissions. `.env` is gitignored.

## Run

```bash
conda activate chess
chess-trainer
```

That starts the server and opens your browser at <http://127.0.0.1:8787>.
`python -m chess_trainer` does the same thing.

```
chess-trainer --help
  --host HOST        interface to bind (default: 127.0.0.1)
  --port PORT        port to listen on (default: 8787)
  --depth DEPTH      Stockfish search depth (default: 20)
  --stockfish PATH   path to the Stockfish binary
  --db PATH          path to the SQLite database
  --no-browser       start the server without opening a browser
```

## Trying it

Press *Start* with all four boxes ticked and work through it.

**Step 1 — Review last game.** Your most recent chess.com game is fetched and your
moves are analysed at depth 20, stopping at the first inaccuracy. A progress bar
counts the moves; a long game can take a minute or two the first time, and is
instant afterwards because results are cached. Then the game auto-replays to the
position just before your first slip and you play the move yourself. Only
Stockfish's top choice is accepted; wrong tries are unlimited and each one updates
the eval bar so you can see what it would have cost. *Show answer* gives up. When
you find it, the review ends with a summary: the move you played and its
classification, the engine's move, the evals either side and the win% you dropped.
If the game had no inaccuracy, it says so.

**Step 2 — Play a game.** *Open chess.com* opens a tab; play your game and come
back. *I'm done — fetch my game* watches the chess.com archive for about two
minutes for a game newer than the one you had before (the archive lags a minute or
so behind a finished game), counting down as it goes. If nothing turns up, a PGN
paste box appears. Either way, finishing hands straight over to step 3.

**Step 3 — Review that game.** The same drill on the game you just played.

**Step 4 — Opening cards.** Anki-style drills built from the Lichess masters
database, grown lazily as you go. The first card is 1.e4; the tree expands only
when you get a card right.

Each card runs the same way: the earlier moves of the line auto-play, then the
branch move appears as an **arrow** for you to play — only that move is draggable.
Playing it reveals the **opening name**, and then you have to find the answer move
with no arrow. Retries are unlimited and the eval bar updates on each one; *Show
answer* gives up. Afterwards you get the **stats table**: every master move with
its share, game count, white/draw/black split and average rating, with the answer
highlighted.

What counts as the answer depends on how well-travelled the position is:

| Master games | Answer | Branches that become new cards |
|---|---|---|
| ≥ 20 | the most played move (a tie is broken by Stockfish, and said so) | every move with ≥ 5% of the games |
| 5–19 | Stockfish's top move, since frequency can't be trusted | the engine's move only |
| < 5 | not a card — you get a **"Max depth reached"** message with that line's stats | — |

The start position is the exception: it is not a card, but *all* twenty of White's
first moves branch from it with no 5% filter, ordered by game count. So 1.a4 and
1.Nh3 get drilled too, and those thin lines are where you will see "Max depth
reached" soonest.

New cards arrive breadth-first: every ≥5% reply to 1.e4 before anything at depth
three. White stays at the bottom whichever side the card asks about, with a *Flip
board* button.

Other things worth poking at:

- **Step bar** — all four steps always visible; click any one to jump forward or
  back at any time, mid-review included. A step you left unticked is dimmed, and
  clicking it selects it on the way in.
- **Board orientation** — a review orients the board to the colour you played.
  *Flip board* turns it round.
- **Eval bar** — always visible, always from White's perspective
  (`+0.45`, `−1.20`, `M3`).
- **PGN paste** — available in both review steps at any point, for when chess.com
  is unreachable or the game has not appeared in the archive yet.
- **Streak** — top right, current and longest. Finishing a review counts the day;
  the boundary is midnight in Asia/Seoul, and a second step the same day does not
  double-count.
- **Review history** — every finished review is written to the `game_reviews`
  table: which game, the Seoul date, the ply of your first inaccuracy, your move
  and its classification, the engine's move, both evals, the attempt count and
  whether you revealed the answer. Card answers go to `card_reviews` the same way.
- **Scheduling** — cards use a modified SM-2 (see below). There is no daily limit:
  due reviews come first, oldest first, then new cards one at a time, until you
  stop. Getting a card wrong brings it back later in the same session.
- **Status bar** — bottom left reports what just happened (or what failed); bottom
  right shows the version, engine depth, chess.com username and whether a Lichess
  token is present.

## Configuration

Settings are read from the environment, falling back to `.env`, then to defaults.
Command line flags override both.

| Variable | Default | Meaning |
|---|---|---|
| `LICHESS_TOKEN` | — | Lichess API token, needed for the opening explorer |
| `CHESS_TRAINER_CHESSCOM_USERNAME` | `test-player` | whose games to fetch |
| `CHESS_TRAINER_STOCKFISH_PATH` | `/opt/homebrew/bin/stockfish` | engine binary |
| `CHESS_TRAINER_ENGINE_DEPTH` | `20` | fixed search depth |
| `CHESS_TRAINER_DB` | `~/.local/share/chess-trainer/chess_trainer.db` | database |
| `CHESS_TRAINER_HOST` | `127.0.0.1` | bind interface |
| `CHESS_TRAINER_PORT` | `8787` | port |
| `CHESS_TRAINER_TIMEZONE` | `Asia/Seoul` | streak day boundary and card due dates |

## Development

```bash
conda run -n chess python -m pytest          # the Python suite
conda run -n chess python -m pytest -q tests/engine   # one package
```

Tests never touch the network. Tests that need the real engine use the
`real_engine` fixture and skip automatically when Stockfish is absent; everything
else runs against a `FakeEngine`.

There is also a frontend smoke test that runs the real ES modules in a DOM against
a live server, so chessground, the board round-trip and the eval bar are actually
executed rather than merely parsed:

```bash
npm install
chess-trainer --no-browser --port 8791 &     # in another shell
npm run smoke
```

A DOM shim has no layout, though: every rectangle in jsdom is zero, so it cannot
see a board whose geometry has gone wrong. The click-mapping test therefore drives
the real app in Chromium and clicks square centres with the mouse, asserting that
the square chessground picks is the square clicked — at each point where the layout
around the board changes. It needs no server, engine, database or network: a stub
serves the real frontend with canned API payloads.

```bash
npm install && npx playwright install chromium
npm run clicks
```

Regenerate the stub's legal-move data from the real rules module after changing the
lines it plays:

```bash
python3 tests/frontend/fixtures/generate.py
```

### Vendored frontend libraries

The app loads no CDN at runtime. [chessground](https://github.com/lichess-org/chessground)
is bundled once into `frontend/vendor/chessground/` and committed. To refresh it
after changing the pinned version in `package.json`:

```bash
npm install && npm run vendor
```

Node is only needed for that and for the frontend tests — never to run the app.
`node_modules/` is gitignored.

chessground is GPL-3.0-or-later, which is why this project is GPL-3.0-or-later too
(see [Licence](#licence)).

## Architecture

Backend: FastAPI + `python-chess` (driving Stockfish over UCI) + SQLite.
Frontend: plain HTML and vanilla JS ES modules, with chessground for the board.

Modules are small and single-purpose, and pure logic is kept apart from I/O so
rules, scheduling and classification can be tested without a network or an engine.

```
chess_trainer/
  cli.py  __main__.py  config.py  paths.py  rules.py
  db/        connection.py, schema.py (migrations), one repository per table
  engine/    stockfish.py (process), analysis.py (cached), eval_format.py,
             winpct.py, classify.py, best_move.py, eval_types.py
  chesscom/  client.py (HTTP), archives.py, latest_game.py, polling.py,
             game_model.py
  pgn/       parse.py, positions.py
  review/    my_moves.py, first_inaccuracy.py, verdict.py, review_session.py,
             review_job.py (background analysis + progress)
  explorer/  lichess_client.py (HTTP), cache.py, rate_limit.py,
             explorer_types.py
  openings/  tree_rules.py, card_builder.py, queue_order.py, opening_names.py,
             stats_table.py, line.py, card_types.py
  srs/       sm2.py, grading.py, due.py, scheduler.py
  streak/    seoul_day.py, streak.py, tracker.py
  session/   steps.py, flow.py
  api/       app.py, deps.py, schemas.py, routers/<one per feature>
frontend/
  index.html  css/app.css  vendor/chessground/  js/<one module per concern>
```
The frontend has one module per concern: `api.js`, `state.js`, `router.js`,
`board.js`, `evalbar.js`, `stepbar.js`, `streak_view.js`, `start_screen.js`,
`review_view.js`, `play_view.js`, `cards_view.js`, `stats_table.js`, `arrows.js`,
`animate.js`, `pgn_paste.js`.

`rules.py` is the single authority on move legality: the browser carries no rules
engine and asks the server instead, which also means a drill answer can never be
judged client-side.

### Review analysis runs in the background

Classifying a move needs the evaluation before it *and* after it, and the "after"
position is not reusable as the next move's "before" (you moved, then your
opponent did). So Stockfish ends up scoring roughly every ply. Two things keep
that bearable: only *your* moves are classified and given a best-move answer, and
the walk **stops at your first inaccuracy** — a slip on move 8 costs a handful of
searches rather than one per ply of the whole game. Everything is cached by
`(fen, depth)`, so re-reviewing is instant.

Even so, a game where the first slip is the last move played can take a minute at
depth 20. That would look like a hung page, so `review/review_job.py` runs the
analysis in a worker thread and reports `assessed / total` progress for the browser
to poll. The job is cancellable, and `AppState.shutdown` cancels and joins it
before closing the database — a background thread reading a closed SQLite
connection is a use-after-free that segfaults the interpreter.

### How the card tree stays cheap

The tree is never prebuilt. Two moments do the work, and only one of them can
touch the network:

* **Expansion**, when a card is first answered correctly. The card's own cached
  explorer record already says how often each branch move was played — and the
  number of games that played a move from a position is exactly the number that
  reached the position after it. So every child row, *including whether it is a
  dead end*, is created without a single extra request, and each child's opening
  name comes from the same record.
* **Preparation**, the first time a card is served. Only then is the position's own
  record fetched, because only then is its answer needed.

So a request is spent per card actually drilled, never per card created:
bootstrapping all twenty first moves costs one request, and expanding 1.e4 into
four new cards costs none. Everything is cached in SQLite forever, keyed by EPD
(a FEN without the move counters) — the explorer is position-based, so two
transposing lines share one cache entry, and a position is only ever one card.

Requests are throttled, and an HTTP 429 waits 60 seconds and retries once.

### The SM-2 variant

Per card: `n`, its position on the interval ladder, an ease factor `EF` (2.5 to
start, floor 1.3) and an interval `I` in days. Grading is automatic — right first
time is q=4, right after a retry is q=3, revealing the answer is q=1 — so only a
reveal actually fails a card.

Passing gives `I = 1`, then `6`, then `round(I × EF)`, and `n += 1`; the ladder
runs 1 → 6 → 15 → 38 → 95 days at the default ease. The interval is computed with
the ease the card had *before* the answer, and the ease is updated afterwards.

Failing departs from textbook SM-2 twice over. The interval is **halved** rather
than dropped to a day (`I = max(1, round(I × 0.5))`), **and `n` is left alone** —
the ladder is never restarted. Keeping `n` is what makes the halving mean
something: the next successful answer continues from the halved interval, so a
lapse costs one step rather than the card's whole history.

```
n=4, I=38d  ──fail──▶  I=19d (n still 4)  ──pass──▶  I=37d   (19 × 1.96)
```

A card that has never passed (`n = 0`) stays at one day either way, which falls
out of the `n = 0` pass rule rather than needing a special case. So `n` counts
completed passes rather than consecutive ones, and `lapses` is tracked separately.

### Why one locked SQLite connection

Engine searches run in worker threads, FastAPI resolves synchronous dependencies in
its own threadpool, and the page issues several requests at once on load — so a
connection gets touched from several threads. Python's `sqlite3` connection cannot
be stepped by two threads at once (it raises `InterfaceError`), so there is a single
connection carrying a reentrant lock, and every read and write goes through the
locked helpers in `db/connection.py`. For a single-user local app the lock is
uncontended.

## API

Interactive docs at <http://127.0.0.1:8787/docs> while the server runs.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | version, engine status, database path, config summary |
| `GET /api/session` | current session and step bar state |
| `POST /api/session/start` | begin a session with the selected steps |
| `POST /api/session/jump/{step}` | jump to any step |
| `POST /api/session/complete/{step}` | finish a step; advances and counts the day |
| `GET /api/streak` | current and longest streak |
| `POST /api/board/state` | legal destinations and status for a FEN |
| `POST /api/board/move` | apply a move, get SAN and the new position |
| `POST /api/engine/eval` | evaluate a position, read through the cache |
| `GET /api/game/latest` | the most recent stored game (no network) |
| `POST /api/game/fetch-latest` | fetch my newest chess.com game and store it |
| `POST /api/game/baseline` | record the newest game *before* I play one |
| `POST /api/game/poll-new` | one ~12s window watching for a newer game |
| `POST /api/game/paste` | store a game from pasted PGN |
| `POST /api/review/start` | begin a review; analyses in the background |
| `GET /api/review/{step}` | review progress and state (polled while analysing) |
| `POST /api/review/attempt` | try a move; returns correctness and an eval |
| `POST /api/review/show-answer` | reveal the engine's move, ending the review |
| `POST /api/review/acknowledge` | close a review that had no inaccuracy |
| `GET /api/cards/state` | the card on screen and the queue behind it |
| `POST /api/cards/next` | serve the next card (due first, then new) |
| `POST /api/cards/attempt` | try a move on the current card |
| `POST /api/cards/show-answer` | reveal the answer, grading it as a failure |

## Troubleshooting

**"Stockfish NOT FOUND" in the status bar** — install it with
`brew install stockfish`, or point `CHESS_TRAINER_STOCKFISH_PATH` at your binary.
The app still starts; only evaluation is unavailable.

**Port already in use** — `chess-trainer --port 8800`.

**"No new game appeared in two minutes"** — the chess.com archive sometimes lags
further behind. Press the fetch button again, or open the game on chess.com and
paste its PGN (Share → PGN) into the box that appears.

**The review is analysing for a long time** — a long game at depth 20 takes a
while the first time. Lower it with `chess-trainer --depth 14` if you would rather
trade some accuracy for speed; results at each depth are cached separately.

**"The opening cards need a Lichess API token"** — the explorer returns 401 for
every request without one. Create a token (no scopes) at
<https://lichess.org/account/oauth/token/create> and put it in `.env`.

**"Lichess is rate limiting the opening explorer"** — it already waited 60 seconds
and retried. Give it a minute; almost everything comes from the local cache, so
this should be rare.

**Starting over** — delete the database
(`~/.local/share/chess-trainer/chess_trainer.db`). It holds the streak, the engine
and explorer caches, the games you have reviewed and the whole card tree with its
scheduling; schema migrations run automatically on startup.

## Licence

GPL-3.0-or-later — see [LICENSE](LICENSE).

The vendored copy of [chessground](https://github.com/lichess-org/chessground) in
`frontend/vendor/chessground/` is GPL-3.0-or-later (Lichess), which is what sets
this project's licence; its own licence text is kept alongside it.
