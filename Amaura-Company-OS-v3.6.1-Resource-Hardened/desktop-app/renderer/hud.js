'use strict';

const byId = (id) => document.getElementById(id);
const state = { sessionId: `desktop-${Date.now()}`, model: 'default', busy: false };

function setStatus(text, online = true) {
    const label = byId('hud-status-text');
    const dot = byId('status-dot');
    if (label) label.textContent = text;
    if (dot) dot.dataset.online = online ? 'true' : 'false';
}

function addMessage(role, text) {
    const host = byId('chat-messages');
    if (!host) return;
    const node = document.createElement('div');
    node.className = `message ${role}`;
    const title = document.createElement('strong');
    title.textContent = role === 'user' ? 'AKSHAT' : 'AMAURA';
    const content = document.createElement('div');
    content.textContent = String(text || '');
    node.append(title, content);
    host.appendChild(node);
    host.scrollTop = host.scrollHeight;
}

async function request(path, method = 'GET', body = null) {
    if (!window.jarvis?.request) throw new Error('Secure desktop bridge unavailable');
    return window.jarvis.request({ path, method, body });
}

async function refreshHealth() {
    try {
        const health = await request('/api/health');
        setStatus(`ONLINE · v${health.version}`, true);
        if (byId('tools-count')) byId('tools-count').textContent = `${health.tools || 0} tools loaded`;
        if (byId('hud-session-count')) byId('hud-session-count').textContent = String(health.sessions || 0);
        const boot = byId('boot-screen');
        const main = byId('hud-main');
        if (boot) boot.style.display = 'none';
        if (main) main.style.display = 'block';
    } catch (error) {
        setStatus('BACKEND OFFLINE', false);
        const bootStatus = byId('boot-status');
        if (bootStatus) bootStatus.textContent = error.message;
    }
}

async function sendMessage(prefill = null) {
    if (state.busy) return;
    const input = byId('chat-input');
    const message = String(prefill ?? input?.value ?? '').trim();
    if (!message) return;
    state.busy = true;
    if (input) { input.value = ''; input.disabled = true; }
    addMessage('user', message);
    setStatus('THINKING', true);
    try {
        const result = await request('/api/chat', 'POST', {
            message,
            session_id: state.sessionId,
            model: state.model,
        });
        addMessage('assistant', result.response || 'No response');
        if (result.model) state.model = result.model;
        if (byId('hud-model')) byId('hud-model').textContent = state.model;
        setStatus('ONLINE', true);
    } catch (error) {
        addMessage('assistant', `Request failed: ${error.message}`);
        setStatus('ERROR', false);
    } finally {
        state.busy = false;
        if (input) { input.disabled = false; input.focus(); }
    }
}

async function showStatus() {
    const modal = byId('modal-status');
    const content = byId('status-content');
    if (modal) modal.style.display = 'flex';
    if (content) content.textContent = 'Loading…';
    try {
        const [health, company] = await Promise.all([
            request('/api/health'),
            request('/api/amaura/company/status').catch((error) => ({ error: error.message })),
        ]);
        if (content) content.textContent = JSON.stringify({ health, company }, null, 2);
    } catch (error) {
        if (content) content.textContent = error.message;
    }
}

function bind() {
    byId('btn-send')?.addEventListener('click', () => sendMessage());
    byId('chat-input')?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); }
    });
    byId('btn-hide')?.addEventListener('click', () => window.jarvis.hideWindow());
    byId('btn-minimize')?.addEventListener('click', () => window.jarvis.minimizeWindow());
    byId('btn-status')?.addEventListener('click', showStatus);
    byId('btn-close-status')?.addEventListener('click', () => { byId('modal-status').style.display = 'none'; });
    byId('btn-clear')?.addEventListener('click', () => { if (byId('chat-messages')) byId('chat-messages').textContent = ''; });
    document.querySelectorAll('.quick-cmd').forEach((button) => button.addEventListener('click', () => sendMessage(button.dataset.cmd)));
    window.jarvis?.onBackendReady(refreshHealth);
    window.jarvis?.onBackendError((message) => { setStatus(`ERROR: ${message}`, false); });
    window.jarvis?.onShowStatus(showStatus);
    setInterval(() => {
        const time = byId('hud-time');
        if (time) time.textContent = new Date().toLocaleTimeString();
    }, 1000);
    refreshHealth();
}

document.addEventListener('DOMContentLoaded', bind);
