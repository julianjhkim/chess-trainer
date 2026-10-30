/**
 * The game score beside the review board: `1. e4 e5  2. Nf3 …`.
 *
 * Built once per move list and then only re-highlighted, so stepping through
 * the game with the arrow keys never rebuilds the panel (a rebuild can change
 * its height, which slides the board). Clicking a move jumps there.
 */

export function createMoveList({ onSelect = null } = {}) {
  const element = document.createElement('div');
  element.className = 'move-list';

  /** One entry per move, in game order; entry i is the position after move i. */
  let entries = [];

  /**
   * `moves` as the review sends them. `marked` is the ply of my first
   * inaccuracy, shown once the review is over, or null.
   */
  function setMoves(moves, { marked = null } = {}) {
    element.replaceChildren();
    entries = [];

    if (!moves.length) {
      const empty = document.createElement('p');
      empty.className = 'choice-note';
      empty.style.margin = '0';
      empty.textContent = 'No moves before this position.';
      element.append(empty);
      return;
    }

    let row = null;
    for (const move of moves) {
      if (move.mover_is_white || row === null) {
        row = document.createElement('div');
        row.className = 'move-row';
        const number = document.createElement('span');
        number.className = 'move-number';
        number.textContent = `${move.move_number}.`;
        row.append(number);
        if (!move.mover_is_white) row.append(placeholder());
        element.append(row);
      }

      const entry = document.createElement('button');
      entry.type = 'button';
      entry.className = 'move';
      if (move.is_mine) entry.classList.add('move-mine');
      if (marked !== null && move.ply === marked) entry.classList.add('move-inaccuracy');
      entry.textContent = move.san;
      entry.title = move.label;
      // Keep focus off the button: a focused button would take the arrow keys'
      // place as the thing Space/Enter acts on, and it draws a ring.
      entry.tabIndex = -1;
      entry.addEventListener('mousedown', (event) => event.preventDefault());
      entry.addEventListener('click', () => onSelect?.(move.ply + 1));
      row.append(entry);
      entries.push(entry);
    }
  }

  /** Highlight the move leading to position `index` (0 highlights nothing). */
  function setCurrent(index) {
    entries.forEach((entry, i) => entry.classList.toggle('move-current', i === index - 1));
    const current = entries[index - 1];
    if (current) keepInView(current);
  }

  /**
   * Scroll the list, never the page, so the current move stays visible.
   * `scrollIntoView` would scroll every scrollable ancestor too, and moving
   * the page moves the board.
   */
  function keepInView(entry) {
    // The list is `position: relative`, so offsets are measured from it.
    const top = entry.offsetTop;
    const bottom = top + entry.offsetHeight;
    if (top < element.scrollTop) element.scrollTop = top;
    else if (bottom > element.scrollTop + element.clientHeight) {
      element.scrollTop = bottom - element.clientHeight;
    }
  }

  return { element, setMoves, setCurrent };
}

function placeholder() {
  const span = document.createElement('span');
  span.className = 'move move-placeholder';
  span.textContent = '…';
  return span;
}
