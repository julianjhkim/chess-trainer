/**
 * Timed auto-replay of a line of moves.
 *
 * Used to walk the board from the start of the game up to the position just
 * before my first inaccuracy. Cancellable, because the step bar lets you leave
 * mid-replay and a stray timer must not keep pushing moves onto a board that
 * has been thrown away.
 */

const DEFAULT_DELAY_MS = 260;

/** Rough total the whole auto-replay should take, however long the line is. */
const REPLAY_BUDGET_MS = 3200;
const MIN_DELAY_MS = 90;

/**
 * Per-move delay for a line of `count` moves.
 *
 * A fixed delay means a 40-move game takes ten seconds to replay before you
 * can do anything, so longer lines are played proportionally faster.
 */
export function replayDelayFor(count) {
  if (count <= 1) return DEFAULT_DELAY_MS;
  return Math.max(MIN_DELAY_MS, Math.min(DEFAULT_DELAY_MS, REPLAY_BUDGET_MS / count));
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Replay `ucis` on `board`, one move at a time.
 *
 * Returns `{ promise, cancel, isCancelled }`. The promise resolves to true when
 * the whole line was played, false if it was cancelled part way.
 */
export function createReplay({ board, ucis, delayMs = DEFAULT_DELAY_MS, onMove = null }) {
  let cancelled = false;

  async function run() {
    for (const [index, uci] of ucis.entries()) {
      if (cancelled) return false;
      // The first move needs no leading pause; later ones are spaced out.
      if (index > 0) await sleep(delayMs);
      if (cancelled) return false;
      const result = await board.pushMove(uci);
      if (onMove) onMove(result, index);
    }
    return !cancelled;
  }

  return {
    promise: run(),
    cancel() {
      cancelled = true;
    },
    get isCancelled() {
      return cancelled;
    },
  };
}

/**
 * A delay that can be cancelled, for "show the wrong move, then take it back".
 */
export function createPause(ms) {
  let timer = null;
  let cancelled = false;
  const promise = new Promise((resolve) => {
    timer = setTimeout(() => resolve(!cancelled), ms);
  });
  return {
    promise,
    cancel() {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    },
  };
}
