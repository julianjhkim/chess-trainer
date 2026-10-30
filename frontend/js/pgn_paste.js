/**
 * The PGN paste box.
 *
 * A fallback in both review steps (when chess.com cannot be reached, or the
 * game has not shown up in the archive yet) and at the end of the play step.
 * Starts collapsed so it does not compete with the normal path.
 */

export function createPgnPaste({
  onSubmit,
  summary = 'Paste a PGN instead',
  hint = 'Copy the PGN from the chess.com game page (Share → PGN) and paste it here.',
  submitLabel = 'Use this PGN',
  open = false,
} = {}) {
  const root = document.createElement('details');
  root.className = 'pgn-paste';
  root.open = open;

  const summaryElement = document.createElement('summary');
  summaryElement.textContent = summary;

  const hintElement = document.createElement('p');
  hintElement.className = 'choice-note';
  hintElement.textContent = hint;

  const textarea = document.createElement('textarea');
  textarea.rows = 7;
  textarea.spellcheck = false;
  textarea.placeholder = '[Event "Live Chess"]\n[White "..."]\n[Black "..."]\n\n1. e4 e5 2. Nf3 ...';
  textarea.setAttribute('aria-label', 'PGN text');

  const row = document.createElement('div');
  row.className = 'button-row';

  const submit = document.createElement('button');
  submit.type = 'button';
  submit.className = 'primary';
  submit.textContent = submitLabel;

  const error = document.createElement('span');
  error.className = 'paste-error';

  row.append(submit, error);
  root.append(summaryElement, hintElement, textarea, row);

  submit.addEventListener('click', async () => {
    const pgn = textarea.value.trim();
    if (!pgn) {
      setError('Paste the PGN first.');
      return;
    }
    setError('');
    setBusy(true);
    try {
      await onSubmit(pgn);
    } catch (failure) {
      setError(failure.message || String(failure));
    } finally {
      setBusy(false);
    }
  });

  function setBusy(busy) {
    submit.disabled = busy;
    submit.textContent = busy ? 'Reading PGN…' : submitLabel;
  }

  function setError(message) {
    error.textContent = message;
  }

  function focus() {
    root.open = true;
    textarea.focus();
  }

  return { element: root, setError, setBusy, focus };
}
