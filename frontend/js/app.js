import { initNewRun } from './new-run.js';
import { initLiveRun, showRun, stopPolling } from './live-run.js';
import { initExport, showExport } from './export.js';
import { getHealth } from './api.js';
import { getInfo, startJob } from './promptfoo-api.js';
import { initPfCommands, showPfCommands } from './pf-commands.js';
import { initPfRun, showPfRun, stopPfRun } from './pf-run.js';
import { initPfResults, showPfResults } from './pf-results.js';

const VIEWS = ['new', 'live', 'export', 'pf-commands', 'pf-run', 'pf-results'];

// Hash routes:  #/new  #/live[/<runId>]  #/export  #/pf-commands  #/pf-run/<jobId>  #/pf-results[/<name>]
function route() {
  const [, raw, id] = location.hash.split('/');
  const view = VIEWS.includes(raw) ? raw : 'new';
  const param = id ? decodeURIComponent(id) : null;
  VIEWS.forEach((v) => { document.getElementById('view-' + v).hidden = v !== view; });
  document.querySelectorAll('.nav-item').forEach((a) => a.classList.toggle('active', a.dataset.view === (view === 'pf-run' ? 'pf-commands' : view)));
  if (view === 'live') showRun(param); else stopPolling();
  if (view === 'pf-run') showPfRun(param); else stopPfRun();
  if (view === 'export') showExport();
  if (view === 'pf-commands') showPfCommands();
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

const openRun = (id) => { location.hash = '#/pf-run/' + encodeURIComponent(id); };

initLiveRun();
initExport();
initNewRun({ onStarted: (id) => { location.hash = '#/live/' + encodeURIComponent(id); } });
initPfCommands({ onJob: openRun });
initPfRun();
initPfResults({
  onRerun: (values) => startJob('eval', values).then((job) => openRun(job.id))
    .catch((err) => alert('Could not start: ' + err.message)),
});
window.addEventListener('hashchange', route);
route();
checkEngines();
setInterval(checkEngines, 30000);
