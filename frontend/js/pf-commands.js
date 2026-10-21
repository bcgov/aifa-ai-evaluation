import { $, el, fillSelect } from './dom.js';
import { listTestFiles, listDatasetCases, runDatasetTests } from './promptfoo-api.js';

const state = { busy: false };

const boxes = () => [...document.querySelectorAll('#pfc-cases input[type=checkbox]')];
const picked = () => boxes().filter((b) => b.checked).map((b) => Number(b.value));

function update() {
  const all = boxes();
  const n = picked().length;
  $('pfc-count').textContent = all.length ? n + ' of ' + all.length + ' selected' : '';
  $('pfc-all').checked = all.length > 0 && n === all.length;
  $('pfc-run').disabled = n === 0 || state.busy;
}

async function loadCases() {
  const dataset = $('pfc-dataset').value;
  const box = $('pfc-cases');
  box.replaceChildren();
  $('pfc-msg').textContent = '';
  if (!dataset) { update(); return; }
  box.append(el('p', { class: 'note', text: 'Loading test cases…' }));
  try {
    const cases = await listDatasetCases(dataset);
    if ($('pfc-dataset').value !== dataset) return;
    box.replaceChildren(...cases.map((c) => el('label', { class: 'pf-case' },
      el('input', { type: 'checkbox', value: String(c.index), onchange: update }),
      el('span', { class: 'pf-check-text' },
        el('span', { class: 'strong', text: c.label }),
        el('span', { class: 'note nomargin', text: c.checks + ' checks' })))));
  } catch (err) {
    box.replaceChildren(el('p', { class: 'note', text: 'Could not list test cases: ' + err.message }));
  }
  update();
}

export function initPfCommands({ onJob }) {
  $('pfc-dataset').addEventListener('change', loadCases);
  $('pfc-all').addEventListener('change', (e) => { boxes().forEach((b) => { b.checked = e.target.checked; }); update(); });
  $('pfc-run').addEventListener('click', async () => {
    state.busy = true;
    update();
    try {
      const job = await runDatasetTests($('pfc-dataset').value, picked());
      onJob(job.id);
    } catch (err) {
      $('pfc-msg').textContent = 'Could not start: ' + err.message;
    } finally {
      state.busy = false;
      update();
    }
  });
}

export async function showPfCommands() {
  const previous = $('pfc-dataset').value;
  let files = [];
  try { files = await listTestFiles(); } catch { $('pfc-msg').textContent = 'Promptfoo service is not reachable.'; }
  fillSelect($('pfc-dataset'), files, (f) => f.name + (f.error ? ' — not a promptfoo test file' : ' — ' + f.cases + ' cases'),
    'No YAML files in data_promptfoo', (f) => f.name);
  if (files.some((f) => f.name === previous)) $('pfc-dataset').value = previous;
  await loadCases();
}
