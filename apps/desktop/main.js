// Trend Desk desktop: one window on the live app. Links to other sites (TradingView, Angel, news) open in the normal browser.
const { app, BrowserWindow, shell, Menu } = require('electron');
const URL = 'https://drsinghap81.github.io/blank-app/';
const OK = ['drsinghap81.github.io'];
function win() {
  const w = new BrowserWindow({ width: 1280, height: 860, minWidth: 380, backgroundColor: '#111827', title: 'Trend Desk',
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false } });
  w.loadURL(URL);
  w.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  w.webContents.on('will-navigate', (e, url) => { try { if (!OK.includes(new globalThis.URL(url).hostname)) { e.preventDefault(); shell.openExternal(url); } } catch (x) { e.preventDefault(); } });
  w.webContents.on('did-fail-load', () => w.loadURL('data:text/html,<body style="font-family:system-ui;background:%23111827;color:%23e5e7eb;display:grid;place-items:center;height:100vh"><div><h2>Trend Desk</h2><p>No connection. Retrying in 10 s…</p></div></body>') && setTimeout(() => w.loadURL(URL), 10000));
}
app.whenReady().then(() => {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(process.platform === 'darwin' ? [{ role: 'appMenu' }] : []),
    { label: 'View', submenu: [{ role: 'reload' }, { role: 'forceReload' }, { type: 'separator' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'resetZoom' }, { role: 'togglefullscreen' }] },
    { role: 'editMenu' }, { role: 'windowMenu' }]));
  win();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) win(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
