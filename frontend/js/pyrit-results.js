import { $, el, fmtTime } from './dom.js';
import { listReports, getReport, getReportInsights } from './api.js';

const state = { name: null, report: null, insights: null, filter: 'all', search: '', reports: [] };

const pct = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '–';
  return Math.round(Number(value)) + '%';
};

const normalizeStatus = (value) => {
  const text = String(value || 'unknown').toLowerCase();
  if (text.includes('error') || text.includes('transport_error')) return 'error';
  if (text.includes('failure') || text.includes('fail')) return 'fail';
  if (text.includes('success')) return 'pass';
  if (text.includes('undetermined') || text.includes('review')) return 'review';
  return 'pass';
};

function flattenTurns(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.flatMap((item) => flattenTurns(item));
  if (typeof value === 'object') {
    if (Array.isArray(value.turns)) return value.turns.flatMap((item) => flattenTurns(item));
    if (Array.isArray(value.results)) return value.results.flatMap((item) => flattenTurns(item));
    if (value.response || value.prompt || value.outcome || value.status) return [value];
    if (value.items && Array.isArray(value.items)) return value.items.flatMap((item) => flattenTurns(item));
  }
  return [];
}

function renderList() {
  const box = $('pyr-list');
  box.replaceChildren();
  const q = $('pyr-list-filter').value.trim().toLowerCase();
  const items = state.reports.filter((r) => !q || `${r.name} ${r.summary?.attack_type || ''} ${r.summary?.status || ''}`.toLowerCase().includes(q));

  if (!items.length) {
    box.append(el('p', { class: 'empty', text: state.reports.length ? 'No saved PyRIT reports match this filter.' : 'No saved PyRIT reports yet. Finish a run first.' }));
    return;
  }

  items.forEach((r) => {
    const s = r.summary || {};
    const passRate = s.total_turns ? ((s.successful_turns || 0) / Number(s.total_turns || 1)) * 100 : 0;
    const statusClass = s.status === 'ok' ? 'ok-text' : s.status === 'unreadable' ? 'warn-text' : 'bad-text';
    box.append(el('a', { class: 'pf-res-row', href: '#/pyrit-results/' + encodeURIComponent(r.name) },
      el('span', {},
        el('span', { class: 'case-name mono', text: r.name }),
        s.attack_type ? el('div', { class: 'note nomargin', text: s.attack_type }) : null),
      el('span', { text: fmtTime(r.updated_at) }),
      el('span', { class: 'mono', text: s.attack_type || '–' }),
      el('span', { text: String(s.total_cases ?? '–') }),
      el('span', { text: String(s.total_turns ?? '–') }),
      el('span', { class: statusClass, text: s.status || '–' }),
      el('span', { class: 'strong', text: pct(passRate) })));
  });
}

function breakdown(boxId, groups, key = 'count') {
  const box = $(boxId);
  box.replaceChildren();
  if (!groups || !groups.length) {
    box.append(el('p', { class: 'empty', text: 'No data.' }));
    return;
  }

  groups.forEach((g) => {
    const total = Math.max(1, Number(g[key] || 0));
    const pctValue = (value) => (100 * (Number(value || 0) / total));
    box.append(el('div', { class: 'pf-break-row' },
      el('span', { class: 'mono pf-break-name', text: g.name || 'unknown' }),
      el('span', { class: 'pf-bar' },
        el('span', { class: 'ok', style: 'width:' + pctValue(g.pass) + '%' }),
        el('span', { class: 'bad', style: 'width:' + pctValue(g.fail) + '%' }),
        el('span', { class: 'warn', style: 'width:' + pctValue(g.error) + '%' })),
      el('span', { class: 'note nomargin mono', text: `${g.pass ?? 0} / ${g.fail ?? 0} / ${g.error ?? 0}` })));
  });
}

function extractRows(report) {
  if (!report) return [];
  const raw = report.results || [];
  const items = Array.isArray(raw) ? raw : raw && typeof raw === 'object' ? [raw] : [];

  return items
    .map((item, index) => {
      const turns = flattenTurns(item.results || item.turns || item);
      const turn = turns[0] || {};
      const outcome = turn.outcome || turn.status || 'unknown';
      const query = item.query || item.prompt || turn.prompt || turn.original_prompt || `Case ${index + 1}`;
      const response = turn.response || turn.output || item.response_preview || item.response || '';
      return {
        name: item.name || item.case_name || `case_${index + 1}`,
        query,
        response,
        outcome,
        status: normalizeStatus(outcome),
        attack_type: item.attack_type || report.attack_type || 'unknown',
        turn_count: turns.length,
      };
    })
    .filter((item) => item.query || item.response);
}

function renderRows() {
  const box = $('pyr-rows');
  const search = state.search.toLowerCase();
  const rows = extractRows(state.report).filter((r) => {
    const matchesFilter = state.filter === 'all' || r.status === state.filter;
    const haystack = `${r.name} ${r.query} ${r.response} ${r.attack_type}`.toLowerCase();
    return matchesFilter && (!search || haystack.includes(search));
  });

  $('pyr-row-count').textContent = rows.length + ' shown';
  box.replaceChildren();

  if (!rows.length) {
    box.append(el('p', { class: 'empty', text: 'No cases match this filter.' }));
    return;
  }

  rows.slice(0, 500).forEach((r) => {
    const detail = el('details', { class: 'pf-row' },
      el('summary', {},
        el('span', { class: 'tag cat mono', text: r.attack_type }),
        el('span', { class: 'tag ' + (r.status === 'fail' ? 'error' : r.status === 'pass' ? 'pass' : 'review') + ' mono', text: r.status }),
        el('span', { class: 'pf-row-text', text: (r.query || 'Case').slice(0, 160) })
      ),
      el('div', { class: 'pf-row-body' },
        el('div', { class: 'turn attacker' },
          el('div', { class: 'turn-role', text: 'Query' }),
          el('div', { class: 'turn-text', text: r.query || '(empty)' })
        ),
        el('div', { class: 'turn target' },
          el('div', { class: 'turn-role', text: 'Response' }),
          el('div', { class: 'turn-text', text: r.response || '(empty)' })
        ),
        r.outcome ? el('p', { class: 'note', text: 'Outcome: ' + r.outcome }) : null,
        r.turn_count ? el('p', { class: 'note', text: 'Turns: ' + r.turn_count }) : null
      )
    );
    box.append(detail);
  });

  if (rows.length > 500) box.append(el('p', { class: 'note pad', text: 'Showing first 500. Download the raw JSON report for everything.' }));
}

function renderDetail() {
  const report = state.report;
  const insights = state.insights || {};
  const summary = insights.summary || report?.summary || {};
  const totalCases = summary.total_cases ?? (report?.results && Array.isArray(report.results) ? report.results.length : 0);
  const totalTurns = summary.total_turns ?? 0;
  const passCount = summary.successful_turns ?? 0;
  const errorCount = summary.error_count ?? 0;
  const reviewCount = summary.unscored_turns ?? 0;
  const rate = summary.total_turns ? (passCount / Number(summary.total_turns || 1)) * 100 : 0;

  $('pyr-title').textContent = state.name;
  $('pyr-sub').textContent = `${state.name} · ${fmtTime(report?.timestamp || report?.updated_at)}`;
  $('pyr-st-total').textContent = String(totalCases);
  $('pyr-st-turns').textContent = String(totalTurns);
  $('pyr-st-pass').textContent = String(passCount);
  $('pyr-st-review').textContent = String(reviewCount);
  $('pyr-st-error').textContent = String(errorCount);
  $('pyr-st-rate').textContent = pct(rate);
  $('pyr-tr-rate').style.width = rate + '%';
  $('pyr-pass-label').textContent = 'Successful turns';
  $('pyr-fail-label').textContent = 'Review / incomplete';

  breakdown('pyr-attacks', insights.attack_breakdown || [], 'count');
  breakdown('pyr-outcomes', insights.outcome_distribution || [], 'count');
  renderRows();
}

export function initPyritResults() {
  $('pyr-list-filter').addEventListener('input', renderList);
  $('pyr-search').addEventListener('input', (e) => {
    state.search = e.target.value.trim();
    renderRows();
  });
  document.querySelectorAll('#pyr-filter button').forEach((button) => button.addEventListener('click', () => {
    state.filter = button.dataset.status;
    document.querySelectorAll('#pyr-filter button').forEach((item) => item.classList.toggle('on', item === button));
    renderRows();
  }));
}

export async function showPyritResults(name) {
  state.name = name || null;
  $('pyr-list-view').hidden = !!name;
  $('pyr-detail').hidden = !name;
  ['pyr-back', 'pyr-json'].forEach((id) => { $(id).hidden = !name; });

  if (!name) {
    $('pyr-title').textContent = 'PyRIT results';
    $('pyr-sub').textContent = 'Every saved red-team report from the local results directory.';
    try {
      state.reports = await listReports();
    } catch (err) {
      state.reports = [];
      $('pyr-sub').textContent = err.message;
    }
    renderList();
    return;
  }

  $('pyr-title').textContent = name;
  $('pyr-sub').textContent = 'Loading…';
  $('pyr-rows').replaceChildren();

  try {
    const [report, insights] = await Promise.all([getReport(name), getReportInsights(name)]);
    state.report = report;
    state.insights = insights;
    if (state.name === name) renderDetail();
    $('pyr-json').href = `/api/reports/${encodeURIComponent(name)}`;
    $('pyr-json').download = name;
  } catch (err) {
    $('pyr-sub').textContent = err.message;
  }
}
