import { $, el, badge, fmtTime, fmtDuration } from './dom.js';
import { listJobs, getJob, getJobLogs, cancelJob } from './promptfoo-api.js';

const ACTIVE = ['queued', 'running'];
const state = { jobId: null, job: null, next: 0, timer: null, autoscroll: true, inflight: false, active: false };

function renderList(jobs) {
  const box = $('pfj-list');
  box.replaceChildren();
  if (!jobs.length) { box.append(el('p', { class: 'empty', text: 'No jobs yet. Start one from Attack builder or Commands.' })); return; }
  jobs.forEach((j) => box.append(el('button', {
    type: 'button', class: 'pf-job-row' + (j.id === state.jobId ? ' sel' : ''),
    onclick: () => { location.hash = '#/pf-jobs/' + encodeURIComponent(j.id); },
  },
  el('span', { class: 'case-name', text: j.label }),
  el('span', { class: 'mono pf-id', text: j.command }),
  badge(statusClass(j.status), j.status),
  el('span', { class: 'note nomargin', text: fmtDuration(j.started_at, j.finished_at) }))));
}

const statusClass = (s) => ({ succeeded: 'pass', failed: 'fail', cancelled: 'error', running: 'running', queued: 'queued' }[s] || '');

function renderJob() {
  const j = state.job;
  $('pfj-panel').hidden = !j;
  $('pfj-sub').textContent = j ? j.label + ' · started ' + fmtTime(j.started_at || j.created_at) : 'Select a job to see its console output.';
  if (!j) return;
  const chip = $('pfj-status');
  chip.hidden = false;
  chip.textContent = j.status + (j.step_count > 1 ? ' · step ' + (j.step + 1) + '/' + j.step_count : '');
  chip.className = 'status-chip ' + ({ succeeded: 'done', failed: 'failed', cancelled: 'stopped', running: 'running' }[j.status] || '');
  $('pfj-cancel').disabled = !ACTIVE.includes(j.status);
  $('pfj-result').hidden = !(j.output && j.output_kind === 'json');
  $('pfj-cmds').replaceChildren(...j.commands.map((c) => el('div', { class: 'mono pf-cmdline', text: '$ ' + c })));
  $('pfj-meta').textContent = [
    j.exit_code !== null ? 'exit ' + j.exit_code : null,
    'elapsed ' + fmtDuration(j.started_at, j.finished_at),
    j.output ? 'output ' + j.output : null,
  ].filter(Boolean).join(' · ');
}

function appendLogs(lines, truncated) {
  const con = $('pfj-console');
  if (truncated) con.append('… earlier output truncated …\n');
  if (lines.length) con.append(lines.join('\n') + '\n');
  if (state.autoscroll) con.scrollTop = con.scrollHeight;
}

async function poll() {
  clearTimeout(state.timer);
  if (state.inflight || !state.active) return;
  state.inflight = true;
  const jobId = state.jobId;
  try {
    const [jobs, job] = await Promise.all([listJobs(), jobId ? getJob(jobId) : null]);
    renderList(jobs);
    if (jobId) {
      const logs = await getJobLogs(jobId, state.next);
      if (jobId !== state.jobId) { state.timer = setTimeout(poll, 0); return; } // user switched jobs mid-request
      state.job = job;
      state.next = logs.next;
      appendLogs(logs.lines, logs.truncated);
      renderJob();
    }
    const busy = jobs.some((j) => ACTIVE.includes(j.status));
    if (state.active) state.timer = setTimeout(poll, busy ? 1500 : 6000);
  } catch (err) {
    $('pfj-sub').textContent = err.message;
    if (state.active) state.timer = setTimeout(poll, 6000);
  } finally {
    state.inflight = false;
  }
}

export function initPfJobs({ onOpenResult }) {
  $('pfj-cancel').addEventListener('click', async () => {
    if (!state.jobId || !confirm('Cancel this promptfoo job?')) return;
    try { await cancelJob(state.jobId); } catch (err) { $('pfj-sub').textContent = err.message; }
    poll();
  });
  $('pfj-result').addEventListener('click', () => state.job?.output && onOpenResult(state.job.output));
  const con = $('pfj-console');
  con.addEventListener('scroll', () => { state.autoscroll = con.scrollTop + con.clientHeight >= con.scrollHeight - 20; });
}

export function showPfJobs(jobId) {
  state.active = true;
  jobId = jobId || null;
  if (jobId !== state.jobId) {
    state.jobId = jobId;
    state.job = null;
    state.next = 0;
    state.autoscroll = true;
    $('pfj-console').textContent = '';
    $('pfj-status').hidden = true;
  }
  renderJob();
  poll();
}

export function stopPfJobs() { state.active = false; clearTimeout(state.timer); }
