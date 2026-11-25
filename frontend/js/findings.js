import { getFindings } from './api.js';

let all = null;
let filterV = 'all';
let search = '';

const el = (id) => document.getElementById(id);
const pct = (v) => Math.round((v || 0) * 100);

function ringSvg(value, color) {
  const r = 26, c = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, value || 0));
  return `<div class="ring">
    <svg width="64" height="64" viewBox="0 0 64 64">
      <circle class="ring-bg" cx="32" cy="32" r="${r}"></circle>
      <circle class="ring-val ${color}" cx="32" cy="32" r="${r}"
        stroke-dasharray="${c * frac} ${c}"></circle>
    </svg>
    <span class="ring-label">${pct(frac)}%</span>
  </div>`;
}

function tone(v, invert = false) {
  const x = invert ? 1 - (v || 0) : (v || 0);
  if (x >= 0.8) return 'ok';
  if (x >= 0.5) return 'warn';
  return 'bad';
}

function aggregate(summaries) {
  const total = summaries.reduce((n, s) => n + (s.total_evaluated || 0), 0) || 1;
  const avg = (k) => summaries.reduce((n, s) => n + (s[k] || 0) * (s.total_evaluated || 0), 0) / total;
  const q = (k) => summaries.reduce((n, s) => n + ((s.quality_rings || {})[k] || 0) * (s.total_evaluated || 0), 0) / total;
  const m = (k) => summaries.reduce((n, s) => n + ((s.average_metrics || {})[k] || 0) * (s.total_evaluated || 0), 0) / total;
  const verdicts = { PASS: 0, FAIL: 0, REFUSED: 0 };
  const risks = { Security: 0, Privacy: 0, Fairness: 0, Integrity: 0, Agency: 0 };
  summaries.forEach((s) => {
    const vc = s.verdict_counts || {};
    Object.keys(verdicts).forEach((k) => { verdicts[k] += vc[k] || 0; });
    const rc = s.risk_class_counts || {};
    Object.keys(risks).forEach((k) => { risks[k] += rc[k] || 0; });
  });
  return { total, avg, q, m, verdicts, risks };
}

function renderRings(a) {
  const rings = [
    ['Pass rate', a.q('pass_rate'), tone(a.q('pass_rate'))],
    ['Groundedness', a.q('groundedness'), tone(a.q('groundedness'))],
    ['Faithfulness', a.q('faithfulness'), tone(a.q('faithfulness'))],
    ['Correctness', a.m('correctness'), tone(a.m('correctness'))],
    ['Hallucination-free', 1 - a.m('hallucination'), tone(1 - a.m('hallucination'))],
    ['Toxicity-free', 1 - a.m('toxicity'), tone(1 - a.m('toxicity'))],
    ['PII clean', a.q('privacy_clean_rate'), tone(a.q('privacy_clean_rate'))],
    ['Policy compliance', a.q('policy_compliance'), tone(a.q('policy_compliance'))],
  ];
  el('findings-rings').innerHTML = rings.map(([label, v, c]) =>
    `<div class="card stat ring-card"><div class="stat-label">${label}</div>${ringSvg(v, c)}</div>`
  ).join('');
}

function renderVerdicts(a) {
  const names = { PASS: 'Pass', FAIL: 'Fail', REFUSED: 'Refused' };
  el('findings-verdicts').innerHTML = Object.keys(names).map((k) =>
    `<div class="findings-verdict"><span class="fv-name">${names[k]}</span><span class="fv-num">${a.verdicts[k]}</span></div>`
  ).join('');
}

function renderRisks(a) {
  el('findings-risks').innerHTML = Object.keys(a.risks).map((k) =>
    `<div class="findings-verdict"><span class="fv-name">${k}</span><span class="fv-num">${a.risks[k]}</span></div>`
  ).join('');
}

function renderList() {
  const list = all.findings.filter((f) => (filterV === 'all' || f.verdict === filterV));
  const q = search.trim().toLowerCase();
  const items = q ? list.filter((f) => JSON.stringify(f).toLowerCase().includes(q)) : list;
  el('findings-count').textContent = items.length + ' finding(s)';
  if (!items.length) {
    el('findings-list').innerHTML = '<p class="empty">No findings match.</p>';
    return;
  }
  el('findings-list').innerHTML = items.map((f) => `
    <div class="finding-row">
      <span class="finding-verdict-${f.verdict}">${f.verdict}</span>
      <span class="finding-sev-${f.severity || 'low'}">${f.severity || 'low'}</span>
      <span class="finding-risk">${f.risk_class || ''}</span>
      <div class="finding-body">
        <div class="finding-expl">${escapeHtml(f.explanation || '')}</div>
        <div class="finding-query">Q: ${escapeHtml(f.query || '')}</div>
        <div class="finding-resp">A: ${escapeHtml(f.response || '')}</div>
        <div class="finding-risk">${escapeHtml(f.report || '')} · ${escapeHtml(f.case || '')}</div>
      </div>
    </div>`).join('');
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export async function showFindings() {
  try {
    all = await getFindings();
  } catch (e) {
    el('findings-sub').textContent = 'Failed to load findings: ' + e.message;
    return;
  }
  el('findings-sub').textContent = `${all.evaluated_reports} evaluated report(s), ${all.findings.length} finding(s) across turns.`;
  const a = aggregate(all.report_summaries);
  renderRings(a);
  renderVerdicts(a);
  renderRisks(a);
  renderList();
}

function exportCsv() {
  if (!all) return;
  const head = ['report', 'case', 'verdict', 'severity', 'risk_class', 'explanation', 'query', 'response'];
  const rows = [head.join(',')].concat(all.findings.map((f) => head.map((h) =>
    '"' + String(f[h] == null ? '' : f[h]).replace(/"/g, '""') + '"').join(',')));
  const blob = new Blob(['\ufeff' + rows.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'findings.csv';
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function initFindings() {
  el('findings-refresh').addEventListener('click', () => showFindings());
  el('findings-export').addEventListener('click', exportCsv);
  el('findings-filter').addEventListener('click', (ev) => {
    const btn = ev.target.closest('button');
    if (!btn) return;
    filterV = btn.dataset.v;
    el('findings-filter').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === btn));
    renderList();
  });
  el('findings-search').addEventListener('input', (ev) => { search = ev.target.value; renderList(); });
}