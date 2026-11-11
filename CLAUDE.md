# CLAUDE.md

Guidance for Claude Code sessions in this repo. README.md is the user-facing
manual and has the full rationale; this file is the short version of what you
must know and must not break.

**Keep this file current.** Whenever a product rule, threshold, command or
convention changes, update the matching section here in the same commit.

## What this is

A local-only web app for a daily chess routine in three steps: solve the
puzzles found in my own games (Lichess-style), make more by pasting a game for
the engine to scan, then drill openings as spaced-repetition cards. (Play-a-game and game-review steps existed and were
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
npm run inaccuracy  # Chromium: puzzles (empty, caught up, scanning a game, one card, a puzzle, a punishment, delete)
npm run me       # Chromium: the names editor in the top bar
```
`clicks`, `cards`, `inaccuracy` and `me` use `tests/frontend/stub_server.mjs` (real frontend, canned
payloads) — no server, engine, DB or network. After changing the lines the stub
plays, regenerate its legal-move fixture: `python3 tests/frontend/fixtures/generate.py`.
`npm run vendor` re-bundles chessground after bumping its pinned version.

## Product rules (don't change without being asked; update here if you do)

### Session flow
- Three steps, in order: `inaccuracy_cards` → `make_card` → `cards` (titles:
  Puzzles, Make puzzles, Opening cards — the drill comes first,
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
  as a puzzle's answer — strict string match, judged server-side.
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

### Puzzles (`inaccuracies/`, `db/inaccuracy_cards_repo.py`, `/api/inaccuracy-cards`)
- Step 1 **"Puzzles"** drills them; step 2 **"Make puzzles"** (`make_card`,
  `make_card_view.js`) makes them. They used to be "revision cards" — the user
  had them renamed, and wanted a Lichess-puzzle system from the start: paste a
  game, the engine finds the puzzles. Internally the old names stay — step
  `inaccuracy_cards`, `/api/inaccuracy-cards`, tables `inaccuracy_*`,
  `InaccuracyCard`, `inaccuracy_cards_view.js`. Don't rename one without the
  others.
- **Made by scanning a game, Lichess-style** (`inaccuracies/scan.py`,
  `api/scan_job.py`): `POST /api/inaccuracy-cards/scan` {pgn, colour?} starts
  a background job (one at a time, 409 otherwise) that checks **every move of
  the game, both sides'**, at the analysis depth; `GET /scan` polls it
  (progress, then what it found), `DELETE /scan` stops it (nothing saved).
  A move losing **≥ 10 win %** (`MIN_DROP`: inaccuracies too — the user first
  chose 20, then lowered it when 20 missed 10.b3?, which lost two pawns from a
  level position: near equality that is only ~15%) is a mistake to punish. The puzzle is the
  position **right after it** (`kind='punish'`), played by the side that can
  punish it: **my opponent's side when the mistake was mine** (that is how I
  learn why it was bad, whether or not they found it), mine when it was
  theirs. The punishing first move must pass the only-move test
  (`build_line(first_must_be_only=True)`), and the line must ask **at least 2
  of the solver's moves** (`MIN_SOLVER_MOVES`): a mistake punished in one move
  (a piece left to an unseen bishop) is too crude to learn from — the user's
  call, reversing an earlier "one move is fine". **After an inaccuracy (10–20%)
  the reward must also be clear: mate, or ≥ 1 pawn of material won**
  (`POSITIONAL_DROP = 20`, `MIN_MATERIAL_GAIN`, `puzzle.reward`), counted after
  the opponent's best reply to the line's last move so a capture about to be
  retaken doesn't count — inaccuracies' usual positional edges are hard to
  read. **After a mistake or blunder (20%+) a positional punishment counts
  too** (the user's rule). Slips without such a line are listed as not
  puzzles. Found
  puzzles are saved (game stored, `slip.punishment_card_for`, due tomorrow);
  the outcome names the mistakes but **never a solution**. Saving any
  completes `make_card` (streak) once. `AppState.shutdown` cancels and joins
  the job before closing the DB. The page polls every 700 ms and picks a
  running scan up again on return.
- Card fields for `punish` (migration 10): `solver_colour` (orientation,
  Lichess colour), `slip_label`/`slip_mine` (the mistake: `move_label`),
  `last_move_uci` = the mistake, `ply` = the position after it (may equal the
  game's length), `my_move_*` = how the game went on ('' if it ended) — **not
  sent while solving** (it may be the answer), named afterwards
  (`played_label`). `my_colour` stays the game owner's and is sent
  (`InaccuracyCardOut.my_colour`) so the prompt can say which side I had
  ("you had White") apart from the side I play. Older puzzles are
  `kind='prevent'` (the position before my slip).
- The older by-hand endpoints still exist for the API and tests (the UI no
  longer uses them): paste PGN + **my move number**
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
- **Puzzles** (`inaccuracies/puzzle.py`, Lichess-style): when a card is made,
  Stockfish plays the line out from its position. The first move is the
  card's answer and needs no test (the user chose this: it is judged strictly
  anyway). Each of my later moves must be an
  **only move** — best beats second best (a search with every other move,
  `best_move.second_best`, cached as `fen|without:<move>`) by
  **≥ 10 points of win %** for me, or mates when the second doesn't, or is the
  only legal move. Opponent replies are the engine's best, played for me. The
  line ends on my move: at mate or the first non-only move, **no length limit**
  (the user's choice; `MAX_PLIES` is only a runaway guard). A slip with no
  forced follow-up stays a one-move card. Stored as
  `inaccuracy_cards.solution_uci` (migration 8; migration 9 cleared one-move
  lines so they are re-checked under the first-move rule); a card without one
  gets it the first time it is served (`/next`). On a mating step any mate counts.
  The line is never sent before the card is finished; each right move returns
  `played` (my move + reply) and the next move is mine (`AppState.
  inaccuracy_progress`). **Grading counts wrong tries over the whole puzzle**
  (`attempts = wrong + 1`): 0 wrong q=4, 1 wrong q=3, 2+ q=2 (fail), Show
  answer (plays out the rest) q=1; Hint is for the current step and caps q=3.
  In the drill the opponent's last move plays in first, puzzle moves join the
  move list as played, and once finished the whole line is the nav aside (←
  walks it back to the slip). **No red arrows anywhere** (the user asked): the
  prompt names whose mistake it was ("Your mistake: 8.Bb3 … You play Black
  now: punish it" / "Their mistake: …") and which side I had.
- One card per position (unique EPD). A new card is scheduled as if passed once:
  `n=1, I=1, EF=2.5`, **due the next day**. Making an existing card again brings
  its due date forward to tomorrow (never later); making a deleted one restores it.
- Tables: `inaccuracy_cards` (migration 5; `deleted_at` migration 6;
  `solution_uci` migration 8),
  `inaccuracy_schedule` (same `ScheduleRow` shape as `card_schedule`),
  `inaccuracy_reviews`.
- Drill: card position (the solver's colour at the bottom, the last move
  highlighted; no arrow). ← / → / Home / End and the move list
  step through the moves *before* the slip (`InaccuracyCardOut.moves`, read from
  the stored game; empty if it is missing); only the live position takes a move.
  Unlimited retries with eval; Hint (from-square + piece) **caps the grade at
  q=3** ("right with a hint", still a pass); Show answer q=1. Otherwise the same
  attempt-based grading and SM-2 as opening cards; a failed card is requeued
  later in the session; the first answer in a session decides the schedule.
  Once answered the whole game is browsable (`InaccuracyResultOut.moves/ply`):
  the board sits on the end of the line as a nav "aside"; ← walks back to the
  puzzle position, where the answer is a green arrow.
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
- **My moves: main line only; the opponent's: every reply the rules allow**
  (`openings/repertoire.py`, `card_builder.py`). A card always asks my move and
  branches **only through its answer**; the position after it (opponent to
  move) is not a card from that side, and the opponent's replies from it (by
  the rules above, from that position's own record — one request per
  expansion) are the next cards, parented two plies up.
  - **Black side**: every first move is a card (1.e4 → find 1...c5, then 2.Nf3,
    2.Nc3, 2.c3 each ask my Black move, …).
  - **White side**: only my `WHITE_FIRST_MOVES` 1.e4, 1.d4, 1.Nf3, 1.c4. When
    such a first-move card is first passed it also branches on every Black
    reply (5%+, one ply down) — those ask my White move, and grow the same way.
    Any other first move is Black-only.
  - **The opponent's first reply is wider** (`tree_rules.first_reply_branches`,
    `FIRST_REPLY_MIN_GAMES = 1000`): every move with **1,000+ master games**
    branches there whatever its share, as do 5% moves. That is White's reply
    after my Black answer to any first move (1.e4 c5 → 2.Nf3 … 2.c4) and
    Black's reply to my White first move (1.e4 → 1...c5 … 1...b6). From the
    next opponent move on, only the usual 5% rule — the user chose this over
    the 1,000-game rule at every depth. `card_builder.widen_first_replies`
    adds the missing ones to older trees at startup (cached records only).
  - The two sides share the tree but never a position (Black-to-move cards are
    my Black side, White-to-move my White side); a transposition keeps the
    card where it was first reached.
  - `openings/prune.py` runs at startup and reshapes trees grown under older
    rules: walks the new tree from the roots over existing rows, re-parents
    what belongs (history kept), deletes the rest (schedules and reviews with
    it), marks cards whose answer position was never grown unexpanded so they
    grow again. Idempotent.
- Tree is lazy: children are created when a card is first **passed** (q≥3)
  (one request, for the answer position's record); a card's own explorer
  record is fetched only when it is first served. Cache keyed by EPD (transpositions
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
  with puzzles).
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
