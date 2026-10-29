/**
 * The eval bar: a vertical White-share bar plus the numeric evaluation.
 *
 * Always White's perspective, as the spec requires, so the number means the
 * same thing in every view. `update` is called after every move the user makes,
 * including wrong retries, so each attempt's cost is visible.
 */

export function createEvalBar() {
  const root = document.createElement('div');
  root.className = 'evalbar';

  const number = document.createElement('div');
  number.className = 'evalbar-number pending';
  number.textContent = '—';
  number.title = "Evaluation from White's perspective";

  const track = document.createElement('div');
  track.className = 'evalbar-track';

  const white = document.createElement('div');
  white.className = 'evalbar-white';
  white.style.height = '50%';

  const mid = document.createElement('div');
  mid.className = 'evalbar-mid';

  track.append(white, mid);
  root.append(number, track);

  /** Show an evaluation payload from the API (`{text, fraction}`). */
  function update(evaluation) {
    if (!evaluation) return clear();
    number.textContent = evaluation.text;
    number.classList.remove('pending');
    white.style.height = `${(evaluation.fraction * 100).toFixed(2)}%`;
  }

  /** Mark the bar as waiting for the engine, keeping the last height. */
  function pending() {
    number.classList.add('pending');
    number.textContent = '…';
  }

  function clear() {
    number.classList.add('pending');
    number.textContent = '—';
    white.style.height = '50%';
  }

  return { element: root, update, pending, clear };
}
