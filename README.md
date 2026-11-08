# chess-trainer

A local-only web app for a daily chess routine: solve puzzles made from your own
games — paste a game and the engine finds them, Lichess-style — then drill
openings as spaced-repetition cards.

Runs entirely on `localhost`. Stockfish does the analysis, the Lichess masters
database supplies the opening lines, and all frontend libraries are vendored into
the repo so the app works offline.

**Status: complete** — all three steps work: solving puzzles, making them,
and opening cards. (Playing
and reviewing a game used to be steps too; they were removed — review your games on
chess.com or Lichess, and make cards from the slips worth drilling.)

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
# then edit .env and set:
#   LICHESS_TOKEN=lip_...
```

Then, in the app, click **👤 Add your name** at the right of the top bar and add
the names you play under — your chess.com name, your Lichess name, a new account
later. They stay in your local database, never in the repo. A pasted game is
yours if either player has one of them, which is how a scanned game knows
which side you played; otherwise you pick White or Black. (An optional
`CHESS_TRAINER_CHESSCOM_USERNAME` in `.env` pre-fills the list the first time.)

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

The start screen has one button per step: click the one you want and the session
starts there. When a step is done the next one follows, and the step bar jumps
anywhere at any time.

**Step 1 — Puzzles.** A warm-up on the puzzles found in your own games (made in
step 2).

Drilling a puzzle: the position right after a mistake, from the side that can
punish it, with the mistake played in first and named ("You played 8.Bb3 — a
mistake. You play Black now: punish it, as your opponent should have."), and the
side you had in the game, so you always know whether it was your mistake or one
of your opponent's you didn't punish. Nothing is drawn on the board while you
solve. Puzzles from before scanning start from the position before your slip
instead. ← / → step back through the moves that led
there (only the position itself takes a move; End comes back). Find the engine's move: only its top choice counts,
retries are unlimited and the eval bar updates on each. *Hint* circles the piece
to move; *Show answer* gives up.

**Where the line is forcing, the card is a puzzle**, as on Lichess or chess.com:
the opponent's last move plays in first, and each right move brings the
opponent's reply (Stockfish's best), played for you, until the line ends. The
first move is the card's answer, Stockfish's top move as always. After it, a move
of yours belongs in the puzzle only if it is the *only* good one — Stockfish's
best beats its second best by at least 10 points of win % (or mates when nothing
else does) — so the puzzle never asks you to guess between equally good moves.
It ends at mate or at the first move that is no longer forced, however long that
takes. When nothing after the first move is forced, the card is a single move, as
before. The moves join the move list as you play them; *Hint* is for the move
you're on, and *Show answer* plays out the rest.

The result shows the grade and the next due date, and the whole game opens up:
the board shows the end of the engine's line, ← walks back along it to the
puzzle's position with the answer in green, and → from there goes on with your
game. Cards are graded and scheduled like the opening cards (see *The
SM-2 variant*), counting wrong moves over the whole puzzle: none is q=4, one is
q=3 (still a pass), two or more q=2 (a fail), *Show answer* q=1; a hint caps the
grade at "right with a hint" (q=3, still a pass). One position is only ever one card: making it again brings the
card back to the next day. *Delete card* (it asks first) takes a card out of the
deck; making that card again restores it. With nothing due the step says so; an
empty deck never counts towards the streak.

Once a card is answered, **Analyse at Lichess ↗** (next to *Next card*) opens the game on the Lichess
analysis board at the card's position, from your side, for trying moves of your
own — something this app deliberately leaves to Lichess. The link carries only
the moves (no names), in the URL itself; nothing is sent to Lichess unless you
click it. It is not offered while you are solving, since Lichess's engine would
give the answer away.

**Step 2 — Make puzzles.** Paste one of your games' PGN and press *Find puzzles*.
Your side is read from your names (top right) in the PGN; if neither player has
one, pick White or Black. Stockfish then checks **every move of the game, yours
and your opponent's**, with a progress bar (a 30-move game takes a minute or
two; *Stop* gives up and saves nothing). It works like Lichess's own puzzles:
after each **mistake or blunder** (a move losing 20% or more of its player's win
chance), the puzzle is to **punish it**:

- after *your* mistake you play your opponent's side, and find what they should
  have done — that is how you learn why your move was bad, even if they missed it;
- after your opponent's mistake you play your own side, and find the punishment,
  whether or not you found it in the game.

The punishing move has to be clearly the only good one (10 points of win %
better than anything else), and the punishment has to take at least two of your
moves: a mistake punished in a single move — a piece left hanging to a bishop
you didn't see — is too crude to be worth drilling. While more only-moves follow,
the puzzle goes on. Mistakes without such a punishment are listed as not puzzles. Each puzzle is due the next day. The list names each
mistake, the side you'll play and how many moves it asks — never the solution;
clicking one shows its position, and ← / → step through the game. Saving the
first puzzles completes the step (and counts the day); the form stays for the
next game. Use the step bar to move on.

**Step 3 — Opening cards.** Anki-style drills built from the Lichess masters
database, grown lazily as you go. The first card is 1.e4; the tree expands only
when you pass a card (right on the first or second try).

The rule throughout: **on your own moves you learn only the main line; on your
opponent's, every reply that is played often enough.** The main line is the
most played move (or the engine's, when there are few master games), and the
opponent's replies are the moves with 5% or more of the games (or the engine's
move in thin positions).

- *Your Black side* covers every first move: 1.e4 asks you for 1...c5, then
  White's 2.Nf3, 2.Nc3 and 2.c3 each ask your next Black move, and so on.
- *Your White side* covers only 1.e4, 1.d4, 1.Nf3 and 1.c4
  (`openings/repertoire.py`): after 1.e4, Black's 1...c5, 1...e5, 1...e6 and
  1...c6 each ask your White move, then every common Black reply to it, and so
  on. After 1.g3 or any other first move you never play, nothing asks a White
  move.

The opponent's **first** reply is wider: any move played in 1,000 or more
master games is included even under 5%, because so early in the game even a
rare-looking move is one you will actually meet (after 1.e4, Black's replies
down to 1...b6; after 1.e4 c5, White's from 2.Nf3 down to 2.c4). From the
opponent's next move on, the usual 5% rule applies.

Nothing ever asks the opponent's move. Cards grown under older rules are
reshaped to this when the app starts (cards that still fit keep their history).

Each card runs the same way: the earlier moves of the line auto-play, then the
branch move appears as an **arrow** for you to play — only that move is draggable —
and the **opening name** follows the board as on Lichess: with the arrow it
names the position so far (1.d3: Mieses Opening), once you play the arrow move
the new one (1.d3 e5: Mieses Opening: Reversed Rat), and once answered the
position after the answer (a position with no book name of its own keeps the
last one). The answer move has to be found with no arrow. Retries are unlimited and the eval bar updates on each one; *Show
answer* gives up. Afterwards you get the **stats table**: every master move with
its share, game count, white/draw/black split and average rating, with the answer,
the most played move and Stockfish's own choice all marked. Next to *Next card*,
**Analyse at Lichess ↗** opens that opening line (not one of your games) on the
Lichess analysis board at the card's position, White at the bottom, with the answer
one move on — press → there to see it.

On a frequency card the question also says whether the most played move is the
one Stockfish would play:

> Heads-up: the most played move is NOT the engine's best move — find the most
> played one.

It is a bare yes or no — naming either move would give the answer away — and it
is resolved before the card is shown, so the card never pauses to search. The
point is that the drill asks for *the move the masters played*, which is not
always the best move on the board; being told which kind of card this is stops
the disagreement feeling like a trick. Engine-mode cards say nothing, since
their answer is the engine's move to begin with.

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

- **Step bar** — all three steps always visible; click any one to jump there at
  any time.
- **Your names** — the 👤 button at the right of the top bar lists the names you
  play under; click it to add or remove one (saved straight away).
- **Board orientation** — a puzzle puts your colour at the bottom; opening
  cards keep White there. *Flip board* turns it round.
- **Eval bar** — always visible, always from White's perspective
  (`+0.45`, `−1.20`, `M3`).
- **Streak** — top right, current and longest. Answering a card counts the day;
  the boundary is midnight in Asia/Seoul, and a second step the same day does not
  double-count.
- **Answer history** — every card answer is logged (`card_reviews` for opening
  cards, `inaccuracy_reviews` for puzzles): the Seoul date, the grade, the
  attempt count and whether you revealed the answer.
- **Scheduling** — cards use a modified SM-2 (see below). There is no daily limit:
  due reviews come first, oldest first, then new cards one at a time, until you
  stop. Getting a card wrong brings it back later in the same session.
- **Status bar** — bottom left reports what just happened (or what failed); bottom
  right shows the version, engine depth and whether a Lichess
  token is present.

## Configuration

Settings are read from the environment, falling back to `.env`, then to defaults.
Command line flags override both.

| Variable | Default | Meaning |
|---|---|---|
| `LICHESS_TOKEN` | — | Lichess API token, needed for the opening explorer |
| `CHESS_TRAINER_CHESSCOM_USERNAME` | — | optional: pre-fills your names (top right) the first time (no default) |
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

The same stub drives a second browser test, over what a card actually says on its
question screen and what its stats table marks afterwards:

```bash
npm run cards
```

And a third over puzzles: an empty deck, an all-caught-up deck, scanning a pasted
game (progress, the puzzles found, no solutions shown), one card solved with a hint after a wrong try (stepping
back through the moves before it, then through the whole game, and the Lichess link),
and deleting a card:

```bash
npm run inaccuracy
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
  pgn/       parse.py, positions.py, my_moves.py
  inaccuracies/  (puzzles) scan.py (finding them in a game), puzzle.py (the
             forcing line), slip.py (move number → position), deck.py
             (adding, serving, grading), hint.py, puzzle.py (the forcing line)
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
`inaccuracy_cards_view.js` (puzzles), `make_card_view.js` (making them), `move_nav.js`, `move_list.js`,
`cards_view.js`, `stats_table.js`, `arrows.js`, `animate.js`.

`rules.py` is the single authority on move legality: the browser carries no rules
engine and asks the server instead, which also means a drill answer can never be
judged client-side.

### How the card tree stays cheap

The tree is never prebuilt. Two moments do the work, and only one of them can
touch the network:

* **Expansion**, when a card is first passed. The card's own cached
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
start, floor 1.3) and an interval `I` in days. Grading is automatic, from the
attempts:

| Outcome | q | |
|---|---|---|
| right on the 1st try | 4 | pass |
| right on the 2nd try | 3 | pass |
| right on the 3rd try or later | 2 | fail |
| answer revealed | 1 | fail |

One wrong try is a stumble; two or more mean the card wasn't really known, so it
fails like a reveal (with a gentler hit to its ease) and comes back later in the
session. The result screen says which: "right on the 2nd try", "right after 3
wrong tries".

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
| `GET /api/cards/state` | the card on screen and the queue behind it |
| `POST /api/cards/next` | serve the next card (due first, then new) |
| `POST /api/cards/attempt` | try a move on the current card |
| `POST /api/cards/show-answer` | reveal the answer, grading it as a failure |
| `GET /api/inaccuracy-cards/state` | the puzzle on screen and the deck's counts |
| `POST /api/inaccuracy-cards/next` | serve the next due puzzle (or say the deck is done) |
| `POST /api/inaccuracy-cards/attempt` | try a move at the current step; a right one brings the opponent's reply |
| `POST /api/inaccuracy-cards/hint` | the square and piece the answer moves (caps the grade at q=3) |
| `POST /api/inaccuracy-cards/show-answer` | play out the rest of the puzzle, grading it as a failure |
| `POST /api/inaccuracy-cards/scan` | scan a pasted game for puzzles, in the background |
| `GET /api/inaccuracy-cards/scan` | the scan's progress; once done, the puzzles it saved (never their solutions) |
| `DELETE /api/inaccuracy-cards/scan` | stop the scan; nothing is saved |
| `POST /api/inaccuracy-cards/preview` | (API only) the position a puzzle at my move number would start from |
| `POST /api/inaccuracy-cards` | (API only) make a puzzle from my move number |
| `DELETE /api/inaccuracy-cards/{id}` | delete a puzzle |
| `GET /api/me` / `PUT /api/me` | the names I play under (read / replace the list) |

## Troubleshooting

**"Stockfish NOT FOUND" in the status bar** — install it with
`brew install stockfish`, or point `CHESS_TRAINER_STOCKFISH_PATH` at your binary.
The app still starts; only evaluation is unavailable.

**Port already in use** — `chess-trainer --port 8800`.

**"Couldn't tell which side you played"** — the PGN doesn't name your chess.com
user (or none is set). Pick White or Black next to the move number.

**Saving a card takes a few seconds** — Stockfish searches the position (and the
one after your move) at depth 20. Lower it with `chess-trainer --depth 14` if you
would rather trade some accuracy for speed; results at each depth are cached.

**"The opening cards need a Lichess API token"** — the explorer returns 401 for
every request without one. Create a token (no scopes) at
<https://lichess.org/account/oauth/token/create> and put it in `.env`.

**"Lichess is rate limiting the opening explorer"** — it already waited 60 seconds
and retried. Give it a minute; almost everything comes from the local cache, so
this should be rare.

**Starting over** — delete the database
(`~/.local/share/chess-trainer/chess_trainer.db`). It holds the streak, the engine
and explorer caches, the games your puzzles came from and the whole card
tree with its scheduling; schema migrations run automatically on startup.

## Licence

GPL-3.0-or-later — see [LICENSE](LICENSE).

The vendored copy of [chessground](https://github.com/lichess-org/chessground) in
`frontend/vendor/chessground/` is GPL-3.0-or-later (Lichess), which is what sets
this project's licence; its own licence text is kept alongside it.
