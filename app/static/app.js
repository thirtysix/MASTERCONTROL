/* ── MASTER CONTROL — Main App ────────────────────────────────── */

let allProjects = [];
let selectedProject = null;

/* ── Mode Toggle (Agentic / Interactive) ────────────────────── */

let currentMode = localStorage.getItem('mastercontrol_mode') || 'agentic';

function getMode() {
    return currentMode;
}

function setMode(mode) {
    currentMode = mode;
    localStorage.setItem('mastercontrol_mode', mode);

    // Update toggle button states
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Update panel header for completed/sessions
    const completedHeader = document.querySelector('#panel-completed .panel-header');
    if (completedHeader) {
        completedHeader.textContent = mode === 'interactive' ? 'Claude Sessions' : 'Completed Tasks';
    }

    // Re-render panels with current project
    if (selectedProject) {
        Panels.updateAll(selectedProject);
    }
}

function initModeToggle() {
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => setMode(btn.dataset.mode));
        btn.classList.toggle('active', btn.dataset.mode === currentMode);
    });

    // Set initial panel header
    const completedHeader = document.querySelector('#panel-completed .panel-header');
    if (completedHeader && currentMode === 'interactive') {
        completedHeader.textContent = 'Claude Sessions';
    }
}

/* ── Terminal Overlay ────────────────────────────────────────── */

let _terminalVisible = false;

function openTerminalOverlay() {
    const overlay = document.getElementById('terminal-overlay');
    overlay.style.display = 'flex';
    _terminalVisible = true;
    document.getElementById('terminal-status').textContent = 'Running...';
}

function minimizeTerminal() {
    document.getElementById('terminal-overlay').style.display = 'none';
    _terminalVisible = false;
}

function showTerminal() {
    document.getElementById('terminal-overlay').style.display = 'flex';
    _terminalVisible = true;
}

function clearTerminal() {
    document.getElementById('terminal-body').innerHTML = '';
}

function appendTerminalLine(lineType, text) {
    const body = document.getElementById('terminal-body');
    const line = document.createElement('div');
    line.className = `term-line ${lineType}`;
    line.textContent = text;
    body.appendChild(line);
    body.scrollTop = body.scrollHeight;
}

function setTerminalStatus(text) {
    document.getElementById('terminal-status').textContent = text;
}

/* ── SSE Task Stream Manager ─────────────────────────────────── */

const TaskStream = (() => {
    let eventSource = null;
    let currentTaskId = null;

    function connect(taskId) {
        disconnect();
        currentTaskId = taskId;
        eventSource = new EventSource(`/api/tasks/${taskId}/stream`);

        eventSource.addEventListener('thinking', (e) => {
            const data = JSON.parse(e.data);
            Panels.appendExecutionLog('thinking', data.text);
        });

        eventSource.addEventListener('tool_call', (e) => {
            const data = JSON.parse(e.data);
            Panels.appendExecutionLog('tool_call', data.tool);
        });

        eventSource.addEventListener('tool_result', (e) => {
            const data = JSON.parse(e.data);
            const icon = data.success ? 'OK' : 'FAIL';
            Panels.appendExecutionLog('tool_result', `${icon} ${data.tool}`);
        });

        eventSource.addEventListener('usage', (e) => {
            const data = JSON.parse(e.data);
            Panels.updateTokenDisplay(data.input_tokens, data.output_tokens);
        });

        eventSource.addEventListener('terminal', (e) => {
            const data = JSON.parse(e.data);
            appendTerminalLine(data.line_type, data.text);
        });

        eventSource.addEventListener('complete', (e) => {
            const data = JSON.parse(e.data);
            Panels.appendExecutionLog('complete', data.result.substring(0, 200));
            setTerminalStatus('Complete');
            Panels.onTaskCompleted(currentTaskId);
            disconnect();
            refreshCurrentProject();
        });

        eventSource.addEventListener('error', (e) => {
            if (e.data) {
                try {
                    const data = JSON.parse(e.data);
                    Panels.appendExecutionLog('error', data.error);
                    appendTerminalLine('error', data.error);
                } catch (_) {}
            }
            setTerminalStatus('Failed');
            Panels.onTaskFailed(currentTaskId);
            disconnect();
            refreshCurrentProject();
        });
    }

    function disconnect() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
            currentTaskId = null;
        }
    }

    return { connect, disconnect };
})();

/* ── Project Selection ────────────────────────────────────────── */

function onProjectSelected(project) {
    selectedProject = project;
    Panels.updateAll(project);
}

/* ── Task Actions ─────────────────────────────────────────────── */

async function createTask() {
    if (!selectedProject) return;
    const title = document.getElementById('task-title')?.value?.trim();
    const desc = document.getElementById('task-desc')?.value?.trim();
    const risk = parseInt(document.getElementById('task-risk')?.value || '1');

    if (!title) {
        alert('Please enter a task title');
        return;
    }

    try {
        await apiFetch('/api/tasks', {
            method: 'POST',
            body: JSON.stringify({
                project_id: selectedProject.id,
                title: title,
                description: desc || title,
                risk_tier: risk,
            }),
        });
        Panels.toggleTaskForm();
        Panels.updateAll(selectedProject);
    } catch (e) {
        console.error('Failed to create task:', e);
        alert('Failed to create task: ' + e.message);
    }
}

async function createAndOpenTask() {
    if (!selectedProject) return;
    const title = document.getElementById('task-title')?.value?.trim();
    const desc = document.getElementById('task-desc')?.value?.trim();
    const risk = parseInt(document.getElementById('task-risk')?.value || '1');
    const terminalSelect = document.getElementById('task-terminal');
    const terminalValue = terminalSelect?.value || '__new__';

    if (!title) {
        alert('Please enter a task title');
        return;
    }

    try {
        // Create the task
        const task = await apiFetch('/api/tasks', {
            method: 'POST',
            body: JSON.stringify({
                project_id: selectedProject.id,
                title: title,
                description: desc || title,
                risk_tier: risk,
            }),
        });

        Panels.toggleTaskForm();

        // Build terminal request
        const terminalBody = {};
        if (terminalValue !== '__new__') {
            terminalBody.session_id = terminalValue;
        }
        terminalBody.task_text = desc || title;
        const planMode = document.getElementById('task-plan-mode')?.checked || false;
        if (planMode) {
            terminalBody.plan_mode = true;
        }

        // Open Claude Code terminal
        await apiFetch(`/api/projects/${selectedProject.id}/claude-terminal`, {
            method: 'POST',
            body: JSON.stringify(terminalBody),
        });

        // Mark task as dispatched (include session_id if using existing session)
        const statusBody = { status: 'dispatched' };
        if (terminalValue !== '__new__') {
            statusBody.session_id = terminalValue;
        }
        await apiFetch(`/api/tasks/${task.id}/status`, {
            method: 'PATCH',
            body: JSON.stringify(statusBody),
        });

        Panels.updateAll(selectedProject);
    } catch (e) {
        console.error('Failed to create and open task:', e);
        alert('Failed to create and open task: ' + e.message);
    }
}

async function deleteTask(taskId) {
    try {
        await apiFetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
        if (selectedProject) Panels.updateAll(selectedProject);
    } catch (e) {
        console.error('Failed to delete task:', e);
    }
}

async function executeTask(taskId) {
    if (currentMode === 'interactive') {
        return executeTaskInteractive(taskId);
    }
    return executeTaskAgentic(taskId);
}

async function executeTaskAgentic(taskId) {
    try {
        clearTerminal();
        openTerminalOverlay();

        const result = await apiFetch(`/api/tasks/${taskId}/execute`, { method: 'POST' });
        TaskStream.connect(taskId);
        if (selectedProject) Panels.updateAll(selectedProject);
    } catch (e) {
        console.error('Failed to execute task:', e);
        setTerminalStatus('Failed to start');
        appendTerminalLine('error', 'Failed to start task: ' + e.message);
    }
}

async function executeTaskInteractive(taskId) {
    if (!selectedProject) return;
    try {
        // Get task details for the description
        const task = await apiFetch(`/api/tasks/${taskId}`);
        const taskText = task.description || task.title;

        // Open Claude Code terminal with task text
        await apiFetch(`/api/projects/${selectedProject.id}/claude-terminal`, {
            method: 'POST',
            body: JSON.stringify({ task_text: taskText }),
        });

        // Mark task as dispatched
        await apiFetch(`/api/tasks/${taskId}/status`, {
            method: 'PATCH',
            body: JSON.stringify({ status: 'dispatched' }),
        });

        if (selectedProject) Panels.updateAll(selectedProject);
    } catch (e) {
        console.error('Failed to open interactive terminal:', e);
        alert('Failed to open Claude Code terminal: ' + e.message);
    }
}

async function markTaskDone(taskId) {
    try {
        await apiFetch(`/api/tasks/${taskId}/status`, {
            method: 'PATCH',
            body: JSON.stringify({ status: 'completed' }),
        });
        if (selectedProject) Panels.updateAll(selectedProject);
    } catch (e) {
        console.error('Failed to mark task done:', e);
    }
}

function refreshCurrentProject() {
    if (selectedProject) {
        // Rescan the project so fields like has_mastercontrol, git_dirty update
        setTimeout(() => rescanProject(selectedProject.id), 500);
    }
}

/* ── Task Detail Overlay ─────────────────────────────────────── */

async function showTaskDetail(taskId) {
    try {
        const t = await apiFetch(`/api/tasks/${taskId}`);
        const overlay = document.getElementById('task-detail-overlay');
        const titleEl = document.getElementById('task-detail-title');
        const statusEl = document.getElementById('task-detail-status');
        const bodyEl = document.getElementById('task-detail-body');

        titleEl.textContent = t.title;

        const statusColors = {
            pending: '#ffa726', running: '#00bcd4', dispatched: '#4fc3f7',
            completed: '#66bb6a', failed: '#ef5350',
        };
        statusEl.textContent = t.status.toUpperCase();
        statusEl.style.color = statusColors[t.status] || '#78909c';

        const rows = [];
        rows.push(`<div class="detail-field"><span class="detail-label">Project</span><span class="detail-value">${escapeHtml(t.project_id)}</span></div>`);
        rows.push(`<div class="detail-field"><span class="detail-label">Risk Tier</span><span class="detail-value">${t.risk_tier}</span></div>`);
        rows.push(`<div class="detail-field"><span class="detail-label">Created</span><span class="detail-value">${formatDate(t.created_at)}</span></div>`);
        if (t.started_at) rows.push(`<div class="detail-field"><span class="detail-label">Started</span><span class="detail-value">${formatDate(t.started_at)}</span></div>`);
        if (t.completed_at) rows.push(`<div class="detail-field"><span class="detail-label">Completed</span><span class="detail-value">${formatDate(t.completed_at)}</span></div>`);
        if (t.token_input + t.token_output > 0) {
            rows.push(`<div class="detail-field"><span class="detail-label">Tokens</span><span class="detail-value">${(t.token_input + t.token_output).toLocaleString()} ($${t.cost_usd.toFixed(4)})</span></div>`);
        }

        let html = `<div class="detail-meta">${rows.join('')}</div>`;

        html += `<div class="detail-section">
            <div class="detail-section-title">Description</div>
            <div class="detail-section-body">${escapeHtml(t.description || '(none)')}</div>
        </div>`;

        if (t.result) {
            html += `<div class="detail-section">
                <div class="detail-section-title">Result</div>
                <div class="detail-section-body">${escapeHtml(t.result)}</div>
            </div>`;
        }
        if (t.error) {
            html += `<div class="detail-section">
                <div class="detail-section-title error">Error</div>
                <div class="detail-section-body error">${escapeHtml(t.error)}</div>
            </div>`;
        }

        // Action buttons
        html += '<div class="detail-actions">';
        if (t.status === 'pending') {
            html += `<button class="run-btn" onclick="closeTaskDetail(); executeTask('${t.id}')">Run</button>`;
            html += `<button class="delete-btn" onclick="closeTaskDetail(); deleteTask('${t.id}')">Delete</button>`;
        }
        if (t.status === 'dispatched') {
            html += `<button class="done-btn" onclick="closeTaskDetail(); markTaskDone('${t.id}')">Mark Done</button>`;
            html += `<button onclick="closeTaskDetail(); replayTerminal('${t.id}')">View Session Log</button>`;
        }
        if (t.status === 'completed' || t.status === 'failed') {
            html += `<button onclick="closeTaskDetail(); replayTerminal('${t.id}')">View Terminal Log</button>`;
        }
        html += '</div>';

        bodyEl.innerHTML = html;
        overlay.style.display = 'flex';
    } catch (e) {
        console.error('Failed to load task detail:', e);
    }
}

function closeTaskDetail() {
    document.getElementById('task-detail-overlay').style.display = 'none';
}

/* ── Suggestion → Task ────────────────────────────────────────── */

async function addSuggestionAsTask(index) {
    if (!selectedProject) return;
    const el = document.getElementById('panel-suggestions-content');
    const suggestions = el._suggestions;
    if (!suggestions || !suggestions[index]) return;

    const s = suggestions[index];
    try {
        await apiFetch('/api/tasks', {
            method: 'POST',
            body: JSON.stringify({
                project_id: selectedProject.id,
                title: s.title,
                description: s.desc,
                risk_tier: s.tier,
            }),
        });
        Panels.updateAll(selectedProject);
    } catch (e) {
        console.error('Failed to create task from suggestion:', e);
    }
}

/* ── Terminal Replay ──────────────────────────────────────────── */

async function replayTerminal(taskId) {
    try {
        const data = await apiFetch(`/api/tasks/${taskId}/terminal`);
        clearTerminal();
        if (data.lines && data.lines.length > 0) {
            data.lines.forEach(line => {
                appendTerminalLine(line.line_type, line.text);
            });
            setTerminalStatus('Replay');
        } else {
            appendTerminalLine('system', 'No terminal log available for this task.');
            setTerminalStatus('No log');
        }
        showTerminal();
    } catch (e) {
        console.error('Failed to load terminal log:', e);
    }
}

/* ── Cross-project Navigation ────────────────────────────────── */

function selectProjectById(projectId) {
    const project = allProjects.find(p => p.id === projectId);
    if (project) {
        HexGrid.selectProject(project);
        onProjectSelected(project);
    }
}

/* ── Claude Code Interactive ─────────────────────────────────── */

function refreshSessions() {
    if (selectedProject) {
        Panels.renderSessions(selectedProject);
    }
}

async function openClaudeCode(projectId) {
    try {
        await apiFetch(`/api/projects/${projectId}/claude-terminal`, {
            method: 'POST',
            body: JSON.stringify({}),
        });
    } catch (e) {
        console.error('Failed to open Claude Code:', e);
        alert('Failed to open Claude Code terminal: ' + e.message);
    }
}

async function resumeSession(projectId, sessionId) {
    try {
        const result = await apiFetch(`/api/projects/${projectId}/claude-terminal`, {
            method: 'POST',
            body: JSON.stringify({ session_id: sessionId }),
        });
        if (result.status === 'activated') {
            // Window was found and brought to foreground — brief status flash
            const dot = document.getElementById('status-dot');
            dot.classList.add('active');
            setTimeout(() => dot.classList.remove('active'), 1500);
        }
    } catch (e) {
        console.error('Failed to resume session:', e);
        alert('Failed to resume session: ' + e.message);
    }
}

/* ── Other Actions ────────────────────────────────────────────── */

async function openTerminal(projectId) {
    try {
        await apiFetch(`/api/projects/${projectId}/terminal`, { method: 'POST' });
    } catch (e) {
        console.error('Failed to open terminal:', e);
    }
}

async function scaffoldProject(projectId) {
    try {
        const result = await apiFetch(`/api/projects/${projectId}/scaffold`, { method: 'POST' });
        const created = result.created || [];
        if (created.length > 0) {
            console.log(`Scaffolded: ${created.join(', ')}`);
        }
        // Update project data from the response
        if (result.project) {
            const idx = allProjects.findIndex(p => p.id === projectId);
            if (idx >= 0) allProjects[idx] = result.project;
            HexGrid.render(allProjects);
            if (selectedProject && selectedProject.id === projectId) {
                selectedProject = result.project;
                Panels.updateAll(result.project);
            }
        }
    } catch (e) {
        console.error('Failed to scaffold project:', e);
        alert('Failed to scaffold project: ' + e.message);
    }
}

async function rescanProject(projectId) {
    try {
        const updated = await apiFetch(`/api/projects/${projectId}/rescan`, { method: 'POST' });
        const idx = allProjects.findIndex(p => p.id === projectId);
        if (idx >= 0) allProjects[idx] = updated;
        HexGrid.render(allProjects);
        if (selectedProject && selectedProject.id === projectId) {
            selectedProject = updated;
            Panels.updateAll(updated);
        }
    } catch (e) {
        console.error('Failed to rescan:', e);
    }
}

async function triggerScan() {
    try {
        await apiFetch('/api/system/scan', { method: 'POST' });
        await loadProjects();
    } catch (e) {
        console.error('Scan failed:', e);
    }
}

function showNewProject() {
    alert('New Project wizard — coming in Phase 4');
}

/* ── Load Projects & Stats ────────────────────────────────────── */

async function loadProjects() {
    try {
        allProjects = await apiFetch('/api/projects');
        HexGrid.render(allProjects);
        updateStatsBar();
        buildTagFilter();
    } catch (e) {
        console.error('Failed to load projects:', e);
    }
}

async function updateStatsBar() {
    try {
        const stats = await apiFetch('/api/system/stats');
        const statsBar = document.getElementById('stats-bar');
        statsBar.textContent = `${stats.total_projects} projects | ${stats.active_projects} active | ${stats.agents_running} agents running | $${stats.cost_today_usd.toFixed(2)} total`;

        const dot = document.getElementById('status-dot');
        if (stats.agents_running > 0) {
            dot.classList.add('active');
        } else {
            dot.classList.remove('active');
        }
    } catch (e) {
        // Fallback
        const active = allProjects.filter(p => p.status === 'active').length;
        document.getElementById('stats-bar').textContent =
            `${allProjects.length} projects | ${active} active`;
    }
}

function buildTagFilter() {
    const bar = document.getElementById('tag-filter-bar');
    const tagCounts = {};
    allProjects.forEach(p => {
        p.tags.forEach(t => { tagCounts[t] = (tagCounts[t] || 0) + 1; });
    });

    bar.innerHTML = Object.entries(tagCounts)
        .sort((a, b) => b[1] - a[1])
        .map(([tag, count]) =>
            `<button class="tag-filter-btn" style="border-color:${getTagColor(tag)};color:${getTagColor(tag)}"
                     onclick="HexGrid.setFilter('${tag}')">${tag} (${count})</button>`
        ).join('');
}

/* ── Init ─────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
    HexGrid.init(document.getElementById('hex-grid'));
    initModeToggle();
    loadProjects();
    Panels.renderAllTasks();

    // Resize SVG on window resize
    window.addEventListener('resize', () => {
        const svg = document.getElementById('hex-grid');
        const parent = svg.parentElement;
        const filterBar = document.getElementById('tag-filter-bar');
        svg.setAttribute('width', parent.clientWidth);
        svg.setAttribute('height', parent.clientHeight - (filterBar?.offsetHeight || 32));
    });

    // Poll stats every 5 seconds
    setInterval(updateStatsBar, 5000);
});
