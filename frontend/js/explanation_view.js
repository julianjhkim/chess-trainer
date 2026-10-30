/**
 * "Why" — the engine's line after its move and after mine, beside the board.
 *
 * Two blocks, each a headline, a few plain sentences read off the moves, and
 * the line itself. Every move in a line is clickable and shows that position
 * on the board, so the reason can be played through rather than imagined.
 */

export function renderExplanation(explanation, { onShow = null } = {}) {
  const root = document.createElement('div');
  root.className = 'explanation';
  root.append(
    block('Best', explanation.best, 'explain-best', onShow),
    block('You played', explanation.mine, 'explain-mine', onShow),
  );
  return root;
}

function block(title, line, className, onShow) {
  const section = document.createElement('section');
  section.className = `explain-line ${className}`;

  const heading = document.createElement('p');
  heading.className = 'explain-heading';
  const first = line.moves[0];
  heading.textContent = `${title}: ${first ? first.label : '—'}  (${line.evaluation.text})`;
  section.append(heading);

  const notes = document.createElement('ul');
  notes.className = 'explain-notes';
  for (const text of line.notes) {
    const item = document.createElement('li');
    item.textContent = text;
    notes.append(item);
  }
  section.append(notes);

  if (line.moves.length) {
    const moves = document.createElement('div');
    moves.className = 'explain-moves';
    line.moves.forEach((move, index) => {
      const entry = document.createElement('button');
      entry.type = 'button';
      entry.className = 'explain-move';
      // Number every White move, and the first move whoever plays it.
      entry.textContent = index === 0 || move.mover_is_white ? move.label : move.san;
      entry.title = 'Show this position on the board';
      entry.tabIndex = -1;
      entry.addEventListener('mousedown', (event) => event.preventDefault());
      entry.addEventListener('click', () => {
        for (const other of section.ownerDocument.querySelectorAll('.explain-move-current')) {
          other.classList.remove('explain-move-current');
        }
        entry.classList.add('explain-move-current');
        onShow?.(move);
      });
      moves.append(entry);
    });
    section.append(moves);
  }
  return section;
}
