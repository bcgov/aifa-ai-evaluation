// Policy Mapping: plain-JS port of the pack's PolicyMappingPage. The rulebook: what we test, what passing
// looks like, the harm, what it's evidence for (EU AI Act, NIST, OWASP) and the fix required at each risk tier.
// Results live on Findings. Data: GET /api/policy (catalog.yaml, crosswalk.yaml, tiers.yaml).
import { el } from './dom.js';
import { getPolicy } from './api.js';

const TIER_STYLE = {
  low: { ink: '#187a5d', bg: '#e9f4ef', border: '#c9e4d7' },
  medium: { ink: '#8a5f00', bg: '#fbf3dd', border: '#ecd9a6' },
  high: { ink: '#b23c22', bg: '#fbe9e3', border: '#eccbc1' },
};
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const S = { policy: null, principle: 'T', tier: 'medium', view: 'principle', error: '' };
const root = () => document.getElementById('policy-root');

export async function showPolicy() {
  if (!S.policy) {
    render();
    try { S.policy = await getPolicy(); } catch (e) { S.error = e.message; }
  }
  render();
}

function render() {
  const host = root();
  if (!host) return;
  if (S.error) { host.replaceChildren(el('p', { class: 'error', text: `Couldn't load the policy: ${S.error}` })); return; }
  const p = S.policy;
  if (!p) { host.replaceChildren(el('p', { class: 'mute', text: 'Loading…' })); return; }
  const fmById = Object.fromEntries(p.catalog.failure_modes.map((f) => [f.id, f]));
  const prByCode = Object.fromEntries(p.catalog.principles.map((x) => [x.code, x]));
  const seg = (key, label) => el('button', { class: S.view === key ? 'on' : '', text: label, onclick: () => { S.view = key; render(); } });

  const header = el('header', { class: 'page-head' },
    el('div', {}, el('h1', { text: 'Policy Mapping' }),
      el('p', { class: 'mute', text: `Pick a BC principle, then the system's risk tier. Results live on Findings. Rulebook ${p.versions?.catalog || ''}.` })),
    el('div', { class: 'row' },
      el('div', { class: 'seg', role: 'tablist' }, seg('principle', 'By principle'), seg('crosswalk', 'Framework crosswalk')),
      el('a', { class: 'btn', href: 'test-plan-by-principle.pdf', download: 'test-plan-by-principle.pdf', text: 'Export test plan PDF' })));

  const body = S.view === 'crosswalk' ? crosswalk(p, fmById, prByCode) : byPrinciple(p, prByCode[S.principle]);
  host.replaceChildren(el('div', { class: 'rt' }, header, ...body));
}

function byPrinciple(p, pr) {
  const fms = p.catalog.failure_modes.filter((f) => f.principle === S.principle);
  return [
    el('div', { class: 'principles' }, ...p.catalog.principles.map((x, i) => {
      const on = x.code === S.principle;
      const n = p.catalog.failure_modes.filter((f) => f.principle === x.code).length;
      return el('button', { class: 'principle', 'aria-pressed': String(on), style: `background:${on ? x.tint : '#fff'};border-color:${on ? x.color : 'var(--rt-line)'}`,
        onclick: () => { S.principle = x.code; render(); } },
      el('span', { class: 'pnum', style: `color:${x.color}`, text: String(i + 1) }), el('strong', { text: x.name }),
      el('span', { class: 'small mute', text: `${n} failure modes · ${x.hand_checks.length} checks` }));
    })),
    el('div', { class: 'tiers' }, ...p.tiers.tiers.map((t) => {
      const s = TIER_STYLE[t.key];
      const on = t.key === S.tier;
      return el('button', { class: 'tier', 'aria-pressed': String(on), style: `background:${s.bg};border:${on ? `2px solid ${s.ink}` : `1px solid ${s.border}`}`,
        onclick: () => { S.tier = t.key; render(); } },
      el('strong', { style: `color:${s.ink}`, text: t.name }), el('span', { class: 'small', text: t.when }),
      el('span', { class: 'small', style: `color:${s.ink}`, text: `Release blocked by any open ${t.blocks_on.map(cap).join(' or ')}` }));
    })),
    el('p', { class: 'asks', style: `border-color:${pr.color}` }, el('strong', { text: 'What BC asks: ' }), pr.asks),
    ...fms.map((f) => fmCard(f, pr)),
    el('section', { class: 'card' }, el('h3', { text: 'Checked by hand' }),
      el('ul', {}, ...pr.hand_checks.map((c) => el('li', {}, `${c.check} `, el('span', { class: 'tag', text: c.ref }))))),
  ];
}

function fmCard(f, pr) {
  const s = TIER_STYLE[S.tier];
  const ev = f.evidence || {};
  const tags = [
    ...(ev.eu_ai_act || []).map((x) => `EU ${x}`),
    ...(ev.nist || []).map((x) => `NIST ${x}`),
    ...((ev.owasp || []).length ? ev.owasp.map((x) => `OWASP ${x}`) : ['Not in OWASP']),
  ];
  const row = (dt, dd) => [el('dt', { text: dt }), el('dd', {}, ...[].concat(dd))];
  return el('section', { class: 'card fm' },
    el('div', { class: 'fm-head' }, el('span', { class: 'id', style: `background:${pr.tint};color:${pr.color}`, text: f.id }),
      el('strong', { text: f.alias }), el('span', { class: 'mute', text: f.name })),
    el('dl', { class: 'fm-grid' },
      ...row('Passes when', f.passes_when),
      ...row('Harm', `${f.harm?.aiaaic || ''}. ${f.harm?.plain || ''}`),
      ...row('Evidence for', tags.map((t) => el('span', { class: 'tag', text: t }))),
      ...row('Techniques', `${(f.techniques || []).join(', ')}${(f.converters || []).length ? ` + ${f.converters.join(', ')}` : ''}`),
      ...row('Catalogue attacks', String(f.catalogue_attacks ?? '')),
      ...row('Graded by', f.graded_by || '')),
    el('details', {}, el('summary', { text: 'Severity ladder' }),
      el('ul', { class: 'ladder' }, ...['pass', 'low', 'medium', 'high'].map((k) =>
        el('li', {}, el('span', { class: `sev ${cap(k)}`, text: cap(k) }), ` ${f.severity_ladder[k]}`)))),
    el('div', { class: 'mit', style: `background:${s.bg};border-color:${s.border}` },
      el('span', { class: 'small', style: `color:${s.ink};font-weight:700`, text: `${S.tier.toUpperCase()} RISK · REQUIRED FIX` }),
      el('p', { text: f.mitigation[S.tier] })));
}

function crosswalk(p, fmById, prByCode) {
  const sections = [p.crosswalk.owasp, p.crosswalk.eu_ai_act, p.crosswalk.nist];
  return [
    el('p', { class: 'mute', text: p.crosswalk.rule || 'A mapping is evidence toward a clause, never a compliance claim.' }),
    ...sections.map((s) => el('section', { class: 'card' }, el('h3', { text: s.title }), el('p', { class: 'small mute', text: s.note || '' }),
      el('table', { class: 'cross' }, el('tbody', {}, ...s.items.map((it) => el('tr', {},
        el('td', { class: 'nowrap' }, el('strong', { text: it.code })),
        el('td', { text: it.name }),
        el('td', {}, ...it.failure_modes.map((id) => {
          const fm = fmById[id];
          const pr = fm ? prByCode[fm.principle] : null;
          return el('span', { class: 'chip', style: pr ? `background:${pr.tint};color:${pr.color}` : '', text: `${id} ${fm ? fm.alias : '(unknown)'}` });
        }), it.note ? el('span', { class: 'small mute', text: ` ${it.note}` }) : null))))))),
  ];
}
