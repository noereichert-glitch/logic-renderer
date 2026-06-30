const { app, BrowserWindow, ipcMain, dialog, shell, Notification } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
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

  pythonProcess = spawn(command, args, {
    env: { ...process.env }
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
  shell.showItemInFinder(filePath);
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
