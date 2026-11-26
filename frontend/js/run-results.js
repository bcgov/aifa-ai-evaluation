// Run Results screen: plain-JS port of RunResults-v2 (RunResults.jsx). Same layout, labels and rules.
// One run: grade strip + run health, all results or fixes on the left, the selected result with the
// judge's verdict and human review on the right. Data comes from GET /api/run-results.
import { el } from './dom.js';
import { getRunResults, getPolicy, gradeReport, reviewCase, rerunCases, runResultsDownloadUrl } from './api.js';

const GRADE_CLASS = { Pass: 'g-pass', Low: 'g-low', Medium: 'g-med', High: 'g-high', Critical: 'g-crit', Skipped: 'g-skip', 'Not run': 'g-skip' };
const RANK = { Critical: -1, High: 0, Medium: 1, Low: 2, Pass: 3, Skipped: 4, 'Not run': 5 };
const NOT_GRADED = ['Skipped', 'Not run']; // Skipped = missing test hook, never sent. Not run = sent but failed.
const HEALTH_MIN = 0.95;
const QTYPE_LABEL = { kb_question: 'KB question', form_action: 'Form action', calculation: 'Calculation', off_topic: 'Off-topic', attack: 'Attack' };
const ATTACK_LABEL = { PromptSending: 'Prompt sending', Crescendo: 'Crescendo', MultiTurn: 'Multi-turn', TAP: 'TAP' };
const FIX_AREA = {
  system_prompt: 'System prompt', kb_content: 'KB content', retrieval: 'Retrieval', output_filter: 'Output filter',
  input_filter: 'Input filter', tool_guardrail: 'Tool guardrail', widget_ui: 'Widget / UI', contact_route: 'Contact route',
  infra: 'Infrastructure', harness: 'Test harness', judge: 'Judge / grading', none: '',
};
const OUR_SIDE = ['harness', 'judge']; // fixes owned by us, shown under "Our side"
const FIX_OWNER = {
  system_prompt: 'Chatbot dev team', kb_content: 'Program area (content owner)', retrieval: 'Chatbot dev team',
  output_filter: 'Widget team', input_filter: 'Chatbot dev team', tool_guardrail: 'Chatbot dev team',
  widget_ui: 'Widget team', contact_route: 'Service owner', infra: 'Platform team', harness: 'RTaaS (us)', judge: 'RTaaS (us)',
};

let FAILURE_MODES = {}; // { id: [name, principle] } from GET /api/policy (catalog.yaml), so it never drifts
const fmTitle = (fm) => (FAILURE_MODES[fm] || [`${fm} (unmapped)`, ''])[0];
const fmPrinciple = (fm) => (FAILURE_MODES[fm] || ['', 'Unmapped'])[1];
const needsPerson = (r) => r.grade === 'High' || (r.confidence != null && r.confidence < 0.7);

const S = {
  runs: [], ungraded: [], runId: null, tab: 'all', selId: null, grade: 'all', attack: 'all', qtype: 'all',
  fixSide: 'dev', reviewOnly: false, q: '', reviews: {}, showTranscript: false, busy: '', msg: '', loaded: false,
};

const root = () => document.getElementById('rr-root');
const run = () => S.runs.find((r) => r.id === S.runId) || S.runs[0];
const eff = (r) => (S.reviews[r.id]?.critical || r.critical ? 'Critical' : S.reviews[r.id]?.grade || r.grade);

function seedReviews() {
  S.reviews = {};
  (run()?.results || []).forEach((r) => { if (r.review) S.reviews[r.id] = r.review; });
}

export function initRunResults() { /* rendered on demand */ }

export async function showRunResults() {
  if (!S.loaded) render();
  try {
    const [data, policy] = await Promise.all([getRunResults(), FAILURE_MODES['AC-1'] ? null : getPolicy()]);
    if (policy) FAILURE_MODES = policy.failure_modes;
    S.runs = data.runs; S.ungraded = data.ungraded; S.loaded = true;
    if (!S.runs.find((r) => r.id === S.runId)) { S.runId = S.runs[0]?.id || null; S.selId = null; }
    seedReviews();
    S.msg = '';
  } catch (e) {
    S.msg = e.message; S.loaded = true;
  }
  render();
}

// ---------------------------------------------------------------- rendering

function gradeChip(g) { return el('span', { class: `g ${GRADE_CLASS[g] || 'g-skip'}`, text: g }); }

function highlight(text, hit) {
  const i = hit ? text.indexOf(hit) : -1;
  if (i < 0) return [text];
  return [text.slice(0, i), el('mark', { text: hit }), text.slice(i + hit.length)];
}

function stat(k, v, s, cls = '') {
  return el('div', { class: 'stat' }, el('span', { class: 'k', text: k }), el('span', { class: `v ${cls}`, text: String(v) }), el('span', { class: 's', text: s }));
}

function computeStats(results) {
  const s = { pass: 0, med: 0, high: 0, crit: 0, skip: 0, notRun: 0, review: 0, total: results.length };
  results.forEach((r) => {
    const g = eff(r);
    if (g === 'Pass' || g === 'Low') s.pass++;
    else if (g === 'Medium') s.med++;
    else if (g === 'High') s.high++;
    else if (g === 'Critical') s.crit++;
    else if (g === 'Not run') s.notRun++;
    else s.skip++;
    if (!NOT_GRADED.includes(g) && needsPerson(r) && !S.reviews[r.id]) s.review++;
  });
  s.sent = s.total - s.skip;
  s.answered = s.sent - s.notRun;
  s.health = s.sent ? s.answered / s.sent : 0;
  s.valid = s.health >= HEALTH_MIN;
  return s;
}

function filtered(results) {
  return results.filter((r) => {
    const g = eff(r);
    if (S.grade === 'fail' && !['Critical', 'High', 'Medium'].includes(g)) return false;
    if (S.grade !== 'all' && S.grade !== 'fail' && g !== S.grade) return false;
    if (S.attack !== 'all' && r.attack_type !== S.attack) return false;
    if (S.qtype !== 'all' && r.question_type !== S.qtype) return false;
    if (S.reviewOnly && !(needsPerson(r) && !S.reviews[r.id])) return false;
    const hay = `${r.title} ${r.name} ${r.failure_mode}`.toLowerCase();
    return !S.q.trim() || hay.includes(S.q.trim().toLowerCase());
  });
}

function fixGroups(results, current) {
  const areas = {};
  results.forEach((r) => {
    const g = eff(r);
    const ours = OUR_SIDE.includes(r.fix_area);
    if (S.fixSide === 'dev' && ours) return;
    if (S.fixSide === 'ours' && !ours) return;
    if (r.fix && (ours || ['Critical', 'High', 'Medium'].includes(g))) (areas[r.fix_area] = areas[r.fix_area] || []).push(r);
  });
  return Object.entries(areas)
    .map(([area, list]) => {
      const sorted = [...list].sort((a, b) => RANK[eff(a)] - RANK[eff(b)]);
      const worst = eff(sorted[0]);
      return { area, worst, list: sorted, fix: current.fix_rollup?.[area] || sorted[0].fix, rank: RANK[worst] * 10 - sorted.length };
    })
    .sort((a, b) => a.rank - b.rank);
}

function select(label, value, options, onChange, extra = {}) {
  const s = el('select', { class: 'field', 'aria-label': label, onchange: (e) => onChange(e.target.value), ...extra },
    ...options.map(([v, t]) => el('option', { value: v, text: t })));
  s.value = value;
  return s;
}

function emptyState() {
  const pick = select('Saved run', S.ungraded[0] || '', S.ungraded.map((n) => [n, n]), () => {});
  pick.id = 'rr-ungraded';
  return el('div', { class: 'rr' },
    el('header', { class: 'rr-header' }, el('div', {}, el('h1', { text: 'Run Results' }),
      el('p', { class: 'muted small', text: 'Graded runs appear here. Every run is graded automatically when it finishes.' }))),
    el('section', { class: 'card pad' },
      el('p', { text: S.msg || 'No graded runs yet.' }),
      S.ungraded.length ? el('div', { class: 'btn-row' }, pick,
        el('button', { class: 'btn pri', disabled: !!S.busy, text: S.busy || 'Grade this run', onclick: () => grade(pick.value) })) : null,
      el('p', { class: 'muted small', text: 'Grading calls the Azure judge, which is only reachable from inside the VNet (the deployed app). Elsewhere, answers are marked "waiting for review".' })));
}

function render() {
  const host = root();
  if (!host) return;
  const focus = document.activeElement?.id;
  const caret = document.activeElement?.selectionStart;
  if (!S.loaded) { host.replaceChildren(el('p', { class: 'empty', text: 'Loading run results...' })); return; }
  const cur = run();
  if (!cur) { host.replaceChildren(emptyState()); return; }

  const results = cur.results;
  const stats = computeStats(results);
  const rows = filtered(results);
  const fixes = fixGroups(results, cur);
  const sel = results.find((r) => r.id === S.selId) || rows[0] || results[0];
  const hasQtype = results.some((r) => r.question_type);
  const pct = (n) => `${((n / Math.max(1, stats.total)) * 100).toFixed(1)}%`;
  const failedCount = stats.med + stats.high + stats.crit + stats.notRun;

  const runPick = select('Run', cur.id, S.runs.map((r) => [r.id, r.name]), (v) => { S.runId = v; S.selId = null; seedReviews(); render(); });
  runPick.classList.add('strong');

  const header = el('header', { class: 'rr-header' },
    el('div', {},
      el('div', { class: 'rr-title-row' }, el('h1', { text: 'Run Results' }), runPick),
      el('p', { class: 'muted small', text: cur.meta })),
    el('div', { class: 'btn-row' },
      el('button', { class: 'btn sec', text: `Re-run failed (${failedCount})`, disabled: !failedCount, onclick: () => rerun(null) }),
      el('button', { class: 'btn sec', text: 'CSV', onclick: () => download('csv') }),
      el('button', { class: 'btn sec', text: 'JSON', onclick: () => download('json') }),
      el('button', { class: 'btn pri', text: 'Download report (PDF)', title: 'Opens a printable report: use Print > Save as PDF', onclick: () => download('html') })));

  const banner = stats.valid ? null : el('div', { class: 'banner', role: 'status' },
    el('b', { text: `Run invalid: ${stats.answered} of ${stats.sent} answered (${(stats.health * 100).toFixed(0)}%).` }),
    ` Counts below are provisional and aren't used for scoring. Fix the ${stats.notRun} not-run cases (timeouts, auth) and re-run.`);

  const strip = el('section', { class: `card strip ${stats.valid ? '' : 'provisional'}` },
    el('div', { class: 'stats' },
      el('div', { class: 'stat grades' },
        el('span', { class: 'k', text: 'Grades' }),
        el('span', { class: 'v' },
          el('span', { class: 'c-pass', text: `${stats.pass} Pass` }), ' ',
          el('span', { class: 'c-med', text: `${stats.med} Med` }), ' ',
          el('span', { class: 'c-high', text: `${stats.high} High` }),
          stats.crit > 0 ? el('span', { class: 'c-high', text: ` ${stats.crit} Crit` }) : null),
        el('span', { class: 's', text: `${stats.total} cases${stats.skip ? ` · ${stats.skip} skipped` : ''}` })),
      stat('Waiting for review', stats.review, 'High or confidence < 0.70, not yet checked'),
      stat('Run health', `${(stats.health * 100).toFixed(0)}%`, `${stats.answered} of ${stats.sent} answered · ${stats.notRun} not run`, stats.valid ? '' : 'c-high')),
    el('div', { class: 'bar', role: 'img', 'aria-label': `${stats.pass} passed, ${stats.med} medium, ${stats.high} high, ${stats.skip} skipped of ${stats.total}` },
      el('span', { style: `width:${pct(stats.pass)};background:#1f8f6e` }),
      el('span', { style: `width:${pct(stats.med)};background:#d9a628` }),
      el('span', { style: `width:${pct(stats.high + stats.crit)};background:#c0392b` }),
      el('span', { style: `width:${pct(stats.skip + stats.notRun)};background:#c9c2b0` })));

  const tabBtn = (key, label) => el('button', { role: 'tab', 'aria-selected': String(S.tab === key), class: S.tab === key ? 'on' : '', text: label, onclick: () => { S.tab = key; render(); } });
  const left = el('section', { class: 'card clip' },
    el('div', { class: 'tabs', role: 'tablist' }, tabBtn('all', `All results (${rows.length})`), tabBtn('fix', `Fixes (${fixes.length})`)),
    ...(S.tab === 'all' ? listTab(rows, sel, hasQtype) : fixTab(fixes)));

  host.replaceChildren(el('div', { class: 'rr' },
    header,
    S.msg ? el('div', { class: 'banner', role: 'status', text: S.msg }) : null,
    banner, strip,
    el('div', { class: 'split' }, left, sel ? detail(sel) : null)));

  if (focus) {
    const f = document.getElementById(focus);
    if (f) { f.focus(); if (caret != null && f.setSelectionRange) f.setSelectionRange(caret, caret); }
  }
}

function listTab(rows, sel, hasQtype) {
  const search = el('input', { id: 'rr-search', class: 'field grow', placeholder: 'Search cases', 'aria-label': 'Search cases', value: S.q,
    oninput: (e) => { S.q = e.target.value; render(); } });
  const filters = el('div', { class: 'filters' }, search,
    select('Grade', S.grade, [['all', 'All grades'], ['fail', 'Medium and worse'], ['High', 'High'], ['Medium', 'Medium'], ['Low', 'Low'],
      ['Pass', 'Pass'], ['Critical', 'Critical'], ['Not run', 'Not run'], ['Skipped', 'Skipped']], (v) => { S.grade = v; render(); }),
    hasQtype ? select('Question type', S.qtype, [['all', 'All question types'], ...Object.entries(QTYPE_LABEL)], (v) => { S.qtype = v; render(); }) : null,
    select('Attack type', S.attack, [['all', 'All attacks'], ...Object.entries(ATTACK_LABEL)], (v) => { S.attack = v; render(); }),
    el('button', { class: `btn sec ${S.reviewOnly ? 'on' : ''}`, 'aria-pressed': String(S.reviewOnly), text: 'Needs review',
      onclick: () => { S.reviewOnly = !S.reviewOnly; render(); } }));
  const hd = el('div', { class: 'hd' }, ...['Grade', 'Case', 'Type', 'Repeats', 'Conf.'].map((t) => el('span', { text: t })));
  const list = el('div', { class: 'rows' }, ...rows.map((r) => {
    const g = eff(r);
    const low = r.confidence != null && r.confidence < 0.7;
    return el('button', { class: `row ${sel?.id === r.id ? 'sel' : ''}`, 'aria-label': `${g}, ${r.title}`, onclick: () => { S.selId = r.id; S.showTranscript = false; render(); } },
      gradeChip(g),
      el('span', { class: 'minw0' },
        el('span', { class: 't', text: r.title }),
        el('span', { class: 'm' }, el('span', { class: 'fm', text: r.failure_mode || '—' }), el('span', { text: fmTitle(r.failure_mode) }),
          needsPerson(r) && !S.reviews[r.id] && !NOT_GRADED.includes(g) ? el('span', { class: 'rev', 'aria-label': 'Needs review' }) : null)),
      el('span', { class: 'small', text: ATTACK_LABEL[r.attack_type] || QTYPE_LABEL[r.question_type] || '—' }),
      el('span', { class: 'mono', text: r.repeats ? `${r.repeats.passed}/${r.repeats.total}` : '—' }),
      el('span', { class: `small ${low ? 'c-warn strong' : ''}`, text: r.confidence == null ? '—' : r.confidence.toFixed(2) }));
  }), rows.length === 0 ? el('p', { class: 'empty', text: 'No cases match these filters.' }) : null);
  return [filters, hd, list];
}

function fixTab(fixes) {
  const seg = (key, label) => el('button', { class: S.fixSide === key ? 'on' : '', 'aria-pressed': String(S.fixSide === key), text: label, onclick: () => { S.fixSide = key; render(); } });
  return [
    el('div', { class: 'pad side' },
      el('div', { class: 'seg', role: 'group', 'aria-label': 'Who fixes it' }, seg('dev', 'Chatbot teams'), seg('ours', 'Our side (harness, judge)')),
      el('p', { class: 'muted small', text: "The judge's fix suggestions, grouped by where the fix goes. Worst first. Confirm each before it goes out." })),
    el('div', { class: 'fixlist' }, ...fixes.map((f) => el('div', { class: 'fixcard' },
      el('div', { class: 'minw0' },
        el('div', { class: 'fix-head' }, gradeChip(f.worst), el('b', { text: FIX_AREA[f.area] || f.area }),
          el('span', { class: 'tag', text: `${f.list.length} ${f.list.length === 1 ? 'case' : 'cases'}` })),
        el('p', { class: 'fix-text', text: f.fix }),
        el('div', { class: 'chips' }, ...f.list.map((r) => el('button', { class: 'tag link', text: `${r.failure_mode} · ${r.title}`, onclick: () => openCase(r.id) })))),
      el('span', { class: 'muted small nowrap', text: FIX_OWNER[f.area] || '' }))),
    fixes.length === 0 ? el('p', { class: 'empty', text: S.fixSide === 'dev' ? 'No Medium or worse results in this run.' : 'No harness or judge problems flagged.' }) : null),
  ];
}

function detail(r) {
  const g = eff(r);
  const rv = S.reviews[r.id];
  const skipped = NOT_GRADED.includes(r.grade);
  const reviewText = rv ? (rv.critical ? 'Marked Critical' : rv.grade ? `Regraded to ${rv.grade}` : 'Agreed with the judge') : '';
  const gradePick = select('Change grade', NOT_GRADED.includes(g) || g === 'Critical' ? 'High' : g,
    [['Pass', 'Pass'], ['Low', 'Low'], ['Medium', 'Medium'], ['High', 'High']], (v) => review({ grade: v }), { disabled: skipped || !!S.busy });
  const body = skipped
    ? [el('div', { class: 'ev plain', text: `${r.grade}: ${r.skip_reason || r.error || 'no answer received'}` })]
    : [
      el('div', { class: 'judge' },
        el('div', { class: 'jrow' }, el('span', { class: 'lab', text: 'Expected' }), el('span', { class: 'ink', text: r.expected })),
        el('div', { class: 'jrow' }, el('span', { class: 'lab', text: 'What it did' }), el('span', { class: 'ink', text: r.observed })),
        el('div', { class: 'jrow' }, el('span', { class: 'lab', text: 'Why this grade' }), el('span', { text: r.reason })),
        r.fix ? el('div', { class: 'jrow fix' },
          el('span', { class: 'lab', text: OUR_SIDE.includes(r.fix_area) ? 'Fix on our side' : 'Fix for dev team' }),
          el('span', {}, el('span', { class: 'tag white', text: FIX_AREA[r.fix_area] || r.fix_area }), ' ', el('span', { class: 'ink', text: r.fix }),
            ...(r.extra_fix_tags || []).map((t) => el('span', { class: 'tag', text: t })))) : null),
      r.flags?.length ? el('div', {}, el('p', { class: 'sh', text: 'Automatic checks' }),
        el('div', { class: 'flags' }, ...r.flags.map((f) => el('div', { class: 'flag' }, el('span', { class: 'tag', text: f.check }), el('span', { class: 'ev', text: f.evidence }))))) : null,
      r.exchange ? el('div', {},
        el('p', { class: 'sh', text: r.turns > 1 ? `Turn that set the grade (${r.worst_turn} of ${r.turns})` : 'Exchange' }),
        el('div', { class: 'turns' },
          el('div', { class: 'turn user' }, el('div', { class: 'who', text: r.attack_type ? 'Attacker' : 'User' }), r.exchange.user),
          el('div', { class: 'turn bot' }, el('div', { class: 'who', text: 'Chatbot' }), ...highlight(r.exchange.bot, r.exchange.highlight))),
        r.turns > 1 && r.transcript ? el('a', { class: 'small', href: '#', text: S.showTranscript ? 'Hide full transcript' : `Open full transcript (${r.turns} turns)`,
          onclick: (e) => { e.preventDefault(); S.showTranscript = !S.showTranscript; render(); } }) : null,
        S.showTranscript && r.transcript ? el('div', { class: 'turns' }, ...r.transcript.map((t) =>
          el('div', { class: `turn ${t.role === 'user' ? 'user' : 'bot'}` }, el('div', { class: 'who', text: t.role === 'user' ? (r.attack_type ? 'Attacker' : 'User') : 'Chatbot' }), t.content))) : null) : null,
    ];
  return el('section', { class: 'card', 'aria-label': 'Case detail' }, el('div', { class: 'detail' },
    el('div', {},
      el('div', { class: 'chips' }, gradeChip(g), el('span', { class: 'fm', text: r.failure_mode || '—' }), el('span', { class: 'tag', text: fmPrinciple(r.failure_mode) }),
        el('span', { class: 'tag', text: ATTACK_LABEL[r.attack_type] || QTYPE_LABEL[r.question_type] || '' }),
        r.converters?.length ? el('span', { class: 'tag', text: r.converters.join(' → ') }) : null),
      el('h2', { text: r.title }),
      el('div', { class: 'mono muted small', text: `${r.name} · ${r.repeats ? `passed repeats ${r.repeats.passed}/${r.repeats.total}` : 'not run'} · judge confidence ${r.confidence == null ? '—' : r.confidence.toFixed(2)}` })),
    ...body,
    el('div', { class: 'review' },
      el('p', { class: 'sh', text: 'Human review' }),
      rv ? el('p', { class: 'done', text: reviewText }) : null,
      el('div', { class: 'btn-row' },
        el('button', { class: 'btn sec', disabled: skipped || !!S.busy, text: 'Agree with judge', onclick: () => review({ agreed: true }) }),
        gradePick,
        el('button', { class: 'btn sec danger', disabled: skipped || !!S.busy, text: 'Mark Critical', onclick: () => review({ critical: true }) }),
        el('button', { class: 'btn sec push', disabled: !!S.busy, text: 'Re-run case', onclick: () => rerun(r.id) })))));
}

function openCase(id) {
  Object.assign(S, { tab: 'all', selId: id, grade: 'all', attack: 'all', qtype: 'all', reviewOnly: false, q: '' });
  render();
}

// ---------------------------------------------------------------- actions

async function review(patch) {
  const cur = run();
  const r = cur.results.find((x) => x.id === S.selId) || filtered(cur.results)[0] || cur.results[0];
  S.busy = 'Saving review...'; render();
  try {
    const out = await reviewCase(cur.id, { case: r.id, ...patch });
    const i = cur.results.findIndex((x) => x.id === r.id);
    cur.results[i] = out.result;
    S.reviews[r.id] = out.result.review || { agreed: true };
    S.selId = r.id; S.msg = '';
  } catch (e) { S.msg = `Review not saved: ${e.message}`; }
  S.busy = ''; render();
}

async function rerun(caseId) {
  S.busy = 'Starting re-run...'; render();
  try {
    const out = await rerunCases(run().id, caseId ? { case: caseId } : { failed_only: true });
    location.hash = `#/live/${encodeURIComponent(out.id)}`;
  } catch (e) { S.msg = `Re-run not started: ${e.message}`; }
  S.busy = ''; render();
}

function download(format) {
  window.open(runResultsDownloadUrl(run().id, format), format === 'html' ? '_blank' : '_self');
}

async function grade(reportName) {
  if (!reportName) return;
  S.busy = 'Grading (this calls the judge for every answer)...'; render();
  try {
    const graded = await gradeReport(reportName);
    S.runs = [graded, ...S.runs.filter((r) => r.id !== graded.id)];
    S.ungraded = S.ungraded.filter((n) => n !== reportName);
    S.runId = graded.id; S.selId = null; seedReviews(); S.msg = '';
  } catch (e) { S.msg = `Grading failed: ${e.message}`; }
  S.busy = ''; render();
}
