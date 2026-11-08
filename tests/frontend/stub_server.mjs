/**
 * A stub of the local API, serving the real frontend.
 *
 * The click-mapping test needs the genuine HTML, CSS, chessground and view
 * modules in a real browser, but it must not need Stockfish, a database, the
 * Lichess API. So this serves `frontend/` as the app
 * does and answers `/api/*` from canned payloads shaped like the FastAPI
 * schemas, with the legal-move data generated from the real rules module
 * (`fixtures/generate.py`).
 *
 * `POST /__scenario {"step": "cards", "engineAgrees": false}` chooses which
 * step the session says is current -- i.e. which view the page renders on the
 * next load -- and what the card says about Stockfish agreeing with the
 * masters. `"inaccuracy": "empty" | "caught-up" | "one" | "puzzle"` picks what the
 * revision-card deck holds.
 */

import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = join(HERE, '..', '..', 'frontend');

const fixture = JSON.parse(
  await readFile(join(HERE, 'fixtures', 'board.json'), 'utf8'),
);

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const AFTER_E4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
};

const STEPS = [
  ['inaccuracy_cards', 'Revision cards'],
  ['make_card', 'Make a revision card'],
  ['cards', 'Opening cards'],
];

const EVALUATION = { cp: 31, mate: null, text: '+0.31', fraction: 0.543 };

/**
 * A long opening name and a wide stats table on purpose: the bug under test is
 * the board moving sideways when the side panel grows, so the fixture has to
 * make it grow.
 */
const CARD = {
  id: 1,
  line_uci: 'e2e4',
  line_label: '1. e4',
  depth: 1,
  side_to_move: 'black',
  replay_ucis: [],
  given_move_uci: 'e2e4',
  given_move_san: 'e4',
  fen_before_given: START_FEN,
  fen: AFTER_E4,
  opening_eco: 'B00',
  opening_name: "King's Pawn Game: Nimzowitsch Defence, Declined Variation",
  opening_label: "B00 — King's Pawn Game: Nimzowitsch Defence, Declined Variation",
  // Made-up names: 1.e4 really starts from the unnamed start position, but the
  // tests need to tell the three names apart.
  opening_before_label: 'A00 Stub Opening Before',
  mode: 'frequency',
  position_games: 1234567,
  source: 'new',
  schedule: null,
  engine_agrees: null,
};

const CARD_ANSWER_UCI = 'e7e5';

const STATS = {
  total_games: 1234567,
  mode: 'frequency',
  tie_note: null,
  engine_note: null,
  rows: [
    row('e5', 'e7e5', 480000, 38.9, { answer: true, mostPlayed: true }),
    // Stockfish prefers a move the masters played less often: the case the
    // question warns about, and the reason both marks exist.
    row('c5', 'c7c5', 400000, 32.4, { engine: true }),
    row('e6', 'e7e6', 180000, 14.6),
    row('c6', 'c7c6', 90000, 7.3),
    row('d5', 'd7d5', 40000, 3.2),
    row('Nf6', 'g8f6', 30000, 2.4),
    row('d6', 'd7d6', 14567, 1.2),
  ],
};

function row(san, uci, games, share, marks = {}) {
  return {
    san,
    uci,
    games,
    share,
    white: Math.round(games * 0.36),
    draws: Math.round(games * 0.38),
    black: Math.round(games * 0.26),
    white_percent: 36,
    draw_percent: 38,
    black_percent: 26,
    average_rating: 2412,
    is_answer: marks.answer === true,
    is_engine_move: marks.engine === true,
    is_most_played: marks.mostPlayed === true,
    is_tied: false,
  };
}

const GRADE = {
  quality: 5,
  description: 'perfect recall',
  passed: true,
  was_new: true,
  rescheduled: true,
  requeued: false,
  interval_days: 1,
  due_on: '2026-11-01',
  ef: 2.5,
};

const OPPONENT = 'a-very-long-opponent-username';

/**
 * The revision card's game: 1.e4 e5 2.Nf3 Nc6 3.Bb5, where 2.Nf3 is the slip
 * and 2.Bc4 the engine's answer.
 */
const BROWSE_LINE = ['e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1b5'];
const BROWSE_TARGET_PLY = 2;
const BROWSE_ANSWER = 'f1c4';
/** The same card as a puzzle (scenario 'puzzle'): 2.Bc4! Nc6 3.Nf3!. */
const PUZZLE_LINE = ['e2e4', 'e7e5', 'f1c4', 'b8c6', 'g1f3'];

/** The move list for `line`, shaped like `GameMoveOut`. */
function movesOf(line, myColour = 'white') {
  let fen = START_FEN;
  return line.map((uci, ply) => {
    const move = fixture.moves[`${fen}|${uci}`];
    if (!move) throw new Error(`no fixture move for ${uci} at ply ${ply}`);
    const moverIsWhite = ply % 2 === 0;
    const moveNumber = Math.floor(ply / 2) + 1;
    const entry = {
      ply,
      move_number: moveNumber,
      label: `${moveNumber}${moverIsWhite ? '.' : '...'}${move.san}`,
      san: move.san,
      uci,
      fen_before: fen,
      fen_after: move.fen,
      mover_is_white: moverIsWhite,
      is_mine: moverIsWhite === (myColour === 'white'),
    };
    fen = move.fen;
    return entry;
  });
}

const BROWSE_MOVES = movesOf(BROWSE_LINE);

const BROWSE_TARGET = {
  ply: BROWSE_TARGET_PLY,
  move_number: 2,
  move_label: '2.Nf3',
  fen_before: BROWSE_MOVES[BROWSE_TARGET_PLY].fen_before,
  replay_ucis: BROWSE_LINE.slice(0, BROWSE_TARGET_PLY),
  mover_is_white: true,
  orientation: 'white',
  my_move_uci: 'g1f3',
  my_move_san: 'Nf3',
  classification: 'inaccuracy',
};

// -- inaccuracy cards ---------------------------------------------------------
/** 'empty' (no cards at all), 'caught-up' (none due) or 'one' (one due card). */
let inaccuracyScenario = 'empty';
let inaccuracyServed = false;
let inaccuracyAnswered = false;
let inaccuracyHinted = false;
let inaccuracyAttempts = 0;
let inaccuracyDeleted = false;
let inaccuracyCreated = 0;
/** Plies of the puzzle line played so far. */
let inaccuracyStep = 0;
/** The names I play under, as `/api/me` keeps them. */
let myNames = ['test-player'];

const INACCURACY_CARD = {
  id: 7,
  fen: BROWSE_TARGET.fen_before,
  orientation: 'white',
  last_move_uci: 'e7e5',
  move_number: 2,
  classification: 'mistake',
  my_move_uci: 'g1f3',
  my_move_san: 'Nf3',
  move_label: '2.Nf3',
  source: 'due',
  opponent: OPPONENT,
  played_on: 1736942614,
  interval_days: 1,
  reps: 0,
  moves: BROWSE_MOVES.slice(0, BROWSE_TARGET_PLY),
};

/** What "Show position" finds for move 2 of the stubbed game. */
const INACCURACY_PREVIEW = {
  colour: 'white',
  move_number: 2,
  ply: BROWSE_TARGET_PLY,
  move_label: '2.Nf3',
  my_move_uci: 'g1f3',
  my_move_san: 'Nf3',
  fen: BROWSE_TARGET.fen_before,
  last_move_uci: 'e7e5',
  opponent: 'test-opponent',
  moves: BROWSE_MOVES.slice(0, BROWSE_TARGET_PLY),
  existing: 'none',
};

const hasDueCard = () => inaccuracyScenario === 'one' || inaccuracyScenario === 'puzzle';

function inaccuracyCounts() {
  const total = (inaccuracyScenario === 'empty' ? 0 : inaccuracyDeleted ? 2 : 3) + inaccuracyCreated;
  const due = hasDueCard() && !inaccuracyAnswered && !inaccuracyDeleted ? 1 : 0;
  return { due, relearning: 0, total, next_due_on: total ? '2026-11-03' : null };
}

function inaccuracyAttempt(body) {
  inaccuracyAttempts += 1;
  const uci = `${body.from}${body.to}${body.promotion ?? ''}`;
  const puzzle = inaccuracyScenario === 'puzzle';
  const line = puzzle ? movesOf(PUZZLE_LINE).slice(BROWSE_TARGET_PLY) : movesOf(PUZZLE_LINE).slice(2, 3);
  const step = line[inaccuracyStep];
  const move = boardMove({ ...body, fen: step.fen_before });
  const correct = uci === step.uci;
  const finished = correct && inaccuracyStep + 1 >= line.length;
  const base = {
    correct,
    uci,
    san: move?.san ?? uci,
    evaluation: EVALUATION,
    fen_after: move?.fen ?? step.fen_before,
    attempts: inaccuracyAttempts,
    finished,
  };
  if (!correct) return base;
  if (!finished) {
    const played = line.slice(inaccuracyStep, inaccuracyStep + 2);
    inaccuracyStep += 2;
    return { ...base, played, reply_san: played[1].san, fen_after_reply: played[1].fen_after };
  }
  inaccuracyAnswered = true;
  return {
    ...base,
    result: {
      answer_uci: BROWSE_ANSWER,
      answer_san: 'Bc4',
      my_move_uci: 'g1f3',
      my_move_san: 'Nf3',
      move_label: '2.Nf3',
      classification: 'mistake',
      win_percent_drop: 21.4,
      revealed: false,
      grade: {
        quality: 3,
        description: inaccuracyHinted ? 'right with a hint' : 'right on the 2nd try',
        passed: true,
        requeued: false,
        interval_days: 6,
        due_on: '2026-11-06',
        ef: 2.36,
      },
      moves: BROWSE_MOVES,
      ply: BROWSE_TARGET_PLY,
      solution: line,
      lichess_url: 'https://lichess.org/analysis/pgn/1.e4%20e5%202.Nf3%20Nc6%203.Bb5?color=white#2',
    },
    counts: inaccuracyCounts(),
    session: { ...session(currentStep), steps: session(currentStep).steps.map((st) => st.step === 'inaccuracy_cards' ? { ...st, completed: true } : st) },
    streak: STREAK,
  };
}

/** Which step the session reports as current; set through `/__scenario`. */
let currentStep = 'cards';
/** What the served card says about Stockfish agreeing with the masters. */
let engineAgrees = null;

function session(step) {
  return {
    started: true,
    current: step,
    finished: false,
    steps: STEPS.map(([name, title], index) => ({
      step: name,
      position: index + 1,
      title,
      enabled: true,
      completed: false,
      current: name === step,
    })),
  };
}

const STREAK = { current: 4, longest: 9, active_today: true, total_days: 21 };

function withCompleted(base, step) {
  return { ...base, steps: base.steps.map((st) => (st.step === step ? { ...st, completed: true } : st)) };
}

function boardMove(body) {
  const key = `${body.fen}|${body.from}${body.to}${body.promotion ?? ''}`;
  const move = fixture.moves[key];
  if (!move) return null;
  return { ...move, state: fixture.states[move.state_fen] };
}

const routes = {
  'GET /api/health': () => ({
    status: 'ok',
    version: '0.0.0-stub',
    engine: { exists: true, depth: 20, path: '/usr/local/bin/stockfish' },
    database: ':memory:',
    chesscom_username: 'tester',
    lichess_token_present: true,
    timezone: 'Asia/Seoul',
  }),
  'GET /api/session': () => session(currentStep),
  'GET /api/me': () => ({ usernames: myNames }),
  'PUT /api/me': (body) => {
    const seen = new Set();
    myNames = (body.usernames ?? []).map((n) => n.trim()).filter((n) => {
      const key = n.toLowerCase();
      if (!n || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    return { usernames: myNames };
  },
  'GET /api/streak': () => STREAK,
  'POST /api/engine/eval': (body) => ({
    fen: body.fen,
    depth: 20,
    evaluation: EVALUATION,
    best_move: 'e2e4',
    cached: true,
  }),
  'POST /api/board/state': (body) =>
    fixture.states[body.fen ?? START_FEN] ?? { error: `no fixture state for ${body.fen}` },
  'POST /api/board/move': (body) =>
    boardMove(body) ?? { error: `no fixture move for ${body.from}${body.to}` },

  // -- opening cards ----------------------------------------------------
  'POST /api/cards/next': () => ({
    card: { ...CARD, engine_agrees: engineAgrees },
    counts: { due: 3, new: 7, relearning: 1 },
    attempts: 0,
    used_show_answer: false,
    solved: false,
    finished: false,
    exhausted: false,
  }),
  'GET /api/cards/state': () => ({
    card: { ...CARD, engine_agrees: engineAgrees },
    counts: { due: 3, new: 7, relearning: 1 },
  }),
  'POST /api/cards/attempt': (body) => {
    const uci = `${body.from}${body.to}${body.promotion ?? ''}`;
    const correct = uci === CARD_ANSWER_UCI;
    const move = boardMove({ ...body, fen: CARD.fen });
    const base = {
      correct,
      uci,
      san: move?.san ?? uci,
      evaluation: EVALUATION,
      fen_after: move?.fen ?? CARD.fen,
      attempts: 1,
      finished: correct,
    };
    if (!correct) return base;
    return {
      ...base,
      answer_uci: CARD_ANSWER_UCI,
      answer_san: 'e5',
      stats: STATS,
      grade: GRADE,
      dead_ends: [],
      branches_created: 2,
      counts: { due: 2, new: 7, relearning: 1 },
      session: session(currentStep),
      streak: STREAK,
      lichess_url: 'https://lichess.org/analysis/pgn/1.e4%20e5?color=white#1',
      opening_after_label: 'C20 Stub Opening After',
    };
  },

  // -- inaccuracy cards -------------------------------------------------
  'POST /api/inaccuracy-cards/next': () => {
    inaccuracyAttempts = 0;
    inaccuracyHinted = false;
    inaccuracyStep = 0;
    if (hasDueCard() && !inaccuracyServed) {
      inaccuracyServed = true;
      return { card: INACCURACY_CARD, counts: inaccuracyCounts(), attempts: 0, finished: false, exhausted: false };
    }
    return { card: null, counts: inaccuracyCounts(), attempts: 0, finished: false, exhausted: true };
  },
  'POST /api/inaccuracy-cards/hint': () => {
    inaccuracyHinted = true;
    return { square: 'f1', piece: 'bishop', text: 'Move your bishop on f1.' };
  },
  'POST /api/inaccuracy-cards/attempt': (body) => inaccuracyAttempt(body),
  'POST /api/inaccuracy-cards/preview': (body) => {
    if (!String(body.pgn ?? '').includes('1.')) return { error: 'That does not look like a PGN.' };
    if (body.move_number !== 2) return { error: `White has no move ${body.move_number} in this game: your moves run from 1 to 3.` };
    return INACCURACY_PREVIEW;
  },
  'POST /api/inaccuracy-cards': (body) => {
    if (body.move_number !== 2) return { error: 'no such move' };
    inaccuracyCreated += 1;
    const first = inaccuracyCreated === 1;
    return {
      move_label: '2.Nf3',
      due_on: '2026-11-03',
      created: true,
      restored: false,
      counts: inaccuracyCounts(),
      session: first ? withCompleted(session(currentStep), 'make_card') : null,
      streak: first ? STREAK : null,
    };
  },
  [`DELETE /api/inaccuracy-cards/${INACCURACY_CARD.id}`]: () => {
    inaccuracyDeleted = true;
    return inaccuracyCounts();
  },
  'POST /api/session/jump/cards': () => {
    currentStep = 'cards';
    return session('cards');
  },
  'POST /api/session/jump/inaccuracy_cards': () => {
    currentStep = 'inaccuracy_cards';
    return session('inaccuracy_cards');
  },
  'POST /api/session/complete/make_card': () => {
    currentStep = 'inaccuracy_cards';
    return { session: withCompleted(session('inaccuracy_cards'), 'make_card'), streak: STREAK };
  },

  // -- test control -----------------------------------------------------
  'POST /__scenario': (body) => {
    currentStep = body.step;
    engineAgrees = body.engineAgrees ?? null;
    inaccuracyScenario = body.inaccuracy ?? 'empty';
    inaccuracyServed = false;
    inaccuracyStep = 0;
    inaccuracyAnswered = false;
    inaccuracyHinted = false;
    inaccuracyAttempts = 0;
    inaccuracyDeleted = false;
    inaccuracyCreated = 0;
    myNames = body.names ?? ['test-player'];
    return { step: currentStep, engineAgrees, inaccuracy: inaccuracyScenario };
  },
};

async function serveStatic(pathname, response) {
  const relative = pathname === '/' ? 'index.html' : normalize(pathname).replace(/^\/+/, '');
  const file = join(FRONTEND, relative);
  if (!file.startsWith(FRONTEND)) {
    response.writeHead(403).end('forbidden');
    return;
  }
  try {
    const body = await readFile(file);
    response.writeHead(200, {
      'Content-Type': MIME[extname(file)] ?? 'application/octet-stream',
      'Cache-Control': 'no-store',
    });
    response.end(body);
  } catch {
    response.writeHead(404).end('not found');
  }
}

export function startStubServer({ port = 0 } = {}) {
  const server = createServer(async (request, response) => {
    const url = new URL(request.url, 'http://127.0.0.1');
    const key = `${request.method} ${url.pathname}`;
    const handler = routes[key];

    if (!handler) {
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/__')) {
        response.writeHead(404, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ detail: `stub has no route for ${key}` }));
        return;
      }
      await serveStatic(url.pathname, response);
      return;
    }

    let body = {};
    if (request.method !== 'GET') {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const text = Buffer.concat(chunks).toString('utf8');
      body = text ? JSON.parse(text) : {};
    }

    const payload = handler(body);
    response.writeHead(payload?.error ? 422 : 200, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    });
    response.end(JSON.stringify(payload?.error ? { detail: payload.error } : payload));
  });

  return new Promise((resolve) => {
    server.listen(port, '127.0.0.1', () => {
      const { port: bound } = server.address();
      resolve({
        url: `http://127.0.0.1:${bound}`,
        close: () => new Promise((done) => server.close(done)),
      });
    });
  });
}
