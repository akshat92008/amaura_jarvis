// AuraStudy Dashboard Application Logic
document.addEventListener('DOMContentLoaded', () => {
    // ── State Management ──────────────────────────────────────────────────────
    let tasks = JSON.parse(localStorage.getItem('aurastudy_tasks')) || [
        { id: '1', title: 'Implement Raft Consensus in Go', priority: 'high', completed: false },
        { id: '2', title: 'Neural Nets Problem Set 4: Backprop', priority: 'high', completed: false },
        { id: '3', title: 'Linear Algebra Chapter 6 Matrix Decomposition', priority: 'medium', completed: true },
        { id: '4', title: 'Read DynamoDB paper for Distributed Systems', priority: 'low', completed: false },
    ];

    let currentFilter = 'all';

    // ── Elements ──────────────────────────────────────────────────────────────
    const tasksListEl = document.getElementById('tasksList');
    const addTaskForm = document.getElementById('addTaskForm');
    const taskTitleInput = document.getElementById('taskTitleInput');
    const taskPrioritySelect = document.getElementById('taskPrioritySelect');
    const taskSummaryEl = document.getElementById('taskSummary');
    const completionRateEl = document.getElementById('completionRate');
    const filterBtns = document.querySelectorAll('.filter-btn');

    // ── Task Rendering ────────────────────────────────────────────────────────
    function renderTasks() {
        tasksListEl.innerHTML = '';
        
        const filteredTasks = tasks.filter(task => {
            if (currentFilter === 'pending') return !task.completed;
            if (currentFilter === 'completed') return task.completed;
            return true;
        });

        if (filteredTasks.length === 0) {
            tasksListEl.innerHTML = '<p style="text-align:center; padding: 20px; color: var(--text-muted); font-size: 13px;">No tasks in this category.</p>';
        } else {
            filteredTasks.forEach(task => {
                const card = document.createElement('div');
                card.className = `task-card ${task.completed ? 'done' : ''}`;
                card.innerHTML = `
                    <div class="task-left">
                        <input type="checkbox" class="task-checkbox" data-id="${task.id}" ${task.completed ? 'checked' : ''}>
                        <div class="task-info">
                            <span class="task-title">${escapeHtml(task.title)}</span>
                            <span class="priority-badge priority-${task.priority}">${task.priority}</span>
                        </div>
                    </div>
                    <button class="task-delete-btn" data-id="${task.id}" title="Delete task">✕</button>
                `;
                tasksListEl.appendChild(card);
            });
        }

        updateStats();
        localStorage.setItem('aurastudy_tasks', JSON.stringify(tasks));
    }

    function updateStats() {
        const total = tasks.length;
        const completed = tasks.filter(t => t.completed).length;
        const pending = total - completed;

        taskSummaryEl.textContent = `${pending} remaining`;
        const rate = total > 0 ? Math.round((completed / total) * 100) : 100;
        completionRateEl.textContent = `${rate}%`;
    }

    function escapeHtml(str) {
        return str.replace(/[&<>'"]/g, 
            tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
        );
    }

    // ── Task Events ───────────────────────────────────────────────────────────
    addTaskForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const title = taskTitleInput.value.trim();
        if (!title) return;

        const newTask = {
            id: Date.now().toString(),
            title: title,
            priority: taskPrioritySelect.value,
            completed: false
        };

        tasks.unshift(newTask);
        taskTitleInput.value = '';
        renderTasks();
    });

    tasksListEl.addEventListener('click', (e) => {
        const target = e.target;
        if (target.classList.contains('task-checkbox')) {
            const id = target.getAttribute('data-id');
            const task = tasks.find(t => t.id === id);
            if (task) {
                task.completed = target.checked;
                renderTasks();
            }
        } else if (target.classList.contains('task-delete-btn')) {
            const id = target.getAttribute('data-id');
            tasks = tasks.filter(t => t.id !== id);
            renderTasks();
        }
    });

    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.getAttribute('data-filter');
            renderTasks();
        });
    });

    // ── Pomodoro Focus Timer ──────────────────────────────────────────────────
    let timerDuration = 25 * 60;
    let timerSecondsLeft = timerDuration;
    let timerInterval = null;
    let isTimerRunning = false;

    const timeRemainingEl = document.getElementById('timeRemaining');
    const timerStateTextEl = document.getElementById('timerStateText');
    const startTimerBtn = document.getElementById('startTimerBtn');
    const pauseTimerBtn = document.getElementById('pauseTimerBtn');
    const resetTimerBtn = document.getElementById('resetTimerBtn');
    const presetChips = document.querySelectorAll('.preset-chip');
    const timerModeBadge = document.getElementById('timerMode');

    function formatTime(seconds) {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    function updateTimerUI() {
        timeRemainingEl.textContent = formatTime(timerSecondsLeft);
    }

    function startTimer() {
        if (isTimerRunning) return;
        isTimerRunning = true;
        startTimerBtn.disabled = true;
        pauseTimerBtn.disabled = false;
        timerStateTextEl.textContent = 'Focusing... 🔥';

        timerInterval = setInterval(() => {
            if (timerSecondsLeft > 0) {
                timerSecondsLeft--;
                updateTimerUI();
            } else {
                clearInterval(timerInterval);
                isTimerRunning = false;
                startTimerBtn.disabled = false;
                pauseTimerBtn.disabled = true;
                timerStateTextEl.textContent = 'Session Complete! 🎉';
                alert('Focus session complete! Great work.');
            }
        }, 1000);
    }

    function pauseTimer() {
        if (!isTimerRunning) return;
        clearInterval(timerInterval);
        isTimerRunning = false;
        startTimerBtn.disabled = false;
        pauseTimerBtn.disabled = true;
        timerStateTextEl.textContent = 'Paused ⏸️';
    }

    function resetTimer() {
        clearInterval(timerInterval);
        isTimerRunning = false;
        timerSecondsLeft = timerDuration;
        startTimerBtn.disabled = false;
        pauseTimerBtn.disabled = true;
        timerStateTextEl.textContent = 'Ready to Focus';
        updateTimerUI();
    }

    startTimerBtn.addEventListener('click', startTimer);
    pauseTimerBtn.addEventListener('click', pauseTimer);
    resetTimerBtn.addEventListener('click', resetTimer);

    presetChips.forEach(chip => {
        chip.addEventListener('click', () => {
            presetChips.forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            const mins = parseInt(chip.getAttribute('data-time'), 10);
            timerDuration = mins * 60;
            timerSecondsLeft = timerDuration;
            timerModeBadge.textContent = chip.textContent;
            resetTimer();
        });
    });

    // ── Theme Toggle & Mobile Sidebar ─────────────────────────────────────────
    const themeBtn = document.getElementById('themeToggle');
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');

    const savedTheme = localStorage.getItem('aurastudy_theme') || 'theme-dark';
    document.body.className = savedTheme;

    themeBtn.addEventListener('click', () => {
        if (document.body.classList.contains('theme-dark')) {
            document.body.className = 'theme-light';
            localStorage.setItem('aurastudy_theme', 'theme-light');
        } else {
            document.body.className = 'theme-dark';
            localStorage.setItem('aurastudy_theme', 'theme-dark');
        }
    });

    menuToggle.addEventListener('click', () => {
        sidebar.classList.toggle('open');
    });

    // Initial render
    renderTasks();
    updateTimerUI();
});
