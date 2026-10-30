/**
 * A stub of the local API, serving the real frontend.
 *
 * The click-mapping test needs the genuine HTML, CSS, chessground and view
 * modules in a real browser, but it must not need Stockfish, a database, the
 * Lichess API or a chess.com account. So this serves `frontend/` as the app
 * does and answers `/api/*` from canned payloads shaped like the FastAPI
 * schemas, with the legal-move data generated from the real rules module
 * (`fixtures/generate.py`).
 *
 * `POST /__scenario {"step": "cards"}` chooses which step the session says is
 * current, i.e. which view the page renders on the next load.
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
  ['review_last_game', 'Review last game'],
  ['play', 'Play a game'],
  ['review_new_game', 'Review that game'],
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
  mode: 'frequency',
  position_games: 1234567,
  source: 'new',
  schedule: null,
};

const CARD_ANSWER_UCI = 'e7e5';

const STATS = {
  total_games: 1234567,
  mode: 'frequency',
  tie_note: null,
  engine_note: null,
  rows: [
    row('e5', 'e7e5', 480000, 38.9, true),
    row('c5', 'c7c5', 400000, 32.4, false),
    row('e6', 'e7e6', 180000, 14.6, false),
    row('c6', 'c7c6', 90000, 7.3, false),
    row('d5', 'd7d5', 40000, 3.2, false),
    row('Nf6', 'g8f6', 30000, 2.4, false),
    row('d6', 'd7d6', 14567, 1.2, false),
  ],
};

function row(san, uci, games, share, isAnswer) {
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
    is_answer: isAnswer,
    is_engine_move: false,
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

const GAME = {
  id: 'stub-game',
  url: 'https://www.chess.com/game/live/0',
  my_colour: 'white',
  opponent: 'a-very-long-opponent-username',
  white_username: 'tester',
  black_username: 'a-very-long-opponent-username',
  my_result: 'checkmated',
  time_class: 'rapid',
  end_time: 1762000000,
  source: 'paste',
  move_count: 4,
};

const REVIEW_TARGET = {
  ply: 0,
  move_number: 1,
  move_label: '1. f3',
  fen_before: START_FEN,
  replay_ucis: [],
  mover_is_white: true,
  orientation: 'white',
};

/** Which step the session reports as current; set through `/__scenario`. */
let currentStep = 'cards';
/** Attempts made in the stubbed review, so the attempts card can grow. */
let reviewAttempts = 0;

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

function reviewState(extra = {}) {
  return {
    step: currentStep,
    status: 'ready',
    game: GAME,
    orientation: 'white',
    depth: 20,
    assessed: 4,
    total_moves: 4,
    progress: 1,
    error: null,
    target: REVIEW_TARGET,
    no_inaccuracy: false,
    attempts: reviewAttempts,
    used_show_answer: false,
    solved: false,
    finished: false,
    summary: null,
    ...extra,
  };
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
    card: CARD,
    counts: { due: 3, new: 7, relearning: 1 },
    attempts: 0,
    used_show_answer: false,
    solved: false,
    finished: false,
    exhausted: false,
  }),
  'GET /api/cards/state': () => ({
    card: CARD,
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
    };
  },

  // -- game review ------------------------------------------------------
  'POST /api/review/start': () => {
    reviewAttempts = 0;
    return reviewState();
  },
  'GET /api/review/review_last_game': () => reviewState(),
  'GET /api/review/review_new_game': () => reviewState(),
  'POST /api/review/attempt': (body) => {
    reviewAttempts += 1;
    const uci = `${body.from}${body.to}${body.promotion ?? ''}`;
    const move = boardMove({ ...body, fen: START_FEN });
    return {
      correct: false,
      uci,
      san: move?.san ?? uci,
      evaluation: EVALUATION,
      fen_after: move?.fen ?? START_FEN,
      attempts: reviewAttempts,
      review: reviewState(),
      session: null,
      streak: null,
    };
  },

  // -- test control -----------------------------------------------------
  'POST /__scenario': (body) => {
    currentStep = body.step;
    reviewAttempts = 0;
    return { step: currentStep };
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
