// stemma renderer — Stemma Folder edition.
// The library IS the stemma folder: the UI mirrors its contents (aliases to
// sessions that never leave home, plus any real sessions dragged in via
// Finder). Adding — via the + button, a window drop, or the droplet — only
// plants an alias in the folder. NOTHING auto-renders: rendering starts only
// from the Render / Render All buttons, one at a time (Logic's limit).

// One backend per DAW, each its own process on its own port (spawned by main.js).
// The export / progress / cancel / health JSON shapes are twins, so the render
// flow below is DAW-agnostic — only the base URL changes per row. A DAW with no
// entry here is listed but not renderable ("Renderer coming soon").
const BACKENDS = { logicx: 'http://127.0.0.1:5123', als: 'http://127.0.0.1:5124' };
const apiFor = (ext) => BACKENDS[ext];
const hasRenderer = (entry) => !!BACKENDS[entry.ext];
// Live health per backend (filled by pollHealth): a row is only renderable
// while its backend answers. The frozen backends of a packaged build take a
// few seconds to come up, and a Render pressed before that failed with a bare
// "Failed to fetch" (owner, 2026-09-17).
const backendUp = {};
const rendererReady = (entry) => hasRenderer(entry) && backendUp[entry.ext] === true;
// Both backends expose /export/cancel (Ableton since 2026-09-16).
const CANCELLABLE = { logicx: true, als: true };
const STORAGE_OUTPUT_FOLDER = 'stemExport.outputFolder';
const SYNC_MS = 3000;          // folder mirror cadence
const STATS_EVERY = 10;        // full du/mtime refresh every Nth sync

const DAW_LABEL = { logicx: 'Logic Pro', als: 'Ableton Live', flp: 'FL Studio' };

// ── State ────────────────────────────────────────────────────────────────────
let entries = [];        // mirror of the folder: {id, aliasPath, path, name, ext, missing}
let stats = {};          // original path -> {exists, mtimeMs, sizeBytes}
let meta = {};           // original path -> {date, folder, zipPath, stemCount}
let runtime = {};        // id -> {status: queued|rendering|done|failed|blocked, detail}  (blocked = macOS grant missing)
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
function extOf(p) {
  const l = p.toLowerCase();
  return l.endsWith('.als') ? 'als' : l.endsWith('.flp') ? 'flp' : 'logicx';
}

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
    .filter(f => /\.(logicx|als|flp)$/i.test(f.name) || f.type === '')
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
// DAW badges (owner picks 2026-09-14): original stemma glyphs, one line weight
// on the lavender tile — Logic = outline platter (disc, grooves, spindle);
// Live = the word itself (Live 12's icon IS just the word), Inter bold;
// FL = the mango as flat border-less shapes (body traced from the real icon,
// crown + stem on its coordinates), two lavender tones set in styles.css.
// No image assets, recolours with the theme. Unknown types fall back to a letter.
const PLATTER_SVG = '<svg viewBox="0 0 42 42" fill="none" aria-label="Logic Pro"><circle cx="21" cy="21" r="14" stroke="currentColor" stroke-width="1.6"/><circle cx="21" cy="21" r="10" stroke="currentColor" stroke-width="1" opacity=".55"/><circle cx="21" cy="21" r="6" stroke="currentColor" stroke-width="1" opacity=".55"/><circle cx="21" cy="21" r="1.7" fill="currentColor"/></svg>';
const MANGO_SVG = '<svg viewBox="0 0 42 42" fill="none" aria-label="FL Studio">'
  + '<path class="fruit" d="M15.4 36.9C13.2 36.2 11.9 33.8 11.2 30.0C10.7 25.7 11.1 21.4 11.9 18.2C12.7 15.5 15.1 14.0 18.3 13.6C22.6 13.3 26.9 15.0 27.9 19.3C28.4 23.6 25.9 27.9 22.9 31.4C20.8 33.9 17.8 37.0 15.4 36.9Z"/>'
  + '<path class="crown" d="M11.5 14.0C12.1 9.9 17.1 8.0 20.9 11.3C20.4 14.0 16.2 15.8 11.5 14.0Z"/>'
  + '<path class="crown" d="M24.7 12.6C27.6 11.3 31.1 14.0 31.1 21.0C28.3 19.9 25.9 17.4 24.7 12.6Z"/>'
  + '<path class="crown" d="M22.9 11.5C20.5 11.0 17.9 12.2 17.9 15.2C17.9 18.5 19.8 20.4 21.5 20.8C23.3 20.2 25.9 17.7 25.8 14.3C25.7 12.6 24.4 11.4 22.9 11.5Z"/>'
  + '<path class="stem" d="M23.0 11.4C23.5 9.1 25.3 6.8 28.0 5.5" stroke-width="1.7" stroke-linecap="round"/></svg>';
function shorten(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

function badgeGlyph(ext) {
  if (ext === 'logicx') return PLATTER_SVG;
  if (ext === 'als') return '<span class="wm" aria-label="Ableton Live">Live</span>';
  if (ext === 'flp') return MANGO_SVG;
  return esc((ext || '?')[0].toUpperCase());
}

const CHECK_SVG = '<svg class="check" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.4"/><path d="M5 8.2 7.2 10.4 11 6.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function statusCellHTML(entry) {
  const rt = runtime[entry.id];
  if (entry.missing) return '<div class="status st-warn"><span>Original not found</span></div>';
  if (rt) {
    if (rt.status === 'queued') return '<div class="status st-idle"><span>Queued</span></div>';
    if (rt.status === 'rendering') {
      // Live warnings get the same clickable mark as a finished row (hover
      // card, click to pin the cascade) so they can be read mid-render —
      // while cancelling is still cheap (owner request 2026-09-16).
      const lw = rt.liveWarnings || [];
      return `<div class="status st-sync"><span class="ring"></span><span>${esc(rt.detail || 'Rendering…')}</span>${warnMark(entry.id, lw)}</div>`;
    }
    if (rt.status === 'blocked')
      // A missing macOS grant is a to-do, not a failed render: amber, and the
      // fix itself travels like any warning — the same ⚠ mark (hover card,
      // click to cascade the full sentence under the row), since the column is
      // too narrow to show it inline (owner request 2026-09-19).
      return `<div class="status st-warn"><span>Permission needed</span>${warnMark(entry.id, rt.warnings)}</div>`;
    if (rt.status === 'failed')
      // The reason travels like a warning — red mark, hover card, click to
      // cascade the full text under the row — because the column can never
      // show a whole error inline (owner request 2026-09-19). The Inbox has
      // the same entry when the backend emitted a failure marker.
      return `<div class="status st-err"><span>Failed</span>${warnMark(entry.id, rt.warnings, 'err')}</div>`;
    if (rt.status === 'done')
      // Success looks like success (owner call 2026-09-14): green as always,
      // with an amber ⚠ mark beside it when there were warnings.
      return `<div class="status st-done" data-reveal="${esc(entry.id)}">${CHECK_SVG}<span>Done — show .zip</span>${warnMark(entry.id, rt.warnings)}</div>`;
  }
  if (!hasRenderer(entry)) return '<div class="status st-idle"><span>Renderer coming soon</span></div>';
  const lr = meta[entry.path];
  if (lr)
    return `<div class="status st-done" data-reveal="${esc(entry.id)}">${CHECK_SVG}<span>Rendered ${fmtDate(Date.parse(lr.date))}</span>${warnMark(entry.id, lr.warnings)}</div>`;
  return '<div class="status st-idle"><span>Ready</span></div>';
}

// The finished row's warning list, if any — appended as a full-width child
// of the row (grid-column 1/-1) so it drops in under all the columns.
function rowWarnings(entry) {
  const rt = runtime[entry.id];
  const list = (rt && (rt.status === 'done' || rt.status === 'blocked' || rt.status === 'failed')) ? rt.warnings
             : (rt && rt.status === 'rendering') ? rt.liveWarnings
             : (!rt && meta[entry.path]) ? meta[entry.path].warnings : null;
  return warnReveal(entry.id, list);
}

// ── Warnings on a finished row (owner design 2026-09-14) ─────────────────────
// At rest: green status + one amber mark with a hover card. Click the mark and
// the full list cascades in under the row — label column, hanging indent,
// affected names brightened — pinned until clicked again. Open state survives
// list rebuilds via openWarnings.
const openWarnings = new Set();

const WARN_LABEL = [
  [/^solo/, 'Solo'], [/^muted/, 'Muted'], [/^completeness/, 'Empty'],
  [/^silence/, 'Silent'], [/^pass_symmetry/, 'Mismatch'], [/^raw_guard/, 'Identical'],
  [/^zip/, 'Zip'], [/^cleanup/, 'Cleanup'], [/^missing_media/, 'Missing media'], [/^empty/, 'Empty'],
  [/^permissions/, 'Permission'], [/^failed/, 'Failed'],
];
function warnLabel(stage) {
  const hit = WARN_LABEL.find(([re]) => re.test(stage || ''));
  return hit ? hit[1] : 'Note';
}

// Escape the message, then brighten each affected name (longest first so a
// name that contains another isn't split in two).
function emphasize(message, names) {
  let html = esc(message || '');
  for (const n of [...(names || [])].sort((a, b) => b.length - a.length)) {
    const e = esc(n);
    if (e) html = html.split(e).join(`<b>${e}</b>`);
  }
  return html;
}

// A failed row carries its reason as a one-item list so the mark / cascade
// machinery below can show it in full (stage 'failed' -> red, label 'Failed').
function failedState(detail) {
  const message = detail || 'The render could not be completed — see Inbox.';
  return { status: 'failed', detail: message,
           warnings: [{ stage: 'failed', message, names: [] }] };
}

function warnMark(id, warnings, tone) {
  const list = warnings || [];
  if (!list.length) return '';
  const open = openWarnings.has(id);
  const items = list.map(w => `<li>${emphasize(w.message, w.names)}</li>`).join('');
  const noun = tone === 'err' ? 'reason' : 'warning';
  return `<span class="mark-wrap"><button class="mark${tone === 'err' ? ' err' : ''}" aria-expanded="${open}" data-warn-toggle="${esc(id)}" aria-label="${list.length} ${noun}s">⚠<span class="chev">▾</span></button>
    <div class="pop"><h4>${list.length} ${noun}${list.length !== 1 ? 's' : ''} · click to pin</h4><ul>${items}</ul></div></span>`;
}

function warnReveal(id, warnings) {
  const list = warnings || [];
  if (!list.length) return '';
  const open = openWarnings.has(id);
  const items = list.map(w =>
    `<div class="item${/^failed/.test(w.stage || '') ? ' err' : ''}${/^permissions/.test(w.stage || '') ? ' perm' : ''}"><span class="m">⚠</span><span class="k">${esc(warnLabel(w.stage))}</span><span>${emphasize(w.message, w.names)}</span></div>`).join('');
  return `<div class="reveal" data-open="${open}" data-warn-region="${esc(id)}"><div><div class="inner">${items}</div></div></div>`;
}

// Update ONE row's status cell in place — no full-list rebuild, no hover
// flicker. Falls back to a full renderList if the row isn't on screen.
function updateRowStatus(entry) {
  const row = rowEls.get(entry.id);
  if (!row) return;
  const tmp = document.createElement('div');
  tmp.innerHTML = statusCellHTML(entry);
  row.replaceChild(tmp.firstChild, row.children[3]);
  // Keep the warning cascade in step with the live warnings: rebuild it only
  // when its content changed, so a pinned-open cascade doesn't flicker on
  // every poll.
  const old = row.querySelector('[data-warn-region]');
  const html = rowWarnings(entry);
  const oldHtml = old ? old.outerHTML : '';
  const probe = document.createElement('div'); probe.innerHTML = html;
  const fresh = probe.firstChild;
  const freshHtml = fresh ? fresh.outerHTML : '';
  if (freshHtml === oldHtml) return;
  if (old && fresh) row.replaceChild(fresh, old);
  else if (old) old.remove();
  else if (fresh) row.appendChild(fresh);
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
      const renderable = rendererReady(entry) && !entry.missing && !busy && outputFolder;
      const cancellable = busy && (rt.status === 'queued' || CANCELLABLE[entry.ext]);

      const row = document.createElement('div');
      row.className = 'row' + (entry.missing ? ' missing' : '');
      row.innerHTML = `
        <div class="name">
          <div class="badge ${entry.ext}">${badgeGlyph(entry.ext)}</div>
          <div class="nm"><b>${esc(entry.name)}</b><span title="${esc(entry.path)}">${DAW_LABEL[entry.ext]} · ${esc(entry.path)}</span></div>
        </div>
        <div class="size">${fmtBytes(st.sizeBytes)}</div>
        <div class="mod">${fmtDate(st.mtimeMs)}</div>
        ${statusCellHTML(entry)}
        <div class="actions">
          ${busy
            ? `<button class="btn-render" data-cancel="${esc(entry.id)}" ${cancellable ? '' : 'disabled'}
                 title="${rt.status === 'queued' ? 'Remove from the render queue'
                        : cancellable ? `Stop this render — ${DAW_LABEL[entry.ext]} quits cleanly, partial files are cleaned up`
                        : `Cancelling an active ${DAW_LABEL[entry.ext]} render isn't supported yet — it will run to the end`}">Cancel</button>`
            : `<button class="btn-render" data-render="${esc(entry.id)}" ${renderable ? '' : 'disabled'}
                 title="${outputFolder
                   ? (rendererReady(entry) ? 'Render stems'
                      : hasRenderer(entry) ? `${DAW_LABEL[entry.ext]} renderer is starting — one moment`
                      : `${DAW_LABEL[entry.ext] || 'This'} renderer not connected yet`)
                   : 'Choose an output folder first'}">Render</button>`}
          <button class="btn-remove" data-remove="${esc(entry.id)}" title="Remove from stemma (alias goes to Trash; original untouched)">✕</button>
        </div>
        ${rowWarnings(entry)}`;
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
  // (warning-mark clicks are delegated on the list — see initWarnToggle — so
  // a mark rebuilt by updateRowStatus mid-render keeps working)
  list.querySelectorAll('[data-reveal]').forEach(el =>
    el.addEventListener('click', (e) => {
      // The ⚠ mark sits inside this cell; its click is the warning toggle
      // only (owner, 2026-09-20). The list-level stopPropagation in
      // initWarnToggle runs AFTER this element-level listener, so it
      // cannot prevent the reveal — ignore the mark here instead.
      if (e.target.closest('.mark-wrap')) return;
      const entry = entries.find(e => e.id === el.dataset.reveal);
      const lr = entry && meta[entry.path];
      if (lr && lr.zipPath) window.electronAPI.revealInFinder(lr.zipPath);
      else if (lr && lr.folder) window.electronAPI.openFolderInFinder(lr.folder);
    }));

  // Render All = every renderable row in the CURRENT filtered view.
  const candidates = visible.filter(e => {
    const rt = runtime[e.id];
    return rendererReady(e) && !e.missing && !(rt && (rt.status === 'queued' || rt.status === 'rendering'));
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
    if (!entry || !CANCELLABLE[entry.ext]) { cancelPending.delete(id); return; }
    updateRowStatus(entry);
    try {
      await fetch(`${apiFor(entry.ext)}/export/cancel`, { method: 'POST' });
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

  const launching = `Launching ${DAW_LABEL[entry.ext]}…`;
  runtime[activeId] = { status: 'rendering', detail: launching };
  renderList();
  setFootProgress(entry.name, launching, 5);

  try {
    const res = await fetch(`${apiFor(entry.ext)}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // Render the ORIGINAL the alias points at — always the current session.
      body: JSON.stringify({ file_path: entry.path, output_folder: outputFolder }),
    });
    const startData = await res.json();
    if (!startData.started) throw new Error(startData.error || 'Could not start export');
    await pollUntilDone(entry);
  } catch (e) {
    const msg = /failed to fetch|networkerror|load failed/i.test(e.message || '')
      ? `${DAW_LABEL[entry.ext]} renderer did not answer — it may still be starting, or it stopped. Try again in a moment.`
      : (e.message || 'Render failed');
    runtime[activeId] = failedState(msg);
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
        const res = await fetch(`${apiFor(entry.ext)}/export/progress`);
        data = await res.json();
      } catch (e) { return; } // backend busy — keep polling
      if (!data.done) {
        // While a cancel is pending, keep showing "Cancelling…" — the backend's
        // status_title still reads "Pass 1/2 …" until the abort lands, which
        // made the label flash and revert (seen live 2026-09-10).
        const detail = cancelPending.has(entry.id)
          ? 'Cancelling…' : (data.status_title || 'Rendering…');
        // Live warnings (surfaced as discovered, e.g. silent stems after Pass 1)
        // ride along so the row can flag them WHILE cancelling is still cheap.
        runtime[entry.id] = { status: 'rendering', detail,
                              liveWarnings: data.warnings || [] };
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
        runtime[entry.id] = data.reason_code === 'permissions'
          ? { status: 'blocked', detail: data.reason || data.error,
              // 'names' are brightened in the cascade and the hover card; the
              // relaunch step is the part people skip (owner, 2026-09-20).
              warnings: [{ stage: 'permissions', message: data.reason || data.error,
                           names: ['then relaunch stemma'] }] }
          : failedState(data.error);
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
      runtime[entry.id] = { status: 'done', warnings: warns };
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
// Start-up grace: a backend that has not answered YET is "initiating", not
// "offline" — the two Python servers take a few seconds to bind their ports
// after the window opens (owner request 2026-09-16). "Offline" means it never
// came up within the grace window, or it was up and went away.
const HEALTH_GRACE_MS = 30000;
const healthStarted = Date.now();
const healthSeenUp = new Set();   // exts that have answered /health at least once

async function pollHealth() {
  const dot = $('health-dot'), label = $('health-label');
  // One /health per backend; name the one that is down rather than hiding it
  // behind a single green dot.
  const results = await Promise.all(Object.entries(BACKENDS).map(async ([ext, base]) => {
    try { const res = await fetch(`${base}/health`); return [ext, res.ok]; }
    catch (e) { return [ext, false]; }
  }));
  let changed = false;
  results.forEach(([ext, ok]) => {
    if (ok) healthSeenUp.add(ext);
    if (backendUp[ext] !== ok) { backendUp[ext] = ok; changed = true; }
  });
  if (changed) renderList();   // Render buttons follow the backends' health
  const inGrace = Date.now() - healthStarted < HEALTH_GRACE_MS;
  const down = results.filter(([, ok]) => !ok).map(([ext]) => ext);
  // Still starting: never answered yet, and the grace window is open.
  const initiating = down.filter(ext => inGrace && !healthSeenUp.has(ext));
  const offline = down.filter(ext => !initiating.includes(ext)).map(ext => DAW_LABEL[ext]);

  if (!down.length) { dot.className = 'sync-dot ok'; label.textContent = 'Renderers ready'; }
  else if (offline.length === results.length) { dot.className = 'sync-dot err'; label.textContent = 'Renderers offline'; }
  else if (offline.length) { dot.className = 'sync-dot err'; label.textContent = `${offline.join(' + ')} renderer offline`; }
  else if (initiating.length === results.length) { dot.className = 'sync-dot'; label.textContent = 'Renderers initiating…'; }
  else { dot.className = 'sync-dot'; label.textContent = `${initiating.map(e => DAW_LABEL[e]).join(' + ')} renderer initiating…`; }
  refreshCounts();
  return !down.length;
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
    const color = isWarning ? '#a8791a' : '#c5473f';
    const icon = isWarning
      ? `<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 3L2 17h16L10 3z" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/><path d="M10 8v4M10 15v.5" stroke="${color}" stroke-width="1.5" stroke-linecap="round"/></svg>`
      : `<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="8" stroke="${color}" stroke-width="1.5"/><path d="M7 7l6 6M13 7l-6 6" stroke="${color}" stroke-width="1.5" stroke-linecap="round"/></svg>`;
    const heading = m.kind === 'permissions'
      ? `Permission needed — ${esc(m.project || 'project')}`
      : isWarning
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
// Warning mark: one delegated listener on the list. The status cell (and its
// mark) is rebuilt on every poll while a row renders, so per-element listeners
// bound at render time were lost — the mark looked clickable but did nothing
// mid-render (2026-09-16).
function initWarnToggle() {
  $('library-list').addEventListener('click', (e) => {
    const b = e.target.closest('[data-warn-toggle]');
    if (!b) return;
    e.stopPropagation();               // never trigger the row's reveal-zip
    const id = b.dataset.warnToggle;
    const open = !openWarnings.has(id);
    if (open) openWarnings.add(id); else openWarnings.delete(id);
    b.setAttribute('aria-expanded', String(open));
    const region = $('library-list').querySelector(`[data-warn-region="${CSS.escape(id)}"]`);
    if (region) region.dataset.open = String(open);
  });
}
initWarnToggle();

// Poll every second until both backends answer, then settle to every 5 s.
(async function healthLoop() {
  const ready = await pollHealth();
  setTimeout(healthLoop, ready ? 5000 : 1000);
})();
