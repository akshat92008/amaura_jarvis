/**
 * J.A.R.V.I.S. Desktop App — Main Process
 *
 * Electron main process that manages the application lifecycle,
 * creates the Iron Man HUD window, handles system tray integration,
 * global shortcuts, and bridges the renderer with the Python backend.
 */

const { app, BrowserWindow, Tray, Menu, globalShortcut, nativeImage, screen, ipcMain, systemPreferences, dialog } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const net = require('net');
const crypto = require('crypto');

// ── Configuration ──────────────────────────────────────────────────────────────

const CONFIG = {
    serverPort: 0,
    serverHost: '127.0.0.1',
    windowWidth: 1100,
    windowHeight: 750,
    minWidth: 700,
    minHeight: 500,
    summonShortcut: 'CommandOrControl+Shift+J',
    voiceShortcut: 'CommandOrControl+Shift+V',
};
const BACKEND_VERSION = '5.4.1';

let mainWindow = null;
let tray = null;
let serverProcess = null;
let isQuitting = false;
let backendRestartCount = 0;
let backendRestartTimer = null;
let backendBootstrapToken = null;
let backendVerified = false;
let backendHealth = null;
let backendGeneration = 0;
let backendAttached = false;

// Do not allow several Electron runtimes (and therefore several Python
// sidecars) to accumulate when the launcher is clicked more than once.
const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
    app.quit();
}

// ── Runtime Configuration ─────────────────────────────────────────────────────

function parseEnvFile(filePath) {
    const values = {};
    if (!fs.existsSync(filePath)) return values;
    for (const rawLine of fs.readFileSync(filePath, 'utf8').split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line || line.startsWith('#') || !line.includes('=')) continue;
        const index = line.indexOf('=');
        const key = line.slice(0, index).trim();
        let value = line.slice(index + 1).trim();
        if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
            value = value.slice(1, -1);
        }
        values[key] = value;
    }
    return values;
}

function runtimeCredentials() {
    const envPath = app.isPackaged
        ? path.join(app.getPath('userData'), '.env.amaura')
        : path.join(getJarvisPath(), '.env.amaura');
    const fileValues = parseEnvFile(envPath);
    return {
        jarvisKey: process.env.JARVIS_API_KEY || fileValues.JARVIS_API_KEY || '',
        operatorKey: process.env.AMAURA_OPERATOR_KEY || fileValues.AMAURA_OPERATOR_KEY || '',
        approvalKey: process.env.AMAURA_APPROVAL_KEY || fileValues.AMAURA_APPROVAL_KEY || '',
    };
}

async function backendRequest({ path: requestPath, method = 'GET', body = null }) {
    // The renderer loads before the sidecar has completed its identity proof.
    // Hold its first requests until that proof succeeds instead of surfacing a
    // transient startup error in the HUD.
    if (!backendVerified) await waitForServer();
    if (!backendVerified || !CONFIG.serverPort) throw new Error('Authenticated backend is not ready');
    if (typeof requestPath !== 'string' || !requestPath.startsWith('/api/')) {
        throw new Error('Only local /api/ paths are permitted');
    }
    const normalizedMethod = String(method).toUpperCase();
    if (!['GET', 'POST', 'DELETE'].includes(normalizedMethod)) {
        throw new Error('Unsupported backend method');
    }
    // Health was already authenticated with a fresh challenge in
    // waitForServer(). Returning that result avoids a second startup request
    // racing with the renderer and makes the boot screen deterministic.
    if (requestPath === '/api/health' && normalizedMethod === 'GET' && backendHealth) {
        return backendHealth;
    }
    const credentials = runtimeCredentials();
    const headers = { 'Content-Type': 'application/json' };
    // The sidecar's health endpoint proves its parent-child relationship.
    // Renderer health requests still travel through this authenticated main
    // process bridge, so attach a fresh challenge rather than exposing the
    // bootstrap token to the renderer.
    if (requestPath === '/api/health' && backendBootstrapToken) {
        headers['X-Amaura-Bootstrap-Challenge'] = crypto.randomBytes(32).toString('hex');
    }
    if (credentials.jarvisKey) headers['X-Jarvis-Key'] = credentials.jarvisKey;
    if (credentials.operatorKey) headers['X-Amaura-Operator-Key'] = credentials.operatorKey;
    if (credentials.approvalKey) headers['X-Amaura-Approval-Key'] = credentials.approvalKey;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000);
    try {
        const response = await fetch(`http://${CONFIG.serverHost}:${CONFIG.serverPort}${requestPath}`, {
            method: normalizedMethod,
            headers,
            body: body === null ? undefined : JSON.stringify(body),
            signal: controller.signal,
            redirect: 'error',
        });
        const text = await response.text();
        let payload;
        try { payload = text ? JSON.parse(text) : {}; } catch (_) { payload = { raw: text }; }
        if (!response.ok) {
            throw new Error(payload.detail || payload.error || `Backend HTTP ${response.status}`);
        }
        return payload;
    } finally {
        clearTimeout(timer);
    }
}

async function backendStream(event, { streamId, path: requestPath, body }) {
    if (!backendVerified || !CONFIG.serverPort) throw new Error('Authenticated backend is not ready');
    if (requestPath !== '/api/chat/stream') throw new Error('Unsupported streaming path');
    const credentials = runtimeCredentials();
    const headers = { 'Content-Type': 'application/json' };
    if (credentials.jarvisKey) headers['X-Jarvis-Key'] = credentials.jarvisKey;
    if (credentials.operatorKey) headers['X-Amaura-Operator-Key'] = credentials.operatorKey;
    const response = await fetch(`http://${CONFIG.serverHost}:${CONFIG.serverPort}${requestPath}`, {
        method: 'POST', headers, body: JSON.stringify(body || {}), redirect: 'error',
    });
    if (!response.ok || !response.body) throw new Error(`Backend HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let complete = {};
    while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
            if (!line.trim()) continue;
            const item = JSON.parse(line);
            if (item.type === 'token') event.sender.send('chat-stream-token', { streamId, token: item.content || '' });
            else if (item.type === 'complete') complete = item;
            else if (item.type === 'error') throw new Error(item.error || 'Streaming request failed');
        }
        if (done) break;
    }
    return complete;
}

// ── Backend Management ────────────────────────────────────────────────────────

function getPythonCommand() {
    return process.platform === 'darwin' ? 'python3' : 'python';
}

function getJarvisPath() {
    return path.join(__dirname, '..');
}

function getBackendLaunch() {
    if (app.isPackaged) {
        const executable = path.join(
            process.resourcesPath,
            'backend',
            process.platform === 'win32' ? 'amaura-backend.exe' : 'amaura-backend',
        );
        if (!fs.existsSync(executable)) {
            throw new Error(`Packaged backend sidecar is missing: ${executable}`);
        }
        return { command: executable, args: [], cwd: path.dirname(executable) };
    }
    const projectRoot = getJarvisPath();
    const venvPython = path.join(projectRoot, '.venv', 'bin', process.platform === 'win32' ? 'python.exe' : 'python');
    return {
        command: fs.existsSync(venvPython) ? venvPython : getPythonCommand(),
        args: ['-m', 'jarvis.server'],
        cwd: projectRoot,
    };
}

function allocateLoopbackPort() {
    return new Promise((resolve, reject) => {
        const reservation = net.createServer();
        reservation.unref();
        reservation.on('error', reject);
        reservation.listen({ host: CONFIG.serverHost, port: 0, exclusive: true }, () => {
            const address = reservation.address();
            const port = address && typeof address === 'object' ? address.port : 0;
            reservation.close((error) => {
                if (error) reject(error);
                else if (!port) reject(new Error('Failed to allocate a loopback port'));
                else resolve(port);
            });
        });
    });
}

async function startBackendServer() {
    const generation = ++backendGeneration;
    backendVerified = false;
    backendHealth = null;
    backendAttached = false;
    CONFIG.serverPort = await allocateLoopbackPort();
    backendBootstrapToken = crypto.randomBytes(32).toString('hex');
    const launch = getBackendLaunch();

    console.log(`[Amaura] Starting authenticated backend on ${CONFIG.serverHost}:${CONFIG.serverPort}`);
    const env = {
        ...process.env,
        JARVIS_PORT: String(CONFIG.serverPort),
        JARVIS_HOST: CONFIG.serverHost,
        JARVIS_RELOAD: '0',
        PYTHONUNBUFFERED: '1',
        AMAURA_RESOURCE_PROFILE: process.env.AMAURA_RESOURCE_PROFILE || 'macbook-8gb',
        AMAURA_JARVIS_PROACTIVE: process.env.AMAURA_JARVIS_PROACTIVE || '0',
        AMAURA_JARVIS_MISSION_RUNNER: process.env.AMAURA_JARVIS_MISSION_RUNNER || '1',
        AMAURA_JARVIS_MISSION_POLL_SECONDS: process.env.AMAURA_JARVIS_MISSION_POLL_SECONDS || '3',
        AMAURA_JARVIS_MISSION_MAX_GOALS: process.env.AMAURA_JARVIS_MISSION_MAX_GOALS || '1',
        AMAURA_COMPANY_AUTOPILOT_RUNTIME: process.env.AMAURA_COMPANY_AUTOPILOT_RUNTIME || '0',
        AMAURA_JARVIS_OLLAMA_PROBE: process.env.AMAURA_JARVIS_OLLAMA_PROBE || '0',
        AMAURA_DESKTOP_BOOTSTRAP_TOKEN: backendBootstrapToken,
    };

    serverProcess = spawn(launch.command, launch.args, {
        cwd: launch.cwd,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
    });
    const child = serverProcess;

    child.stdout.on('data', (data) => console.log(`[Backend] ${data.toString().trim()}`));
    child.stderr.on('data', (data) => console.log(`[Backend:err] ${data.toString().trim()}`));
    child.on('error', (err) => console.error('[Amaura] Failed to start backend:', err.message));
    child.on('close', (code) => {
        console.log(`[Amaura] Backend exited with code ${code}`);
        if (serverProcess === child) serverProcess = null;
        backendVerified = false;
        if (isQuitting || generation !== backendGeneration) return;
        backendRestartCount += 1;
        if (backendRestartCount > 5) {
            console.error('[Amaura] Backend crash circuit opened after 5 restart attempts');
            if (mainWindow) mainWindow.webContents.send('backend-error', 'Backend crash circuit opened');
            return;
        }
        const backoff = Math.min(30000, 1000 * (2 ** (backendRestartCount - 1)));
        backendRestartTimer = setTimeout(() => {
            startBackendServer()
                .then(() => waitForServer())
                .then(() => {
                    backendRestartCount = 0;
                    if (mainWindow) mainWindow.webContents.send('backend-ready', {
                        serverUrl: `http://${CONFIG.serverHost}:${CONFIG.serverPort}`,
                    });
                })
                .catch((error) => {
                    console.error('[Amaura] Backend restart failed:', error.message);
                    if (serverProcess) serverProcess.kill('SIGTERM');
                });
        }, backoff);
    });
    return child;
}

function stopBackendServer() {
    backendGeneration += 1;
    backendVerified = false;
    backendBootstrapToken = null;
    backendHealth = null;
    backendAttached = false;
    if (backendRestartTimer) {
        clearTimeout(backendRestartTimer);
        backendRestartTimer = null;
    }
    const child = serverProcess;
    serverProcess = null;
    if (!child) return;
    console.log('[Amaura] Stopping backend server...');
    child.kill('SIGTERM');
    const killTimer = setTimeout(() => {
        // child.killed only means Node successfully *sent* a signal. It does
        // not mean Python exited. Check process completion and force-stop a
        // wedged sidecar so it cannot retain gigabytes of compressed memory.
        if (child.exitCode === null && child.signalCode === null) {
            console.warn('[Amaura] Backend did not stop promptly; sending SIGKILL');
            child.kill('SIGKILL');
        }
    }, 3000);
    killTimer.unref();
}

function verifyHealthPayload(payload, challenge, expectedBuildId = null) {
    if (!payload || payload.status !== 'online' || payload.version !== BACKEND_VERSION) return false;
    if (expectedBuildId && payload.build_id && payload.build_id !== expectedBuildId) return false;
    if (!serverProcess) return false;
    // macOS virtual-environment launchers may exec through a Python shim, so
    // the child PID seen by Electron is not guaranteed to equal the Uvicorn
    // process PID.  The per-launch HMAC below is the actual authenticity
    // boundary and cannot be forged by a process that only captures the port.
    const expected = crypto.createHmac('sha256', backendBootstrapToken).update(challenge).digest('hex');
    const supplied = String(payload.bootstrap_proof || '');
    if (expected.length !== supplied.length) return false;
    return crypto.timingSafeEqual(Buffer.from(expected, 'hex'), Buffer.from(supplied, 'hex'));
}

async function tryAttachBackgroundService() {
    const port = Number(process.env.AMAURA_BACKGROUND_PORT || 8000);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return false;
    const serviceSecret = runtimeCredentials().jarvisKey;
    if (!serviceSecret || serviceSecret.length < 32) return false;
    const expectedBuildId = process.env.AMAURA_EXPECTED_BUILD_ID || null;
    const challenge = crypto.randomBytes(32).toString('hex');
    return new Promise((resolve) => {
        const req = http.request({
            hostname: CONFIG.serverHost, port, path: '/api/health', method: 'GET', timeout: 1000,
            headers: { 'X-Amaura-Service-Challenge': challenge },
        }, (res) => {
            let body = '';
            res.setEncoding('utf8');
            res.on('data', (chunk) => { body += chunk; });
            res.on('end', () => {
                try {
                    const payload = JSON.parse(body);
                    const expected = crypto.createHmac('sha256', serviceSecret).update(challenge).digest('hex');
                    const supplied = String(payload.service_proof || '');
                    const authenticated = expected.length === supplied.length
                        && crypto.timingSafeEqual(Buffer.from(expected, 'hex'), Buffer.from(supplied, 'hex'));
                    const buildMatches = !expectedBuildId || !payload.build_id || payload.build_id === expectedBuildId;
                    if (res.statusCode === 200 && authenticated && payload.status === 'online' && payload.version === BACKEND_VERSION && buildMatches) {
                        CONFIG.serverPort = port;
                        backendVerified = true;
                        backendHealth = payload;
                        backendAttached = true;
                        console.log(`[Amaura] Attached to background backend on ${CONFIG.serverHost}:${port} (build_id=${payload.build_id || 'unknown'})`);
                        resolve(true);
                        return;
                    }
                } catch (_) { /* unavailable or not Amaura */ }
                resolve(false);
            });
        });
        req.on('error', () => resolve(false));
        req.on('timeout', () => { req.destroy(); resolve(false); });
        req.end();
    });
}

function waitForServer(retries = 40, delay = 250) {
    if (backendAttached && backendVerified) return Promise.resolve(true);
    return new Promise((resolve, reject) => {
        let attempts = 0;
        const check = () => {
            attempts += 1;
            if (!serverProcess || !backendBootstrapToken || !CONFIG.serverPort) {
                reject(new Error('Backend process is not running'));
                return;
            }
            const challenge = crypto.randomBytes(32).toString('hex');
            const req = http.request({
                hostname: CONFIG.serverHost,
                port: CONFIG.serverPort,
                path: '/api/health',
                method: 'GET',
                headers: { 'X-Amaura-Bootstrap-Challenge': challenge },
                timeout: 2000,
            }, (res) => {
                let body = '';
                res.setEncoding('utf8');
                res.on('data', (chunk) => { body += chunk; });
                res.on('end', () => {
                    let payload = null;
                    try { payload = JSON.parse(body); } catch (_) { payload = null; }
                    if (res.statusCode === 200 && verifyHealthPayload(payload, challenge)) {
                        backendVerified = true;
                        backendHealth = payload;
                        resolve(true);
                    } else if (attempts < retries) {
                        setTimeout(check, delay);
                    } else {
                        reject(new Error('Backend identity verification failed'));
                    }
                });
            });
            req.on('error', () => {
                if (attempts < retries) setTimeout(check, delay);
                else reject(new Error('Backend not reachable'));
            });
            req.on('timeout', () => req.destroy(new Error('Backend health timeout')));
            req.end();
        };
        check();
    });
}

// ── Window Creation ────────────────────────────────────────────────────────────

function createMainWindow() {
    const { width, height } = screen.getPrimaryDisplay().workAreaSize;

    mainWindow = new BrowserWindow({
        width: CONFIG.windowWidth,
        height: CONFIG.windowHeight,
        minWidth: CONFIG.minWidth,
        minHeight: CONFIG.minHeight,
        x: Math.round((width - CONFIG.windowWidth) / 2),
        y: Math.round((height - CONFIG.windowHeight) / 2),
        title: 'Amaura Company OS',
        icon: path.join(__dirname, 'assets', 'icon.png'),
        backgroundColor: '#050a0f',
        titleBarStyle: 'hiddenInset',
        vibrancy: 'dark',
        visualEffectState: 'active',
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
        },
        show: false,
        frame: true,
        transparent: false,
    });

    // Load the HUD interface
    const hudPath = path.join(__dirname, 'renderer', 'hud.html');
    mainWindow.loadFile(hudPath);
    mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    mainWindow.webContents.on('will-navigate', (event, targetUrl) => {
        if (!targetUrl.startsWith('file://')) event.preventDefault();
    });
    mainWindow.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));

    // Show window when ready (prevents white flash)
    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        // Fade in
        mainWindow.webContents.executeJavaScript(`
            document.body.style.opacity = '0';
            document.body.style.transition = 'opacity 0.5s ease-in';
            requestAnimationFrame(() => {
                document.body.style.opacity = '1';
            });
        `);
    });

    mainWindow.on('close', (e) => {
        if (!isQuitting) {
            e.preventDefault();
            mainWindow.hide();
        }
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });

    return mainWindow;
}

// ── System Tray ────────────────────────────────────────────────────────────────

function createTray() {
    // Create a simple tray icon (16x16 PNG)
    const iconSize = 16;
    const trayIcon = nativeImage.createEmpty();

    // Use a simple template image
    const iconPath = path.join(__dirname, 'assets', 'tray-icon.png');
    if (fs.existsSync(iconPath)) {
        tray = new Tray(iconPath);
    } else {
        // Create a minimal icon programmatically
        const canvas = Buffer.alloc(iconSize * iconSize * 4);
        // Simple blue dot
        for (let i = 0; i < canvas.length; i += 4) {
            canvas[i] = 0;     // R
            canvas[i + 1] = 212; // G
            canvas[i + 2] = 255; // B
            canvas[i + 3] = 255; // A
        }
        const img = nativeImage.createFromBuffer(canvas, { width: iconSize, height: iconSize });
        tray = new Tray(img);
    }

    tray.setToolTip('J.A.R.V.I.S. — At your service, sir.');

    const contextMenu = Menu.buildFromTemplate([
        {
            label: 'Show J.A.R.V.I.S.',
            click: () => {
                if (mainWindow) {
                    mainWindow.show();
                    mainWindow.focus();
                }
            },
        },
        {
            label: 'Voice Mode',
            type: 'checkbox',
            checked: false,
            click: (menuItem) => {
                if (mainWindow) {
                    mainWindow.webContents.send('toggle-voice', menuItem.checked);
                }
            },
        },
        { type: 'separator' },
        {
            label: 'System Status',
            click: () => {
                if (mainWindow) {
                    mainWindow.show();
                    mainWindow.webContents.send('show-status');
                }
            },
        },
        { type: 'separator' },
        {
            label: 'Quit J.A.R.V.I.S.',
            click: () => {
                isQuitting = true;
                stopBackendServer();
                app.quit();
            },
        },
    ]);

    tray.setContextMenu(contextMenu);

    tray.on('click', () => {
        if (mainWindow) {
            if (mainWindow.isVisible()) {
                mainWindow.hide();
            } else {
                mainWindow.show();
                mainWindow.focus();
            }
        }
    });
}

// ── Global Shortcuts ───────────────────────────────────────────────────────────

function registerGlobalShortcuts() {
    // Summon shortcut
    globalShortcut.register(CONFIG.summonShortcut, () => {
        if (mainWindow) {
            if (mainWindow.isVisible()) {
                mainWindow.hide();
            } else {
                mainWindow.show();
                mainWindow.focus();
                mainWindow.webContents.send('summon');
            }
        }
    });

    // Voice shortcut
    globalShortcut.register(CONFIG.voiceShortcut, () => {
        if (mainWindow) {
            mainWindow.show();
            mainWindow.focus();
            mainWindow.webContents.send('start-voice');
        }
    });
}

// ── IPC Handlers ───────────────────────────────────────────────────────────────

function setupIPC() {
    ipcMain.handle('get-server-url', () => {
        return `http://${CONFIG.serverHost}:${CONFIG.serverPort}`;
    });

    ipcMain.handle('get-ws-url', () => {
        return `ws://${CONFIG.serverHost}:${CONFIG.serverPort}/ws/chat`;
    });

    ipcMain.handle('get-config', () => {
        return CONFIG;
    });

    ipcMain.handle('backend-request', async (_event, request) => {
        return backendRequest(request || {});
    });
    ipcMain.handle('backend-stream', async (event, request) => backendStream(event, request || {}));

    ipcMain.handle('restart-backend', async () => {
        if (backendAttached) {
            const attached = await tryAttachBackgroundService();
            return attached
                ? { success: true, managedBy: 'background-service' }
                : { success: false, error: 'Background service is unavailable; restart it through launchd.' };
        }
        stopBackendServer();
        try {
            await startBackendServer();
            await waitForServer(40, 250);
            return { success: true };
        } catch (e) {
            return { success: false, error: e.message };
        }
    });

    ipcMain.on('set-tray-voice', (event, enabled) => {
        // Update tray menu voice checkbox
        if (tray) {
            const menu = tray.getContextMenu();
            const voiceItem = menu.items.find(item => item.label === 'Voice Mode');
            if (voiceItem) {
                voiceItem.checked = enabled;
            }
        }
    });

    ipcMain.on('hide-window', () => {
        if (mainWindow) {
            mainWindow.hide();
        }
    });

    ipcMain.on('minimize-window', () => {
        if (mainWindow) {
            mainWindow.minimize();
        }
    });

    ipcMain.handle('get-system-info', async () => {
        try {
            return await backendRequest({ path: '/api/system', method: 'GET' });
        } catch (e) {
            return { info: 'System info unavailable' };
        }
    });
}

// ── App Lifecycle ──────────────────────────────────────────────────────────────

if (hasSingleInstanceLock) app.whenReady().then(async () => {
    console.log('[JARVIS] Starting up...');

    // Setup IPC
    setupIPC();

    // Reuse the login/background service when it is available. The desktop
    // starts its authenticated sidecar only as a local fallback.
    try {
        if (!await tryAttachBackgroundService()) await startBackendServer();
    } catch (error) {
        console.error('[Amaura] Backend launch failed:', error.message);
    }

    // Create window
    createMainWindow();

    // Create tray
    createTray();

    // Register shortcuts
    registerGlobalShortcuts();

    // Wait for backend to be ready
    console.log('[JARVIS] Waiting for backend server...');
    try {
        await waitForServer();
        console.log('[Amaura] Backend server is ready!');
        backendRestartCount = 0;
        if (mainWindow) {
            mainWindow.webContents.send('backend-ready', { serverUrl: `http://${CONFIG.serverHost}:${CONFIG.serverPort}` });
        }
    } catch (e) {
        console.error('[JARVIS] Backend failed to start:', e.message);
        if (mainWindow) {
            mainWindow.webContents.send('backend-error', e.message);
        }
    }
});

app.on('second-instance', () => {
    if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
    }
});

app.on('window-all-closed', () => {
    // Don't quit on macOS — keep running in tray
    if (process.platform !== 'darwin') {
        isQuitting = true;
        stopBackendServer();
        app.quit();
    }
});

app.on('before-quit', () => {
    isQuitting = true;
    if (backendRestartTimer) clearTimeout(backendRestartTimer);
    stopBackendServer();
    globalShortcut.unregisterAll();
});

app.on('activate', () => {
    // macOS: re-create window when dock icon clicked
    if (!mainWindow) {
        createMainWindow();
    } else {
        mainWindow.show();
        mainWindow.focus();
    }
});
