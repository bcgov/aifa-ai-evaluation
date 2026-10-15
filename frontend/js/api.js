// All backend calls live here. No data in this file.
const API_BASE = '/api';

async function send(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...options,
  });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail; } catch { /* non-JSON error body */ }
    throw new Error(typeof detail === 'string' && detail ? detail : path + ' failed (' + res.status + ')');
  }
  return res;
}

async function request(path, options) {
  const res = await send(path, options);
  return res.status === 204 ? null : res.json();
}

const post = (path, body) => request(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

const CONVERTER_LABELS = {
  base64: 'Base64 · instant',
  rot13: 'ROT13 · instant',
  leetspeak: 'Leetspeak · instant',
  morse: 'Morse code · instant',
  ascii_smuggler: 'Hidden text (ASCII smuggler) · instant',
  translation: 'Translation (French) · needs LLM',
};
export const LLM_CONVERTERS = ['translation'];

// Dropdown sources
export const getTenants  = () => request('/tenants');   // [{ id, name, approved }]
export const getDatasets = () => request('/datasets');  // [{ id, name, case_count }]
export const getConverters = async () =>                 // backend returns names; UI wants { id, name }
  (await request('/converters')).map((id) => ({ id, name: CONVERTER_LABELS[id] || id }));

// Runs
export const startRun = (payload) => post('/runs', payload); // -> { id }
export const listRuns = () => request('/runs');
export const getRun   = (id) => request('/runs/' + encodeURIComponent(id));
export const getCase  = (runId, caseId) =>
  request('/runs/' + encodeURIComponent(runId) + '/cases/' + encodeURIComponent(caseId));
export const pauseRun = (id) => post('/runs/' + encodeURIComponent(id) + '/pause');
export const stopRun  = (id) => post('/runs/' + encodeURIComponent(id) + '/stop');

// Saved reports + export
export const listReports = () => request('/reports');

// payload: { reports: [names] } or { all: true }. Downloads a single CSV file.
export async function exportCsv(payload) {
  const res = await send('/export/csv', { method: 'POST', body: JSON.stringify(payload) });
  const match = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '');
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement('a'), { href: url, download: match ? match[1] : 'red_team_export.csv' });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
