import { $, el, badge, fmtTime } from './dom.js';
import { listResults, getResult, resultDownloadUrl, resultCsvUrl } from './promptfoo-api.js';

const state = { name: null, detail: null, filter: 'all', search: '', results: [] };
const pct = (v) => (v === null || v === undefined ? '–' : v + '%');

function renderList() {
  const box = $('pfr-list');
  box.replaceChildren();
  const q = $('pfr-list-filter').value.trim().toLowerCase();
  const items = state.results.filter((r) => !q || (r.name + ' ' + (r.summary.description || '')).toLowerCase().includes(q));
  if (!items.length) { box.append(el('p', { class: 'empty', text: 'No promptfoo results yet.' })); return; }
  items.forEach((r) => {
    const s = r.summary || {};
    box.append(el('a', { class: 'pf-res-row', href: '#/pf-results/' + encodeURIComponent(r.name) },
      el('span', {}, el('span', { class: 'case-name mono', text: r.name }),
        s.description ? el('div', { class: 'note nomargin', text: s.description }) : null),
      el('span', { text: fmtTime(r.updated_at) }),
      el('span', { class: 'mono', text: r.meta?.command || (s.redteam ? 'redteam' : 'eval') }),
      el('span', { text: s.unreadable ? 'unreadable' : String(s.total ?? '–') }),
      el('span', { class: 'ok-text', text: String(s.pass ?? '–') }),
      el('span', { class: 'bad-text', text: String(s.fail ?? '–') }),
      el('span', { text: String(s.error ?? '–') }),
      el('span', { class: 'strong', text: pct(s.pass_rate) })));
  });
}

function breakdown(boxId, groups) {
  const box = $(boxId);
  box.replaceChildren();
  if (!groups.length) { box.append(el('p', { class: 'empty', text: 'No data.' })); return; }
  groups.forEach((g) => {
    const total = g.pass + g.fail + g.error || 1;
    box.append(el('div', { class: 'pf-break-row' },
      el('span', { class: 'mono pf-break-name', text: g.name }),
      el('span', { class: 'pf-bar' },
        el('span', { class: 'ok', style: 'width:' + (100 * g.pass / total) + '%' }),
        el('span', { class: 'bad', style: 'width:' + (100 * g.fail / total) + '%' }),
        el('span', { class: 'warn', style: 'width:' + (100 * g.error / total) + '%' })),
      el('span', { class: 'note nomargin mono', text: g.pass + ' / ' + g.fail + ' / ' + g.error })));
  });
}

function block(cls, role, text) {
  return el('div', { class: 'turn ' + cls }, el('div', { class: 'turn-role', text: role }), el('div', { class: 'turn-text', text: text || '(empty)' }));
}

function renderRows() {
  const box = $('pfr-rows');
  box.replaceChildren();
  const q = state.search.toLowerCase();
  const rows = (state.detail?.rows || []).filter((r) => (state.filter === 'all' || r.status === state.filter)
    && (!q || [r.prompt, r.output, r.reason, r.plugin, r.strategy, r.description].join(' ').toLowerCase().includes(q)));
  $('pfr-row-count').textContent = rows.length + ' shown';
  if (!rows.length) { box.append(el('p', { class: 'empty', text: 'No tests match.' })); return; }
  rows.slice(0, 500).forEach((r) => box.append(el('details', { class: 'pf-row' },
    el('summary', {},
      badge(r.status),
      r.plugin ? el('span', { class: 'tag cat mono', text: r.plugin }) : null,
      r.strategy && r.strategy !== 'basic' ? el('span', { class: 'tag cat mono', text: r.strategy }) : null,
      el('span', { class: 'pf-row-text', text: (r.description || r.prompt || '').slice(0, 180) })),
    el('div', { class: 'pf-row-body' },
      block('attacker', 'Prompt', r.prompt),
      block('target', 'Response', r.output),
      block('judge', 'Grader' + (r.score !== null && r.score !== undefined ? ' · score ' + r.score : ''), r.reason),
      r.latency_ms ? el('p', { class: 'note', text: 'Latency ' + r.latency_ms + ' ms' }) : null))));
  if (rows.length > 500) box.append(el('p', { class: 'note pad', text: 'Showing first 500. Download CSV for everything.' }));
}

function renderDetail() {
  const d = state.detail;
  const s = d.summary;
  $('pfr-title').textContent = s.description || d.name;
  $('pfr-sub').textContent = d.name + (s.eval_id ? ' · eval ' + s.eval_id : '') + (s.timestamp ? ' · ' + fmtTime(s.timestamp) : '');
  $('pfr-json').href = resultDownloadUrl(d.name);
  $('pfr-csv').href = resultCsvUrl(d.name);
  $('pfr-rerun').hidden = !(d.meta?.eval_config && s.fail + s.error > 0);
  $('pfr-st-total').textContent = s.total;
  $('pfr-st-pass').textContent = s.pass;
  $('pfr-st-fail').textContent = s.fail;
  $('pfr-st-error').textContent = s.error;
  $('pfr-st-rate').textContent = pct(s.pass_rate);
  $('pfr-tr-rate').style.width = (s.pass_rate || 0) + '%';
  $('pfr-fail-label').textContent = s.redteam ? 'Attacks that worked' : 'Failed';
  $('pfr-pass-label').textContent = s.redteam ? 'Defended' : 'Passed';
  $('pfr-breakdowns').hidden = !s.redteam;
  breakdown('pfr-plugins', d.by_plugin);
  breakdown('pfr-strategies', d.by_strategy);
  renderRows();
}

export function initPfResults({ onRerun }) {
  $('pfr-list-filter').addEventListener('input', renderList);
  $('pfr-search').addEventListener('input', (e) => { state.search = e.target.value.trim(); renderRows(); });
  document.querySelectorAll('#pfr-filter button').forEach((b) => b.addEventListener('click', () => {
    state.filter = b.dataset.status;
    document.querySelectorAll('#pfr-filter button').forEach((x) => x.classList.toggle('on', x === b));
    renderRows();
  }));
  $('pfr-rerun').addEventListener('click', () => {
    if (state.detail) onRerun({ config: state.detail.meta.eval_config, filter_failing: state.detail.name });
  });
}

export async function showPfResults(name) {
  state.name = name || null;
  $('pfr-list-view').hidden = !!name;
  $('pfr-detail').hidden = !name;
  ['pfr-back', 'pfr-json', 'pfr-csv'].forEach((id) => { $(id).hidden = !name; });
  $('pfr-rerun').hidden = true;
  if (!name) {
    $('pfr-title').textContent = 'Promptfoo results';
    $('pfr-sub').textContent = 'Every eval and red-team run saved by the promptfoo container.';
    try { state.results = await listResults(); } catch (err) { state.results = []; $('pfr-sub').textContent = err.message; }
    renderList();
    return;
  }
  $('pfr-title').textContent = name;
  $('pfr-sub').textContent = 'Loading…';
  $('pfr-rows').replaceChildren();
  try {
    state.detail = await getResult(name);
    if (state.name === name) renderDetail();
  } catch (err) {
    $('pfr-sub').textContent = err.message;
  }
}
