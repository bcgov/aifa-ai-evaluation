import { listReports, exportCsv } from './api.js';

const $ = (id) => document.getElementById(id);
const EXPORTABLE = /^((run)|(scan))_.*\.json$/;

let reports = [];
const selected = new Set();
let lastFilter = '';

const matchesFilter = (r) => !lastFilter
  || r.name.toLowerCase().includes(lastFilter)
  || String(r.summary?.attack_type || '').toLowerCase().includes(lastFilter);

function rowCells(r) {
  const date = r.updated_at ? new Date(r.updated_at).toLocaleString() : '–';
  const s = r.summary || {};
  return [date, s.attack_type || '–', String(s.total_cases ?? '–'), String(s.total_turns ?? '–'), s.status || '–'];
}

function renderList() {
  const list = $('exp-list');
  list.replaceChildren();
  const shown = reports.filter(matchesFilter);
  if (!shown.length) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = reports.length ? 'No reports match this filter.' : 'No saved reports yet. Finish a run first.';
    list.append(p);
  }
  shown.forEach((r) => {
    const row = document.createElement('div');
    row.className = 'exp-row clickable';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = selected.has(r.name);
    box.setAttribute('aria-label', 'Select ' + r.name);
    const name = document.createElement('span'); name.className = 'mono'; name.textContent = r.name;
    row.append(box, name);
    rowCells(r).forEach((cell) => {
      const span = document.createElement('span');
      if (cell === r.summary?.status) {
        span.className = 'badge ' + (cell === 'ok' ? 'pass' : cell === 'unreadable' ? 'review' : 'error');
      }
      span.textContent = cell;
      row.append(span);
    });
    row.addEventListener('click', (e) => {
      if (e.target !== box) box.checked = !box.checked;
      box.checked ? selected.add(r.name) : selected.delete(r.name);
      renderButtons();
    });
    list.append(row);
  });
  renderButtons();
}

function renderButtons() {
  const shown = reports.filter(matchesFilter);
  $('exp-check-all').checked = shown.length > 0 && shown.every((r) => selected.has(r.name));
  $('exp-selected').disabled = selected.size === 0;
  $('exp-selected').textContent = selected.size
    ? 'Export ' + selected.size + ' report' + (selected.size > 1 ? 's' : '') + ' to one CSV'
    : 'Export selected';
}

async function download(payload, msg) {
  const button = payload.all ? $('exp-all') : $('exp-selected');
  button.disabled = true;
  try {
    await exportCsv(payload);
    $('exp-msg').textContent = msg;
  } catch (err) {
    $('exp-msg').textContent = 'Export failed: ' + err.message;
  } finally {
    button.disabled = false;
    renderButtons();
  }
}

export function showExport() {
  $('exp-msg').textContent = '';
  loadReports();
}

async function loadReports() {
  try {
    reports = (await listReports()).filter((r) => EXPORTABLE.test(r.name));
  } catch (err) {
    reports = [];
    $('exp-msg').textContent = 'Could not load saved reports: ' + err.message;
  }
  for (const name of [...selected]) if (!reports.some((r) => r.name === name)) selected.delete(name);
  renderList();
}

export function initExport() {
  $('exp-filter').addEventListener('input', () => {
    lastFilter = $('exp-filter').value.trim().toLowerCase();
    renderList();
  });
  $('exp-check-all').addEventListener('click', () => {
    const shown = reports.filter(matchesFilter);
    const allOn = shown.every((r) => selected.has(r.name));
    shown.forEach((r) => (allOn ? selected.delete(r.name) : selected.add(r.name)));
    renderList();
  });
  $('exp-selected').addEventListener('click', () =>
    download({ reports: [...selected] }, 'Exported ' + selected.size + ' report' + (selected.size > 1 ? 's' : '') + ' as one CSV.'));
  $('exp-all').addEventListener('click', () =>
    download({ all: true }, 'Exported every saved run as one CSV.'));
}
