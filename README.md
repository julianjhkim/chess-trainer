# chess-trainer

A local-only web app for a daily chess routine: review your latest chess.com game,
play a new one, review that, and drill openings as spaced-repetition cards.

Runs entirely on `localhost`. Stockfish does the analysis, the Lichess masters
database supplies the opening lines, and all frontend libraries are vendored into
the repo so the app works offline.

**Status: Phase 1 complete** — app skeleton, board, eval bar, start screen, step
bar and streak. The four step views are scaffolds for now; game review arrives in
Phase 2 and opening cards in Phase 3.

---

## Setup

Requires the conda env `chess` (Python 3.15) and Stockfish.

```bash
# Stockfish (if not already installed)
brew install stockfish

# Python dependencies, into the existing `chess` env
conda run -n chess pip install -e .
```

Optional, for the opening cards in Phase 3 — the Lichess explorer requires a token:

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

## Trying what Phase 1 built

1. **Start screen** — four checkboxes, all checked. Untick some and press *Start*;
   only the ticked steps are selected, and *Start* greys out if you untick them all.
2. **Step bar** — all four steps are always shown at the top. Click any of them to
   jump forward or back, at any time. A step you left unticked is shown dimmed, and
   clicking it selects it on the way in.
3. **Board** — each step currently shows a playable board. Drag a piece: legality
   comes from the server (python-chess), so illegal moves snap back. *Flip board*
   and *Reset position* are below it.
4. **Eval bar** — left of the board, always visible, with the number from White's
   perspective (`+0.45`, `−1.20`, `M3`). It updates after every move. The first
   analysis of a position takes about a second at depth 20; the same position again
   is instant, because results are cached in SQLite.
5. **Streak** — press *Mark this step complete*. The top right shows current and
   longest streak; the day boundary is midnight in Asia/Seoul. Completing a second
   step on the same day does not double-count it.
6. **Status bar** — bottom left reports what just happened (or what failed); bottom
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
| `CHESS_TRAINER_TIMEZONE` | `Asia/Seoul` | streak day boundary |

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

### Vendored frontend libraries

The app loads no CDN at runtime. [chessground](https://github.com/lichess-org/chessground)
is bundled once into `frontend/vendor/chessground/` and committed. To refresh it
after changing the pinned version in `package.json`:

```bash
npm install && npm run vendor
```

Node is only needed for that and for the smoke test — never to run the app.
`node_modules/` is gitignored.

> chessground is **GPL-3.0-or-later**, and it is vendored into this public repo.
> Bear that in mind if you ever want to license this project differently.

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
  chesscom/  client.py, archives.py, latest_game.py, polling.py, game_model.py   [Phase 2]
  pgn/       parse.py, positions.py                                              [Phase 2]
  review/    first_inaccuracy.py, review_session.py, my_moves.py, verdict.py     [Phase 2]
  explorer/  lichess_client.py, cache.py, rate_limit.py, masters.py              [Phase 3]
  openings/  tree_rules.py, card_builder.py, queue_order.py, opening_names.py,
             stats_table.py, line.py, card_types.py                              [Phase 3]
  srs/       sm2.py, grading.py, due.py, scheduler.py                            [Phase 3]
  streak/    seoul_day.py, streak.py, tracker.py
  session/   steps.py, flow.py
  api/       app.py, deps.py, schemas.py, routers/<one per feature>
frontend/
  index.html  css/app.css  vendor/chessground/  js/<one module per concern>
```

`rules.py` is the single authority on move legality: the browser carries no rules
engine and asks the server instead, which also means a drill answer can never be
judged client-side.

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

## Troubleshooting

**"Stockfish NOT FOUND" in the status bar** — install it with
`brew install stockfish`, or point `CHESS_TRAINER_STOCKFISH_PATH` at your binary.
The app still starts; only evaluation is unavailable.

**Port already in use** — `chess-trainer --port 8800`.

**Starting over** — delete the database
(`~/.local/share/chess-trainer/chess_trainer.db`). It holds the streak and the
analysis cache; schema migrations run automatically on startup.
