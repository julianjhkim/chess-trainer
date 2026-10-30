/**
 * Decides which view the main area shows.
 *
 * The step bar drives this: whatever step the session says is current gets
 * rendered. Before the session is started, the start screen is shown; once
 * every selected step is done, a short summary.
 */

import { renderPlaceholder } from './placeholder_view.js';
import { renderPlayView } from './play_view.js';
import { renderReviewView } from './review_view.js';
import { renderStartScreen } from './start_screen.js';

export function createRouter(container, { onStarted, onCompleted }) {
  let active = null;

  function render(session) {
    if (active && active.destroy) active.destroy();
    active = null;

    if (!session) return;

    if (!session.started) {
      renderStartScreen(container, { session, onStarted });
      return;
    }

    if (session.finished || session.current === null) {
      renderFinished(container, session);
      return;
    }

    const step = session.steps.find((s) => s.step === session.current);
    active = renderStep(container, { session, step, onStarted, onCompleted });
  }

  return { render };
}

/** Pick the view for a step. Opening cards are still a Phase 3 scaffold. */
function renderStep(container, { session, step, onCompleted }) {
  const handleCompleted = (nextSession, options = {}) => {
    if (options.rerender === false) return;
    if (onCompleted) onCompleted(nextSession);
  };

  switch (step.step) {
    case 'review_last_game':
    case 'review_new_game':
      return renderReviewView(container, { step, onCompleted: handleCompleted });
    case 'play':
      return renderPlayView(container, { step, onCompleted });
    default:
      return renderPlaceholder(container, { session, step, onCompleted });
  }
}

function renderFinished(container, session) {
  container.replaceChildren();

  const panel = document.createElement('section');
  panel.className = 'panel';

  const heading = document.createElement('h2');
  heading.textContent = 'Session complete';

  const sub = document.createElement('p');
  sub.className = 'sub';
  const completed = session.steps.filter((s) => s.completed).length;
  sub.textContent = `${completed} step${completed === 1 ? '' : 's'} finished. Click any step above to go back to it.`;

  panel.append(heading, sub);
  container.append(panel);
}
