/**
 * Arrows drawn on the board.
 *
 * An opening card shows its branch move as an arrow for you to play; the move
 * you then have to find is never shown. After a card is answered the accepted
 * move is highlighted the same way.
 */

/** chessground brushes, by what the arrow means. */
export const BRUSH = {
  given: 'blue',
  answer: 'green',
  wrong: 'red',
  hint: 'yellow',
};

/** One arrow from a UCI move, e.g. `move('e2e4')`. */
export function move(uci, brush = BRUSH.given) {
  if (!uci || uci.length < 4) return null;
  return { orig: uci.slice(0, 2), dest: uci.slice(2, 4), brush };
}

/** A shapes list for chessground, dropping anything unusable. */
export function shapes(...entries) {
  return entries.filter((entry) => entry !== null && entry !== undefined);
}

/** The arrow for a card's given move. */
export function givenMove(uci) {
  return shapes(move(uci, BRUSH.given));
}

/** The arrow for a card's accepted answer. */
export function answerMove(uci) {
  return shapes(move(uci, BRUSH.answer));
}
