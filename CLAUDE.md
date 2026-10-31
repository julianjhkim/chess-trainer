# CLAUDE.md

Guidance for Claude Code sessions in this repo. README.md is the user-facing
manual and has the full rationale; this file is the short version of what you
must know and must not break.

**Keep this file current.** Whenever a product rule, threshold, command or
convention changes, update the matching section here in the same commit.

## What this is

A local-only web app for a daily chess routine: drill the slips from past reviews
(inaccuracy cards), play a game, review it, then drill openings as
spaced-repetition cards.
FastAPI + python-chess (Stockfish over UCI) + SQLite on the backend; plain HTML
and vanilla JS ES modules with a vendored chessground on the frontend. No CDN,
no Node at runtime. Status: all four steps complete (phases 0–3 done, plus fixes).

## Environment

- **Python**: conda env `chess` (Python 3.15). The shell may not have it
  activated — always run Python, pip and pytest via `conda run -n chess ...`
  (or the env's python directly). Never use the system `python3` for the app.
- **Stockfish**: `/opt/homebrew/bin/stockfish` (the default
  `CHESS_TRAINER_STOCKFISH_PATH`).
- **chess.com user**: set in `.env` as `CHESS_TRAINER_CHESSCOM_USERNAME`. There
  is **no default in code** (the repo is public and meant for anyone to run);
  without it, fetching returns 503 with instructions and pasting assumes White.
  Tests use the placeholder `test-player` (opponent `test-opponent`). Never write
  the owner's real username into the repo.
- **Lichess token**: `LICHESS_TOKEN` in `.env` (gitignored; template in
  `.env.example`). Needed for the opening explorer (401 without it). **Never
  commit, print, log or echo it** — don't `cat .env`.
- Timezone `Asia/Seoul` sets the streak day boundary and card due dates.
- Database: `~/.local/share/chess-trainer/chess_trainer.db` (migrations run on
  startup; deleting it starts over).
- Remote: `git@github.com:julianjhkim/chess-trainer.git`, branch `main`.

## Running

```bash
conda run -n chess pip install -e .            # once
conda run -n chess chess-trainer               # server + browser at http://127.0.0.1:8787
conda run -n chess chess-trainer --no-browser --port 8791   # e.g. for the smoke test
```

Flags: `--host --port --depth --stockfish --db --no-browser`. API docs at `/docs`.

## Tests — run all relevant suites before committing

```bash
conda run -n chess python -m pytest            # full Python suite (no network)
conda run -n chess python -m pytest -q tests/engine   # one package
```
Real-engine tests use the `real_engine` fixture and skip without Stockfish;
everything else uses `FakeEngine`.

Frontend (Node is dev-only; `npm install` and `npx playwright install chromium` once):

```bash
npm run smoke    # jsdom run of the real ES modules — needs a live server on :8791 (see above)
npm run clicks   # Chromium: clicks square centres, asserts the right square is picked
npm run cards    # Chromium: card question text + stats-table marks
npm run review   # Chromium: review move browsing, Hint, Why, Lichess link, single chess.com link
npm run inaccuracy  # Chromium: inaccuracy-card drill (empty deck, caught up, one card)
```
`clicks` and `cards` use `tests/frontend/stub_server.mjs` (real frontend, canned
payloads) — no server, engine, DB or network. After changing the lines the stub
plays, regenerate its legal-move fixture: `python3 tests/frontend/fixtures/generate.py`.
`npm run vendor` re-bundles chessground after bumping its pinned version.

## Product rules (don't change without being asked; update here if you do)

### Session flow
- Four steps, in order: `inaccuracy_cards` → `play` → `review_new_game` → `cards`
  (titles: Inaccuracy cards, Play a game, Review that game, Opening cards;
  `session/steps.py`, `session/flow.py`). There is no "review last game" step any
  more: `review_new_game` is the only review step (it falls back to the latest
  stored/fetched game if step 2 was skipped). Finishing the review advances to
  `cards`.
- **Start screen = one button per step** (no checkboxes): clicking a step starts
  the session there with all four steps enabled (`POST /api/session/start` with
  `start_at`); finishing a step advances to the next. All four are always on the
  step bar; clicking any one jumps there, forward or back, at any time
  (mid-review included). The backend still accepts a `steps` subset (dimmed on
  the bar) but the UI no longer sends one.
- Play step: open chess.com, then poll the archive ~2 min for a game newer than
  the baseline; fall back to PGN paste. PGN paste is also available in the review.
- Cards have no end; the step counts as completed once a card is answered, but
  the session stays on it (`mark_completed`).

### Game review
- Win% is Lichess's model: `50 + 50*(2/(1+exp(-0.00368208*cp)) - 1)`, cp capped
  at ±1000, mate = 100/0 (`engine/winpct.py`).
- Classification by win% drop for the mover (`engine/classify.py`):
  ≥10 inaccuracy, ≥20 mistake, ≥30 blunder.
- Only *my* moves are classified; the walk **stops at my first inaccuracy (or
  worse)** — nothing past it is analysed.
- The drill replays to the position before that move. **Only Stockfish's top-1
  move at the analysis depth (default 20) is accepted** — strict string match,
  judged server-side (`review/verdict.py`). Unlimited retries, eval bar updates
  on each; "Show answer" gives up. No inaccuracy → say so; if I also **won or
  drew**, the review says "Congratulations — a perfect game!" (outcome from
  chess.com's result code, else the PGN `Result` header: `review/outcome.py`,
  `GameOut.my_outcome`). A clean loss gets no congratulation.
- **Hint** (`review/hint.py`, `POST /api/review/hint`): reveals only the
  from-square and piece type of the answer (yellow circle via
  `board.setHighlights` = chessground autoShapes, which clicks don't erase).
  Only while unsolved. Doesn't change correctness; recorded as `used_hint` in
  the summary and `game_reviews` (migration 4).
- **Why** (`review/explain.py`, `POST /api/review/explain`, `explanation_view.js`):
  only after the review is finished (409 before — it names the answer). Two
  lines from the slip position: best = answer + engine PV from the position
  after it; mine = my move + engine PV after it. Notes are facts read off the
  moves (capture/check/mate/promotion, the reply to my move, eval or mate,
  material each side captures) — no LLM, stays local. Lines cut at 10 plies,
  extended while the last move was a capture/check (max 20). Clicking a line
  move shows it as a nav "aside". The analysis cache stores the PV (`pv`
  column); `analysis.analyse(..., need_line=True)` re-searches entries cached
  without one.
- **Review at Lichess** (`review/lichess_link.py`, `ReviewStateOut.lichess_url`):
  set only once the review is finished (clean games too). URL form
  `https://lichess.org/analysis/pgn/<movetext>?color=<my colour>#<target ply>`
  (verified against lichess.org); movetext is percent-escaped except dots (SAN
  has `#`, `+`, `=`), moves only — no player names. Non-standard start FEN →
  `/analysis/<fen with _ for spaces>`. A plain link; the app never calls Lichess
  for this. Trying your own moves is left to Lichess on purpose — don't build a
  free-play board in the app.
- Board-column layout under the review board: buttons → Review at Lichess →
  Why → Attempts. Side panel: Game → prompt → Moves.
- **Move browsing** (`review/browse.py`, `frontend/js/move_nav.js`, `move_list.js`):
  ← / → step, Home/↑ and End/↓ jump, the move list is clickable. While the drill
  is open the server sends only the moves *before* the slip (never my move or
  anything after it) and the board accepts a move only at the live position.
  Once finished (solved, revealed, or no inaccuracy) the whole game is sent; the
  engine's answer is an "aside" between the position before the slip and the
  move I played (← from it: green best + red mine arrows; →: my actual move).
  Keys typed in text fields (PGN box) are ignored.
- Analysis runs in a background job with progress polling; cached by `(fen, depth)`.
  `AppState.shutdown` must cancel/join the job before closing the DB.

### Inaccuracy cards (`inaccuracies/`, `db/inaccuracy_cards_repo.py`, `/api/inaccuracy-cards`)
- Step 1. A card = the position before my first inaccuracy in a reviewed game
  (oriented to my colour, opponent's last move highlighted); answer = the engine
  top-1 recorded by the review (strict match, same as the review). Created in
  the review's `_finish` whenever the review had a target (solved or revealed);
  clean games make none. **No backfill** of reviews from before this feature.
- One card per position (unique EPD). A new card is scheduled as if passed once:
  `n=1, I=1, EF=2.5`, **due the next day**. Slipping into an existing card's
  position again brings its due date forward to tomorrow (never later).
- Tables (migration 5): `inaccuracy_cards`, `inaccuracy_schedule` (same
  `ScheduleRow` shape as `card_schedule`), `inaccuracy_reviews`.
- Drill: unlimited retries with eval; Hint (from-square + piece) **caps the grade
  at q=3** ("right with a hint", still a pass); Show answer q=1. Otherwise the
  same attempt-based grading and SM-2 as opening cards; a failed card is
  requeued later in the session; the first answer in a session decides the
  schedule. Result shows answer (green arrow) and my game move (red).
- First answer marks the step completed (streak) but the step stays until the
  deck is empty. With nothing due (or no cards yet) it says so; "Continue to
  Play a game" completes the step if a card was answered, otherwise just jumps
  to `play` (an empty deck never counts towards the streak).
- The review summary says "Added to your inaccuracy cards — first due …"
  (`ReviewStateOut.inaccuracy_card`).

### Opening-card tree (`openings/tree_rules.py`)
- **Root exception**: the start position is not a card; *all* of White's first
  moves branch from it (no 5% filter), ordered by game count.
- Otherwise by master games in the position:
  - **≥20**: answer = most played move; a tie is broken by Stockfish among the
    tied moves (and the UI says so). Branches = every move with **≥5%** share.
  - **5–19**: answer = Stockfish's top move (engine mode). The only branch is
    the engine's move.
  - **<5** (or no recorded continuation): not a card — show **"Max depth
    reached"** with that line's stats.
- Tree is lazy: children are created when a card is first **passed** (q≥3)
  (from the cached record, no extra request); a position's explorer record is
  fetched only when the card is first served. Cache keyed by EPD (transpositions
  share a card). New cards arrive breadth-first. Lichess calls are throttled; a
  429 waits 60 s and retries once.
- Card flow: earlier moves auto-play → branch move shown as an arrow (only it is
  draggable) → opening name revealed → find the answer with no arrow → stats
  table (answer, most played, Stockfish's choice marked).
- Frequency cards say, without naming moves, whether the most played move is
  the engine's best (`engine_agrees`); engine-mode cards say nothing. Resolved
  when the card is served, via the analysis cache.
- White always at the bottom, with a Flip board button.

### Scheduling — modified SM-2 (`srs/sm2.py`, `srs/grading.py`)
- Automatic grading by attempts: right on the 1st try q=4, **2nd try q=3**,
  **3rd try or later q=2 (a fail: halved interval, requeued, lapse)**, revealed
  q=1. Pass is q≥3. Labels: "right first time", "right on the 2nd try",
  "right after N wrong tries" (`AnswerOutcome.attempts`).
- Pass: `n=0 → I=1`, `n=1 → I=6`, else `I=round(I×EF)`; `n += 1`.
- **Fail: `I = max(1, round(I × 0.5))` and `n` is NOT reset** (`lapses` is
  tracked separately).
- EF starts 2.5, floor 1.3, standard SM-2 update applied *after* computing the
  interval with the old EF.
- No daily limit: due cards first (oldest first), then new cards one at a time.
  A failed card comes back later in the same session.

### Streak (`streak/`)
- A day is active if at least one session step was completed (finishing a
  review, or answering a card); multiple steps the same day count once.
- Day boundary is midnight Asia/Seoul.
- Current streak = run ending today, or ending yesterday if today isn't active
  yet; breaks only after a whole day with nothing completed. Longest is tracked too.

## Conventions

- **Fine-grained modules**: one concern per file (backend packages and one JS
  module per concern in `frontend/js/`). Follow the existing layout.
- **Pure logic separate from I/O**: rules, scheduling, classification, streak
  math take plain data and a supplied date; repositories/clients/trackers do the
  I/O. Pure modules say so in their docstring.
- `rules.py` is the single authority on move legality; the browser asks the server.
- SQLite: one connection with a reentrant lock; go through `db/connection.py` helpers.
- **Tests for everything**, including frontend behaviour; tests never hit the network.
- **Commit and push after each change** (to `main` unless told otherwise).
  Commit style: a plain-English subject describing the user-visible effect,
  then a prose body explaining why.
- **The GitHub repo is public.** Keep personal information out of everything
  committed — files, test fixtures, commit messages and metadata: no tokens or
  `.env`, emails, real names, local absolute paths (`/Users/...`), or real game
  data beyond what the user has approved (a real game also exposes the
  opponent). Prefer synthetic fixtures. Scan each diff for personal strings
  before committing, and ask when in doubt. Never rewrite published history
  (force-push) without explicit approval.
- License **GPL-3.0-or-later** (forced by vendored chessground). Keep it on new files/metadata.
- Update README.md as well when behaviour changes.

## Known gotchas

- **chessground caches the board's bounds.** It re-measures on window resize,
  scroll and its own size change — but not when the board merely *moves*
  (e.g. a side panel grows). Stale bounds make clicks land on the wrong square
  and arrows render as NaN. `frontend/js/board.js` watches the board and its
  ancestors, and views must call `board.refresh()` (synchronous) after any layout
  change around the board. A freshly built board is detached, so it needs a
  refresh once inserted. jsdom can't catch this — use `npm run clicks`.
- Don't let the background review thread outlive the DB connection (segfault).
- Review state is re-rendered on every 700 ms progress poll: anything a render
  adds must go inside the card body that `setBody` replaces, never appended to
  the card root (that once stacked up "Open on chess.com" links).
- The browser tests' stub (`tests/frontend/stub_server.mjs`) only knows positions
  in `fixtures/board.json`; add new lines to `fixtures/generate.py` and rerun it.
