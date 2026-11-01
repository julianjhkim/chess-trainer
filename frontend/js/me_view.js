/**
 * The names I play under, at the right of the top bar.
 *
 * A button shows them; clicking it opens a small editor to add or remove one.
 * They tell the app which side I had in a pasted game (a game is mine if
 * either player has one of these names), so a new account later is just one
 * more name. Every change is saved straight away.
 */

import * as api from './api.js';
import { setStatus } from './state.js';

export function createMeView(container) {
  let names = [];
  let open = false;

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'me-button';
  toggle.setAttribute('aria-haspopup', 'dialog');
  toggle.addEventListener('click', () => setOpen(!open));

  const panel = document.createElement('div');
  panel.className = 'me-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Your names');
  panel.hidden = true;

  container.append(toggle, panel);

  document.addEventListener('mousedown', (event) => {
    if (open && !container.contains(event.target)) setOpen(false);
  });
  document.addEventListener('keydown', (event) => {
    if (open && event.key === 'Escape') setOpen(false);
  });

  load();

  async function load() {
    try {
      names = (await api.getMe()).usernames;
    } catch (error) {
      setStatus(error.message, 'error');
    }
    render();
  }

  async function save(next) {
    try {
      names = (await api.putMe(next)).usernames;
    } catch (error) {
      setStatus(error.message, 'error');
    }
    render();
  }

  function setOpen(value) {
    open = value;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    if (open) panel.querySelector('input')?.focus();
  }

  function render() {
    toggle.textContent = names.length ? `👤 ${names.join(', ')}` : '👤 Add your name';
    toggle.title = 'The names you play under';

    const heading = document.createElement('h3');
    heading.textContent = 'Your names';
    const note = document.createElement('p');
    note.className = 'choice-note';
    note.textContent = 'As they appear in your games (chess.com, Lichess, …). A pasted game is yours if either player has one of them.';

    const list = document.createElement('ul');
    list.className = 'me-list';
    for (const name of names) {
      const item = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = name;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'me-remove';
      remove.textContent = '×';
      remove.title = `Remove ${name}`;
      remove.setAttribute('aria-label', `Remove ${name}`);
      remove.addEventListener('click', () => save(names.filter((n) => n !== name)));
      item.append(label, remove);
      list.append(item);
    }
    if (!names.length) {
      const empty = document.createElement('li');
      empty.className = 'choice-note';
      empty.textContent = 'No names yet.';
      list.append(empty);
    }

    const form = document.createElement('form');
    form.className = 'me-add';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Add a name';
    input.maxLength = 50;
    input.setAttribute('aria-label', 'New name');
    const add = document.createElement('button');
    add.type = 'submit';
    add.textContent = 'Add';
    form.append(input, add);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) return;
      await save([...names, value]);
      panel.querySelector('input')?.focus();
    });

    panel.replaceChildren(heading, note, list, form);
  }

  return { reload: load };
}
