const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('webkit', {messageHandlers: {ambi: {
  postMessage: message => ipcRenderer.send('ambi-native', message)
}}});
contextBridge.exposeInMainWorld('ambiLinux', {
  submitKey: value => ipcRenderer.invoke('ambi-key', value),
  stop: () => ipcRenderer.send('ambi-stop')
});
