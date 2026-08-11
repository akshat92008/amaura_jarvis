/**
 * J.A.R.V.I.S. Desktop App — Preload Script
 *
 * Bridges the renderer process with the main process via contextBridge.
 * Exposes a secure API for the HUD interface to communicate with the
 * Python backend and control Electron features.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jarvis', {
    // ── Server Info ──────────────────────────────────────────────────────
    getServerUrl: () => ipcRenderer.invoke('get-server-url'),
    getWsUrl: () => ipcRenderer.invoke('get-ws-url'),
    getConfig: () => ipcRenderer.invoke('get-config'),
    request: (request) => ipcRenderer.invoke('backend-request', request),
    stream: async (request, onToken) => {
        const streamId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        const listener = (_event, payload) => {
            if (payload && payload.streamId === streamId) onToken(String(payload.token || ''));
        };
        ipcRenderer.on('chat-stream-token', listener);
        try {
            return await ipcRenderer.invoke('backend-stream', { ...request, streamId });
        } finally {
            ipcRenderer.removeListener('chat-stream-token', listener);
        }
    },

    // ── Backend Management ───────────────────────────────────────────────
    restartBackend: () => ipcRenderer.invoke('restart-backend'),

    // ── Window Control ───────────────────────────────────────────────────
    hideWindow: () => ipcRenderer.send('hide-window'),
    minimizeWindow: () => ipcRenderer.send('minimize-window'),

    // ── System Info ──────────────────────────────────────────────────────
    getSystemInfo: () => ipcRenderer.invoke('get-system-info'),

    // ── Voice Control ────────────────────────────────────────────────────
    setTrayVoice: (enabled) => ipcRenderer.send('set-tray-voice', enabled),

    // ── Events from Main Process ─────────────────────────────────────────
    onBackendReady: (callback) => {
        ipcRenderer.on('backend-ready', () => callback());
    },
    onBackendError: (callback) => {
        ipcRenderer.on('backend-error', (_, msg) => callback(msg));
    },
    onSummon: (callback) => {
        ipcRenderer.on('summon', () => callback());
    },
    onStartVoice: (callback) => {
        ipcRenderer.on('start-voice', () => callback());
    },
    onToggleVoice: (callback) => {
        ipcRenderer.on('toggle-voice', (_, enabled) => callback(enabled));
    },
    onShowStatus: (callback) => {
        ipcRenderer.on('show-status', () => callback());
    },

    // ── Cleanup ──────────────────────────────────────────────────────────
    removeAllListeners: (channel) => {
        ipcRenderer.removeAllListeners(channel);
    },
});
