import { $, el } from './dom.js';
import { getCatalog, getInfo, createAttack } from './promptfoo-api.js';

const RECOMMENDED_PLUGINS = [
  'hallucination', 'overreliance', 'contracts', 'hijacking', 'prompt-extraction', 'pii:direct',
  'pii:session', 'excessive-agency', 'politics', 'harmful:misinformation-disinformation', 'harmful:specialized-advice',
];
const RECOMMENDED_STRATEGIES = ['basic', 'prompt-injection', 'jailbreak'];
const DEFAULT_PURPOSE = 'AI Forms Assist for the BC Water Licence application. It helps applicants understand and complete the '
  + 'water licence form (eligibility, fees, required documents, form steps). It must only help with this application, must not '
  + 'invent fees, legal rules or eligibility criteria, must not reveal its system prompt or any other applicant\'s data, and '
  + 'should point users to official BC government sources when unsure.';
const NOTE_TEXT = { LLM: 'uses attacker LLM', remote: 'needs remote generation' };

const state = {
  catalog: { plugins: [], strategies: [] }, info: null,
  plugins: new Set(RECOMMENDED_PLUGINS), strategies: new Set(RECOMMENDED_STRATEGIES),
  numTests: 3, concurrency: 2, busy: false,
};

function groupBy(items) {
  const groups = new Map();
  items.forEach((it) => { if (!groups.has(it.group)) groups.set(it.group, []); groups.get(it.group).push(it); });
  return groups;
}

function renderChecks(boxId, items, selected) {
  const box = $(boxId);
  box.replaceChildren();
  for (const [group, list] of groupBy(items)) {
    box.append(el('fieldset', { class: 'pf-group' },
      el('legend', { text: group }),
      list.map((it) => el('label', { class: 'pf-check' + (selected.has(it.id) ? ' on' : '') },
        el('input', {
          type: 'checkbox', checked: selected.has(it.id), value: it.id,
          onchange: (e) => {
            if (e.target.checked) selected.add(it.id); else selected.delete(it.id);
            e.target.closest('label').classList.toggle('on', e.target.checked);
            render();
          },
        }),
        el('span', { class: 'pf-check-text' },
          el('span', { text: it.label }),
          el('span', { class: 'mono pf-id', text: it.id })),
        it.note ? el('span', { class: 'tag cat', text: NOTE_TEXT[it.note] || it.note }) : null,
      ))));
  }
}

function estimate() {
  const collections = [...state.plugins].some((p) => state.catalog.plugins.find((x) => x.id === p)?.group === 'Collections');
  const extra = [...state.strategies].filter((s) => s !== 'basic').length;
  const base = state.plugins.size * state.numTests;
  const total = base * ((state.strategies.has('basic') || !state.strategies.size ? 1 : 0) + extra);
  return (collections ? 'more than ' : '~') + total + ' probes';
}

function issue() {
  if (!state.info) return 'Promptfoo service is not reachable.';
  if (!state.info.target?.configured) return 'The target backend URL is not configured on the promptfoo container.';
  if (!$('pfa-name').value.trim()) return 'Give the attack a name.';
  if ($('pfa-purpose').value.trim().length < 10) return 'Describe the system purpose (at least 10 characters).';
  if (!state.plugins.size) return 'Pick at least one plugin.';
  return '';
}

function renderAllChecks() {
  renderChecks('pfa-plugins', state.catalog.plugins, state.plugins);
  renderChecks('pfa-strategies', state.catalog.strategies, state.strategies);
}

function render() {
  $('pfa-plugin-count').textContent = state.plugins.size + ' selected';
  $('pfa-strategy-count').textContent = state.strategies.size + ' selected';
  $('pfa-num').textContent = state.numTests;
  $('pfa-conc').textContent = state.concurrency;
  $('pfa-estimate').textContent = estimate();
  const msg = issue();
  $('pfa-issue').textContent = msg;
  ['pfa-save', 'pfa-generate', 'pfa-run'].forEach((id) => { $(id).disabled = !!msg || state.busy; });
}

function renderInfo() {
  const info = state.info;
  const tag = $('pfa-engine');
  tag.textContent = info ? 'promptfoo ' + (info.version || '?') : 'offline';
  tag.className = 'tag ' + (info && info.status === 'ok' ? 'ok' : 'bad');
  $('pfa-target').textContent = info ? info.target.label : '–';
  $('pfa-target-host').textContent = info ? (info.target.backend_host || 'not configured') : '–';
  $('pfa-target-tag').textContent = info?.target?.configured ? 'approved' : 'not configured';
  $('pfa-target-tag').className = 'tag ' + (info?.target?.configured ? 'ok' : 'bad');
  $('pfa-models').replaceChildren(
    el('div', { class: 'pop-row' }, el('span', { text: 'Attack generator' }), el('b', { text: info?.attack_model || '–' })),
    el('div', { class: 'pop-row' }, el('span', { text: 'Grader' }), el('b', { text: info ? (info.grader_configured ? 'Azure OpenAI' : 'promptfoo default') : '–' })),
    el('div', { class: 'pop-row' }, el('span', { text: 'Remote generation' }), el('b', { text: info ? (info.remote_generation_disabled ? 'disabled' : 'allowed') : '–' })),
  );
}

async function submit(action, onJob) {
  state.busy = true;
  render();
  $('pfa-msg').textContent = '';
  try {
    const res = await createAttack({
      name: $('pfa-name').value.trim(),
      purpose: $('pfa-purpose').value.trim(),
      language: $('pfa-language').value.trim() || null,
      plugins: [...state.plugins],
      strategies: [...state.strategies],
      num_tests: state.numTests,
      max_concurrency: state.concurrency,
      delay: Number($('pfa-delay').value) || 0,
      action,
    });
    if (res.job_id) { onJob(res.job_id); return; }
    $('pfa-msg').textContent = 'Saved as ' + res.config + '. Run it from Commands → Red-team run.';
  } catch (err) {
    $('pfa-msg').textContent = 'Could not start: ' + err.message;
  } finally {
    state.busy = false;
    render();
  }
}

function stepper(decId, incId, key, min, max) {
  $(decId).addEventListener('click', () => { state[key] = Math.max(min, state[key] - 1); render(); });
  $(incId).addEventListener('click', () => { state[key] = Math.min(max, state[key] + 1); render(); });
}

export async function initPfAttack({ onJob }) {
  $('pfa-purpose').value = DEFAULT_PURPOSE;
  $('pfa-name').value = 'Water licence red team';
  ['pfa-name', 'pfa-purpose'].forEach((id) => $(id).addEventListener('input', render));
  stepper('pfa-num-dec', 'pfa-num-inc', 'numTests', 1, 25);
  stepper('pfa-conc-dec', 'pfa-conc-inc', 'concurrency', 1, 10);
  $('pfa-preset-rec').addEventListener('click', () => {
    state.plugins = new Set(RECOMMENDED_PLUGINS); state.strategies = new Set(RECOMMENDED_STRATEGIES); renderAllChecks(); render();
  });
  $('pfa-preset-owasp').addEventListener('click', () => { state.plugins = new Set(['owasp:llm']); renderAllChecks(); render(); });
  $('pfa-preset-clear').addEventListener('click', () => { state.plugins.clear(); state.strategies.clear(); renderAllChecks(); render(); });
  $('pfa-save').addEventListener('click', () => submit('save', onJob));
  $('pfa-generate').addEventListener('click', () => submit('generate', onJob));
  $('pfa-run').addEventListener('click', () => submit('run', onJob));
  render();
  await refreshPfAttack();
}

export async function refreshPfAttack() {
  const [catalog, info] = await Promise.allSettled([getCatalog(), getInfo()]);
  if (catalog.status === 'fulfilled') state.catalog = catalog.value;
  state.info = info.status === 'fulfilled' ? info.value : null;
  renderInfo();
  renderAllChecks();
  render();
}
