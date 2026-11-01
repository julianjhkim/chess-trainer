/**
 * A minimal observable store.
 *
 * The app is small enough that a dependency-free store beats a framework: views
 * subscribe to the slices they care about and re-render when those change.
 */

const listeners = new Set();

/** @type {{session: object|null, streak: object|null, health: object|null, status: {text: string, kind: string}}} */
const state = {
  session: null,
  streak: null,
  health: null,
  status: { text: '', kind: '' },
};

export function get() {
  return state;
}

/** Shallow-merge a patch into the state and notify subscribers. */
export function set(patch) {
  Object.assign(state, patch);
  for (const listener of listeners) listener(state);
  return state;
}

/** Subscribe to every change. Returns an unsubscribe function. */
export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Set the footer status line. `kind` is '', 'busy' or 'error'. */
export function setStatus(text, kind = '') {
  set({ status: { text, kind } });
}

/** Run an async task while showing a busy status, surfacing errors. */
export async function withStatus(busyText, task) {
  setStatus(busyText, 'busy');
  try {
    const result = await task();
    setStatus('');
    return result;
  } catch (error) {
    setStatus(error.message || String(error), 'error');
    throw error;
  }
}
