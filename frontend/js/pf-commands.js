import { $, el } from './dom.js';
import { getCommands, listConfigs, listResults, startJob, getConfigText } from './promptfoo-api.js';

const state = { commands: [], configs: [], results: [], selected: 'eval', busy: false };

const current = () => state.commands.find((c) => c.id === state.selected);
const fieldId = (opt) => 'pfc-f-' + opt.name;

function readValue(opt) {
  const node = $(fieldId(opt));
  if (!node) return undefined;
  if (opt.kind === 'bool') return node.checked;
  if (opt.kind === 'multi') return [...node.selectedOptions].map((o) => o.value);
  if (opt.kind === 'int') return node.value === '' ? undefined : Number(node.value);
  return node.value.trim() || undefined;
}

function collect() {
  const cmd = current();
  const options = {};
  (cmd?.options || []).forEach((opt) => {
    const v = readValue(opt);
    if (v !== undefined && v !== false && !(Array.isArray(v) && !v.length)) options[opt.name] = v;
  });
  return options;
}

function preview() {
  const cmd = current();
  if (!cmd) return '';
  const values = collect();
  const parts = [cmd.cli];
  cmd.options.filter((o) => !o.flag && values[o.name] !== undefined).forEach((o) => parts.push(String(values[o.name])));
  cmd.options.filter((o) => o.flag && values[o.name] !== undefined).forEach((o) => {
    const v = values[o.name];
    parts.push(o.kind === 'bool' ? o.flag : o.flag + ' ' + JSON.stringify(Array.isArray(v) ? v.join(',') : v));
  });
  if (cmd.output) parts.push('--output <auto ' + cmd.output + '>');
  return parts.join(' ');
}

function issue() {
  const cmd = current();
  if (!cmd) return 'Promptfoo service is not reachable.';
  const values = collect();
  const missing = cmd.options.find((o) => o.required && values[o.name] === undefined);
  return missing ? missing.label + ' is required.' : '';
}

function update() {
  $('pfc-cli').textContent = preview();
  const msg = issue();
  $('pfc-issue').textContent = msg;
  $('pfc-run').disabled = !!msg || state.busy;
}

function optionList(items, label, value, allowEmpty, emptyText) {
  const opts = items.map((it) => new Option(label(it), value(it)));
  return allowEmpty ? [new Option(emptyText, ''), ...opts] : opts;
}

function field(opt) {
  const id = fieldId(opt);
  const common = { id, class: 'text-in', oninput: update, onchange: update };
  let input;
  if (opt.kind === 'bool') {
    return el('label', { class: 'note check pf-field' },
      el('input', { id, type: 'checkbox', checked: !!opt.default, onchange: update }), opt.label,
      opt.help ? el('span', { class: 'pf-help', text: ' — ' + opt.help }) : null);
  }
  if (opt.kind === 'config') {
    input = el('select', { ...common, class: 'drop' },
      optionList(state.configs, (c) => c.name + ' · ' + c.kind, (c) => c.name, !opt.required, '(none)'));
  } else if (opt.kind === 'result') {
    input = el('select', { ...common, class: 'drop' },
      optionList(state.results, (r) => r.name, (r) => r.name, !opt.required, '(none)'));
  } else if (opt.kind === 'choice') {
    input = el('select', { ...common, class: 'drop' },
      optionList(opt.choices.map((c) => ({ id: c })), (c) => c.id, (c) => c.id, !opt.required && !opt.default, '(default)'));
    if (opt.default) input.value = opt.default;
  } else if (opt.kind === 'multi') {
    input = el('select', { ...common, class: 'text-in pf-multi', multiple: true, size: 6 },
      opt.choices.map((c) => new Option(c, c)));
  } else if (opt.kind === 'int') {
    input = el('input', { ...common, type: 'number', min: String(opt.min), max: String(opt.max), placeholder: 'default' });
    if (opt.default !== null && opt.default !== undefined) input.value = String(opt.default);
  } else {
    input = el('input', { ...common, type: 'text', maxlength: '2000', placeholder: opt.kind === 'id' ? 'e.g. latest or eval-abc123' : '' });
  }
  const extra = opt.kind === 'config'
    ? el('button', { type: 'button', class: 'det-link', text: 'View', onclick: () => showConfig(input.value) })
    : null;
  return el('div', { class: 'pf-field' },
    el('label', { class: 'label', for: id, text: opt.label + (opt.required ? ' *' : '') + (opt.flag ? '  ' + opt.flag : '') }),
    extra ? el('div', { class: 'row-gap center' }, input, extra) : input,
    opt.kind === 'multi' ? el('p', { class: 'note', text: 'Ctrl/Cmd-click to pick several. Leave empty to use the config.' }) : null,
    opt.help ? el('p', { class: 'note', text: opt.help }) : null);
}

async function showConfig(name) {
  const box = $('pfc-config-view');
  if (!name) { box.hidden = true; return; }
  box.hidden = false;
  box.textContent = 'Loading ' + name + '…';
  try { box.textContent = await getConfigText(name); } catch (err) { box.textContent = err.message; }
}

function renderList() {
  const box = $('pfc-list');
  box.replaceChildren();
  const groups = new Map();
  state.commands.forEach((c) => { if (!groups.has(c.group)) groups.set(c.group, []); groups.get(c.group).push(c); });
  for (const [group, list] of groups) {
    box.append(el('div', { class: 'nav-sec', text: group }),
      list.map((c) => el('button', {
        type: 'button', class: 'pf-cmd' + (c.id === state.selected ? ' on' : ''),
        onclick: () => { state.selected = c.id; renderList(); renderForm(); },
      }, el('span', { class: 'strong', text: c.label }), el('span', { class: 'mono pf-id', text: c.cli }))));
  }
}

function renderForm() {
  const cmd = current();
  $('pfc-title').textContent = cmd ? cmd.label : 'No command';
  $('pfc-summary').textContent = cmd ? cmd.summary : '';
  $('pfc-config-view').hidden = true;
  $('pfc-fields').replaceChildren(...(cmd?.options || []).map(field));
  if (cmd && !cmd.options.length) $('pfc-fields').append(el('p', { class: 'note', text: 'No options.' }));
  $('pfc-msg').textContent = '';
  update();
}

export async function initPfCommands({ onJob }) {
  $('pfc-run').addEventListener('click', async () => {
    state.busy = true;
    update();
    try {
      const job = await startJob(state.selected, collect());
      onJob(job.id);
    } catch (err) {
      $('pfc-msg').textContent = 'Could not start: ' + err.message;
    } finally {
      state.busy = false;
      update();
    }
  });
}

export async function showPfCommands(commandId) {
  const [cmds, configs, results] = await Promise.allSettled([getCommands(), listConfigs(), listResults()]);
  state.commands = cmds.status === 'fulfilled' ? cmds.value.commands : [];
  state.configs = configs.status === 'fulfilled' ? configs.value : [];
  state.results = results.status === 'fulfilled' ? results.value : [];
  if (commandId && state.commands.some((c) => c.id === commandId)) state.selected = commandId;
  renderList();
  renderForm();
}

// Pre-fill and open a command, e.g. "re-run failures" from the results page.
export async function openPfCommand(commandId, values) {
  await showPfCommands(commandId);
  const cmd = current();
  Object.entries(values || {}).forEach(([name, value]) => {
    const opt = cmd?.options.find((o) => o.name === name);
    const node = opt && $(fieldId(opt));
    if (node) { if (opt.kind === 'bool') node.checked = !!value; else node.value = value; }
  });
  update();
}
