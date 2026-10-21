// Promptfoo container API. nginx routes /api/promptfoo/* to the promptfoo container.
import { request, post } from './api.js';

const enc = encodeURIComponent;
const PF = '/promptfoo';

export const PF_BASE_URL = '/api' + PF;
export const getInfo     = () => request(PF + '/info');

export const listTestFiles = () => request(PF + '/tests/files');                   // every YAML file in data_promptfoo
export const listDatasetCases = (name) => request(PF + '/tests/datasets/' + enc(name) + '/cases');
export const runDatasetTests = (dataset, cases) => post(PF + '/tests/run', { dataset, cases }); // -> job
export const startJob  = (command, options) => post(PF + '/jobs', { command, options });
export const getJob    = (id) => request(PF + '/jobs/' + enc(id));
export const getJobLogs = (id, since) => request(PF + '/jobs/' + enc(id) + '/logs?since=' + since);
export const cancelJob = (id) => post(PF + '/jobs/' + enc(id) + '/cancel');

export const listResults = () => request(PF + '/results');
export const getResult = (name, status = 'all') => request(PF + '/results/' + enc(name) + '?status=' + enc(status));
export const resultDownloadUrl = (name) => PF_BASE_URL + '/results/' + enc(name) + '/download';
export const resultCsvUrl = (name) => PF_BASE_URL + '/results/' + enc(name) + '/csv';
