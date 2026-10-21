// Tiny DOM helpers. Text is always set via textContent, never innerHTML.
export const $ = (id) => document.getElementById(id);

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key in node && typeof value !== 'string') node[key] = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

export function fillSelect(select, items, label, emptyText, value = (it) => it.id) {
  select.replaceChildren();
  if (!items.length) { select.add(new Option(emptyText, '')); return; }
  items.forEach((it) => select.add(new Option(label(it), value(it))));
}

export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : '–');

export function fmtDuration(startIso, endIso) {
  if (!startIso) return '–';
  const secs = Math.max(0, Math.round(((endIso ? new Date(endIso) : new Date()) - new Date(startIso)) / 1000));
  const m = Math.floor(secs / 60);
  return m ? m + 'm ' + (secs % 60) + 's' : secs + 's';
}

export const badge = (status, text) => el('span', { class: 'badge ' + status, text: text || status });
