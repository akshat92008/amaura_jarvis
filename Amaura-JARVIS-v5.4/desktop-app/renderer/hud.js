'use strict';

const byId = (id) => document.getElementById(id);
const state = { sessionId: `desktop-${Date.now()}`, model: 'default', busy: false, goals: [], lastIntent: 'conversation', voiceActive: false };

async function request(path, method = 'GET', body = null) {
  if (!window.jarvis?.request) throw new Error('Secure desktop bridge unavailable');
  return window.jarvis.request({ path, method, body });
}

function setStatus(text, online = true) {
  byId('hud-status-text').textContent = text;
  const dot = byId('status-dot');
  dot.style.background = online ? '#75f0be' : '#ff7f8d';
  dot.style.boxShadow = online ? '0 0 12px #75f0be' : '0 0 12px #ff7f8d';
}

function splitList(value) {
  return String(value || '').split(';').map((v) => v.trim()).filter(Boolean);
}

function escapeText(value) { return String(value ?? ''); }

function addMessage(role, text) {
  const host = byId('chat-messages');
  const node = document.createElement('div');
  node.className = `message ${role}`;
  const title = document.createElement('strong');
  title.textContent = role === 'user' ? 'YOU' : 'AMAURA';
  const content = document.createElement('div');
  content.textContent = escapeText(text);
  node.append(title, content);
  host.appendChild(node);
  host.scrollTop = host.scrollHeight;
}

async function refreshHealth() {
  try {
    const health = await request('/api/health');
    setStatus(`ONLINE · v${health.version}`, true);
    byId('metric-tools').textContent = health.tools || 0;
    byId('boot-screen').classList.add('hidden');
    byId('app').classList.remove('hidden');
  } catch (error) {
    setStatus('BACKEND OFFLINE', false);
    byId('boot-status').textContent = error.message;
  }
}

async function sendMessage() {
  if (state.busy) return;
  const input = byId('chat-input');
  const message = input.value.trim();
  if (!message) return;
  state.busy = true; input.value = ''; input.disabled = true;
  addMessage('user', message); setStatus('THINKING', true);
  try {
    const result = await request('/api/chat', 'POST', {
      message,
      session_id: state.sessionId,
      model: state.model,
      workspace: byId('chat-workspace').value.trim(),
      autonomy: byId('chat-autonomy').value,
      coding_backend: byId('chat-backend').value,
    });
    state.lastIntent = result.intent || 'conversation';
    addMessage('assistant', result.response || 'No response');
    if (result.model_key) {
      state.model = result.model_key;
      const provider = result.model_provider ? `${result.model_provider} · ` : '';
      const fallback = result.model_fallback_used ? ' · FALLBACK' : '';
      byId('hud-model').textContent = `MODEL: ${provider}${result.model || state.model}${fallback}`;
    }
    if (result.intent === 'mission' || result.intent === 'mission_control') {
      addMessage('assistant', `Mission ${result.goal_id || ''} is ${result.state || 'accepted'}. I will keep its execution and evidence in Activity.`);
      await Promise.all([refreshGoals(), refreshApprovals(), refreshProactive()]);
    }
    setStatus('ONLINE', true);
  } catch (error) { addMessage('assistant', `Request failed: ${error.message}`); setStatus('ERROR', false); }
  finally { state.busy = false; input.disabled = false; input.focus(); }
}

async function toggleVoice() {
  const button = byId('btn-voice');
  button.disabled = true;
  try {
    if (!state.voiceActive) {
      const result = await request('/api/voice/session/start', 'POST', {
        session_id: state.sessionId,
        workspace: byId('chat-workspace').value.trim(),
        autonomy: byId('chat-autonomy').value,
        coding_backend: byId('chat-backend').value,
        wake_word: 'Hey JARVIS',
      });
      state.voiceActive = true;
      button.textContent = 'STOP VOICE';
      addMessage('assistant', result.detail || 'Voice session started.');
    } else {
      const result = await request('/api/voice/session/stop', 'POST', {});
      state.voiceActive = false;
      button.textContent = 'VOICE';
      addMessage('assistant', result.detail || 'Voice session stopped.');
    }
  } catch (error) {
    state.voiceActive = false;
    button.textContent = 'VOICE';
    addMessage('assistant', `Voice unavailable: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function launchGoal() {
  const objective = byId('goal-objective').value.trim();
  if (!objective) { byId('mission-feedback').textContent = 'Enter an objective first.'; return; }
  const button = byId('btn-launch-goal'); button.disabled = true;
  byId('mission-feedback').textContent = 'Compiling and queuing governed mission…'; setStatus('PLANNING', true);
  try {
    const result = await request('/api/amaura/jarvis/goals', 'POST', {
      objective,
      success_criteria: splitList(byId('goal-criteria').value),
      workspace: byId('goal-workspace').value.trim(),
      constraints: splitList(byId('goal-constraints').value),
      autonomy: byId('goal-autonomy').value,
      coding_backend: byId('goal-backend').value,
      priority: Number(byId('goal-priority').value),
      max_steps: 8,
      max_replans: 2,
      metadata: {},
    });
    const goalId = result.goal?.id || '';
    const execution = result.execution;
    byId('mission-feedback').textContent = result.state === 'planned' ? `Plan held: ${goalId}` : result.state === 'handoff_required' ? `Manual handoff required: ${goalId}` : `Mission queued for Antigravity: ${goalId}`;
    byId('goal-objective').value = '';
    await Promise.all([refreshGoals(), refreshApprovals()]);
  } catch (error) { byId('mission-feedback').textContent = `Mission failed to start: ${error.message}`; }
  finally { button.disabled = false; setStatus('ONLINE', true); }
}

function goalCard(goal) {
  const card = document.createElement('div'); card.className = 'card';
  const meta = goal.metadata || {};
  const head = document.createElement('div'); head.className = 'card-head';
  const left = document.createElement('div');
  const title = document.createElement('h4'); title.textContent = goal.title || goal.description || goal.id;
  const desc = document.createElement('p'); desc.textContent = goal.description || '';
  left.append(title, desc);
  const pill = document.createElement('span'); pill.className = `pill ${goal.state}`; pill.textContent = String(goal.state || 'unknown').toUpperCase();
  head.append(left, pill); card.append(head);
  const lifecycle = meta.mission_paused ? 'held' : meta.antigravity_handoff ? 'handoff' : meta.mission_runnable ? 'runnable' : 'planned';
  const detail = document.createElement('p'); detail.textContent = `ID ${goal.id} · ${meta.goal_plan?.domain || 'mission'} · ${lifecycle} · replans ${meta.replans_used || 0}/${meta.max_replans || 0}`; card.append(detail);
  const actions = document.createElement('div'); actions.className = 'card-actions';
  const inspect = document.createElement('button'); inspect.textContent = 'Inspect'; inspect.onclick = () => inspectGoal(goal.id);
  actions.append(inspect);
  if (goal.state === 'draft' && !meta.antigravity_handoff && !meta.mission_paused) {
    const activate = document.createElement('button'); activate.textContent = 'Activate'; activate.onclick = () => controlGoal(goal.id, 'activate'); actions.append(activate);
  } else if (meta.mission_paused) {
    const resume = document.createElement('button'); resume.textContent = 'Resume'; resume.onclick = () => controlGoal(goal.id, 'activate'); actions.append(resume);
  } else if (meta.mission_runnable && !['completed', 'cancelled'].includes(goal.state)) {
    const pause = document.createElement('button'); pause.textContent = 'Pause'; pause.onclick = () => controlGoal(goal.id, 'pause'); actions.append(pause);
  }
  if (!['completed', 'cancelled'].includes(goal.state)) {
    const cancel = document.createElement('button'); cancel.textContent = 'Cancel'; cancel.onclick = () => controlGoal(goal.id, 'cancel'); actions.append(cancel);
  }
  card.append(actions); return card;
}

async function refreshGoals() {
  try {
    const result = await request('/api/amaura/jarvis/goals'); state.goals = result.goals || [];
    byId('metric-goals').textContent = state.goals.length;
    const host = byId('goal-list'); host.textContent = '';
    if (!state.goals.length) { const empty = document.createElement('div'); empty.className = 'card'; empty.textContent = 'No missions yet.'; host.append(empty); }
    state.goals.slice(0, 30).forEach((goal) => host.append(goalCard(goal)));
  } catch (error) { byId('goal-list').textContent = `Unable to load goals: ${error.message}`; }
}

async function inspectGoal(goalId) {
  try {
    const result = await request(`/api/amaura/jarvis/goals/${encodeURIComponent(goalId)}`);
    showStatusPayload(result, `MISSION ${goalId}`);
  } catch (error) { showStatusPayload({ error: error.message }, 'MISSION ERROR'); }
}

async function controlGoal(goalId, action) {
  setStatus(action === 'activate' ? 'QUEUING' : action.toUpperCase(), true);
  try {
    const result = await request(`/api/amaura/jarvis/goals/${encodeURIComponent(goalId)}/${action}`, 'POST', { reason: `Founder desktop ${action}` });
    showStatusPayload(result, `MISSION ${String(result.state || action).toUpperCase()}`);
    await Promise.all([refreshGoals(), refreshApprovals(), refreshProactive()]);
  } catch (error) { showStatusPayload({ error: error.message }, 'MISSION ERROR'); }
  finally { setStatus('ONLINE', true); }
}

async function refreshMemory() {
  try {
    const result = await request('/api/amaura/jarvis/memory?scope=all');
    const host = byId('memory-list'); host.textContent = '';
    (result.memory || []).forEach((item) => {
      const card = document.createElement('div'); card.className = 'card';
      const head = document.createElement('div'); head.className = 'card-head';
      const title = document.createElement('h4'); title.textContent = `${item.namespace}:${item.key}`;
      const del = document.createElement('button'); del.textContent = 'Forget';
      del.onclick = async () => { await request('/api/amaura/jarvis/memory/forget', 'POST', { key: item.key, scope: item.namespace.endsWith('personal') ? 'personal' : 'project' }); await refreshMemory(); };
      head.append(title, del); card.append(head);
      const value = document.createElement('p'); value.textContent = typeof item.value === 'string' ? item.value : JSON.stringify(item.value); card.append(value); host.append(card);
    });
    if (!(result.memory || []).length) host.textContent = 'No JARVIS memory stored yet.';
  } catch (error) { byId('memory-list').textContent = `Unable to load memory: ${error.message}`; }
}

async function saveMemory() {
  const key = byId('memory-key').value.trim(); const value = byId('memory-value').value.trim();
  if (!key || !value) return;
  await request('/api/amaura/jarvis/memory', 'POST', { key, value, scope: byId('memory-scope').value, sensitivity: 'internal' });
  byId('memory-key').value = ''; byId('memory-value').value = ''; await refreshMemory();
}

async function refreshProactive() {
  const host = byId('proactive-list');
  try {
    const result = await request('/api/amaura/jarvis/proactive');
    const items = result.insights || result.proactive || [];
    host.textContent = '';
    if (!items.length) { host.textContent = 'No urgent insight.'; return; }
    items.slice(0, 4).forEach((item) => {
      const line = document.createElement('p');
      line.textContent = `${String(item.severity || 'info').toUpperCase()}: ${item.message || item.code || 'Operational insight'}`;
      host.appendChild(line);
    });
  } catch (error) { host.textContent = `Insight unavailable: ${error.message}`; }
}

function simpleCard(titleText, bodyText, pillText = '') {
  const card = document.createElement('div'); card.className = 'card';
  const head = document.createElement('div'); head.className = 'card-head';
  const title = document.createElement('h4'); title.textContent = titleText;
  head.append(title);
  if (pillText) { const pill = document.createElement('span'); pill.className = 'pill'; pill.textContent = pillText; head.append(pill); }
  const body = document.createElement('p'); body.textContent = bodyText;
  card.append(head, body); return card;
}

function cashflowActionCard(action) {
  const card = simpleCard(action.title || action.action_type, `${action.action_type} · stream ${action.stream_id || 'portfolio'}`, String(action.status || 'proposed').toUpperCase());
  const actions = document.createElement('div'); actions.className = 'card-actions';
  if (action.requires_founder_approval && action.status === 'proposed') {
    const approve = document.createElement('button'); approve.textContent = 'Approve';
    approve.onclick = async () => {
      const reason = window.prompt('Approval reason:') || ''; if (!reason.trim()) return;
      await request('/api/amaura/ventures/cashflow/founder/actions', 'POST', { action_id: action.id, status: 'approved', reason, result: {} });
      await refreshVentures();
    };
    const cancel = document.createElement('button'); cancel.textContent = 'Cancel';
    cancel.onclick = async () => {
      const reason = window.prompt('Cancellation reason:') || ''; if (!reason.trim()) return;
      await request('/api/amaura/ventures/cashflow/founder/actions', 'POST', { action_id: action.id, status: 'cancelled', reason, result: {} });
      await refreshVentures();
    };
    actions.append(approve, cancel);
  }
  if (actions.children.length) card.append(actions);
  return card;
}

async function refreshVentures() {
  const summaryHost = byId('ventures-summary'); const actionHost = byId('ventures-actions'); const oppHost = byId('ventures-opportunities');
  try {
    const result = await request('/api/amaura/ventures/cashflow');
    const portfolio = result.portfolio || {}; const streams = portfolio.streams || []; const totals = portfolio.totals_by_currency || {};
    byId('metric-ventures').textContent = portfolio.live_streams || 0;
    summaryHost.textContent = '';
    summaryHost.append(simpleCard('Portfolio', `${streams.length} stream(s) · ${portfolio.live_streams || 0} live · ${portfolio.founder_minutes_per_week || 0} founder min/week`));
    Object.entries(totals).forEach(([currency, values]) => summaryHost.append(simpleCard(`${currency} economics`, `Gross ${(values.gross_revenue_cents || 0) / 100} · Net ${(values.net_cashflow_cents || 0) / 100} · Costs ${(values.costs_cents || 0) / 100}`)));
    streams.slice(0, 12).forEach((stream) => summaryHost.append(simpleCard(stream.name, `${stream.lane} · ${stream.platform} · price ${(stream.price_cents || 0) / 100} ${stream.currency} · ${stream.founder_minutes_per_week || 0} min/week`, String(stream.status || '').toUpperCase())));

    actionHost.textContent = '';
    (result.action_queue || []).slice(0, 20).forEach((action) => actionHost.append(cashflowActionCard(action)));
    if (!(result.action_queue || []).length) actionHost.append(simpleCard('No queued actions', 'Run the cash-flow cycle to generate evidence-backed next actions.'));

    oppHost.textContent = '';
    (portfolio.ranked_opportunities || []).slice(0, 10).forEach((opp) => oppHost.append(simpleCard(opp.title || opp.opportunity_id, `${opp.lane} · cash-flow score ${opp.cashflow_score} · venture score ${opp.venture_score} · ${opp.estimated_build_days} day build`, 'RANKED')));
    if (!(portfolio.ranked_opportunities || []).length) oppHost.append(simpleCard('No qualified opportunities', 'JARVIS will populate this after evidence-backed venture discovery.'));
  } catch (error) {
    summaryHost.textContent = `Unable to load Ventures: ${error.message}`; actionHost.textContent = ''; oppHost.textContent = '';
  }
}

async function runVenturesTick() {
  const button = byId('btn-ventures-tick'); button.disabled = true; setStatus('VENTURES', true);
  try { await request('/api/amaura/ventures/cashflow/tick', 'POST', {}); await refreshVentures(); }
  catch (error) { showStatusPayload({ error: error.message }, 'VENTURES ERROR'); }
  finally { button.disabled = false; setStatus('ONLINE', true); }
}

async function refreshCompany() {
  try {
    const [status, dashboard, agents] = await Promise.all([
      request('/api/amaura/company/status'), request('/api/amaura/dashboard'), request('/api/amaura/agents')
    ]);
    byId('metric-agents').textContent = agents.agents?.length || 0;
    byId('company-output').textContent = JSON.stringify({ status, dashboard }, null, 2);
  } catch (error) { byId('company-output').textContent = error.message; }
}

function approvalCard(approval) {
  const card = document.createElement('div'); card.className = 'card';
  const head = document.createElement('div'); head.className = 'card-head';
  const title = document.createElement('h4'); title.textContent = approval.payload?.title || approval.action_type || approval.id;
  const pill = document.createElement('span'); pill.className = 'pill awaiting_approval'; pill.textContent = String(approval.risk || 'approval').toUpperCase();
  head.append(title, pill); card.append(head);
  const body = document.createElement('p'); body.textContent = approval.payload?.summary || `Task ${approval.task_id}`; card.append(body);
  const actions = document.createElement('div'); actions.className = 'card-actions';
  const yes = document.createElement('button'); yes.textContent = 'Approve'; yes.onclick = () => decideApproval(approval.id, 'approved');
  const no = document.createElement('button'); no.textContent = 'Reject'; no.onclick = () => decideApproval(approval.id, 'rejected');
  actions.append(yes, no); card.append(actions); return card;
}

async function refreshApprovals() {
  try {
    const result = await request('/api/amaura/approvals'); const approvals = result.approvals || [];
    byId('metric-approvals').textContent = approvals.length; const host = byId('approval-list'); host.textContent = '';
    approvals.forEach((item) => host.append(approvalCard(item)));
    if (!approvals.length) host.textContent = 'No founder approvals pending.';
  } catch (error) { byId('approval-list').textContent = `Unable to load approvals: ${error.message}`; }
}

async function decideApproval(id, decision) {
  const reason = window.prompt(`${decision === 'approved' ? 'Approval' : 'Rejection'} reason:`) || '';
  if (!reason.trim()) return;
  try { await request(`/api/amaura/approvals/${encodeURIComponent(id)}`, 'POST', { decision, reason }); await Promise.all([refreshApprovals(), refreshGoals()]); }
  catch (error) { showStatusPayload({ error: error.message }, 'APPROVAL ERROR'); }
}

function showStatusPayload(payload, title = 'SYSTEM STATUS') {
  byId('modal-status').classList.remove('hidden');
  byId('status-content').textContent = `${title}\n\n${JSON.stringify(payload, null, 2)}`;
}

async function showStatus() {
  try {
    const [health, supervisor, runner, engineering, runtime, capabilities] = await Promise.all([
      request('/api/health'), request('/api/amaura/supervisor/status'),
      request('/api/amaura/jarvis/runner'), request('/api/amaura/jarvis/engineering'),
      request('/api/amaura/runtime/status'), request('/api/amaura/capabilities/status')
    ]);
    showStatusPayload({ health, runtime, supervisor, runner, engineering, capabilities });
  } catch (error) { showStatusPayload({ error: error.message }); }
}

function switchView(name) {
  document.querySelectorAll('.nav[data-view]').forEach((button) => button.classList.toggle('active', button.dataset.view === name));
  document.querySelectorAll('.view').forEach((view) => view.classList.remove('active'));
  byId(`view-${name}`).classList.add('active');
  if (name === 'mission') { refreshGoals(); refreshProactive(); }
  if (name === 'memory') refreshMemory();
  if (name === 'company') refreshCompany();
  if (name === 'ventures') refreshVentures();
  if (name === 'approvals') refreshApprovals();
}

function bind() {
  document.querySelectorAll('.nav[data-view]').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
  byId('btn-send').addEventListener('click', sendMessage);
  byId('btn-voice').addEventListener('click', toggleVoice);
  byId('chat-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(); });
  byId('btn-launch-goal').addEventListener('click', launchGoal);
  byId('btn-refresh-goals').addEventListener('click', refreshGoals);
  byId('btn-memory-save').addEventListener('click', saveMemory);
  byId('btn-refresh-company').addEventListener('click', refreshCompany);
  byId('btn-refresh-ventures').addEventListener('click', refreshVentures);
  byId('btn-ventures-tick').addEventListener('click', runVenturesTick);
  byId('btn-refresh-approvals').addEventListener('click', refreshApprovals);
  byId('btn-status').addEventListener('click', showStatus);
  byId('btn-close-status').addEventListener('click', () => byId('modal-status').classList.add('hidden'));
  byId('btn-clear').addEventListener('click', () => byId('chat-messages').textContent = '');
  byId('btn-hide').addEventListener('click', () => window.jarvis.hideWindow());
  byId('btn-minimize').addEventListener('click', () => window.jarvis.minimizeWindow());
  window.jarvis?.onBackendReady(() => { refreshHealth(); refreshGoals(); refreshApprovals(); refreshProactive(); });
  window.jarvis?.onBackendError((message) => setStatus(`ERROR: ${message}`, false));
  window.jarvis?.onShowStatus(showStatus);
  window.jarvis?.onStartVoice(toggleVoice);
  window.jarvis?.onToggleVoice((enabled) => { if (Boolean(enabled) !== state.voiceActive) toggleVoice(); });
  setInterval(() => { byId('hud-time').textContent = new Date().toLocaleTimeString(); }, 1000);
  setInterval(() => { if (!document.hidden) Promise.all([refreshGoals(), refreshApprovals(), refreshProactive()]); }, 5000);
  refreshHealth(); refreshGoals(); refreshApprovals(); refreshCompany(); refreshVentures(); refreshProactive();
}

document.addEventListener('DOMContentLoaded', bind);
