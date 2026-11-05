# CLAUDE.md

Guidance for Claude Code sessions in this repo. README.md is the user-facing
manual and has the full rationale; this file is the short version of what you
must know and must not break.

**Keep this file current.** Whenever a product rule, threshold, command or
convention changes, update the matching section here in the same commit.

## What this is

A local-only web app for a daily chess routine in three steps: make revision
cards from slips I pick in my own games, drill them, then drill openings as
spaced-repetition cards. (Play-a-game and game-review steps existed and were
**removed on purpose** — the user reviews games elsewhere. Don't bring back
chess.com fetching, a review step or an in-app analysis board without being asked.)
FastAPI + python-chess (Stockfish over UCI) + SQLite on the backend; plain HTML
and vanilla JS ES modules with a vendored chessground on the frontend. No CDN,
no Node at runtime.

## Environment

- **Python**: conda env `chess` (Python 3.15). The shell may not have it
  activated — always run Python, pip and pytest via `conda run -n chess ...`
  (or the env's python directly). Never use the system `python3` for the app.
- **Stockfish**: `/opt/homebrew/bin/stockfish` (the default
  `CHESS_TRAINER_STOCKFISH_PATH`).
- **My names**: the names I play under (any site), a list edited from the top
  bar's right end (👤 button, `me_view.js`, `GET/PUT /api/me`), stored in the
  local DB (`app_state` key `my_usernames`, `db/usernames_repo.py`). A pasted
  game is mine if exactly one player has one of them (`pgn/my_side.py`,
  case-insensitive); otherwise the card form asks for a colour. The optional
  `.env` `CHESS_TRAINER_CHESSCOM_USERNAME` only seeds the list on first read.
  There is **no default in code** (the repo is public and meant for anyone to
  run). Tests use the placeholder `test-player` (opponent `test-opponent`, a
  second name `second-account`). Never write the owner's real usernames into
  the repo — they live only in the local DB.
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
npm run inaccuracy  # Chromium: revision cards (empty, caught up, making one, one card, delete)
npm run me       # Chromium: the names editor in the top bar
```
`clicks`, `cards`, `inaccuracy` and `me` use `tests/frontend/stub_server.mjs` (real frontend, canned
payloads) — no server, engine, DB or network. After changing the lines the stub
plays, regenerate its legal-move fixture: `python3 tests/frontend/fixtures/generate.py`.
`npm run vendor` re-bundles chessground after bumping its pinned version.

## Product rules (don't change without being asked; update here if you do)

### Session flow
- Three steps, in order: `inaccuracy_cards` → `make_card` → `cards` (titles:
  Revision cards, Make a revision card, Opening cards — the drill comes first,
  as a warm-up, by the user's choice; `session/steps.py`,
  `session/flow.py`). Making cards and drilling them are separate steps on
  purpose — the drill screen has **no** card-making button (the user found two
  buttons for one thing confusing).
- **Start screen = one button per step** (no checkboxes): clicking a step starts
  the session there with every step enabled (`POST /api/session/start` with
  `start_at`); finishing a step advances to the next. Both are always on the
  step bar; clicking any one jumps there at any time. The backend still accepts a
  `steps` subset (dimmed on the bar) but the UI no longer sends one.
- Cards have no end; the step counts as completed once a card is answered, but
  the session stays on it (`mark_completed`).

### Engine judgement (shared)
- Win% is Lichess's model: `50 + 50*(2/(1+exp(-0.00368208*cp)) - 1)`, cp capped
  at ±1000, mate = 100/0 (`engine/winpct.py`).
- Classification by win% drop for the mover (`engine/classify.py`):
  ≥10 inaccuracy, ≥20 mistake, ≥30 blunder (else `good`).
- **Only Stockfish's top-1 move at the analysis depth (default 20) is accepted**
  as a revision card's answer — strict string match, judged server-side.
- Analysis is cached by `(fen, depth)` (`analysis_cache`, which also stores the PV).
- **Hint** (`inaccuracies/hint.py`): only the from-square and piece type of the
  answer (yellow circle via `board.setHighlights` = chessground autoShapes,
  which clicks don't erase). Only while unsolved.
- **Lichess link** (`pgn/lichess_link.py`): URL form
  `https://lichess.org/analysis/pgn/<movetext>?color=<my colour>#<ply>`
  (verified against lichess.org); movetext is percent-escaped except dots (SAN
  has `#`, `+`, `=`), moves only — no player names. Non-standard start FEN or no
  stored game → `/analysis/<fen with _ for spaces>`. A plain link; the app never
  calls Lichess for this. Trying your own moves is left to Lichess on purpose —
  the user chose this over an in-app analysis board; don't build one unasked.
- **Move browsing** (`frontend/js/move_nav.js`, `move_list.js`): ← / → step,
  Home/↑ and End/↓ jump, the move list is clickable; keys typed in text fields
  are ignored. An "aside" is a position beside the game (the engine's answer
  between the slip position and my move).

### Revision cards (`inaccuracies/`, `db/inaccuracy_cards_repo.py`, `/api/inaccuracy-cards`)
- Step 1 **"Revision cards"** drills them; step 2 **"Make a revision card"**
  (`make_card`, `make_card_view.js`) makes them. Internally the drill keeps the
  old name — step `inaccuracy_cards`, `/api/inaccuracy-cards`, tables
  `inaccuracy_*`, `InaccuracyCard`, `inaccuracy_cards_view.js`. Don't rename one
  without the others.
- **Made by hand only**, in step 2: paste PGN + type **my move number**
  ("9" = my 9th move, White or Black; `inaccuracies/slip.py: find_slip`). Colour:
  the request's `colour`, else my names (top bar) in the PGN, else 422 asking to
  pick. `POST /preview` (no engine) returns the position before the move, my move
  (red arrow), the moves before it (browsable) and whether the position already
  has a card (`existing`: none/active/deleted). `POST /api/inaccuracy-cards`
  analyses before/after at the analysis depth: answer = engine top-1 (strict, as
  in the opening cards' engine mode), classification/win% drop from the two evals (may be `good`;
  then the prompt just says "You played X here."). **Refused (422) if the top
  move is the move I played.** The game is stored in `games` (`paste_id`) so the
  card can show its moves. The answer is never sent before the card is answered.
  The first card saved in a session marks `make_card` completed (streak) but the
  step stays open for more. There are **no "Continue to …" buttons** anywhere
  (the user asked to remove them): the step bar is how you move on.
- One card per position (unique EPD). A new card is scheduled as if passed once:
  `n=1, I=1, EF=2.5`, **due the next day**. Making an existing card again brings
  its due date forward to tomorrow (never later); making a deleted one restores it.
- Tables: `inaccuracy_cards` (migration 5; `deleted_at` migration 6),
  `inaccuracy_schedule` (same `ScheduleRow` shape as `card_schedule`),
  `inaccuracy_reviews`.
- Drill: card position (my colour at the bottom, opponent's last move
  highlighted), my game move as a red arrow. ← / → / Home / End and the move list
  step through the moves *before* the slip (`InaccuracyCardOut.moves`, read from
  the stored game; empty if it is missing); only the live position takes a move.
  Unlimited retries with eval; Hint (from-square + piece) **caps the grade at
  q=3** ("right with a hint", still a pass); Show answer q=1. Otherwise the same
  attempt-based grading and SM-2 as opening cards; a failed card is requeued
  later in the session; the first answer in a session decides the schedule.
  Once answered the whole game is browsable (`InaccuracyResultOut.moves/ply`):
  the board sits on the answer as a nav "aside"; ← from it = slip position with
  green answer + red mine arrows.
- **Analyse at Lichess ↗** (`InaccuracyResultOut.lichess_url`; a button right
  of Next card, `lichess_button.js`): only once the
  card is answered (never while solving — Lichess's engine would give it away),
  opened at the card's position, my colour at the bottom.
- **Delete card** (`DELETE /api/inaccuracy-cards/{id}`), while solving or after
  answering, behind an inline confirm: soft delete (`deleted_at` set, schedule
  row removed, review log kept). Doesn't grade or count the step.
- First answer marks the step completed (streak) but the step stays until the
  deck is empty. With nothing due (or no cards yet) it says so (pointing to step
  2); an empty deck never counts towards the streak.

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
- **My White repertoire** (`openings/repertoire.py`, `WHITE_FIRST_MOVES`):
  1.e4, 1.d4, 1.Nf3, 1.c4 — those trees are studied from both sides as below.
  Any other first move is **Black-only**: a card branches only through its
  answer (Black's main move by the rules below), the White-to-move position
  after it is **never a card**, and White's replies from it (by the same rules,
  from that position's own record — one request per expansion) are the next
  Black-to-move cards, parented to the card two plies up, down to the dead ends.
  `openings/prune.py` runs at startup and brings older trees into line
  (other Black moves deleted with their subtrees, White-to-move cards deleted
  and their replies moved up with their history); idempotent. The user will
  set rules for their Black side of 1.e4/1.d4/1.Nf3/1.c4 later — not decided.
- Tree is lazy: children are created when a card is first **passed** (q≥3)
  (from the cached record, no extra request); a position's explorer record is
  fetched only when the card is first served. Cache keyed by EPD (transpositions
  share a card). New cards arrive breadth-first. Lichess calls are throttled; a
  429 waits 60 s and retries once.
- Opening names come from the explorer, which names only exact book positions;
  a card it gives no name takes its parent's (as Lichess's board does), and an
  exact name found later wins. Migration 7 backfilled older cards this way.
- The opening name follows the board, as on Lichess: with the arrow, the name of
  the position it is played from (`CardOut.opening_before_label` = the parent
  card's; none for a first move); once played, the card's own name; once
  answered, the position after the answer (`opening_after_label`: the answer
  move's book name from the card's record, else the card's name carries on).
- Card flow: earlier moves auto-play → branch move shown as an arrow (only it is
  draggable) → find the answer with no arrow → stats
  table (answer, most played, Stockfish's choice marked) and **Analyse at
  Lichess ↗** as a button right of Next card (`lichess_url` on the attempt/show-answer response, only once
  finished): `/analysis/pgn/<line + answer>?color=white#<line length>`, i.e. the
  card's position with the answer one move on (`pgn/lichess_link.py`, shared
  with revision cards).
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
- A day is active if at least one session step was completed (answering a
  card of either kind); multiple steps the same day count once.
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

## Look and feel

- Colours are tokens in `frontend/css/app.css` for both themes. Anything painted
  solid (current step, primary/danger buttons, badges) uses the soft pastel
  `--*-fill` tokens with their `--on-*` text colour — the user found the
  saturated blue and green too strong. Board arrows use the softened
  chessground brushes in `board.js` (`BRUSHES`).

## Known gotchas

- **chessground caches the board's bounds.** It re-measures on window resize,
  scroll and its own size change — but not when the board merely *moves*
  (e.g. a side panel grows). Stale bounds make clicks land on the wrong square
  and arrows render as NaN. `frontend/js/board.js` watches the board and its
  ancestors, and views must call `board.refresh()` (synchronous) after any layout
  change around the board. A freshly built board is detached, so it needs a
  refresh once inserted. jsdom can't catch this — use `npm run clicks`.
- Views re-render panels through each card's `setBody`; anything a render adds
  must go inside that body, never be appended to the card root (that once
  stacked up duplicate links).
- Frontend files are served with `Cache-Control: no-cache` (`api/app.py`):
  without it the browser ran stale cached modules after an update, so a new
  button simply didn't appear. Keep it.
- The browser tests' stub (`tests/frontend/stub_server.mjs`) only knows positions
  in `fixtures/board.json`; add new lines to `fixtures/generate.py` and rerun it.
