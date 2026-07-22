// stemma renderer — Project Library edition.
// The library is a persisted list of session paths (sessions never move).
// Render one row, or Render All — a serial queue feeds the one-at-a-time
// Logic export backend (POST /export + progress polling, unchanged).

const API = 'http://127.0.0.1:5123';
const STORAGE_OUTPUT_FOLDER = 'stemExport.outputFolder';

const DAW_LABEL = { logicx: 'Logic Pro', als: 'Ableton Live' };

// ── State ────────────────────────────────────────────────────────────────────
let library = [];        // [{id, path, name, ext, addedAt, lastRender}]
let stats = {};          // path -> {exists, mtimeMs, sizeBytes}
let runtime = {};        // id -> {status: queued|rendering|done|failed, detail, progress}
let queue = [];          // ids waiting to render
let activeId = null;     // id currently rendering
let dawFilter = 'all';
let outputFolder = localStorage.getItem(STORAGE_OUTPUT_FOLDER) || null;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ── Rail nav ─────────────────────────────────────────────────────────────────
document.querySelectorAll('.rail .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.rail .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const screen = tab.dataset.screen;
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    $(`screen-${screen}`).classList.add('active');
    if (screen === 'history') loadHistory();
    if (screen === 'inbox') loadInbox();
  });
});

// ── Output folder (remembered between runs) ──────────────────────────────────
function refreshOutputFolderDisplay() {
  const el = $('output-path-display');
  el.textContent = outputFolder || 'Not set';
  el.title = outputFolder || '';
  el.classList.toggle('empty', !outputFolder);
}

$('btn-pick-folder').addEventListener('click', async () => {
  const folder = await window.electronAPI.openFolder();
  if (folder) {
    outputFolder = folder;
    localStorage.setItem(STORAGE_OUTPUT_FOLDER, folder);
    refreshOutputFolderDisplay();
    renderList();
  }
});

// ── Library ──────────────────────────────────────────────────────────────────
function extOf(p) {
  if (p.endsWith('.als')) return 'als';
  // .logicx package, or a folder-style Logic project (no extension) — the
  // backend resolver turns either into the inner .logicx at render time.
  return 'logicx';
}

function nameOf(p) {
  const base = p.replace(/\/+$/, '').split('/').pop();
  return base.replace(/\.(logicx|als)$/i, '');
}

async function loadLibrary() {
  library = await window.electronAPI.getLibrary();
  await refreshStats();
  renderList();
}

async function refreshStats() {
  if (!library.length) { stats = {}; return; }
  stats = await window.electronAPI.libraryStats(library.map(e => e.path));
}

$('btn-add-projects').addEventListener('click', async () => {
  const paths = await window.electronAPI.addProjects();
  if (!paths.length) return;
  const known = new Set(library.map(e => e.path));
  for (const p of paths) {
    if (known.has(p)) continue;
    known.add(p);
    library.push({
      id: 'p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
      path: p,
      name: nameOf(p),
      ext: extOf(p),
      addedAt: new Date().toISOString(),
      lastRender: null,
    });
  }
  await window.electronAPI.saveLibrary(library);
  await refreshStats();
  renderList();
});

async function removeEntry(id) {
  const entry = library.find(e => e.id === id);
  if (!entry) return;
  // Never yank a session out from under the queue.
  if (activeId === id) return;
  queue = queue.filter(q => q !== id);
  library = library.filter(e => e.id !== id);
  delete runtime[id];
  await window.electronAPI.saveLibrary(library);
  renderList();
}

$('daw-filter').addEventListener('change', (e) => {
  dawFilter = e.target.value;
  renderList();
});

// ── Formatting helpers ───────────────────────────────────────────────────────
function fmtBytes(n) {
  if (n == null) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(1) + ' GB';
  if (n >= 1e6) return Math.round(n / 1e6) + ' MB';
  return Math.max(1, Math.round(n / 1e3)) + ' KB';
}

function fmtDate(ms) {
  if (!ms) return '—';
  const d = new Date(ms);
  const now = new Date();
  const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  const sameDay = (a, b) => a.toDateString() === b.toDateString();
  if (sameDay(d, now)) return `Today, ${time}`;
  const yest = new Date(now); yest.setDate(now.getDate() - 1);
  if (sameDay(d, yest)) return `Yesterday, ${time}`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ', ' + time;
}

// ── List rendering ───────────────────────────────────────────────────────────
const CHECK_SVG = '<svg class="check" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" stroke="#7fd4a8" stroke-width="1.4"/><path d="M5 8.2 7.2 10.4 11 6.4" stroke="#7fd4a8" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function statusCell(entry) {
  const rt = runtime[entry.id];
  const st = stats[entry.path] || {};
  if (st.exists === false) return '<div class="status st-warn"><span>File not found</span></div>';
  if (rt) {
    if (rt.status === 'queued') return '<div class="status st-idle"><span>Queued</span></div>';
    if (rt.status === 'rendering')
      return `<div class="status st-sync"><span class="ring"></span><span>${esc(rt.detail || 'Rendering…')}</span></div>`;
    if (rt.status === 'failed')
      return `<div class="status st-err" title="${esc(rt.detail || '')}"><span>Failed — see Inbox</span></div>`;
    if (rt.status === 'done')
      return `<div class="status st-done" data-reveal="${entry.id}">${CHECK_SVG}<span>Done — show .zip</span></div>`;
  }
  if (entry.ext === 'als') return '<div class="status st-idle"><span>Renderer coming soon</span></div>';
  if (entry.lastRender)
    return `<div class="status st-done" data-reveal="${entry.id}">${CHECK_SVG}<span>Rendered ${fmtDate(Date.parse(entry.lastRender.date))}</span></div>`;
  return '<div class="status st-idle"><span>Ready</span></div>';
}

function renderList() {
  const list = $('library-list');
  const visible = library.filter(e => dawFilter === 'all' || e.ext === dawFilter);

  $('count-projects').textContent = library.length;

  if (!visible.length) {
    list.innerHTML = `<div class="empty-state">${library.length
      ? 'No projects match this filter.'
      : 'Your library is empty. Add sessions with “+ Add Projects” —<br>they stay in place on disk; stemma only remembers where they live.'}</div>`;
  } else {
    list.innerHTML = '';
    for (const entry of visible) {
      const st = stats[entry.path] || {};
      const rt = runtime[entry.id];
      const missing = st.exists === false;
      const busy = rt && (rt.status === 'queued' || rt.status === 'rendering');
      const renderable = entry.ext === 'logicx' && !missing && !busy && outputFolder;

      const row = document.createElement('div');
      row.className = 'row' + (missing ? ' missing' : '');
      row.innerHTML = `
        <div class="name">
          <div class="badge ${entry.ext}">${entry.ext === 'als' ? 'A' : 'L'}</div>
          <div class="nm"><b>${esc(entry.name)}</b><span title="${esc(entry.path)}">${DAW_LABEL[entry.ext]} · ${esc(entry.path)}</span></div>
        </div>
        <div class="size">${fmtBytes(st.sizeBytes)}</div>
        <div class="mod">${fmtDate(st.mtimeMs)}</div>
        ${statusCell(entry)}
        <div class="actions">
          <button class="btn-render" data-render="${entry.id}" ${renderable ? '' : 'disabled'}
            title="${outputFolder ? (entry.ext === 'als' ? 'Ableton renderer not connected yet' : 'Render stems') : 'Choose an output folder first'}">Render</button>
          <button class="btn-remove" data-remove="${entry.id}" title="Remove from library">✕</button>
        </div>`;
      list.appendChild(row);
    }
  }

  // Delegated clicks (rebuilt rows each pass keep this simple).
  list.querySelectorAll('[data-render]').forEach(b =>
    b.addEventListener('click', () => enqueue([b.dataset.render])));
  list.querySelectorAll('[data-remove]').forEach(b =>
    b.addEventListener('click', () => removeEntry(b.dataset.remove)));
  list.querySelectorAll('[data-reveal]').forEach(el =>
    el.addEventListener('click', () => {
      const entry = library.find(e => e.id === el.dataset.reveal);
      const lr = entry && entry.lastRender;
      if (lr && lr.zipPath) window.electronAPI.revealInFinder(lr.zipPath);
      else if (lr && lr.folder) window.electronAPI.openFolderInFinder(lr.folder);
    }));

  // Render All: everything visible, renderable, not already queued.
  const candidates = visible.filter(e => {
    const st = stats[e.path] || {};
    const rt = runtime[e.id];
    return e.ext === 'logicx' && st.exists !== false && !(rt && (rt.status === 'queued' || rt.status === 'rendering'));
  });
  const btnAll = $('btn-render-all');
  btnAll.disabled = !outputFolder || !candidates.length;
  btnAll.onclick = () => enqueue(candidates.map(e => e.id));

  // Footstrip summary.
  const totalBytes = library.reduce((a, e) => a + ((stats[e.path] || {}).sizeBytes || 0), 0);
  $('foot-summary').textContent =
    `${library.length} project${library.length !== 1 ? 's' : ''} · ${fmtBytes(totalBytes)}` +
    (queue.length ? ` · ${queue.length} queued` : '');
}

// ── Render queue (strictly serial — Logic can only run one export) ───────────
function enqueue(ids) {
  for (const id of ids) {
    if (queue.includes(id) || id === activeId) continue;
    queue.push(id);
    runtime[id] = { status: 'queued' };
  }
  renderList();
  processQueue();
}

async function processQueue() {
  if (activeId || !queue.length) return;
  activeId = queue.shift();
  const entry = library.find(e => e.id === activeId);
  if (!entry) { activeId = null; return processQueue(); }

  runtime[activeId] = { status: 'rendering', detail: 'Launching Logic Pro…' };
  renderList();
  setFootProgress(entry.name, 'Launching Logic Pro…', 5);

  try {
    const res = await fetch(`${API}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: entry.path, output_folder: outputFolder }),
    });
    const startData = await res.json();
    if (!startData.started) throw new Error(startData.error || 'Could not start export');
    await pollUntilDone(entry);
  } catch (e) {
    runtime[activeId] = { status: 'failed', detail: e.message || 'Render failed' };
  }

  activeId = null;
  if (!queue.length) setFootProgress(null);
  renderList();
  processQueue();
}

function pollUntilDone(entry) {
  return new Promise((resolve) => {
    const poller = setInterval(async () => {
      let data;
      try {
        const res = await fetch(`${API}/export/progress`);
        data = await res.json();
      } catch (e) { return; } // backend busy — keep polling
      if (!data.done) {
        const detail = data.status_title || 'Rendering…';
        runtime[entry.id] = { status: 'rendering', detail };
        const stEl = document.querySelector(`[data-render="${entry.id}"]`);
        if (stEl) renderList(); // row exists → refresh its status text
        setFootProgress(entry.name, detail, data.progress || 0);
        return;
      }
      clearInterval(poller);
      if (data.error) {
        runtime[entry.id] = { status: 'failed', detail: data.error };
        resolve();
        return;
      }
      const sets = data.sets || {};
      const stemCount = Object.values(sets).reduce((a, f) => a + (f || []).length, 0);
      entry.lastRender = {
        date: new Date().toISOString(),
        folder: data.project_folder || outputFolder,
        zipPath: data.zip_path || null,
        stemCount,
      };
      runtime[entry.id] = { status: 'done' };
      await window.electronAPI.saveLibrary(library);
      await window.electronAPI.saveHistory({
        project: entry.path.split('/').pop(),
        date: entry.lastRender.date,
        folder: entry.lastRender.folder,
        zip_path: entry.lastRender.zipPath,
        set_counts: Object.fromEntries(Object.entries(sets).map(([k, f]) => [k, (f || []).length])),
      });
      resolve();
    }, 800);
  });
}

function setFootProgress(name, detail, pct) {
  const wrap = $('foot-progress');
  if (!name) { wrap.style.display = 'none'; return; }
  wrap.style.display = '';
  $('foot-progress-label').textContent = `${name} — ${detail}`;
  $('foot-progress-bar').style.width = (pct || 0) + '%';
}

// ── Backend health pill ──────────────────────────────────────────────────────
async function pollHealth() {
  const dot = $('health-dot'), label = $('health-label');
  try {
    const res = await fetch(`${API}/health`);
    if (res.ok) { dot.className = 'sync-dot ok'; label.textContent = 'Renderer ready'; return; }
    throw new Error();
  } catch (e) {
    dot.className = 'sync-dot err'; label.textContent = 'Renderer offline';
  }
}

// ── History ──────────────────────────────────────────────────────────────────
async function loadHistory() {
  const history = await window.electronAPI.getHistory();
  $('count-history').textContent = history.length;
  const list = $('history-list');

  if (!history.length) {
    list.innerHTML = '<div class="empty-state">No renders yet.</div>';
    return;
  }

  list.innerHTML = '';
  history.forEach(h => {
    const date = new Date(h.date).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit'
    });
    const counts = h.set_counts || {};
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const stemSummary = total > 0 ? `${total} stems` : '';

    const item = document.createElement('div');
    item.className = 'history-item';
    item.style.cursor = 'pointer';
    item.innerHTML = `
      <div class="history-icon">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M4 2h8l4 4v12H4V2z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 2v4h4" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
      </div>
      <div class="history-info">
        <div class="history-name">${esc(h.project)}</div>
        <div class="history-meta">${date}${stemSummary ? ' · ' + stemSummary : ''} · ${esc(h.folder || '')}</div>
      </div>
      <div class="history-arrow">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M5 3l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </div>`;
    item.addEventListener('click', () => {
      if (h.zip_path) window.electronAPI.revealInFinder(h.zip_path);
      else if (h.folder) window.electronAPI.openFolderInFinder(h.folder);
    });
    list.appendChild(item);
  });
}

$('btn-clear-history').addEventListener('click', async () => {
  await window.electronAPI.clearHistory();
  loadHistory();
});

// ── Inbox (critically-failed renders) ────────────────────────────────────────
async function loadInbox() {
  const messages = await window.electronAPI.getInbox();
  $('count-inbox').textContent = messages.length;
  const list = $('inbox-list');

  if (!messages.length) {
    list.innerHTML = '<div class="empty-state">No messages. Failed renders will appear here.</div>';
    return;
  }

  list.innerHTML = '';
  messages.forEach(m => {
    const date = new Date(m.date).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit'
    });
    const item = document.createElement('div');
    item.className = 'history-item';
    item.innerHTML = `
      <div class="history-icon">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 2L1 17h18L10 2z" stroke="#e88a8a" stroke-width="1.5" stroke-linejoin="round"/><path d="M10 8v4M10 14v.5" stroke="#e88a8a" stroke-width="1.5" stroke-linecap="round"/></svg>
      </div>
      <div class="history-info">
        <div class="history-name">Render failed — ${esc(m.project || 'project')}</div>
        <div class="history-meta">${esc(m.reason || '')}</div>
        <div class="history-meta">${date}</div>
      </div>`;
    list.appendChild(item);
  });
}

$('btn-clear-inbox').addEventListener('click', async () => {
  await window.electronAPI.clearInbox();
  loadInbox();
});

// ── Init ─────────────────────────────────────────────────────────────────────
refreshOutputFolderDisplay();
loadLibrary();
pollHealth();
setInterval(pollHealth, 5000);
// Rail counts on startup (screens lazy-load their lists on first visit).
window.electronAPI.getHistory().then(h => { $('count-history').textContent = h.length; });
window.electronAPI.getInbox().then(m => { $('count-inbox').textContent = m.length; });
