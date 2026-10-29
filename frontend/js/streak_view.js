/**
 * Streak display: current and longest, on an Asia/Seoul day boundary.
 *
 * A day counts once at least one step has been completed on it.
 */

export function createStreakView(container) {
  function render(streak) {
    container.replaceChildren();
    if (!streak) return;

    container.append(
      field(streak.active_today ? '🔥' : '·', 'Current', `${streak.current}`, 'flame'),
      field('', 'Best', `${streak.longest}`),
    );
    container.title = streak.active_today
      ? 'A step has been completed today — the streak is safe.'
      : 'No step completed today yet (Asia/Seoul day).';
  }

  function field(icon, label, value, extraClass = '') {
    const wrap = document.createElement('span');
    if (extraClass) wrap.classList.add(extraClass);
    wrap.append(
      document.createTextNode(icon ? `${icon} ` : ''),
      document.createTextNode(`${label} `),
    );
    const strong = document.createElement('b');
    strong.textContent = value;
    wrap.append(strong);
    return wrap;
  }

  return { render };
}
