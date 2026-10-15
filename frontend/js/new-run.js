import { getTenants, getDatasets, getConverters, startRun, LLM_CONVERTERS } from './api.js';

// Fixed product options (not data from the backend). Ids are the backend's values.
const MODES = [
  { id: 'pyrit-scan', name: 'PyRIT scan' },
];
const ATTACKS = [
  { id: 'PromptSending', name: 'Prompt sending' },
  { id: 'Crescendo', name: 'Crescendo', llm: true },
  { id: 'MultiTurn', name: 'Multi-turn', llm: true },
  { id: 'RedTeaming', name: 'Red teaming', llm: true },
];
const LLM_NOTE = ' needs the Azure OpenAI attacker/judge model. It only works where that endpoint is reachable (e.g. the deployed environment).';

const $ = (id) => document.getElementById(id);
const state = { tenants: [], datasets: [], converters: [], source: 'saved', repeats: 5, stack: [], starting: false };

function fillSelect(select, items, label, emptyText) {
  select.replaceChildren();
  if (!items.length) {
    select.add(new Option(emptyText, ''));
    return;
  }
  items.forEach((it) => select.add(new Option(label(it), it.id)));
}

const selected = (list, selectId) => list.find((x) => String(x.id) === $(selectId).value);
const customQuestions = () => $('custom-text').value.split('\n').map((l) => l.trim()).filter(Boolean);
const converterName = (id) => (state.converters.find((x) => String(x.id) === String(id)) || {}).name || id;

function questionCount() {
  if (state.source === 'custom') return customQuestions().length;
  const ds = selected(state.datasets, 'dataset');
  return ds ? ds.case_count || 0 : 0;
}

function issue() {
  const t = selected(state.tenants, 'tenant');
  if (!t) return 'Choose a system to test.';
  if (!t.approved) return 'This system is not approved for testing.';
  if (questionCount() === 0) return 'Add at least one question to start.';
  return '';
}

function render() {
  // tenant status tag
  const t = selected(state.tenants, 'tenant');
  const tag = $('tenant-status');
  tag.textContent = t ? (t.approved ? 'approved' : 'not approved') : '';
  tag.className = 'tag ' + (t ? (t.approved ? 'ok' : 'bad') : '');

  // source toggle
  const saved = state.source === 'saved';
  $('src-saved').classList.toggle('on', saved);
  $('src-custom').classList.toggle('on', !saved);
  $('saved-box').hidden = !saved;
  $('custom-box').hidden = saved;
  $('custom-count').textContent = customQuestions().length + ' questions';

  // attack + repeats
  const attack = selected(ATTACKS, 'attack');
  $('attack-note').hidden = !attack?.llm;
  $('attack-note').textContent = attack?.llm ? attack.name + LLM_NOTE : '';
  $('rep-val').textContent = state.repeats;

  // converter chips (textContent only, never innerHTML)
  const chips = $('conv-chips');
  chips.replaceChildren();
  state.stack.forEach((id, i) => {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.append((i + 1) + '. ' + converterName(id) + ' ');
    const x = document.createElement('button');
    x.type = 'button';
    x.textContent = '×';
    x.setAttribute('aria-label', 'Remove ' + converterName(id));
    x.addEventListener('click', () => { state.stack.splice(i, 1); render(); });
    chip.append(x);
    chips.append(chip);
  });
  $('conv-empty').hidden = state.stack.length > 0;
  const llmConv = state.stack.find((id) => LLM_CONVERTERS.includes(id));
  $('conv-note').hidden = !llmConv;
  $('conv-note').textContent = llmConv ? converterName(llmConv).split(' ·')[0] + LLM_NOTE : '';

  // start button + issue
  const msg = issue();
  $('run-issue').textContent = msg;
  $('start').disabled = msg !== '' || state.starting;

  renderDetails();
}

function renderDetails() {
  const t = selected(state.tenants, 'tenant');
  const ds = selected(state.datasets, 'dataset');
  const n = questionCount();
  const names = state.stack.map(converterName);
  const rows = [
    ['Mode', $('mode').selectedOptions[0]?.text || '–'],
    ['System', t ? t.name : '–'],
    ['Questions', state.source === 'custom' ? 'Custom query (' + n + ')'
      : (ds ? ds.name + ' (' + n + ' cases' + ($('only-failed').checked ? ', failed only' : '') + ')' : '–')],
    ['Attack type', $('attack').selectedOptions[0]?.text || '–'],
    ['Repeats each', String(state.repeats)],
    ['Disguises', names.length ? names.join(' → ') : 'none'],
    ['Total attempts', $('only-failed').checked && state.source === 'saved'
      ? 'up to ' + n * state.repeats + ' (failed cases only)'
      : n + ' questions × ' + state.repeats + ' repeats = ' + n * state.repeats],
  ];
  const box = $('details-rows');
  box.replaceChildren();
  rows.forEach(([k, v]) => {
    const row = document.createElement('div');
    row.className = 'pop-row';
    const a = document.createElement('span'); a.textContent = k;
    const b = document.createElement('b'); b.textContent = v;
    row.append(a, b);
    box.append(row);
  });
}

function buildPayload() {
  const payload = {
    mode: $('mode').value,
    tenant_id: $('tenant').value,
    attack_type: $('attack').value,
    repeats: state.repeats,
    converters: state.stack,
  };
  if (state.source === 'custom') payload.questions = customQuestions();
  else { payload.dataset_id = $('dataset').value; payload.only_failed = $('only-failed').checked; }
  return payload;
}

export async function initNewRun({ onStarted }) {
  fillSelect($('mode'), MODES, (m) => m.name, '');
  fillSelect($('attack'), ATTACKS, (a) => a.name, '');
  fillSelect($('tenant'), [], null, 'Loading…');
  fillSelect($('dataset'), [], null, 'Loading…');
  fillSelect($('converter'), [], null, 'Loading…');

  // events
  ['mode', 'tenant', 'dataset', 'attack'].forEach((id) => $(id).addEventListener('change', render));
  $('only-failed').addEventListener('change', render);
  $('custom-text').addEventListener('input', render);
  $('src-saved').addEventListener('click', () => { state.source = 'saved'; render(); });
  $('src-custom').addEventListener('click', () => { state.source = 'custom'; render(); });
  $('rep-dec').addEventListener('click', () => { state.repeats = Math.max(1, state.repeats - 1); render(); });
  $('rep-inc').addEventListener('click', () => { state.repeats = Math.min(20, state.repeats + 1); render(); });
  $('conv-add').addEventListener('click', () => {
    const id = $('converter').value;
    if (id && !state.stack.includes(id)) { state.stack.push(id); render(); }
  });
  $('details-toggle').addEventListener('click', () => {
    const open = $('details-pop').hidden;
    $('details-pop').hidden = !open;
    $('details-toggle').setAttribute('aria-expanded', String(open));
  });
  $('details-close').addEventListener('click', () => {
    $('details-pop').hidden = true;
    $('details-toggle').setAttribute('aria-expanded', 'false');
  });
  $('start').addEventListener('click', async () => {
    state.starting = true;
    render();
    try {
      const { id } = await startRun(buildPayload());
      onStarted(id);
    } catch (err) {
      state.starting = false;
      render();
      $('run-issue').textContent = 'Could not start the run: ' + err.message;
      return;
    }
    state.starting = false;
    render();
  });

  render();

  // load dropdown data from the backend
  const [tenants, datasets, converters] = await Promise.allSettled([getTenants(), getDatasets(), getConverters()]);
  state.tenants = tenants.status === 'fulfilled' ? tenants.value : [];
  state.datasets = datasets.status === 'fulfilled' ? datasets.value : [];
  state.converters = converters.status === 'fulfilled' ? converters.value : [];
  fillSelect($('tenant'), state.tenants, (t) => t.name, 'No systems available');
  fillSelect($('dataset'), state.datasets, (d) => d.name + ' — ' + d.case_count + ' cases', 'No datasets available');
  fillSelect($('converter'), state.converters, (c) => c.name, 'No converters available');
  render();
}
