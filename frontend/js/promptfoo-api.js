// Promptfoo container API. nginx routes /api/promptfoo/* to the promptfoo container.
import { request, post } from './api.js';

const enc = encodeURIComponent;
const PF = '/promptfoo';

export const PF_BASE_URL = '/api' + PF;
export const getInfo     = () => request(PF + '/info');
export const getCommands = () => request(PF + '/commands');
export const getCatalog  = () => request(PF + '/catalog');
export const listConfigs = () => request(PF + '/configs');
export const getConfigText = async (name) => {
  const res = await fetch(PF_BASE_URL + '/configs/' + enc(name), { credentials: 'same-origin' });
  if (!res.ok) throw new Error('Could not load config (' + res.status + ')');
  return res.text();
};

export const createAttack = (payload) => post(PF + '/attacks', payload);           // -> { config, job_id? }
export const startJob  = (command, options) => post(PF + '/jobs', { command, options });
export const listJobs  = () => request(PF + '/jobs');
export const getJob    = (id) => request(PF + '/jobs/' + enc(id));
export const getJobLogs = (id, since) => request(PF + '/jobs/' + enc(id) + '/logs?since=' + since);
export const cancelJob = (id) => post(PF + '/jobs/' + enc(id) + '/cancel');

export const listResults = () => request(PF + '/results');
export const getResult = (name, status = 'all') => request(PF + '/results/' + enc(name) + '?status=' + enc(status));
export const resultDownloadUrl = (name) => PF_BASE_URL + '/results/' + enc(name) + '/download';
export const resultCsvUrl = (name) => PF_BASE_URL + '/results/' + enc(name) + '/csv';
