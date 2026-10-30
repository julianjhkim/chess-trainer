/**
 * The statistics table shown once a card has been answered.
 *
 * One row per master move: the move, its share, the game count, the
 * white/draw/black split and the average rating. The accepted answer is
 * highlighted, the engine's own move is marked, and a tie the engine broke is
 * noted beneath. The question says only *whether* the most played move was
 * the engine's; this is where you see which move each one was.
 */

const MAX_ROWS = 12;

export function renderStatsTable(table) {
  const root = document.createElement('div');
  root.className = 'stats-wrap';

  if (!table || !table.rows.length) {
    const empty = document.createElement('p');
    empty.className = 'choice-note';
    empty.textContent = 'No master moves recorded for this position.';
    root.append(empty);
    return root;
  }

  const caption = document.createElement('p');
  caption.className = 'choice-note stats-caption';
  caption.textContent = `${table.total_games.toLocaleString()} master games in this position`;
  root.append(caption);

  const element = document.createElement('table');
  element.className = 'stats-table';

  const head = document.createElement('thead');
  head.append(headRow(['Move', '%', 'Games', 'W / D / L', 'Avg']));
  element.append(head);

  const body = document.createElement('tbody');
  for (const row of table.rows.slice(0, MAX_ROWS)) {
    body.append(bodyRow(row));
  }
  element.append(body);
  root.append(element);

  if (table.rows.length > MAX_ROWS) {
    const more = document.createElement('p');
    more.className = 'choice-note';
    more.textContent = `… and ${table.rows.length - MAX_ROWS} rarer move${
      table.rows.length - MAX_ROWS === 1 ? '' : 's'
    }.`;
    root.append(more);
  }

  for (const note of [table.engine_note, table.tie_note]) {
    if (!note) continue;
    const paragraph = document.createElement('p');
    paragraph.className = 'stats-note';
    paragraph.textContent = note;
    root.append(paragraph);
  }

  return root;
}

function headRow(labels) {
  const row = document.createElement('tr');
  for (const [index, label] of labels.entries()) {
    const cell = document.createElement('th');
    cell.textContent = label;
    if (index > 0) cell.className = 'numeric';
    row.append(cell);
  }
  return row;
}

function bodyRow(row) {
  const element = document.createElement('tr');
  element.classList.toggle('stats-answer', row.is_answer);

  const move = document.createElement('td');
  move.className = 'mono stats-move';
  move.textContent = row.san;
  if (row.is_answer) move.append(badge('answer', 'badge-answer'));
  // On a frequency card the answer *is* the most played move, so saying both
  // would be noise; the badge is for the cards where they come apart.
  if (row.is_most_played && !row.is_answer) {
    move.append(badge('most played', 'badge-played'));
  }
  if (row.is_engine_move) move.append(badge('engine', 'badge-engine'));
  if (row.is_tied) move.append(badge('tied', 'badge-tied'));

  element.append(
    move,
    numeric(`${row.share.toFixed(1)}%`),
    numeric(row.games.toLocaleString()),
    wdl(row),
    numeric(row.average_rating == null ? '—' : String(row.average_rating)),
  );
  return element;
}

function numeric(text) {
  const cell = document.createElement('td');
  cell.className = 'numeric mono';
  cell.textContent = text;
  return cell;
}

/** The white/draw/black split, as a small stacked bar plus the numbers. */
function wdl(row) {
  const cell = document.createElement('td');
  cell.className = 'numeric';

  const bar = document.createElement('span');
  bar.className = 'wdl-bar';
  bar.title = `${row.white} white wins, ${row.draws} draws, ${row.black} black wins`;
  for (const [key, percent] of [
    ['white', row.white_percent],
    ['draw', row.draw_percent],
    ['black', row.black_percent],
  ]) {
    const segment = document.createElement('span');
    segment.className = `wdl-${key}`;
    segment.style.width = `${percent}%`;
    bar.append(segment);
  }

  const text = document.createElement('span');
  text.className = 'mono wdl-text';
  text.textContent = `${Math.round(row.white_percent)}/${Math.round(
    row.draw_percent,
  )}/${Math.round(row.black_percent)}`;

  cell.append(bar, text);
  return cell;
}

function badge(text, className) {
  const element = document.createElement('span');
  element.className = `badge ${className}`;
  element.textContent = text;
  return element;
}
