import { initNewRun } from './new-run.js';
import { initLiveRun, showRun, stopPolling } from './live-run.js';
import { initExport, showExport } from './export.js';

const VIEWS = ['new', 'live', 'export'];

// Hash routes:  #/new   #/live   #/live/<runId>   #/export
function route() {
  const [, raw, id] = location.hash.split('/');
  const view = VIEWS.includes(raw) ? raw : 'new';
  VIEWS.forEach((v) => { document.getElementById('view-' + v).hidden = v !== view; });
  document.querySelectorAll('.nav-item').forEach((a) => a.classList.toggle('active', a.dataset.view === view));
  if (view === 'live') showRun(id ? decodeURIComponent(id) : null); else stopPolling();
  if (view === 'export') showExport();
}

initLiveRun();
initExport();
initNewRun({ onStarted: (id) => { location.hash = '#/live/' + encodeURIComponent(id); } });
window.addEventListener('hashchange', route);
route();
