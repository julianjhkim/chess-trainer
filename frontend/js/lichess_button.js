/**
 * "Analyse at Lichess ↗": a link that looks like a button, for the row under
 * the board next to *Next card*. Opens Lichess's analysis board in a new tab;
 * nothing is sent to Lichess unless it is clicked.
 */

export function lichessButton(url) {
  const link = document.createElement('a');
  link.className = 'button-link lichess-link';
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = 'Analyse at Lichess ↗';
  return link;
}
