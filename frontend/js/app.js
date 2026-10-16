import { initNewRun } from './new-run.js';
import { initLiveRun, showRun, stopPolling } from './live-run.js';
import { initExport, showExport } from './export.js';
import { getHealth } from './api.js';
import { getInfo } from './promptfoo-api.js';
import { initPfAttack, refreshPfAttack } from './pf-attack.js';
import { initPfCommands, openPfCommand } from './pf-commands.js';
import { initPfJobs, showPfJobs, stopPfJobs } from './pf-jobs.js';
import { initPfResults, showPfResults } from './pf-results.js';

const VIEWS = ['new', 'live', 'export', 'pf-attack', 'pf-commands', 'pf-jobs', 'pf-results'];
let pendingCommand = null; // pre-filled command handed from Results to Run tests

// Hash routes:  #/new  #/live[/<runId>]  #/export  #/pf-attack  #/pf-commands  #/pf-jobs[/<jobId>]  #/pf-results[/<name>]
function route() {
  const [, raw, id] = location.hash.split('/');
  const view = VIEWS.includes(raw) ? raw : 'new';
  const param = id ? decodeURIComponent(id) : null;
  VIEWS.forEach((v) => { document.getElementById('view-' + v).hidden = v !== view; });
  document.querySelectorAll('.nav-item').forEach((a) => a.classList.toggle('active', a.dataset.view === view));
  if (view === 'live') showRun(param); else stopPolling();
  if (view === 'pf-jobs') showPfJobs(param); else stopPfJobs();
  if (view === 'export') showExport();
  if (view === 'pf-attack') refreshPfAttack();
  if (view === 'pf-commands') { openPfCommand(pendingCommand?.command, pendingCommand?.values); pendingCommand = null; }
  if (view === 'pf-results') showPfResults(param);
}

async function checkEngines() {
  const [pyrit, pf] = await Promise.allSettled([getHealth(), getInfo()]);
  const set = (id, ok, title) => {
    const dot = document.getElementById(id);
    dot.className = 'dot ' + (ok ? 'ok' : 'bad');
    dot.title = title;
  };
  set('eng-pyrit', pyrit.status === 'fulfilled', pyrit.status === 'fulfilled' ? 'PyRIT reachable' : 'PyRIT unreachable');
  const pfOk = pf.status === 'fulfilled' && pf.value.status === 'ok';
  set('eng-promptfoo', pfOk, pfOk ? 'promptfoo ' + pf.value.version : 'Promptfoo unreachable');
}

const openJob = (id) => { location.hash = '#/pf-jobs/' + encodeURIComponent(id); };

initLiveRun();
initExport();
initNewRun({ onStarted: (id) => { location.hash = '#/live/' + encodeURIComponent(id); } });
initPfAttack({ onJob: openJob });
initPfCommands({ onJob: openJob });
initPfJobs({ onOpenResult: (name) => { location.hash = '#/pf-results/' + encodeURIComponent(name); } });
initPfResults({
  onRerun: (values) => { pendingCommand = { command: 'eval', values }; location.hash = '#/pf-commands'; },
});
window.addEventListener('hashchange', route);
route();
checkEngines();
setInterval(checkEngines, 30000);
