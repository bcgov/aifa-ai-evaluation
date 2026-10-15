import { getRun, getCase, pauseRun, stopRun, exportCsv, listRuns } from './api.js';

const $ = (id) => document.getElementById(id);
const POLL_MS = 2000;
const TICK_MS = 1000;
const FINAL = ['done', 'stopped', 'failed'];
const LABEL = {
  queued: 'QUEUED', running: 'RUNNING', pass: 'PASS', fail: 'FAIL', review: 'REVIEW',
  refused: 'REFUSED', error: 'ERROR', stopping: 'STOPPING', paused: 'PAUSED',
};

let runId = null;
let selectedCase = null;
let attemptTab = 1;
let timer = null;
let ticker = null;

const pct = (value, total) => (total ? Math.round(((value || 0) / total) * 100) : 0);
const fmtClock = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000));
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
};

function setTrack(trackId, value, total) {
  $(trackId).style.width = pct(value, total) + '%';
}

function renderHeader(run) {
  const chip = $('live-status');
  chip.hidden = !run;
  if (run) {
    chip.textContent = (LABEL[run.status] || run.status.toUpperCase());
    chip.className = 'status-chip ' + run.status;
  }
  $('live-sub').textContent = run ? run.name : 'No run selected.';

  const active = run && !FINAL.includes(run.status) && run.status !== 'stopping';
  $('live-pause').disabled = !active;
  $('live-stop').disabled = !(run && !FINAL.includes(run.status));
  $('live-pause').textContent = run?.status === 'paused' ? 'Resume' : 'Pause';
  $('live-export').hidden = !(run && run.report_name);
  $('live-export').onclick = () => exportCsv({ reports: [run.report_name] });
}

function renderStats(run) {
  const c = run?.counts || {};
  const done = c.done || 0, total = c.total || 0;
  const sent = c.attempts_sent || 0, sentTotal = c.attempts_total || 0;

  $('st-done').textContent = total ? done + ' / ' + total : '–';
  setTrack('tr-done', done, total);

  $('st-sent').textContent = sentTotal ? sent + ' / ' + sentTotal : '–';
  $('st-sent-total').textContent = sentTotal && sent > sentTotal ? ' (stopped early)' : '';
  setTrack('tr-sent', sent, sentTotal);

  $('st-fail').textContent = c.fail ?? '–';
  setTrack('tr-fail', c.fail, sentTotal);
  const bits = [];
  if (c.pass) bits.push(c.pass + ' passed');
  if (c.review) bits.push(c.review + ' need review');
  if (c.error) bits.push(c.error + ' errored');
  if (c.refused) bits.push(c.refused + ' attacker refusals');
  $('st-other').textContent = bits.join(' · ');
}

function renderClock(run) {
  if (!run || !run.started_at) { $('st-elapsed').textContent = '–'; $('st-remaining').textContent = ''; return; }
  const end = run.finished_at ? new Date(run.finished_at) : new Date();
  const elapsedMs = end - new Date(run.started_at);
  $('st-elapsed').textContent = fmtClock(elapsedMs);
  const c = run.counts || {};
  const sent = c.attempts_sent || 0, sentTotal = c.attempts_total || 0;
  const rate = sent > 1 ? sent / (elapsedMs / 1000) : 0;
  $('st-remaining').textContent = rate && !FINAL.includes(run.status) && sent < sentTotal
    ? '≈ ' + fmtClock(((sentTotal - sent) / rate) * 1000) + ' remaining'
    : '';
}

function renderCases(run) {
  const list = $('case-list');
  list.replaceChildren();
  if (!run || !run.cases?.length) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = run ? 'No cases in this run.' : 'Start a run from New Run, or pick one under Export once it is saved.';
    list.append(p);
    return;
  }
  run.cases.forEach((cs) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'case-row' + (cs.id === selectedCase ? ' sel' : '');
    const name = document.createElement('span'); name.className = 'case-name'; name.textContent = cs.name;
    const attack = document.createElement('span'); attack.textContent = cs.attack || '–';
    const rep = document.createElement('span'); rep.className = 'mono'; rep.textContent = cs.repeat || '–';
    const prog = document.createElement('span');
    prog.className = 'mini-track';
    const fill = document.createElement('span');
    fill.style.width = pct(parseInt(cs.repeat || '0', 10), parseInt((cs.repeat || '/1').split('/')[1], 10)) + '%';
    prog.append(fill);
    const badge = document.createElement('span');
    badge.className = 'badge ' + cs.status;
    badge.textContent = LABEL[cs.status] || cs.status;
    row.append(name, attack, rep, prog, badge);
    row.addEventListener('click', () => selectCase(cs.id));
    list.append(row);
  });
}

async function selectCase(id) {
  selectedCase = id;
  attemptTab = 1;
  await renderCase();
  renderCases(latestRun); // refresh highlight
}

let latestRun = null;

async function renderCase() {
  const box = $('transcript');
  box.hidden = !selectedCase;
  if (!selectedCase) return;
  let data;
  try {
    data = await getCase(runId, selectedCase);
  } catch (err) {
    box.hidden = false;
    $('turns').textContent = 'Could not load the transcript: ' + err.message;
    return;
  }

  $('tr-name').textContent = data.name;
  $('tr-meta').replaceChildren();
  const meta = document.createElement('span');
  meta.textContent = 'Expected: ' + (data.expected_behavior || 'not set') + (data.converters?.length ? ' · Disguises: ' + data.converters.join(' → ') : ' · No disguises');
  $('tr-meta').append(meta);

  // attempt tabs
  const tabs = $('tr-attempts');
  tabs.replaceChildren();
  (data.attempts || []).forEach((a) => {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = (a.attempt === attemptTab ? 'on ' : '') + a.status;
    tab.textContent = 'Try ' + a.attempt;
    tab.setAttribute('role', 'tab');
    tab.addEventListener('click', () => { attemptTab = a.attempt; renderCase(); });
    tabs.append(tab);
  });
  if (!(data.attempts || []).some((a) => a.attempt === attemptTab)) attemptTab = (data.attempts || [])[0]?.attempt || 1;

  const attempt = (data.attempts || []).find((a) => a.attempt === attemptTab);
  const turns = $('turns');
  turns.replaceChildren();
  if (!attempt) {
    turns.textContent = 'This case has not started yet.';
    return;
  }
  (attempt.turns || []).forEach((t) => {
    const turn = document.createElement('div');
    turn.className = 'turn ' + t.role;
    const role = document.createElement('div'); role.className = 'turn-role'; role.textContent = t.role;
    turn.append(role);
    const text = document.createElement('div'); text.className = 'turn-text'; text.textContent = t.text || '';
    turn.append(text);
    if (t.converted && t.converted !== t.text) {
      const sub = document.createElement('div'); sub.className = 'turn-sub';
      sub.textContent = 'Sent as: ' + t.converted + (t.readable && t.readable !== t.converted ? ' (readable: ' + t.readable + ')' : '');
      turn.append(sub);
    }
    if (t.category) {
      const cat = document.createElement('span'); cat.className = 'tag cat'; cat.textContent = 'category: ' + t.category;
      turn.append(cat);
    }
    turns.append(turn);
  });
  if (!(attempt.turns || []).length) turns.textContent = 'No turns recorded for this attempt yet.';
}

async function poll(schedule = true) {
  let run = null;
  try {
    run = await getRun(runId);
  } catch (err) {
    $('live-sub').textContent = 'Lost contact with the server: ' + err.message;
    if (schedule) timer = setTimeout(poll, POLL_MS * 2);
    return;
  }
  latestRun = run;
  renderHeader(run);
  renderStats(run);
  renderClock(run);
  renderCases(run);
  if (selectedCase) await renderCase();
  const finished = FINAL.includes(run.status);
  if (schedule && !finished) timer = setTimeout(poll, POLL_MS);
  if (finished) stopTicker(); else ensureTicker();
}

function ensureTicker() {
  if (!ticker) ticker = setInterval(() => { if (latestRun) { renderClock(latestRun); } }, TICK_MS);
}
function stopTicker() { clearInterval(ticker); ticker = null; }

export async function showRun(id) {
  clearTimeout(timer);
  stopTicker();
  runId = id;
  selectedCase = null;
  $('transcript').hidden = true;
  if (!runId) {
    const runs = await listRuns().catch(() => []);
    const latest = runs.find((r) => !FINAL.includes(r.status)) || runs[0];
    if (!latest) { renderHeader(null); renderStats({}); renderCases(null); return; }
    runId = latest.id;
  }
  poll();
}

export function stopPolling() { clearTimeout(timer); stopTicker(); }

export function initLiveRun() {
  $('live-pause').addEventListener('click', async () => { if (runId) { await pauseRun(runId); poll(false); } });
  $('live-stop').addEventListener('click', async () => {
    if (runId && confirm('Stop this run? Cases that already finished are kept and saved.')) { await stopRun(runId); poll(false); }
  });
}
