const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  openFolder: () => ipcRenderer.invoke('dialog:openFolder'),
  openProject: () => ipcRenderer.invoke('dialog:openProject'),
  openFolderInFinder: (p) => ipcRenderer.invoke('shell:openFolder', p),
  revealInFinder: (p) => ipcRenderer.invoke('shell:revealInFinder', p),
  getHistory: () => ipcRenderer.invoke('history:get'),
  saveHistory: (entry) => ipcRenderer.invoke('history:save', entry),
  clearHistory: () => ipcRenderer.invoke('history:clear'),
  getInbox: () => ipcRenderer.invoke('inbox:get'),
  clearInbox: () => ipcRenderer.invoke('inbox:clear'),
  addProjects: () => ipcRenderer.invoke('dialog:addProjects'),
  libraryStats: (paths) => ipcRenderer.invoke('library:stats', paths),
  scanStemma: () => ipcRenderer.invoke('stemma:scan'),
  addToStemma: (paths) => ipcRenderer.invoke('stemma:add', paths),
  removeFromStemma: (aliasPath) => ipcRenderer.invoke('stemma:remove', aliasPath),
  chooseStemmaFolder: () => ipcRenderer.invoke('stemma:choose'),
  getRenderMeta: () => ipcRenderer.invoke('meta:get'),
  saveRenderMeta: (metaMap) => ipcRenderer.invoke('meta:save', metaMap),
});
