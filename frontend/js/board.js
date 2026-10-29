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

  function getFen() {
    return currentFen;
  }

  function destroy() {
    ground.destroy();
  }

  return {
    element,
    ground,
    setFen,
    pushMove,
    setOrientation,
    orientation: currentOrientation,
    flip,
    setInteractive,
    setMoveHandler,
    setShapes,
    getFen,
    destroy,
    START_FEN,
  };
}

export { START_FEN };
