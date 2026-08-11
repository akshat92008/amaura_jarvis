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

let mainWindow = null;
let tray = null;
let serverProcess = null;
let isQuitting = false;
let backendRestartCount = 0;
let backendRestartTimer = null;
let backendBootstrapToken = null;
let backendVerified = false;
let backendGeneration = 0;

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
    if (!backendVerified || !CONFIG.serverPort) throw new Error('Authenticated backend is not ready');
    if (typeof requestPath !== 'string' || !requestPath.startsWith('/api/')) {
        throw new Error('Only local /api/ paths are permitted');
    }
    const normalizedMethod = String(method).toUpperCase();
    if (!['GET', 'POST', 'DELETE'].includes(normalizedMethod)) {
        throw new Error('Unsupported backend method');
    }
    const credentials = runtimeCredentials();
    const headers = { 'Content-Type': 'application/json' };
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
        if (!child.killed) child.kill('SIGKILL');
    }, 3000);
    killTimer.unref();
}

function verifyHealthPayload(payload, challenge) {
    if (!payload || payload.status !== 'online' || payload.version !== '5.4.0') return false;
    if (!serverProcess || Number(payload.pid) !== Number(serverProcess.pid)) return false;
    const expected = crypto.createHmac('sha256', backendBootstrapToken).update(challenge).digest('hex');
    const supplied = String(payload.bootstrap_proof || '');
    if (expected.length !== supplied.length) return false;
    return crypto.timingSafeEqual(Buffer.from(expected, 'hex'), Buffer.from(supplied, 'hex'));
}

function waitForServer(retries = 40, delay = 250) {
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

    ipcMain.handle('restart-backend', async () => {
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

app.whenReady().then(async () => {
    console.log('[JARVIS] Starting up...');

    // Setup IPC
    setupIPC();

    // Start the bundled/authenticated backend sidecar.
    try {
        await startBackendServer();
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