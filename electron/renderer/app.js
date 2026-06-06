// StemExport renderer — One-Click edition.
// All export settings are locked defaults (Concept §3); the UI only carries
// the project path and output folder.

const API = 'http://127.0.0.1:5123';
const STORAGE_OUTPUT_FOLDER = 'stemExport.outputFolder';

// ── State ────────────────────────────────────────────────────────────────────
let currentFile = null;
let outputFolder = localStorage.getItem(STORAGE_OUTPUT_FOLDER) || null;

// ── Sidebar nav ──────────────────────────────────────────────────────────────
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const screen = btn.dataset.screen;
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(`screen-${screen}`).classList.add('active');
    if (screen === 'history') loadHistory();
  });
});

function showStep(id) {
  document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function showExportScreen() {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('[data-screen="export"]').classList.add('active');
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById('screen-export').classList.add('active');
}

// ── Drop zone + browse ───────────────────────────────────────────────────────
const dropZone = document.getElementById('drop-zone');

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  const file = e.dataTransfer.files[0];
  // Accept a .logicx package OR a folder-style project (dropped folders have no
  // extension / empty type). The backend resolver validates & resolves to the
  // inner .logicx, and shows an error in the file row if it isn't a project.
  if (file && (file.name.endsWith('.logicx') || file.type === '')) handleFileSelect(file.path);
});
dropZone.addEventListener('click', () => document.getElementById('btn-browse').click());

document.getElementById('btn-browse').addEventListener('click', async (e) => {
  e.stopPropagation();
  const path = await window.electronAPI.openProject();
  if (path) handleFileSelect(path);
});

document.getElementById('btn-clear-file').addEventListener('click', () => {
  currentFile = null;
  document.getElementById('file-info').classList.add('hidden');
  dropZone.style.display = '';
  checkExportReady();
});

async function handleFileSelect(filePath) {
  currentFile = filePath;
  const fileName = filePath.split('/').pop();
  document.getElementById('file-name').textContent = fileName;
  document.getElementById('track-count').textContent = 'Parsing…';
  document.getElementById('file-info').classList.remove('hidden');
  dropZone.style.display = 'none';

  try {
    const res = await fetch(`${API}/parse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath })
    });
    const data = await res.json();
    if (data.error) {
      document.getElementById('track-count').textContent = data.error;
    } else if (!data.track_count) {
      // Logic .logicx isn't parsed up front (the render names the stems itself) — no
      // track count to show, so just confirm the project is ready to render.
      document.getElementById('track-count').textContent = 'Logic Pro project — ready to render';
    } else {
      const groupCount = (data.tracks || []).filter(t => t.type === 'group').length;
      const tail = groupCount > 0 ? ` · ${groupCount} group${groupCount !== 1 ? 's' : ''}` : '';
      document.getElementById('track-count').textContent = `${data.track_count} tracks${tail}`;
    }
  } catch (e) {
    document.getElementById('track-count').textContent = 'Could not reach backend';
  }
  checkExportReady();
}

// ── Output folder (remembered between runs) ──────────────────────────────────
function refreshOutputFolderDisplay() {
  const el = document.getElementById('output-path-display');
  el.textContent = outputFolder || 'No folder selected';
  el.classList.toggle('folder-path-empty', !outputFolder);
}

document.getElementById('btn-pick-folder').addEventListener('click', async () => {
  const folder = await window.electronAPI.openFolder();
  if (folder) {
    outputFolder = folder;
    localStorage.setItem(STORAGE_OUTPUT_FOLDER, folder);
    refreshOutputFolderDisplay();
    checkExportReady();
  }
});

refreshOutputFolderDisplay();

// ── Stem Export button enable state ──────────────────────────────────────────
function checkExportReady() {
  document.getElementById('btn-start-export').disabled = !(currentFile && outputFolder);
}

// ── Export ───────────────────────────────────────────────────────────────────
document.getElementById('btn-start-export').addEventListener('click', startExport);

function setExportStatus(title, sub, progress) {
  document.getElementById('export-status-title').textContent = title;
  document.getElementById('export-status-sub').textContent = sub;
  document.getElementById('export-progress-bar').style.width = (progress || 0) + '%';
}

let progressPoller = null;
function stopProgressPolling() {
  if (progressPoller) { clearInterval(progressPoller); progressPoller = null; }
}

async function startExport() {
  showStep('step-exporting');
  setExportStatus('Launching Logic Pro…', 'Running silently in the background', 5);

  try {
    const res = await fetch(`${API}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_path: currentFile,
        output_folder: outputFolder,
      })
    });
    const startData = await res.json();
    if (!startData.started) {
      setExportStatus('Export failed', startData.error || 'Could not start export', 0);
      return;
    }

    stopProgressPolling();
    progressPoller = setInterval(async () => {
      try {
        const pollRes = await fetch(`${API}/export/progress`);
        const data = await pollRes.json();
        if (data.status_title) {
          setExportStatus(data.status_title, data.status_sub || '', data.progress || 0);
        }
        document.getElementById('export-track-label').textContent = data.current_track || '';

        if (data.done) {
          stopProgressPolling();
          if (data.error) {
            setExportStatus('Export failed', data.error, 0);
            return;
          }
          const sets = data.sets || {};
          const projectFolder = data.project_folder || outputFolder;
          const zipPath = data.zip_path || null;
          showDoneScreen(sets, projectFolder, zipPath);

          await window.electronAPI.saveHistory({
            project: currentFile.split('/').pop(),
            date: new Date().toISOString(),
            folder: projectFolder,
            zip_path: zipPath,
            set_counts: countSets(sets),
          });
        }
      } catch (e) {
        // Backend temporarily busy — keep polling.
      }
    }, 800);
  } catch (e) {
    stopProgressPolling();
    setExportStatus('Connection error', 'Could not reach the Python backend. Is it running?', 0);
  }
}

// ── Done screen ──────────────────────────────────────────────────────────────
const SET_LABEL = {
  '01_With_FX': 'With FX',
  '02_With_Returns_And_Master': 'Returns + Master',
  '03_Raw': 'Raw (devices bypassed)',
  '_flat': 'Stems',
};

function countSets(sets) {
  const out = {};
  for (const k of Object.keys(sets)) out[k] = (sets[k] || []).length;
  return out;
}

function showDoneScreen(sets, projectFolder, zipPath, fromHistory = false) {
  const orderedKeys = ['01_With_FX', '02_With_Returns_And_Master', '03_Raw'];
  const presentKeys = orderedKeys.filter(k => sets[k]);
  const extraKeys = Object.keys(sets).filter(k => !orderedKeys.includes(k));
  const keys = [...presentKeys, ...extraKeys];

  const totalStems = keys.reduce((acc, k) => acc + (sets[k] || []).length, 0);
  document.getElementById('done-subtitle').textContent =
    `${keys.length} set${keys.length !== 1 ? 's' : ''} · ${totalStems} stem${totalStems !== 1 ? 's' : ''}`;

  const list = document.getElementById('set-summary-list');
  list.innerHTML = '';
  for (const k of keys) {
    const files = sets[k] || [];
    const row = document.createElement('div');
    row.className = 'stem-item';
    row.innerHTML = `
      <div class="file-icon">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3 4h14v12H3V4z" stroke="#00ff88" stroke-width="1.5" stroke-linejoin="round"/><path d="M3 8h14" stroke="#00ff88" stroke-width="1.5"/></svg>
      </div>
      <div class="stem-info">
        <div class="stem-name">${k}</div>
        <div class="stem-file">${SET_LABEL[k] || k} · ${files.length} stem${files.length !== 1 ? 's' : ''}</div>
      </div>
    `;
    list.appendChild(row);
  }

  const btnZip = document.getElementById('btn-open-zip');
  if (zipPath) {
    btnZip.style.display = '';
    btnZip.onclick = () => window.electronAPI.revealInFinder(zipPath);
  } else {
    btnZip.style.display = 'none';
  }

  document.getElementById('btn-open-folder').onclick = () =>
    window.electronAPI.openFolderInFinder(projectFolder);

  // Back-to-history button — created lazily, shown only when arriving from history.
  const btnNewExport = document.getElementById('btn-new-export');
  let btnBackHistory = document.getElementById('btn-back-history');
  if (!btnBackHistory) {
    btnBackHistory = document.createElement('button');
    btnBackHistory.id = 'btn-back-history';
    btnBackHistory.className = 'btn-secondary';
    btnBackHistory.textContent = '← Back to History';
    btnNewExport.parentNode.insertBefore(btnBackHistory, btnNewExport);
    btnBackHistory.addEventListener('click', () => {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      document.querySelector('[data-screen="history"]').classList.add('active');
      document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
      document.getElementById('screen-history').classList.add('active');
      loadHistory();
    });
  }
  btnBackHistory.style.display = fromHistory ? '' : 'none';

  btnNewExport.onclick = resetToMain;

  showStep('step-done');
}

function resetToMain() {
  currentFile = null;
  document.getElementById('file-info').classList.add('hidden');
  document.getElementById('drop-zone').style.display = '';
  refreshOutputFolderDisplay();
  checkExportReady();
  showExportScreen();
  showStep('step-main');
}

// ── History ──────────────────────────────────────────────────────────────────
async function loadHistory() {
  const history = await window.electronAPI.getHistory();
  const list = document.getElementById('history-list');

  if (!history.length) {
    list.innerHTML = '<div class="empty-state">No exports yet. Start by dropping a .logicx file.</div>';
    return;
  }

  list.innerHTML = '';
  history.forEach(h => {
    const date = new Date(h.date).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit'
    });
    const counts = h.set_counts || {};
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const stemSummary = total > 0
      ? `${total} stems across ${Object.keys(counts).length} set${Object.keys(counts).length !== 1 ? 's' : ''}`
      : (typeof h.stems === 'number' ? `${h.stems} stems` : '');

    const item = document.createElement('div');
    item.className = 'history-item';
    item.style.cursor = 'pointer';
    item.innerHTML = `
      <div class="history-icon">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M4 2h8l4 4v12H4V2z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 2v4h4" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
      </div>
      <div class="history-info">
        <div class="history-name">${h.project}</div>
        <div class="history-meta">${date}${stemSummary ? ' · ' + stemSummary : ''} · ${h.folder}</div>
      </div>
      <div class="history-arrow">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M5 3l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </div>
    `;
    item.addEventListener('click', () => openHistoryEntry(h));
    list.appendChild(item);
  });
}

async function openHistoryEntry(h) {
  try {
    const res = await fetch(`${API}/folder/stems`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: h.folder })
    });
    const data = await res.json();
    if (data.error) {
      alert('Could not read folder: ' + data.error);
      return;
    }
    showExportScreen();
    showDoneScreen(data.sets || {}, data.output_folder || h.folder, h.zip_path || null, true);
  } catch (e) {
    alert('Could not reach backend. Is the app running?');
  }
}

document.getElementById('btn-clear-history').addEventListener('click', async () => {
  await window.electronAPI.clearHistory();
  loadHistory();
});

// ── Init ─────────────────────────────────────────────────────────────────────
checkExportReady();
