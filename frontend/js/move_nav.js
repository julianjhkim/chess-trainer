/**
 * Stepping back and forth through a game's moves.
 *
 * A cursor over the positions of a move list: position 0 is before the first
 * move, position i is after move i. The view decides what to draw; this only
 * says where the cursor is and tells it when that changes.
 *
 * One position may sit *beside* the game rather than in it: the engine's move
 * at my first inaccuracy, shown once the review is over. That "aside" lives
 * between the position before my move and the one after it, so ← from it goes
 * back to where I went wrong and → goes on to the move I actually played.
 *
 * No DOM beyond the keyboard binding, so the cursor logic is testable alone.
 */

const FIRST_KEYS = new Set(['Home', 'ArrowUp']);
const LAST_KEYS = new Set(['End', 'ArrowDown']);

/**
 * `moves` is the review's move list (`{uci, fen_before, fen_after, ...}`).
 * `onChange(view)` gets `{index, aside, fen, lastMove, move}` after every move
 * of the cursor; `lastMove` is a UCI string or null.
 */
export function createMoveNav({ moves = [], index = null, onChange = null } = {}) {
  let list = moves;
  let cursor = index ?? list.length;
  /** Index of the position the aside follows, or null when there is none. */
  let asideAfter = null;
  let onAside = false;
  let asideView = null;

  function clamp(value) {
    return Math.max(0, Math.min(list.length, value));
  }

  function view() {
    if (onAside) {
      return { index: asideAfter, aside: true, ...asideView };
    }
    const move = cursor > 0 ? list[cursor - 1] : null;
    return {
      index: cursor,
      aside: false,
      fen: move ? move.fen_after : (list[0]?.fen_before ?? null),
      lastMove: move ? move.uci : null,
      move,
    };
  }

  function changed() {
    if (onChange) onChange(view());
  }

  function go(next) {
    const target = clamp(next);
    if (!onAside && target === cursor) return false;
    onAside = false;
    cursor = target;
    changed();
    return true;
  }

  function back() {
    if (onAside) return go(asideAfter);
    return go(cursor - 1);
  }

  function forward() {
    if (onAside) return go(asideAfter + 1);
    return go(cursor + 1);
  }

  return {
    go,
    back,
    forward,
    first: () => go(0),
    last: () => go(list.length),

    /** Replace the move list, keeping the cursor where it was if it still fits. */
    setMoves(next, { index: at = null } = {}) {
      list = next;
      cursor = clamp(at ?? cursor);
      onAside = false;
    },

    /**
     * Put a position beside the game, after position `after`, and move onto it.
     * `fen` and `lastMove` describe what to draw there; anything else given
     * (arrows, say) is handed back in the view untouched.
     */
    showAside({ after, fen, lastMove, move = null, ...extra }) {
      asideAfter = after;
      asideView = { ...extra, fen, lastMove, move };
      onAside = true;
      cursor = after;
      changed();
    },

    /** Return to the aside, if there is one. */
    returnToAside() {
      if (asideAfter === null) return false;
      onAside = true;
      cursor = asideAfter;
      changed();
      return true;
    },

    get index() {
      return cursor;
    },
    get length() {
      return list.length;
    },
    get onAside() {
      return onAside;
    },
    get atEnd() {
      return !onAside && cursor === list.length;
    },
    view,
  };
}

/**
 * Drive `nav` from the keyboard: ← / → step, Home / ↑ to the start, End / ↓ to
 * the end. `enabled()` is asked on every key, so the view can mute it while
 * the board is busy (an auto-replay, a move being judged). Keys typed into a
 * text field -- the PGN paste box -- are left alone.
 *
 * Returns a function that removes the binding.
 */
export function bindArrowKeys(nav, { enabled = () => true, target = document } = {}) {
  function onKey(event) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (isTyping(event.target)) return;

    let action = null;
    if (event.key === 'ArrowLeft') action = nav.back;
    else if (event.key === 'ArrowRight') action = nav.forward;
    else if (FIRST_KEYS.has(event.key)) action = nav.first;
    else if (LAST_KEYS.has(event.key)) action = nav.last;
    if (!action) return;

    // Arrows would otherwise scroll the page, which also moves the board.
    event.preventDefault();
    if (enabled()) action();
  }

  target.addEventListener('keydown', onKey);
  return () => target.removeEventListener('keydown', onKey);
}

function isTyping(element) {
  if (!element || !element.tagName) return false;
  const tag = element.tagName.toLowerCase();
  return tag === 'textarea' || tag === 'input' || tag === 'select' || element.isContentEditable;
}
