// Findings: plain-JS port of the pack's FindingsPage. Results only: no principle scores and no
// framework tags here (those are on Policy Mapping). Data: GET /api/rtaas/findings?run=...
import { el } from './dom.js';
import { getRunResults, getRtaasFindings, rtaasReportUrl } from './api.js';

const COLOR = { pass: '#187a5d', warn: '#b4800f', fail: '#be4a30', empty: '#c9c2b0' };
const SVG = 'http://www.w3.org/2000/svg';
const S = { run: 'latest', runs: [], tab: 'headline', data: null, error: '', exportOpen: false };

const root = () => document.getElementById('rtf-root');
const scoreColor = (s) => (s == null ? COLOR.empty : s >= 8 ? COLOR.pass : s >= 5 ? COLOR.warn : COLOR.fail);
const metricColor = (v, t) => (v == null ? COLOR.empty : v >= t ? COLOR.pass : v >= t - 0.1 ? COLOR.warn : COLOR.fail);

function svg(tag, attrs, ...kids) {
  const n = document.createElementNS(SVG, tag);
  Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
  kids.forEach((k) => n.append(k));
  return n;
}

// Half circle for the overall 0-10 score
function halfGauge(score, band) {
  const half = Math.PI * 100;
  const filled = score == null ? 0 : (half * score) / 10;
  const arc = 'M20 120 A100 100 0 0 1 220 120';
  return svg('svg', { viewBox: '0 0 240 140', width: 240, height: 140, role: 'img', 'aria-label': `Overall score ${score ?? 'not reported'} out of 10` },
    svg('path', { d: arc, fill: 'none', stroke: '#ece8dd', 'stroke-width': 18, 'stroke-linecap': 'round' }),
    svg('path', { d: arc, fill: 'none', stroke: scoreColor(score), 'stroke-width': 18, 'stroke-linecap': 'round', 'stroke-dasharray': `${filled} ${half}` }),
    svg('text', { x: 120, y: 104, 'text-anchor': 'middle', 'font-size': 40, 'font-weight': 700, fill: '#1c2231' }, score == null ? '–' : score.toFixed(1)),
    svg('text', { x: 120, y: 128, 'text-anchor': 'middle', 'font-size': 13, fill: '#666e82' }, `out of 10 · ${band}`));
}

// Small ring for one metric (0..1)
function ringGauge(value, target) {
  const r = 38, circ = 2 * Math.PI * r;
  return svg('svg', { viewBox: '0 0 96 96', width: 84, height: 84, 'aria-hidden': 'true' },
    svg('circle', { cx: 48, cy: 48, r, fill: 'none', stroke: '#ece8dd', 'stroke-width': 9 }),
    svg('circle', { cx: 48, cy: 48, r, fill: 'none', stroke: metricColor(value, target), 'stroke-width': 9,
      'stroke-dasharray': `${(value ?? 0) * circ} ${circ}`, 'stroke-linecap': 'round', transform: 'rotate(-90 48 48)' }),
    svg('text', { x: 48, y: 54, 'text-anchor': 'middle', 'font-size': 18, 'font-weight': 700, fill: '#1c2231' }, value == null ? '–' : `${Math.round(value * 100)}%`));
}

export function initFindings() { /* rendered on demand */ }

export async function showFindings() {
  render();
  try {
    const list = await getRunResults().catch(() => ({ runs: [] }));
    S.runs = list.runs.map((r) => ({ id: r.report_name ? 'rtaas_' + r.report_name.replace(/^rtaas_/, '') : r.id, name: r.name }));
    if (S.run === 'latest' && !S.runs.length) S.run = 'demo';
    S.data = await getRtaasFindings(S.run);
    S.error = '';
  } catch (e) { S.error = e.message; S.data = null; }
  render();
}

function render() {
  const host = root();
  if (!host) return;
  const runPick = el('select', { class: 'field', 'aria-label': 'Run', onchange: (e) => { S.run = e.target.value; S.data = null; showFindings(); } },
    el('option', { value: 'latest', text: 'Latest graded run' }),
    ...S.runs.map((r) => el('option', { value: r.id, text: r.name })),
    el('option', { value: 'demo', text: 'Demo data (sample run, not real results)' }));
  runPick.value = S.run;

  if (S.error) { host.replaceChildren(el('div', { class: 'rt' }, head(null, runPick), el('p', { class: 'error', text: `Couldn't load findings: ${S.error}` }))); return; }
  const d = S.data;
  if (!d) { host.replaceChildren(el('div', { class: 'rt' }, head(null, runPick), el('p', { class: 'mute', text: 'Loading…' }))); return; }

  const invalid = d.run_health && d.run_health.invalid && d.run_health.total;
  const metrics = d.metrics.filter((m) => m.tab === S.tab);
  const activeTab = d.tabs.find((t) => t.key === S.tab);
  const anyPreview = d.metrics.some((m) => m.preview);

  host.replaceChildren(el('div', { class: 'rt' },
    head(d, runPick),
    d.demo ? el('div', { class: 'note-box warn', text: 'Demo data from the sample run. These are not results from your chatbot.' }) : null,
    invalid ? el('div', { class: 'note-box bad', role: 'status' },
      el('strong', { text: `Run invalid: ${d.run_health.valid} of ${d.run_health.total} answered.` }),
      ' Scores are not reported when fewer than 95% of tests got an answer. Fix the not-run cases and re-run.') : null,
    ...(d.warnings || []).map((w) => el('div', { class: 'note-box warn', text: w })),

    el('section', { class: 'card row' },
      invalid ? el('div', { class: 'gauge-off', text: 'No score: run invalid' }) : halfGauge(d.overall.score, d.overall.band),
      el('div', { class: `gate ${d.gate.blocked ? 'blocked' : 'clear'}` },
        el('strong', { text: d.gate.blocked ? `Blocked: ${d.gate.reasons[0]}` : 'Clear to release' }),
        !invalid && d.headline ? el('p', { class: 'small ink', text: d.headline.text }) : null,
        !invalid && d.overall.capped_by ? el('p', { class: 'small', text: `Score capped at ${d.overall.score?.toFixed(1)} while a ${d.overall.capped_by} finding is open (uncapped ${d.overall.raw?.toFixed(1)}).` }) : null,
        !invalid && d.index && d.index.value != null ? el('p', { class: 'small', text: `Index ${d.index.value.toFixed(1)}${d.index.capped_by ? ` (${d.index.raw.toFixed(1)} before cap)` : ''} over ${d.index.eligible_failure_modes} failure modes with 5+ tests · ${d.index.label}` }) : null,
        d.overall.low_coverage && !invalid ? el('p', { class: 'small', text: 'Low coverage: fewer than 10 tests.' }) : null,
        d.review_queue?.length ? el('p', { class: 'small', text: `${d.review_queue.length} result${d.review_queue.length === 1 ? '' : 's'} waiting for human review (see Run Results).` }) : null,
        d.gate.reasons.length > 1 ? el('p', { class: 'small', text: `+ ${d.gate.reasons.length - 1} more release conditions not met. See the developer report.` }) : null,
        d.gate.not_measured?.length ? el('p', { class: 'small', text: `Not measured yet (release-blocking): ${d.gate.not_measured.join(', ')}.` }) : null)),

    el('section', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', { text: 'Answer quality' }),
        anyPreview ? el('span', { class: 'chip warn', text: 'Preview values, not measured yet' }) : null),
      el('div', { class: 'tabs', role: 'tablist' }, ...d.tabs.map((t) => el('button', { role: 'tab', 'aria-selected': String(t.key === S.tab),
        class: t.key === S.tab ? 'tab on' : 'tab', text: t.label, onclick: () => { S.tab = t.key; render(); } }))),
      el('p', { class: 'mute small', text: activeTab?.note || '' }),
      el('div', { class: 'metric-grid' }, ...metrics.map((m) => el('div', { class: 'metric', title: m.skipped_reason || '' },
        ringGauge(invalid ? null : m.value, m.target),
        el('div', {},
          el('div', { class: 'metric-label', text: m.label }),
          el('div', { class: 'metric-class', text: m.deepeval_class }),
          el('div', { class: 'small mute', text: `Target ${Math.round(m.target * 100)}%${m.blocks_release ? ' · blocks release' : m.report_only ? ' · report only' : ''}` }),
          m.value == null ? el('div', { class: 'small mute', text: 'Not measured' }) : el('div', { class: 'small mute', text: `${m.passed} of ${m.cases} passed${m.low_sample ? ' · under 30 tests' : ''}` })))))),

    el('section', { class: 'card' },
      el('h2', { text: 'Main issues' }),
      d.issues.length === 0 ? el('p', { class: 'mute', text: 'No High or Medium findings.' }) : el('table', { class: 'issues' },
        el('thead', {}, el('tr', {}, ...['Issue', 'Severity', 'Found', 'What went wrong'].map((t) => el('th', { text: t })))),
        el('tbody', {}, ...d.issues.map((i) => el('tr', {},
          el('td', { text: i.title }), el('td', {}, el('span', { class: `sev ${i.severity}`, text: i.severity })),
          el('td', { class: 'nowrap', text: i.found }), el('td', { text: i.what_went_wrong }))))))));
}

function head(d, runPick) {
  const runId = d ? (d.demo ? 'demo' : (d.report_name ? 'rtaas_' + d.report_name.replace(/^rtaas_/, '') : S.run)) : S.run;
  return el('header', { class: 'page-head' },
    el('div', {}, el('h1', { text: 'Findings' }),
      el('p', { class: 'mute', text: d ? `${d.target_name} · run ${d.run_date} · ${d.tests} tests graded · rules ${Object.values(d.policy_versions || {})[0] || ''}` : 'Results of graded runs.' })),
    el('div', { class: 'row' }, runPick,
      el('div', { class: 'menu' },
        el('button', { class: 'btn', 'aria-expanded': String(S.exportOpen), text: 'Export report ▾', disabled: !d, onclick: () => { S.exportOpen = !S.exportOpen; render(); } }),
        S.exportOpen && d ? el('div', { class: 'menu-list', role: 'menu' },
          el('a', { role: 'menuitem', href: rtaasReportUrl(runId, 'exec'), target: '_blank' },
            el('strong', { text: 'Executive summary' }), el('span', { text: '1 page · verdict, top issues, next steps' })),
          el('a', { role: 'menuitem', href: rtaasReportUrl(runId, 'dev'), target: '_blank' },
            el('strong', { text: 'Developer report' }), el('span', { text: '2 pages · every failure mode and metric' })),
          el('span', { class: 'menu-note', text: 'Opens a printable page. Use Print > Save as PDF.' })) : null)));
}
