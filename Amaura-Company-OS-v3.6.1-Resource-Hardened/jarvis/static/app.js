/**
 * J.A.R.V.I.S. Command & Voice Web HUD (v2.5)
 * Full Voice Control (STT/TTS), Typed Command Matrix, WebSocket Streaming,
 * Real-Time System Diagnostics, Model Selector, & Capability Matrix.
 */

document.addEventListener("DOMContentLoaded", () => {
    // ── DOM ELEMENTS ────────────────────────────────────────────────────────
    const statusPill = document.getElementById("status-pill");
    const statusText = document.getElementById("status-text");
    const systemClock = document.getElementById("system-clock");
    const audioWaves = document.getElementById("audio-waves");
    const modelSelect = document.getElementById("model-select");
    const ttsToggleBtn = document.getElementById("tts-toggle-btn");
    const sidebarToggleBtn = document.getElementById("sidebar-toggle-btn");
    const hudSidebar = document.getElementById("hud-sidebar");
    
    // Sidebar Tabs & Content
    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabPanes = document.querySelectorAll(".tab-pane");
    const cpuVal = document.getElementById("cpu-val");
    const cpuBar = document.getElementById("cpu-bar");
    const ramVal = document.getElementById("ram-val");
    const ramBar = document.getElementById("ram-bar");
    const diskVal = document.getElementById("disk-val");
    const diskBar = document.getElementById("disk-bar");
    const sysOs = document.getElementById("sys-os");
    const sysUptime = document.getElementById("sys-uptime");
    const sysToolsCount = document.getElementById("sys-tools-count");
    const sysWsStatus = document.getElementById("sys-ws-status");
    const refreshSysBtn = document.getElementById("refresh-sys-btn");
    const amauraProgrammes = document.getElementById("amaura-programmes");
    const amauraAgents = document.getElementById("amaura-agents");
    const amauraApprovals = document.getElementById("amaura-approvals");
    const amauraCost = document.getElementById("amaura-cost");
    const amauraViolations = document.getElementById("amaura-violations");
    const amauraTaskStates = document.getElementById("amaura-task-states");
    const amauraApprovalList = document.getElementById("amaura-approval-list");
    const refreshAmauraBtn = document.getElementById("refresh-amaura-btn");

    const toolSearch = document.getElementById("tool-search");
    const toolsList = document.getElementById("tools-list");

    const memoryInput = document.getElementById("memory-input");
    const addMemoryBtn = document.getElementById("add-memory-btn");
    const memoryList = document.getElementById("memory-list");
    const clearMemoryBtn = document.getElementById("clear-memory-btn");

    const voiceSelect = document.getElementById("voice-select");
    const voiceRate = document.getElementById("voice-rate");
    const rateVal = document.getElementById("rate-val");
    const voicePitch = document.getElementById("voice-pitch");
    const pitchVal = document.getElementById("pitch-val");
    const autoSpeakChk = document.getElementById("auto-speak-chk");
    const continuousSttChk = document.getElementById("continuous-stt-chk");
    const testVoiceBtn = document.getElementById("test-voice-btn");

    // Chat Stage & Dock
    const chatMessages = document.getElementById("chat-messages");
    const transcriptOverlay = document.getElementById("transcript-overlay");
    const transcriptText = document.getElementById("transcript-text");
    const autocompletePopup = document.getElementById("autocomplete-popup");
    const chatInput = document.getElementById("chat-input");
    const micBtn = document.getElementById("mic-btn");
    const micIcon = document.getElementById("mic-icon");
    const stopSpeechBtn = document.getElementById("stop-speech-btn");
    const clearChatBtn = document.getElementById("clear-chat-btn");
    const sendBtn = document.getElementById("send-btn");
    const chipBtns = document.querySelectorAll(".chip-btn");

    // ── STATE VARIABLES ─────────────────────────────────────────────────────
    let socket = null;
    let recognition = null;
    let isListening = false;
    let ttsEnabled = true;
    let commandHistory = [];
    let historyIdx = -1;
    let availableVoices = [];
    let toolsData = [];
    let systemPollInterval = null;
    let webSocketRetryCount = 0;

    // Available Slash Commands definition
    const SLASH_COMMANDS = [
        { cmd: "/help", desc: "Show command matrix help" },
        { cmd: "/status", desc: "Show system diagnostics" },
        { cmd: "/company", desc: "Show Amaura company status" },
        { cmd: "/briefing", desc: "Generate founder briefing" },
        { cmd: "/approvals", desc: "Show pending founder approvals" },
        { cmd: "/tools", desc: "List all 61+ available tools" },
        { cmd: "/models", desc: "List supported AI models" },
        { cmd: "/model", desc: "Switch active model (e.g. /model kimi)" },
        { cmd: "/memory", desc: "View personal remembered facts" },
        { cmd: "/remember", desc: "Teach Jarvis a fact (e.g. /remember I like Python)" },
        { cmd: "/voice", desc: "Toggle voice mode" },
        { cmd: "/clear", desc: "Clear current conversation log" },
    ];

    // ── INITIALIZATION ──────────────────────────────────────────────────────
    function init() {
        startClock();
        connectWebSocket();
        setupSpeechRecognition();
        setupSpeechSynthesis();
        setupEventListeners();
        fetchSystemMetrics();
        fetchToolsList();
        fetchMemoryList();
        fetchAmauraDashboard();

        // System polling every 4 seconds
        systemPollInterval = setInterval(fetchSystemMetrics, 4000);
        setInterval(fetchAmauraDashboard, 12000);
    }

    // ── CLOCK ───────────────────────────────────────────────────────────────
    function startClock() {
        const update = () => {
            const now = new Date();
            systemClock.textContent = now.toTimeString().split(" ")[0];
        };
        update();
        setInterval(update, 1000);
    }

    // ── LOCAL AUTHENTICATION ───────────────────────────────────────────────
    let jarvisApiKey = sessionStorage.getItem("jarvisApiKey") || "";
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    if (fragment.get("api_key")) {
        jarvisApiKey = fragment.get("api_key").trim();
        sessionStorage.setItem("jarvisApiKey", jarvisApiKey);
        history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    }

    function requireApiKey() {
        if (!jarvisApiKey) {
            jarvisApiKey = (window.prompt("Enter the JARVIS_API_KEY from .env.amaura") || "").trim();
            if (jarvisApiKey) sessionStorage.setItem("jarvisApiKey", jarvisApiKey);
        }
        return jarvisApiKey;
    }

    function jarvisHeaders(extra = {}) {
        const key = requireApiKey();
        return key ? { ...extra, "X-Jarvis-Key": key } : { ...extra };
    }

    function websocketProtocols() {
        const key = requireApiKey();
        if (!key) return ["jarvis"];
        const bytes = new TextEncoder().encode(key);
        let binary = "";
        bytes.forEach((value) => { binary += String.fromCharCode(value); });
        const encoded = btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
        return ["jarvis", `jarvis-key.${encoded}`];
    }

    // ── WEBSOCKET CONNECTION ────────────────────────────────────────────────
    function connectWebSocket() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

        socket = new WebSocket(wsUrl, websocketProtocols());

        socket.onopen = () => {
            console.log("JARVIS WebSocket connected.");
            webSocketRetryCount = 0;
            sysWsStatus.textContent = "Connected";
            sysWsStatus.className = "text-success";
            setStatus("online", "ONLINE");
        };

        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleServerMessage(data);
            } catch (err) {
                console.error("Error parsing WebSocket message:", err);
            }
        };

        socket.onerror = (err) => {
            console.error("WebSocket error:", err);
            sysWsStatus.textContent = "Error";
            sysWsStatus.className = "text-danger";
        };

        socket.onclose = () => {
            webSocketRetryCount += 1;
            if (webSocketRetryCount <= 3) {
                console.warn("WebSocket closed. Attempting reconnect in 3s...");
                sysWsStatus.textContent = "Reconnecting";
                sysWsStatus.className = "text-muted";
                setStatus("offline", "RECONNECTING");
                setTimeout(connectWebSocket, 3000);
            } else {
                console.warn("WebSocket unavailable. Continuing through the REST fallback.");
                sysWsStatus.textContent = "REST fallback";
                sysWsStatus.className = "text-success";
                setStatus("online", "REST MODE");
            }
        };
    }

    // ── SERVER MESSAGE HANDLER ──────────────────────────────────────────────
    function handleServerMessage(data) {
        switch (data.type) {
            case "system":
                addMessage(data.content, "system");
                if (data.model) {
                    selectModelByValue(data.model);
                }
                break;

            case "user_echo":
            case "voice_echo":
                // Message already displayed locally
                break;

            case "agent_event":
                // Live tool execution feedback
                const evt = data.event;
                if (evt.type === "tool_start") {
                    addToolEventBadge(evt.name, evt.args, false);
                    setStatus("thinking", `EXECUTING: ${evt.name}`);
                } else if (evt.type === "tool_end") {
                    updateToolEventBadge(evt.name, true);
                    setStatus("thinking", "PROCESSING...");
                }
                break;

            case "response":
                setStatus("online", "ONLINE");
                addMessage(data.content, "ai");
                if (ttsEnabled && autoSpeakChk.checked && data.content) {
                    speakText(data.content);
                }
                break;

            case "error":
                setStatus("online", "ONLINE");
                addMessage(`ERROR: ${data.content}`, "system");
                break;

            case "help":
                addMessage(`**JARVIS Command Matrix:**\n` + data.commands.map(c => `- \`${c.cmd}\`: ${c.desc}`).join("\n"), "system");
                break;

            case "models":
                const modelList = data.models.map(m => `- **${m.name}** (\`${m.key}\`): ${m.desc}`).join("\n");
                addMessage(`**Available AI Models:**\n${modelList}`, "system");
                break;

            case "memory":
                addMessage(`**Personal Memory Summary:**\n${data.content || "No facts remembered yet."}`, "system");
                fetchMemoryList();
                break;

            case "tools_list":
                addMessage(`**Capable Tools Loaded (${data.count}):**\n` + data.tools.map(t => `- \`${t.name}\`: ${t.desc}`).join("\n"), "system");
                break;

            default:
                if (data.content) {
                    addMessage(data.content, "system");
                }
                break;
        }
    }

    // ── SPEECH RECOGNITION (STT) ────────────────────────────────────────────
    function setupSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.warn("Web Speech Recognition API not supported in this browser.");
            micBtn.title = "Voice recognition not supported in this browser";
            return;
        }

        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = "en-US";

        recognition.onstart = () => {
            isListening = true;
            micBtn.classList.add("listening");
            transcriptOverlay.classList.remove("hidden");
            transcriptText.textContent = "Listening...";
            audioWaves.classList.add("active");
            setStatus("listening", "LISTENING...");
        };

        recognition.onresult = (event) => {
            let interim = "";
            let final = "";

            for (let i = event.resultIndex; i < event.results.length; i++) {
                const trans = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    final += trans;
                } else {
                    interim += trans;
                }
            }

            const current = final || interim;
            if (current) {
                transcriptText.textContent = `"${current}"`;
                chatInput.value = current;
            }

            if (final) {
                stopListening();
                sendUserMessage(final);
                if (continuousSttChk.checked) {
                    setTimeout(() => startListening(), 1000);
                }
            }
        };

        recognition.onerror = (event) => {
            console.error("Speech recognition error:", event.error);
            stopListening();
            if (event.error !== "no-speech") {
                addMessage(`Voice recognition error: ${event.error}`, "system");
            }
        };

        recognition.onend = () => {
            stopListening();
        };
    }

    function startListening() {
        if (!recognition) return;
        if (window.speechSynthesis && window.speechSynthesis.speaking) {
            window.speechSynthesis.cancel();
        }
        try {
            recognition.start();
        } catch (e) {
            console.log("STT already active");
        }
    }

    function stopListening() {
        isListening = false;
        micBtn.classList.remove("listening");
        transcriptOverlay.classList.add("hidden");
        audioWaves.classList.remove("active");
        if (recognition) recognition.stop();
        if (statusText.textContent === "LISTENING...") {
            setStatus("online", "ONLINE");
        }
    }

    // ── SPEECH SYNTHESIS (TTS) ──────────────────────────────────────────────
    function setupSpeechSynthesis() {
        if (!("speechSynthesis" in window)) {
            console.warn("Speech Synthesis API not available.");
            return;
        }

        const loadVoices = () => {
            availableVoices = window.speechSynthesis.getVoices();
            voiceSelect.innerHTML = "";

            if (availableVoices.length === 0) return;

            // Preferred voices: Jarvis, Daniel, Alex, Google UK English Male, Samantha
            availableVoices.forEach((voice, index) => {
                const option = document.createElement("option");
                option.value = index;
                option.textContent = `${voice.name} (${voice.lang})`;
                if (voice.name.includes("Daniel") || voice.name.includes("Jarvis") || voice.name.includes("UK English Male") || voice.name.includes("Oliver")) {
                    option.selected = true;
                }
                voiceSelect.appendChild(option);
            });
        };

        loadVoices();
        if (speechSynthesis.onvoiceschanged !== undefined) {
            speechSynthesis.onvoiceschanged = loadVoices;
        }
    }

    function speakText(text) {
        if (!ttsEnabled || !("speechSynthesis" in window)) return;

        window.speechSynthesis.cancel(); // Stop current

        // Strip Markdown tags for speech
        const cleanText = text
            .replace(/```[\s\S]*?```/g, "Code block omitted.")
            .replace(/`([^`]+)`/g, "$1")
            .replace(/[*_#~]/g, "")
            .trim();

        if (!cleanText) return;

        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.rate = parseFloat(voiceRate.value) || 1.0;
        utterance.pitch = parseFloat(voicePitch.value) || 1.0;

        const selectedIndex = voiceSelect.value;
        if (availableVoices[selectedIndex]) {
            utterance.voice = availableVoices[selectedIndex];
        }

        utterance.onstart = () => {
            stopSpeechBtn.classList.remove("hidden");
            audioWaves.classList.add("active");
            setStatus("speaking", "SPEAKING...");
        };

        utterance.onend = () => {
            stopSpeechBtn.classList.add("hidden");
            audioWaves.classList.remove("active");
            setStatus("online", "ONLINE");
        };

        utterance.onerror = (e) => {
            console.error("SpeechSynthesis error:", e);
            stopSpeechBtn.classList.add("hidden");
            audioWaves.classList.remove("active");
            setStatus("online", "ONLINE");
        };

        window.speechSynthesis.speak(utterance);
    }

    // ── SEND USER MESSAGE ───────────────────────────────────────────────────
    function sendUserMessage(textOverride) {
        const text = textOverride || chatInput.value.trim();
        if (!text) return;

        // Add to input history
        if (!commandHistory.includes(text)) {
            commandHistory.push(text);
        }
        historyIdx = commandHistory.length;

        // Display user msg
        addMessage(text, "user");

        chatInput.value = "";
        closeAutocomplete();

        // Check if slash command
        if (text.startsWith("/")) {
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: "command", content: text }));
            } else {
                handleLocalCommandFallback(text);
            }
            return;
        }

        // Send over WebSocket or REST
        if (socket && socket.readyState === WebSocket.OPEN) {
            setStatus("thinking", "THINKING...");
            socket.send(JSON.stringify({ type: "chat", content: text }));
        } else {
            sendRestChat(text);
        }
    }

    async function sendRestChat(text) {
        setStatus("thinking", "THINKING...");
        try {
            const res = await fetch("/api/chat", {
                method: "POST",
                headers: jarvisHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify({ message: text, model: modelSelect.value }),
            });
            const data = await res.json();
            setStatus("online", "ONLINE");
            addMessage(data.response, "ai");
            if (ttsEnabled && autoSpeakChk.checked) {
                speakText(data.response);
            }
        } catch (err) {
            console.error(err);
            setStatus("online", "ONLINE");
            addMessage("ERROR: Unable to connect to JARVIS server.", "system");
        }
    }

    function handleLocalCommandFallback(cmd) {
        if (cmd === "/clear") {
            chatMessages.innerHTML = "";
            addMessage("Workspace cleared, sir.", "system");
        } else if (cmd === "/help") {
            addMessage("Commands: /help, /status, /tools, /models, /remember <fact>, /clear", "system");
        } else {
            addMessage(`Command '${cmd}' sent.`, "system");
        }
    }

    // ── SAFE RENDERING HELPERS ───────────────────────────────────────────────
    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function renderSafeMarkdown(value) {
        // Escape first, then add a deliberately tiny Markdown subset. No raw HTML.
        let safe = escapeHtml(value);
        const codeBlocks = [];
        safe = safe.replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g, (_m, language, code) => {
            const index = codeBlocks.length;
            codeBlocks.push(`<pre><code class="language-${escapeHtml(language)}">${code}</code></pre>`);
            return `@@AMAURA_CODE_${index}@@`;
        });
        safe = safe
            .replace(/^###\s+(.+)$/gm, "<h3>$1</h3>")
            .replace(/^##\s+(.+)$/gm, "<h2>$1</h2>")
            .replace(/^#\s+(.+)$/gm, "<h1>$1</h1>")
            .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/`([^`]+)`/g, "<code>$1</code>")
            .replace(/\n/g, "<br>");
        codeBlocks.forEach((block, index) => { safe = safe.replace(`@@AMAURA_CODE_${index}@@`, block); });
        return safe;
    }

    function amauraOperatorHeaders() {
        let key = sessionStorage.getItem("amaura_operator_key") || "";
        if (!key) {
            key = window.prompt("Enter AMAURA_OPERATOR_KEY to access company data:") || "";
            if (key) sessionStorage.setItem("amaura_operator_key", key);
        }
        return key ? {"X-Amaura-Operator-Key": key} : {};
    }

    // ── MESSAGE DISPLAY HELPERS ──────────────────────────────────────────────
    function addMessage(content, type) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `msg ${type}-msg`;

        const iconDiv = document.createElement("div");
        iconDiv.className = "msg-icon";

        if (type === "user") iconDiv.innerHTML = `<i class="fa-solid fa-user"></i>`;
        else if (type === "ai") iconDiv.innerHTML = `<i class="fa-solid fa-brain"></i>`;
        else iconDiv.innerHTML = `<i class="fa-solid fa-shield-halved"></i>`;

        const bubbleDiv = document.createElement("div");
        bubbleDiv.className = "msg-bubble";

        if (type === "ai") {
            bubbleDiv.innerHTML = renderSafeMarkdown(content);
            bubbleDiv.querySelectorAll("pre code").forEach((block) => {
                // Add copy button
                const pre = block.parentElement;
                const copyBtn = document.createElement("button");
                copyBtn.className = "copy-code-btn";
                copyBtn.innerHTML = `<i class="fa-solid fa-copy"></i> Copy`;
                copyBtn.onclick = () => {
                    navigator.clipboard.writeText(block.textContent);
                    copyBtn.innerHTML = `<i class="fa-solid fa-check"></i> Copied!`;
                    setTimeout(() => { copyBtn.innerHTML = `<i class="fa-solid fa-copy"></i> Copy`; }, 2000);
                };
                pre.appendChild(copyBtn);
            });
        } else {
            bubbleDiv.textContent = content;
        }

        msgDiv.appendChild(iconDiv);
        msgDiv.appendChild(bubbleDiv);
        chatMessages.appendChild(msgDiv);

        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function addToolEventBadge(toolName, args, completed = false) {
        const badge = document.createElement("div");
        badge.className = `tool-event-badge ${completed ? "completed" : ""}`;
        badge.dataset.tool = toolName;
        badge.innerHTML = `
            <i class="fa-solid ${completed ? 'fa-circle-check' : 'fa-gear fa-spin'}"></i>
            <span>${completed ? 'Tool Completed:' : 'Executing Tool:'} <strong>${escapeHtml(toolName)}</strong></span>
        `;
        chatMessages.appendChild(badge);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function updateToolEventBadge(toolName) {
        const badges = chatMessages.querySelectorAll(`.tool-event-badge[data-tool="${toolName}"]`);
        if (badges.length > 0) {
            const lastBadge = badges[badges.length - 1];
            lastBadge.classList.add("completed");
            lastBadge.querySelector("i").className = "fa-solid fa-circle-check";
            lastBadge.querySelector("span").innerHTML = `Tool Completed: <strong>${escapeHtml(toolName)}</strong>`;
        }
    }

    // ── STATUS HELPERS ──────────────────────────────────────────────────────
    function setStatus(type, label) {
        statusPill.className = `status-pill ${type}`;
        statusText.textContent = label;
    }

    function selectModelByValue(modelName) {
        for (let i = 0; i < modelSelect.options.length; i++) {
            if (modelSelect.options[i].value === modelName || modelSelect.options[i].text.includes(modelName)) {
                modelSelect.selectedIndex = i;
                break;
            }
        }
    }

    // ── SYSTEM METRICS FETCH ────────────────────────────────────────────────
    async function fetchSystemMetrics() {
        try {
            const res = await fetch("/api/system", { headers: jarvisHeaders() });
            if (!res.ok) return;
            const data = await res.json();
            const info = data.info || {};

            if (info.cpu) {
                cpuVal.textContent = `${info.cpu.percent}%`;
                cpuBar.style.width = `${info.cpu.percent}%`;
            }
            if (info.memory) {
                ramVal.textContent = `${info.memory.percent}%`;
                ramBar.style.width = `${info.memory.percent}%`;
            }
            if (info.disk) {
                diskVal.textContent = `${info.disk.percent}%`;
                diskBar.style.width = `${info.disk.percent}%`;
            }
            if (info.os) {
                sysOs.textContent = `${info.os.system} ${info.os.release}`;
            }
            if (info.uptime) {
                sysUptime.textContent = info.uptime.uptime_str || "--";
            }
        } catch (e) {
            console.error("Error fetching system info:", e);
        }
    }

    async function fetchAmauraDashboard() {
        if (!amauraTaskStates) return;
        try {
            const dashboardResponse = await fetch("/api/amaura/dashboard", {headers: amauraOperatorHeaders()});
            if (!dashboardResponse.ok) return;
            const dashboard = await dashboardResponse.json();
            amauraProgrammes.textContent = dashboard.active_programmes || 0;
            amauraAgents.textContent = dashboard.agents?.total || 0;
            amauraApprovals.textContent = dashboard.pending_approvals || 0;
            amauraCost.textContent = dashboard.total_cost_cents || 0;
            amauraViolations.textContent = dashboard.policy_violations || 0;

            amauraTaskStates.innerHTML = "";
            const states = Object.entries(dashboard.task_states || {});
            if (!states.length) {
                const empty = document.createElement("div");
                empty.className = "company-empty";
                empty.textContent = "No programmes yet. Give JARVIS a measurable company objective.";
                amauraTaskStates.appendChild(empty);
            }
            states.forEach(([state, count]) => {
                const row = document.createElement("div");
                row.className = "company-state-row";
                const label = document.createElement("span");
                label.textContent = state.replaceAll("_", " ");
                const value = document.createElement("strong");
                value.textContent = count;
                row.append(label, value);
                amauraTaskStates.appendChild(row);
            });

            amauraApprovalList.innerHTML = "";
            const decisionNotice = document.createElement("div");
            decisionNotice.className = "company-empty";
            decisionNotice.textContent = dashboard.pending_approvals
                ? `${dashboard.pending_approvals} decision(s) waiting. Review them through authenticated Telegram or the approval API.`
                : "No decisions waiting.";
            amauraApprovalList.appendChild(decisionNotice);
        } catch (error) {
            console.error("Error fetching Amaura company state:", error);
        }
    }

    // ── TOOLS & MEMORY FETCH ────────────────────────────────────────────────
    async function fetchToolsList() {
        try {
            const res = await fetch("/api/tools", { headers: jarvisHeaders() });
            const data = await res.json();
            toolsData = data.tools || [];
            sysToolsCount.textContent = `${toolsData.length} Active`;
            renderToolsList(toolsData);
        } catch (e) {
            toolsList.innerHTML = `<div class="text-danger">Failed to load tools.</div>`;
        }
    }

    function renderToolsList(tools) {
        toolsList.innerHTML = "";
        tools.forEach((t) => {
            const item = document.createElement("div");
            item.className = "tool-item";
            item.innerHTML = `
                <div class="tool-name"><i class="fa-solid fa-wrench"></i> ${escapeHtml(t.name)}</div>
                <div class="tool-desc">${escapeHtml(t.description)}</div>
            `;
            item.onclick = () => {
                chatInput.value = `Execute tool ${t.name}`;
                chatInput.focus();
            };
            toolsList.appendChild(item);
        });
    }

    async function fetchMemoryList() {
        try {
            const res = await fetch("/api/memory", { headers: jarvisHeaders() });
            const data = await res.json();
            renderMemoryList(data.facts || []);
        } catch (e) {
            memoryList.innerHTML = `<div class="text-danger">Failed to load memory.</div>`;
        }
    }

    function renderMemoryList(facts) {
        memoryList.innerHTML = "";
        if (facts.length === 0) {
            memoryList.innerHTML = `<div class="text-muted font-mono" style="font-size:12px;">No facts stored in memory yet.</div>`;
            return;
        }
        facts.forEach((fact) => {
            const item = document.createElement("div");
            item.className = "memory-item";
            item.innerHTML = `
                <span><i class="fa-solid fa-lightbulb"></i> ${escapeHtml(fact)}</span>
            `;
            memoryList.appendChild(item);
        });
    }

    // ── AUTOCOMPLETE FOR SLASH COMMANDS ─────────────────────────────────────
    function handleInputAutocomplete() {
        const val = chatInput.value;
        if (val.startsWith("/")) {
            const filter = val.toLowerCase();
            const matches = SLASH_COMMANDS.filter((sc) => sc.cmd.toLowerCase().startsWith(filter));
            if (matches.length > 0) {
                renderAutocomplete(matches);
                return;
            }
        }
        closeAutocomplete();
    }

    function renderAutocomplete(items) {
        autocompletePopup.innerHTML = "";
        items.forEach((item, idx) => {
            const div = document.createElement("div");
            div.className = `ac-item ${idx === 0 ? "selected" : ""}`;
            div.innerHTML = `
                <span>${item.cmd}</span>
                <span class="ac-desc">${item.desc}</span>
            `;
            div.onclick = () => {
                chatInput.value = item.cmd + " ";
                chatInput.focus();
                closeAutocomplete();
            };
            autocompletePopup.appendChild(div);
        });
        autocompletePopup.classList.remove("hidden");
    }

    function closeAutocomplete() {
        autocompletePopup.classList.add("hidden");
    }

    // ── EVENT LISTENERS SETUP ───────────────────────────────────────────────
    function setupEventListeners() {
        // Send button & keypress
        sendBtn.onclick = () => sendUserMessage();

        chatInput.onkeydown = (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendUserMessage();
            } else if (e.key === "ArrowUp") {
                if (historyIdx > 0) {
                    historyIdx--;
                    chatInput.value = commandHistory[historyIdx] || "";
                }
            } else if (e.key === "ArrowDown") {
                if (historyIdx < commandHistory.length - 1) {
                    historyIdx++;
                    chatInput.value = commandHistory[historyIdx] || "";
                } else {
                    historyIdx = commandHistory.length;
                    chatInput.value = "";
                }
            }
        };

        chatInput.oninput = handleInputAutocomplete;

        // Mic Button
        micBtn.onclick = () => {
            if (isListening) {
                stopListening();
            } else {
                startListening();
            }
        };

        // Stop speech
        stopSpeechBtn.onclick = () => {
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            stopSpeechBtn.classList.add("hidden");
            audioWaves.classList.remove("active");
            setStatus("online", "ONLINE");
        };

        // Clear chat
        clearChatBtn.onclick = () => {
            chatMessages.innerHTML = "";
            addMessage("Workspace cleared, sir.", "system");
        };

        // Model selector change
        modelSelect.onchange = () => {
            const model = modelSelect.value;
            sendUserMessage(`/model ${model}`);
        };

        // TTS Toggle Button
        ttsToggleBtn.onclick = () => {
            ttsEnabled = !ttsEnabled;
            ttsToggleBtn.classList.toggle("active", ttsEnabled);
            const icon = document.getElementById("tts-icon");
            icon.className = ttsEnabled ? "fa-solid fa-volume-high" : "fa-solid fa-volume-xmark";
        };

        // Sidebar Toggle
        sidebarToggleBtn.onclick = () => {
            hudSidebar.classList.toggle("collapsed");
        };

        // Sidebar Tabs
        tabBtns.forEach((btn) => {
            btn.onclick = () => {
                tabBtns.forEach((b) => b.classList.remove("active"));
                tabPanes.forEach((p) => p.classList.remove("active"));

                btn.classList.add("active");
                const targetPane = document.getElementById(btn.dataset.tab);
                if (targetPane) targetPane.classList.add("active");
                if (btn.dataset.tab === "tab-amaura") fetchAmauraDashboard();
            };
        });

        // Slash Chips
        chipBtns.forEach((chip) => {
            chip.onclick = () => {
                const cmd = chip.dataset.cmd;
                chatInput.value = cmd + " ";
                chatInput.focus();
            };
        });

        // Tools search
        toolSearch.oninput = () => {
            const q = toolSearch.value.toLowerCase();
            const filtered = toolsData.filter(
                (t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)
            );
            renderToolsList(filtered);
        };

        // Memory Actions
        addMemoryBtn.onclick = async () => {
            const fact = memoryInput.value.trim();
            if (!fact) return;
            try {
                await fetch("/api/memory", {
                    method: "POST",
                    headers: jarvisHeaders({ "Content-Type": "application/json" }),
                    body: JSON.stringify({ fact }),
                });
                memoryInput.value = "";
                fetchMemoryList();
                addMessage(`Remembered: "${fact}"`, "system");
            } catch (e) {
                console.error(e);
            }
        };

        clearMemoryBtn.onclick = async () => {
            if (confirm("Are you sure you want to reset JARVIS memory?")) {
                await fetch("/api/memory", { method: "DELETE", headers: jarvisHeaders() });
                fetchMemoryList();
                addMessage("JARVIS memory cleared.", "system");
            }
        };

        refreshSysBtn.onclick = fetchSystemMetrics;
        if (refreshAmauraBtn) refreshAmauraBtn.onclick = fetchAmauraDashboard;

        // Sliders
        voiceRate.oninput = () => (rateVal.textContent = `${voiceRate.value}x`);
        voicePitch.oninput = () => (pitchVal.textContent = voicePitch.value);

        testVoiceBtn.onclick = () => {
            speakText("J.A.R.V.I.S. voice output operational. At your service, sir.");
        };
    }

    // Launch
    init();
});
