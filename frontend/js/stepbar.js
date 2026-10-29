/**
 * The step bar: all four steps, always visible, each one clickable.
 *
 * Clicking any step jumps there, forwards or backwards — including a step that
 * was left unchecked on the start screen, which selects it on the way.
 */

import * as api from './api.js';
import { set, withStatus } from './state.js';

export function createStepBar(container, { onJump } = {}) {
  function render(session) {
    container.replaceChildren();
    if (!session) return;

    for (const step of session.steps) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'step';
      button.classList.toggle('current', step.current);
      button.classList.toggle('completed', step.completed);
      button.classList.toggle('disabled', !step.enabled);
      button.setAttribute('aria-current', step.current ? 'step' : 'false');
      button.title = step.enabled
        ? `Go to step ${step.position}: ${step.title}`
        : `Step ${step.position} is unchecked — click to run it anyway`;

      const num = document.createElement('span');
      num.className = 'step-num';
      num.textContent = step.completed ? '✓' : String(step.position);

      const label = document.createElement('span');
      label.textContent = step.title;

      button.append(num, label);
      button.addEventListener('click', () => jump(step.step));
      container.append(button);
    }
  }

  async function jump(stepName) {
    const session = await withStatus('Switching step…', () => api.jumpToStep(stepName));
    set({ session });
    if (onJump) onJump(session);
  }

  return { render };
}
