const { app, BrowserWindow, ipcMain, dialog, shell, Notification } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, execFile } = require('child_process');
const Store = require('electron-store');

const store = new Store();
let mainWindow;
let pythonProcess;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 780,
    minWidth: 900,
    minHeight: 650,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#0a0a0a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer/index.html'));
}

function startPythonServer() {
  let command, args;

  if (app.isPackaged) {
    const binaryPath = path.join(process.resourcesPath, 'stemexport-server');
    command = binaryPath;
    args = [];
    console.log('[Python] Using bundled binary:', binaryPath);
  } else {
    const serverPath = path.join(__dirname, '../python/server.py');
    command = 'python3';
    args = [serverPath];
    console.log('[Python] Using python3 dev server');
  }

  // Tell the render backend which app names are US (the send-stems launcher) so its
  // focus-restore never targets our own window — it must return focus to the user's
  // real working window instead. Dev shows up as 'Electron'; a packaged build shows
  // up as its product name / executable basename. Pass every candidate (newline-
  // separated); the Python side also derives the parent process name as a fallback.
  const launcherApps = new Set();
  try { launcherApps.add(app.getName()); } catch (e) {}
  try { launcherApps.add(path.basename(process.execPath).replace(/\.app$/i, '')); } catch (e) {}
  if (!app.isPackaged) launcherApps.add('Electron');
  const launcherEnv = Array.from(launcherApps).filter(Boolean).join('\n');
  console.log('[Python] focus-exclude launcher apps:', launcherEnv.split('\n').join(', '));

  pythonProcess = spawn(command, args, {
    env: { ...process.env, STEMEXPORT_LAUNCHER_APPS: launcherEnv }
  });

  // Line-buffer the server's stdout: chunks can split mid-line, so accumulate and
  // dispatch only on complete '\n'-terminated lines. Each line is logged, and a
  // [[EXPORT_FAILURE]] marker line fires the native failure notification.
  let stdoutBuffer = '';
  pythonProcess.stdout.on('data', (data) => {
    stdoutBuffer += data.toString();
    let nl;
    while ((nl = stdoutBuffer.indexOf('\n')) >= 0) {
      const line = stdoutBuffer.slice(0, nl);
      stdoutBuffer = stdoutBuffer.slice(nl + 1);
      console.log('[Python]', line);
      handleServerLine(line);
    }
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error('[Python Error]', data.toString());
  });

  pythonProcess.on('close', (code) => {
    console.log('[Python] exited with code', code);
  });
}

const EXPORT_FAILURE_MARKER = '[[EXPORT_FAILURE]]';

// Inspect one server stdout line; on the failure marker, fire a single native macOS
// notification (project name + friendly reason). Electron's Notification shows even
// when the app is backgrounded — which is the whole point (renders run invisibly).
// Malformed payloads are logged and ignored, never thrown.
function handleServerLine(line) {
  const at = line.indexOf(EXPORT_FAILURE_MARKER);
  if (at < 0) return;
  let payload;
  try {
    payload = JSON.parse(line.slice(at + EXPORT_FAILURE_MARKER.length).trim());
  } catch (e) {
    console.error('[Notify] could not parse EXPORT_FAILURE payload:', e);
    return;
  }
  const project = (payload && payload.project) || 'project';
  const reason = (payload && payload.reason) || 'The render could not be completed.';
  try {
    if (Notification.isSupported()) {
      new Notification({ title: `Render failed — ${project}`, body: reason }).show();
    }
  } catch (e) {
    console.error('[Notify] failed to show notification:', e);
  }
  // Persist the same terminal-failure signal to the in-UI inbox (electron-store),
  // mirroring history:*. Driven from here (not the renderer poll) so the message is
  // recorded even while the app is backgrounded. detail = raw {title,body,buttons}.
  try {
    const messages = store.get('messages', []);
    messages.unshift({
      project,
      reason,
      detail: (payload && payload.detail) || null,
      date: new Date().toISOString(),
    });
    if (messages.length > 50) messages.splice(50);
    store.set('messages', messages);
  } catch (e) {
    console.error('[Inbox] failed to save message:', e);
  }
}

app.whenReady().then(() => {
  startPythonServer();
  setTimeout(() => {
    createWindow();
  }, 1500);
});

app.on('window-all-closed', () => {
  if (pythonProcess) pythonProcess.kill();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (pythonProcess) pythonProcess.kill();
});

ipcMain.handle('dialog:openFolder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory']
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('dialog:openProject', async () => {
  // Accept BOTH Logic save styles: a `.logicx` package (a bundle macOS treats as
  // a file) and a folder-style project (a directory containing the inner .logicx).
  // openFile+openDirectory lets the user pick either; the backend resolver (§11)
  // turns whatever is chosen into the inner .logicx.
  const result = await dialog.showOpenDialog(mainWindow, {
    filters: [{ name: 'Logic Pro Project', extensions: ['logicx'] }],
    properties: ['openFile', 'openDirectory']
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('shell:openFolder', async (event, folderPath) => {
  shell.openPath(folderPath);
});

// Reveal a specific file (e.g. the .zip) in Finder rather than opening it.
ipcMain.handle('shell:revealInFinder', async (event, filePath) => {
  shell.showItemInFolder(filePath);
});

ipcMain.handle('history:get', () => {
  return store.get('history', []);
});

ipcMain.handle('history:save', (event, entry) => {
  const history = store.get('history', []);
  history.unshift(entry);
  if (history.length > 20) history.splice(20);
  store.set('history', history);
  return history;
});

ipcMain.handle('history:clear', () => {
  store.set('history', []);
  return [];
});

// In-UI message inbox (critically-failed renders) — mirrors history:* exactly.
ipcMain.handle('inbox:get', () => {
  return store.get('messages', []);
});

ipcMain.handle('inbox:clear', () => {
  store.set('messages', []);
  return [];
});

// ── Stemma folder ────────────────────────────────────────────────────────────
// The library IS the stemma folder: a normal Finder folder holding ALIASES
// (symlinks) to sessions that never leave their original locations. The app,
// the window-drop and the droplet all plant aliases here; the UI mirrors the
// folder's contents. Renders/ inside it is the default output. Adding to the
// folder NEVER triggers a render — rendering starts only from the UI buttons.

const DEFAULT_STEMMA_FOLDER = () => path.join(app.getPath('music'), 'Stemma');

function stemmaFolderPath() {
  return store.get('stemmaFolder', DEFAULT_STEMMA_FOLDER());
}

function ensureStemmaFolder() {
  const folder = stemmaFolderPath();
  fs.mkdirSync(path.join(folder, 'Renders'), { recursive: true });
  return folder;
}

const SESSION_RE = /\.(logicx|als)$/i;
// Plain session names AND Finder-alias names ("X.logicx alias",
// duplicated ones get "X.logicx alias 2").
const SESSION_OR_ALIAS_RE = /\.(logicx|als)(?: alias(?: \d+)?)?$/i;
const FINDER_ALIAS_SUFFIX_RE = / alias(?: \d+)?$/i;

// Finder-alias files start with the bookmark magic "book". This is the ground
// truth — names are unreliable: Finder DROPS the extension when it names an
// alias to a package (an alias to "Gamabunta.logicx" is just "Gamabunta").
function hasBookmarkMagic(p) {
  try {
    const fd = fs.openSync(p, 'r');
    const buf = Buffer.alloc(4);
    fs.readSync(fd, buf, 0, 4, 0);
    fs.closeSync(fd);
    return buf.toString('latin1') === 'book';
  } catch (e) { return false; }
}

// "This plain file is a Finder alias, not a real session": by suffix, by the
// impossible shape (a FILE named .logicx — real ones are directories), or by
// content signature (covers extensionless aliases; a real .als is gzip data,
// so no confusion).
function looksLikeFinderAlias(p, ent, name) {
  if (!ent.isFile()) return false;
  if (FINDER_ALIAS_SUFFIX_RE.test(name)) return true;
  if (/\.logicx$/i.test(name)) return true;
  return hasBookmarkMagic(p);
}

// Resolve a Finder alias via the macOS bookmark API (JXA/ObjC) — no Finder
// automation, no permission prompt. Returns the target path or null.
const RESOLVE_ALIAS_JXA = `ObjC.import('Foundation');
function run(argv) {
  const url = $.NSURL.fileURLWithPath(argv[0]);
  const data = $.NSURL.bookmarkDataWithContentsOfURLError(url, $());
  if (!data || data.isNil()) return '';
  const target = $.NSURL.URLByResolvingBookmarkDataOptionsRelativeToURLBookmarkDataIsStaleError(
    data, 256 /* WithoutUI */, $(), $(), $());
  if (!target || target.isNil()) return '';
  return target.path.js;
}`;

function resolveFinderAlias(aliasPath) {
  return new Promise((resolve) => {
    execFile('osascript', ['-l', 'JavaScript', '-e', RESOLVE_ALIAS_JXA, aliasPath],
      (err, stdout) => resolve((stdout || '').trim() || null));
  });
}

// Resolutions are cached by mtime so the 3s rescan doesn't respawn osascript.
const finderAliasCache = new Map(); // aliasPath -> {mtimeMs, target}

async function resolveFinderAliasCached(aliasPath) {
  let st = null;
  try { st = fs.statSync(aliasPath); } catch (e) {}
  const cached = finderAliasCache.get(aliasPath);
  if (cached && st && cached.mtimeMs === st.mtimeMs) return cached.target;
  const target = await resolveFinderAlias(aliasPath);
  if (st && target) finderAliasCache.set(aliasPath, { mtimeMs: st.mtimeMs, target });
  return target;
}

// List the folder's sessions. Three shortcut flavors plus the real thing all
// count: symlinks (planted by the app/droplet), Finder aliases (⌥⌘-drag —
// any name, found by content signature), and real session files/packages.
// Each resolves to its original; dangling shortcuts report missing:true so
// the UI greys them out instead of breaking.
//
// Housekeeping done in passing:
//  - NORMALIZE: a Finder alias whose name lacks the original's full name is
//    renamed to it ("Gamabunta" -> "Gamabunta.logicx"), so folder names always
//    reflect the session they point at.
//  - DEDUPE: shortcuts resolving to the same original produce ONE item.
async function listStemmaItems(folder) {
  const byTarget = new Map(); // resolved target -> item
  const items = [];
  for (const ent of fs.readdirSync(folder, { withFileTypes: true })) {
    if (ent.name.startsWith('.')) continue;
    let aliasPath = path.join(folder, ent.name);
    let name = ent.name;
    let targetPath = aliasPath;
    let missing = false;

    if (ent.isSymbolicLink()) {
      if (!SESSION_RE.test(name)) continue;
      try {
        targetPath = fs.realpathSync(aliasPath);
      } catch (e) {
        try { targetPath = fs.readlinkSync(aliasPath); } catch (e2) {}
        missing = true;
      }
    } else if (looksLikeFinderAlias(aliasPath, ent, name)) {
      const resolved = await resolveFinderAliasCached(aliasPath);
      if (!resolved) {
        // Unresolvable alias: only list it if its name says "session".
        if (!SESSION_OR_ALIAS_RE.test(name)) continue;
        missing = true;
      } else if (!SESSION_RE.test(resolved)) {
        continue; // alias to something that isn't a DAW session — not ours
      } else {
        targetPath = resolved;
        missing = !fs.existsSync(resolved);
        // Normalize the alias's filename to the original's full name.
        const desired = path.basename(resolved);
        if (name !== desired) {
          let dest = path.join(folder, desired);
          if (!lexists(dest)) {
            try {
              fs.renameSync(aliasPath, dest);
              finderAliasCache.delete(aliasPath);
              finderAliasCache.set(dest, { mtimeMs: fs.statSync(dest).mtimeMs, target: resolved });
              aliasPath = dest;
              name = desired;
            } catch (e) { console.error('[Stemma] normalize rename failed:', e); }
          }
          // If desired name is taken, leave as is — dedupe below handles it.
        }
      }
    } else if (ent.isDirectory() || ent.isFile()) {
      if (!SESSION_RE.test(name)) continue; // real session package/file only
    } else {
      continue;
    }

    const item = {
      aliasPath,
      name: name.replace(FINDER_ALIAS_SUFFIX_RE, ''),
      targetPath,
      missing,
      ext: /\.als$/i.test(targetPath) || /\.als/i.test(name) ? 'als' : 'logicx',
    };
    // Dedupe by original: first healthy shortcut wins; a healthy one replaces
    // a dangling duplicate.
    const key = targetPath;
    const seen = byTarget.get(key);
    if (!seen) {
      byTarget.set(key, item);
      items.push(item);
    } else if (seen.missing && !item.missing) {
      items[items.indexOf(seen)] = item;
      byTarget.set(key, item);
    }
  }
  return items;
}

ipcMain.handle('stemma:scan', async () => {
  const folder = ensureStemmaFolder();
  return {
    folder,
    defaultOutput: path.join(folder, 'Renders'),
    items: await listStemmaItems(folder),
  };
});

// True if anything sits at p — including a dangling symlink, which
// fs.existsSync() reports as absent because it follows the link.
function lexists(p) {
  try { fs.lstatSync(p); return true; } catch (e) { return false; }
}

// Plant aliases for the given originals. A session already reachable through
// ANY existing shortcut in the folder (symlink, Finder alias, or the real
// file) is skipped — no duplicate rows, no duplicate files. Name collisions
// with a DIFFERENT session get a numbered name (My Song 2.logicx).
ipcMain.handle('stemma:add', async (event, originalPaths) => {
  const folder = ensureStemmaFolder();
  const existing = new Set((await listStemmaItems(folder)).map(it => {
    try { return fs.realpathSync(it.targetPath); } catch (e) { return it.targetPath; }
  }));
  let added = 0;
  for (const original of originalPaths || []) {
    let realOriginal = original;
    try { realOriginal = fs.realpathSync(original); } catch (e) {}
    if (existing.has(realOriginal)) continue; // already in the folder — no-op
    const ext = path.extname(realOriginal);
    const stem = path.basename(realOriginal, ext);
    let dest = path.join(folder, stem + ext);
    let n = 2;
    while (lexists(dest)) {
      dest = path.join(folder, `${stem} ${n}${ext}`);
      n += 1;
    }
    try {
      fs.symlinkSync(realOriginal, dest);
      existing.add(realOriginal);
      added += 1;
    } catch (e) {
      console.error('[Stemma] could not alias', original, e);
    }
  }
  return added;
});

// Remove = trash the alias (or the real file, if one was dragged straight into
// the folder) — always recoverable, and originals behind aliases are untouched.
ipcMain.handle('stemma:remove', async (event, aliasPath) => {
  const folder = stemmaFolderPath();
  if (path.dirname(aliasPath) !== folder) return false; // only ever touch the folder
  await shell.trashItem(aliasPath);
  return true;
});

ipcMain.handle('stemma:choose', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory']
  });
  if (result.canceled) return null;
  store.set('stemmaFolder', result.filePaths[0]);
  return ensureStemmaFolder();
});

// Per-session render results (keyed by ORIGINAL path — survives alias renames).
ipcMain.handle('meta:get', () => store.get('renderMeta', {}));
ipcMain.handle('meta:save', (event, metaMap) => {
  store.set('renderMeta', metaMap);
  return metaMap;
});

// Multi-select picker for library additions. openFile+openDirectory so both a
// .logicx package and a folder-style project can be chosen (same reasoning as
// dialog:openProject); .als is a plain file.
ipcMain.handle('dialog:addProjects', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    filters: [{ name: 'DAW Project', extensions: ['logicx', 'als'] }],
    properties: ['openFile', 'openDirectory', 'multiSelections']
  });
  return result.canceled ? [] : result.filePaths;
});

// Batch stats for library rows: exists + mtime from fs, on-disk size via one
// `du -sk` call (a .logicx package is a directory — fs.stat can't size it).
ipcMain.handle('library:stats', async (event, paths) => {
  const out = {};
  const existing = [];
  for (const p of paths) {
    try {
      const st = fs.statSync(p);
      out[p] = { exists: true, mtimeMs: st.mtimeMs, sizeBytes: null };
      existing.push(p);
    } catch (e) {
      out[p] = { exists: false, mtimeMs: null, sizeBytes: null };
    }
  }
  if (existing.length) {
    try {
      const sizes = await new Promise((resolve) => {
        execFile('du', ['-sk', ...existing], { maxBuffer: 1024 * 1024 }, (err, stdout) => {
          // du exits non-zero on permission holes but still prints what it
          // measured — use stdout regardless.
          resolve(stdout || '');
        });
      });
      for (const line of sizes.split('\n')) {
        const m = line.match(/^(\d+)\t(.+)$/);
        if (m && out[m[2]]) out[m[2]].sizeBytes = parseInt(m[1], 10) * 1024;
      }
    } catch (e) {
      console.error('[Library] du failed:', e);
    }
  }
  return out;
});
