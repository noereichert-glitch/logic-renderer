const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
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

  pythonProcess.stdout.on('data', (data) => {
    console.log('[Python]', data.toString());
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error('[Python Error]', data.toString());
  });

  pythonProcess.on('close', (code) => {
    console.log('[Python] exited with code', code);
  });
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
  const result = await dialog.showOpenDialog(mainWindow, {
    filters: [{ name: 'Logic Pro Project', extensions: ['logicx'] }],
    properties: ['openFile']
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
