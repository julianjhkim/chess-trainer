/**
 * Chessground wrapper.
 *
 * Owns the board instance and the current FEN, and asks the backend for legal
 * destinations so the browser carries no rules engine of its own. Callers get a
 * `onMove(move)` callback with the SAN/UCI the server resolved.
 */

import { Chessground } from '../vendor/chessground/chessground.js';
import * as api from './api.js';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

/**
 * Every live board, newest last.
 *
 * `app.js` hands this to `window.chessTrainer` so a board can be inspected
 * from the console, and the browser tests use it to read chessground's own
 * state (cached bounds, selection) rather than guessing from the DOM.
 */
export const boards = new Set();

/** Convert the API's `dests` object into the Map chessground expects. */
function toDestsMap(dests) {
  return new Map(Object.entries(dests ?? {}));
}

export function createBoard({
  fen = START_FEN,
  orientation = 'white',
  interactive = true,
  onMove = null,
  animationMs = 220,
} = {}) {
  const element = document.createElement('div');
  element.className = 'cg-wrap';

  let currentFen = fen;
  let moveHandler = onMove;
  let enabled = interactive;
  /** Last position state from the server, so a restriction can be undone. */
  let lastState = null;
  let destroyed = false;

  const ground = Chessground(element, {
    fen,
    orientation,
    animation: { enabled: true, duration: animationMs },
    highlight: { lastMove: true, check: true },
    movable: { free: false, color: undefined, dests: new Map(), showDests: true },
    draggable: { enabled: interactive, showGhost: true },
    drawable: { enabled: true, visible: true },
    events: { move: handleUserMove },
  });

  // -- geometry ----------------------------------------------------------
  /*
   * Chessground measures the board once and caches that rectangle: clicks,
   * drags and arrows are all resolved against it. It drops the cache on a
   * window resize, on a scroll, and when the board's own box changes size —
   * but not when the board merely *moves*, and moving is exactly what happens
   * here. The views centre the board next to a side panel that grows as
   * content lands in it (the opening name, the stats table, the attempts
   * list), which slides the board sideways without changing its size. The
   * cached rectangle then sits a fraction of a square from the real one and a
   * click on e2 is read as d2.
   *
   * So watch the board and every box it is laid out inside, and redraw
   * whenever its on-screen rectangle actually moves or resizes. `redrawAll`
   * is what both re-measures and re-renders the arrows, which are scaled from
   * the same rectangle — drawn at a stale size they come out as NaN and
   * vanish.
   */
  let lastRect = null;
  let syncQueued = false;
  const observed = new Set();
  // Deferred, not straight to `syncGeometry`: several boxes can report a new
  // size for one layout change, and that is one re-measure. Measuring inside
  // the observer's own callback would also risk a resize loop.
  const observer =
    typeof ResizeObserver === 'function' ? new ResizeObserver(scheduleSync) : null;
  if (observer) observer.observe(element);

  /** Watch every ancestor box, since the board moves when one of them grows. */
  function observeLayout() {
    if (!observer) return;
    for (let node = element.parentElement; node; node = node.parentElement) {
      if (observed.has(node)) continue;
      observed.add(node);
      observer.observe(node);
    }
  }

  function movedSince(rect) {
    return (
      lastRect === null ||
      Math.abs(lastRect.left - rect.left) > 0.1 ||
      Math.abs(lastRect.top - rect.top) > 0.1 ||
      Math.abs(lastRect.width - rect.width) > 0.1 ||
      Math.abs(lastRect.height - rect.height) > 0.1
    );
  }

  /**
   * Re-measure if the board has moved. Cheap and idempotent: when nothing has
   * moved it does nothing, which is also what stops a redraw from feeding the
   * observer that triggered it.
   */
  function syncGeometry() {
    syncQueued = false;
    if (destroyed) return;
    observeLayout();

    const rect = element.getBoundingClientRect();
    // Not laid out yet (the views build a board before inserting it).
    if (!rect.width || !rect.height) return;
    if (!movedSince(rect)) return;
    lastRect = rect;

    // Mid-drag, dropping the cached rectangle is enough and rebuilding the
    // DOM under the pointer would cancel the drag; the next sync redraws.
    if (ground.state.draggable.current) {
      ground.state.dom.bounds.clear();
      lastRect = null;
      return;
    }
    ground.redrawAll();
  }

  /**
   * Re-measure now, because the caller has just changed something around the
   * board.
   *
   * Deliberately synchronous. A board is built detached and measures nothing,
   * so until the first re-measure every click falls outside the board and is
   * dropped; waiting a frame for that would leave the board live but deaf for
   * as long as it takes to paint. The forced layout costs a view re-render,
   * and after the first one it is a no-op: nothing moved, nothing to redraw.
   */
  function refresh() {
    if (destroyed) return;
    syncGeometry();
  }

  /** Re-measure on the next frame, coalescing a burst of observer events. */
  function scheduleSync() {
    if (destroyed || syncQueued) return;
    syncQueued = true;
    requestAnimationFrame(syncGeometry);
  }

  async function handleUserMove(from, to) {
    if (!enabled) return;
    try {
      const result = await api.playMove(currentFen, from, to);
      currentFen = result.fen;
      applyState(result.state, [from, to]);
      if (moveHandler) await moveHandler(result);
    } catch (error) {
      // The server rejected it: snap back to the authoritative position.
      await setFen(currentFen);
      throw error;
    }
  }

  /** Push a server-provided position state into chessground. */
  function applyState(state, lastMove = undefined) {
    lastState = state;
    ground.set({
      fen: state.fen,
      turnColor: state.turn,
      check: state.in_check ? state.turn : false,
      lastMove,
      movable: {
        free: false,
        color: enabled && !state.game_over ? state.turn : undefined,
        dests: toDestsMap(state.dests),
        showDests: true,
      },
    });
  }

  /** Jump to a position, fetching its legal moves. */
  async function setFen(nextFen, { lastMove } = {}) {
    currentFen = nextFen;
    const state = await api.boardState(nextFen);
    applyState(state, lastMove);
    return state;
  }

  /** Play a move on the board without user input (used by auto-replay). */
  async function pushMove(uci) {
    const from = uci.slice(0, 2);
    const to = uci.slice(2, 4);
    const promotion = uci.length > 4 ? uci[4] : undefined;
    const result = await api.playMove(currentFen, from, to, promotion);
    currentFen = result.fen;
    applyState(result.state, [from, to]);
    return result;
  }

  function setOrientation(color) {
    ground.set({ orientation: color });
  }

  function flip() {
    ground.toggleOrientation();
  }

  // Named distinctly from the `orientation` parameter: a function declaration
  // sharing a parameter's name overwrites that binding for the whole body,
  // which would hand chessground this function instead of the colour.
  function currentOrientation() {
    return ground.state.orientation;
  }

  /** Enable or disable piece dragging (e.g. during auto-replay). */
  function setInteractive(value) {
    enabled = value;
    ground.set({
      draggable: { enabled: value },
      movable: { color: value ? ground.state.turnColor : undefined },
    });
  }

  function setMoveHandler(handler) {
    moveHandler = handler;
  }

  /** Draw arrows; `shapes` is a list of `{orig, dest, brush}`. */
  function setShapes(shapes) {
    ground.setShapes(shapes ?? []);
  }

  /**
   * Allow only one move to be played.
   *
   * An opening card shows its branch move as an arrow and expects that move to
   * be played; restricting the legal destinations makes the board say so
   * rather than letting a wrong drag through to be rejected.
   */
  function restrictTo(uci) {
    const from = uci.slice(0, 2);
    const to = uci.slice(2, 4);
    ground.set({
      movable: {
        free: false,
        color: enabled ? ground.state.turnColor : undefined,
        dests: new Map([[from, [to]]]),
        showDests: true,
      },
    });
  }

  /** Undo `restrictTo`, restoring every legal move. */
  function clearRestriction() {
    if (lastState) applyState(lastState);
  }

  function getFen() {
    return currentFen;
  }

  function destroy() {
    destroyed = true;
    boards.delete(handle);
    observer?.disconnect();
    ground.destroy();
  }

  const handle = {
    element,
    ground,
    refresh,
    setFen,
    pushMove,
    setOrientation,
    orientation: currentOrientation,
    flip,
    setInteractive,
    setMoveHandler,
    setShapes,
    restrictTo,
    clearRestriction,
    getFen,
    destroy,
    START_FEN,
  };

  boards.add(handle);
  return handle;
}

export { START_FEN };
