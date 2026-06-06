const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  openFolder: () => ipcRenderer.invoke('dialog:openFolder'),
  openProject: () => ipcRenderer.invoke('dialog:openProject'),
  openFolderInFinder: (p) => ipcRenderer.invoke('shell:openFolder', p),
  revealInFinder: (p) => ipcRenderer.invoke('shell:revealInFinder', p),
  getHistory: () => ipcRenderer.invoke('history:get'),
  saveHistory: (entry) => ipcRenderer.invoke('history:save', entry),
  clearHistory: () => ipcRenderer.invoke('history:clear'),
});
