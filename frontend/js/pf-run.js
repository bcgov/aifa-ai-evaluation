import { $, el, badge, fmtDuration } from './dom.js';
import { getJob, getJobLogs, cancelJob, getResult } from './promptfoo-api.js';

const ACTIVE = ['queued', 'running'];
const CHIP = { succeeded: 'done', failed: 'failed', cancelled: 'stopped', running: 'running' };
const state = { jobId: null, next: 0, timer: null, inflight: false, autoscroll: true, summarized: false, active: false };

const pct = (v) => (v === null || v === undefined ? '–' : v + '%');

function print(text) {
  const con = $('pfx-console');
  con.append(text);
  if (state.autoscroll) con.scrollTop = con.scrollHeight;
}

function renderJob(job) {
  const running = ACTIVE.includes(job.status);
  $('pfx-sub').textContent = job.label + (job.step_count > 1 ? ' · step ' + (job.step + 1) + '/' + job.step_count : '')
    + ' · ' + fmtDuration(job.started_at, job.finished_at);
  const chip = $('pfx-status');
  chip.hidden = false;
  chip.textContent = job.status;
  chip.className = 'status-chip ' + (CHIP[job.status] || '');
  $('pfx-cancel').disabled = !running;
  const open = $('pfx-open');
  open.hidden = !(job.status === 'succeeded' && job.output && job.output_kind === 'json');
  if (!open.hidden) open.href = '#/pf-results/' + encodeURIComponent(job.output);
}

async function showSummary(job) {
  state.summarized = true;
  if (job.status !== 'succeeded' || !job.output || job.output_kind !== 'json') {
    print('\n── ' + job.status.toUpperCase() + (job.exit_code !== null ? ' (exit ' + job.exit_code + ')' : '') + ' ──\n');
    return;
  }
  try {
    const { summary: s, rows } = await getResult(job.output);
    $('pfx-st-total').textContent = s.total;
    $('pfx-st-pass').textContent = s.pass;
    $('pfx-st-fail').textContent = s.fail;
    $('pfx-st-error').textContent = s.error;
    $('pfx-st-rate').textContent = pct(s.pass_rate);
    $('pfx-summary').hidden = false;
    print('\n── Summary ──\n✔ passed: ' + s.pass + '   ✖ failed: ' + s.fail + '   ⚠ errors: ' + s.error
      + '   (' + s.total + ' tests, pass rate ' + pct(s.pass_rate) + ')\n');
    $('pfx-rows').replaceChildren(...rows.map((r) => el('details', { class: 'pf-row' },
      el('summary', {}, badge(r.status), el('span', { class: 'pf-row-text', text: (r.description || r.prompt || '').slice(0, 180) })),
      el('div', { class: 'pf-row-body' },
        el('div', { class: 'turn target' }, el('div', { class: 'turn-role', text: 'Response' }), el('div', { class: 'turn-text', text: r.output || '(empty)' })),
        el('div', { class: 'turn judge' }, el('div', { class: 'turn-role', text: 'Grader' + (r.score !== null && r.score !== undefined ? ' · score ' + r.score : '') }),
          el('div', { class: 'turn-text', text: r.reason || '(no reason)' }))))));
  } catch (err) {
    print('\n(could not load the result summary: ' + err.message + ')\n');
  }
}

async function poll() {
  clearTimeout(state.timer);
  if (!state.active || state.inflight || !state.jobId) return;
  state.inflight = true;
  const id = state.jobId;
  try {
    const job = await getJob(id);
    const logs = await getJobLogs(id, state.next);
    if (id !== state.jobId) return;
    state.next = logs.next;
    if (logs.truncated) print('… earlier output truncated …\n');
    if (logs.lines.length) print(logs.lines.join('\n') + '\n');
    renderJob(job);
    if (ACTIVE.includes(job.status)) state.timer = setTimeout(poll, 1000);
    else if (!state.summarized) await showSummary(job);
  } catch (err) {
    $('pfx-sub').textContent = err.message;
    if (state.active) state.timer = setTimeout(poll, 4000);
  } finally {
    state.inflight = false;
    if (state.active && state.jobId !== id) poll();
  }
}

export function initPfRun() {
  const con = $('pfx-console');
  con.addEventListener('scroll', () => { state.autoscroll = con.scrollTop + con.clientHeight >= con.scrollHeight - 20; });
  $('pfx-cancel').addEventListener('click', async () => {
    if (!state.jobId || !confirm('Cancel this run?')) return;
    try { await cancelJob(state.jobId); } catch (err) { $('pfx-sub').textContent = err.message; }
    poll();
  });
}

export function showPfRun(jobId) {
  state.active = true;
  if (jobId !== state.jobId) {
    state.jobId = jobId || null;
    state.next = 0;
    state.summarized = false;
    state.autoscroll = true;
    $('pfx-console').textContent = '';
    $('pfx-summary').hidden = true;
    $('pfx-status').hidden = true;
    $('pfx-open').hidden = true;
    $('pfx-rows').replaceChildren();
    $('pfx-sub').textContent = jobId ? 'Starting…' : 'No run selected. Start one from Run tests.';
  }
  poll();
}

export function stopPfRun() {
  state.active = false;
  clearTimeout(state.timer);
}
