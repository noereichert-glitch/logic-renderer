// stemma renderer — Stemma Folder edition.
// The library IS the stemma folder: the UI mirrors its contents (aliases to
// sessions that never leave home, plus any real sessions dragged in via
// Finder). Adding — via the + button, a window drop, or the droplet — only
// plants an alias in the folder. NOTHING auto-renders: rendering starts only
// from the Render / Render All buttons, one at a time (Logic's limit).

const API = 'http://127.0.0.1:5123';
const STORAGE_OUTPUT_FOLDER = 'stemExport.outputFolder';
const SYNC_MS = 3000;          // folder mirror cadence
const STATS_EVERY = 10;        // full du/mtime refresh every Nth sync

const DAW_LABEL = { logicx: 'Logic Pro', als: 'Ableton Live' };

// ── State ────────────────────────────────────────────────────────────────────
let entries = [];        // mirror of the folder: {id, aliasPath, path, name, ext, missing}
let stats = {};          // original path -> {exists, mtimeMs, sizeBytes}
let meta = {};           // original path -> {date, folder, zipPath, stemCount}
let runtime = {};        // id -> {status: queued|rendering|done|failed, detail}
let queue = [];          // ids waiting to render
let activeId = null;     // id currently rendering
let dawFilter = 'all';
let stemmaFolder = null;
let outputFolder = localStorage.getItem(STORAGE_OUTPUT_FOLDER) || null;
let userPickedOutput = !!outputFolder;
let rowEls = new Map();  // id -> row element (for targeted status updates)
let syncTick = 0;

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

// ── Folders (rail footer) ────────────────────────────────────────────────────
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
    userPickedOutput = true;
    localStorage.setItem(STORAGE_OUTPUT_FOLDER, folder);
    refreshOutputFolderDisplay();
    renderList();
  }
});

$('btn-reveal-stemma').addEventListener('click', () =>
  stemmaFolder && window.electronAPI.openFolderInFinder(stemmaFolder));

$('btn-change-stemma').addEventListener('click', async () => {
  const folder = await window.electronAPI.chooseStemmaFolder();
  if (folder) syncFolder(true);
});

// ── Folder mirror ────────────────────────────────────────────────────────────
function extOf(p) { return p.toLowerCase().endsWith('.als') ? 'als' : 'logicx'; }

async function syncFolder(force) {
  const res = await window.electronAPI.scanStemma();
  stemmaFolder = res.folder;
  const el = $('stemma-folder-display');
  el.textContent = stemmaFolder;
  el.title = stemmaFolder;

  // Default output = Renders/ inside the stemma folder, until the user picks
  // their own (which persists and always wins).
  if (!userPickedOutput && outputFolder !== res.defaultOutput) {
    outputFolder = res.defaultOutput;
    refreshOutputFolderDisplay();
  }

  const prevPaths = entries.map(e => e.id).join('\n');
  entries = res.items.map(it => ({
    id: it.aliasPath,
    aliasPath: it.aliasPath,
    path: it.targetPath,
    name: it.name.replace(/\.(logicx|als)$/i, ''),
    ext: it.ext || extOf(it.name),
    missing: it.missing,
  }));
  const changed = entries.map(e => e.id).join('\n') !== prevPaths;

  if (changed || force || (syncTick % STATS_EVERY === 0)) {
    const targets = entries.filter(e => !e.missing).map(e => e.path);
    stats = targets.length ? await window.electronAPI.libraryStats(targets) : {};
  }
  syncTick += 1;
  if (changed || force) renderList();
}

// ── Adding sessions (all three roads end here — never renders anything) ──────
async function addOriginals(paths) {
  if (!paths || !paths.length) return;
  await window.electronAPI.addToStemma(paths);
  await syncFolder(true);
}

$('btn-add-projects').addEventListener('click', async () => {
  addOriginals(await window.electronAPI.addProjects());
});

// Drag-and-drop anywhere on the window: plant aliases for dropped sessions.
// Accept .logicx / .als and folder-style projects (dropped folders report an
// empty type). Anything else is ignored.
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => {
  e.preventDefault();
  const paths = Array.from(e.dataTransfer.files)
    .filter(f => f.name.endsWith('.logicx') || f.name.endsWith('.als') || f.type === '')
    .map(f => f.path)
    .filter(Boolean);
  addOriginals(paths);
});

async function removeEntry(id) {
  const entry = entries.find(e => e.id === id);
  if (!entry) return;
  if (activeId === id) return; // never yank a rendering session
  queue = queue.filter(q => q !== id);
  delete runtime[id];
  await window.electronAPI.removeFromStemma(entry.aliasPath);
  await syncFolder(true);
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

function statusCellHTML(entry) {
  const rt = runtime[entry.id];
  if (entry.missing) return '<div class="status st-warn"><span>Original not found</span></div>';
  if (rt) {
    if (rt.status === 'queued') return '<div class="status st-idle"><span>Queued</span></div>';
    if (rt.status === 'rendering')
      return `<div class="status st-sync"><span class="ring"></span><span>${esc(rt.detail || 'Rendering…')}</span></div>`;
    if (rt.status === 'failed')
      return `<div class="status st-err" title="${esc(rt.detail || '')}"><span>Failed — see Inbox</span></div>`;
    if (rt.status === 'done') {
      if (rt.warning)
        return `<div class="status st-warn" data-reveal="${esc(entry.id)}" title="${esc(rt.warning)}"><span>Done — with warnings</span></div>`;
      return `<div class="status st-done" data-reveal="${esc(entry.id)}">${CHECK_SVG}<span>Done — show .zip</span></div>`;
    }
  }
  if (entry.ext === 'als') return '<div class="status st-idle"><span>Renderer coming soon</span></div>';
  const lr = meta[entry.path];
  if (lr)
    return `<div class="status st-done" data-reveal="${esc(entry.id)}">${CHECK_SVG}<span>Rendered ${fmtDate(Date.parse(lr.date))}</span></div>`;
  return '<div class="status st-idle"><span>Ready</span></div>';
}

// Update ONE row's status cell in place — no full-list rebuild, no hover
// flicker. Falls back to a full renderList if the row isn't on screen.
function updateRowStatus(entry) {
  const row = rowEls.get(entry.id);
  if (!row) return;
  const tmp = document.createElement('div');
  tmp.innerHTML = statusCellHTML(entry);
  row.replaceChild(tmp.firstChild, row.children[3]);
}

function renderList() {
  const list = $('library-list');
  const visible = entries.filter(e => dawFilter === 'all' || e.ext === dawFilter);

  $('count-projects').textContent = entries.length;
  rowEls = new Map();

  if (!visible.length) {
    list.innerHTML = `<div class="empty-state">${entries.length
      ? 'No projects match this filter.'
      : 'The stemma folder is empty. Drag sessions onto this window (or the droplet),<br>or use “+ Add Projects” — originals never move; stemma keeps an alias.'}</div>`;
  } else {
    list.innerHTML = '';
    for (const entry of visible) {
      const st = stats[entry.path] || {};
      const rt = runtime[entry.id];
      const busy = rt && (rt.status === 'queued' || rt.status === 'rendering');
      const renderable = entry.ext === 'logicx' && !entry.missing && !busy && outputFolder;

      const row = document.createElement('div');
      row.className = 'row' + (entry.missing ? ' missing' : '');
      row.innerHTML = `
        <div class="name">
          <div class="badge ${entry.ext}">${entry.ext === 'als' ? 'A' : 'L'}</div>
          <div class="nm"><b>${esc(entry.name)}</b><span title="${esc(entry.path)}">${DAW_LABEL[entry.ext]} · ${esc(entry.path)}</span></div>
        </div>
        <div class="size">${fmtBytes(st.sizeBytes)}</div>
        <div class="mod">${fmtDate(st.mtimeMs)}</div>
        ${statusCellHTML(entry)}
        <div class="actions">
          ${busy
            ? `<button class="btn-render" data-cancel="${esc(entry.id)}"
                 title="${rt.status === 'queued' ? 'Remove from the render queue' : 'Stop this render — Logic quits cleanly, partial files are cleaned up'}">Cancel</button>`
            : `<button class="btn-render" data-render="${esc(entry.id)}" ${renderable ? '' : 'disabled'}
                 title="${outputFolder ? (entry.ext === 'als' ? 'Ableton renderer not connected yet' : 'Render stems') : 'Choose an output folder first'}">Render</button>`}
          <button class="btn-remove" data-remove="${esc(entry.id)}" title="Remove from stemma (alias goes to Trash; original untouched)">✕</button>
        </div>`;
      rowEls.set(entry.id, row);
      list.appendChild(row);
    }
  }

  list.querySelectorAll('[data-render]').forEach(b =>
    b.addEventListener('click', () => enqueue([b.dataset.render])));
  list.querySelectorAll('[data-cancel]').forEach(b =>
    b.addEventListener('click', () => cancelEntry(b.dataset.cancel)));
  list.querySelectorAll('[data-remove]').forEach(b =>
    b.addEventListener('click', () => removeEntry(b.dataset.remove)));
  list.querySelectorAll('[data-reveal]').forEach(el =>
    el.addEventListener('click', () => {
      const entry = entries.find(e => e.id === el.dataset.reveal);
      const lr = entry && meta[entry.path];
      if (lr && lr.zipPath) window.electronAPI.revealInFinder(lr.zipPath);
      else if (lr && lr.folder) window.electronAPI.openFolderInFinder(lr.folder);
    }));

  // Render All = every renderable row in the CURRENT filtered view.
  const candidates = visible.filter(e => {
    const rt = runtime[e.id];
    return e.ext === 'logicx' && !e.missing && !(rt && (rt.status === 'queued' || rt.status === 'rendering'));
  });
  const btnAll = $('btn-render-all');
  btnAll.disabled = !outputFolder || !candidates.length;
  btnAll.onclick = () => enqueue(candidates.map(e => e.id));

  const totalBytes = entries.reduce((a, e) => a + ((stats[e.path] || {}).sizeBytes || 0), 0);
  $('foot-summary').textContent =
    `${entries.length} project${entries.length !== 1 ? 's' : ''} · ${fmtBytes(totalBytes)}` +
    (queue.length ? ` · ${queue.length} queued` : '');
}

// Cancel: a QUEUED row is simply dequeued (nothing in flight); the ACTIVE row
// asks the backend for a cooperative abort — Logic quits cleanly, partial files
// are removed, and the row returns to Ready ('cancelled' outcome: no history
// entry, no inbox alarm). The rest of the queue continues.
const cancelPending = new Set(); // ids whose "Cancelling…" must not be clobbered

async function cancelEntry(id) {
  if (queue.includes(id)) {
    queue = queue.filter(q => q !== id);
    delete runtime[id];
    renderList();
    return;
  }
  if (id === activeId) {
    cancelPending.add(id);
    runtime[id] = { status: 'rendering', detail: 'Cancelling…' };
    const entry = entries.find(e => e.id === id);
    if (entry) updateRowStatus(entry);
    try {
      await fetch(`${API}/export/cancel`, { method: 'POST' });
    } catch (e) { /* backend unreachable — the poll loop will surface it */ }
  }
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
  const entry = entries.find(e => e.id === activeId);
  if (!entry) { activeId = null; return processQueue(); }

  runtime[activeId] = { status: 'rendering', detail: 'Launching Logic Pro…' };
  renderList();
  setFootProgress(entry.name, 'Launching Logic Pro…', 5);

  try {
    const res = await fetch(`${API}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // Render the ORIGINAL the alias points at — always the current session.
      body: JSON.stringify({ file_path: entry.path, output_folder: outputFolder }),
    });
    const startData = await res.json();
    if (!startData.started) throw new Error(startData.error || 'Could not start export');
    await pollUntilDone(entry);
  } catch (e) {
    runtime[activeId] = { status: 'failed', detail: e.message || 'Render failed' };
  }

  activeId = null;
  refreshCounts();
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
        // While a cancel is pending, keep showing "Cancelling…" — the backend's
        // status_title still reads "Pass 1/2 …" until the abort lands, which
        // made the label flash and revert (seen live 2026-09-10).
        const detail = cancelPending.has(entry.id)
          ? 'Cancelling…' : (data.status_title || 'Rendering…');
        runtime[entry.id] = { status: 'rendering', detail };
        updateRowStatus(entry);
        setFootProgress(entry.name, detail, data.progress || 0);
        return;
      }
      clearInterval(poller);
      cancelPending.delete(entry.id);
      if (data.status === 'cancelled') {
        // User cancel: row returns to Ready — no meta, no history, no alarm.
        delete runtime[entry.id];
        resolve();
        return;
      }
      if (data.error) {
        runtime[entry.id] = { status: 'failed', detail: data.error };
        resolve();
        return;
      }
      const sets = data.sets || {};
      const stemCount = Object.values(sets).reduce((a, f) => a + (f || []).length, 0);
      const warns = data.warnings || [];
      meta[entry.path] = {
        date: new Date().toISOString(),
        folder: data.project_folder || outputFolder,
        zipPath: data.zip_path || null,
        stemCount,
        warnings: warns,
      };
      runtime[entry.id] = warns.length
        ? { status: 'done', warning: warns[0].message }
        : { status: 'done' };
      await window.electronAPI.saveRenderMeta(meta);
      await window.electronAPI.saveHistory({
        project: entry.path.split('/').pop(),
        date: meta[entry.path].date,
        folder: meta[entry.path].folder,
        zip_path: meta[entry.path].zipPath,
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

// ── Backend health + live rail counts ────────────────────────────────────────
async function pollHealth() {
  const dot = $('health-dot'), label = $('health-label');
  try {
    const res = await fetch(`${API}/health`);
    if (res.ok) { dot.className = 'sync-dot ok'; label.textContent = 'Renderer ready'; }
    else throw new Error();
  } catch (e) {
    dot.className = 'sync-dot err'; label.textContent = 'Renderer offline';
  }
  refreshCounts();
}

async function refreshCounts() {
  const [h, m] = await Promise.all([
    window.electronAPI.getHistory(), window.electronAPI.getInbox(),
  ]);
  $('count-history').textContent = h.length;
  $('count-inbox').textContent = m.length;
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
    const isWarning = m.level === 'warning';
    const color = isWarning ? '#e8c07a' : '#e88a8a';
    const icon = isWarning
      ? `<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 3L2 17h16L10 3z" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/><path d="M10 8v4M10 15v.5" stroke="${color}" stroke-width="1.5" stroke-linecap="round"/></svg>`
      : `<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="8" stroke="${color}" stroke-width="1.5"/><path d="M7 7l6 6M13 7l-6 6" stroke="${color}" stroke-width="1.5" stroke-linecap="round"/></svg>`;
    const heading = isWarning
      ? `Completed with warnings — ${esc(m.project || 'project')}`
      : `Render failed — ${esc(m.project || 'project')}`;
    const item = document.createElement('div');
    item.className = 'history-item';
    item.innerHTML = `
      <div class="history-icon">${icon}</div>
      <div class="history-info">
        <div class="history-name">${heading}</div>
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
(async () => {
  meta = await window.electronAPI.getRenderMeta();
  await syncFolder(true);
})();
setInterval(syncFolder, SYNC_MS);
pollHealth();
setInterval(pollHealth, 5000);
