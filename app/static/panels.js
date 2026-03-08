/* ── MASTER CONTROL — Bottom Panel Renderers ─────────────────── */

const Panels = (() => {

    let _taskFormVisible = false;
    let _allTasksFilter = null; // null = nothing selected, project_id = specific, '__all__' = all

    function renderProjectStatus(project) {
        const el = document.getElementById('panel-status-content');
        if (!project) {
            el.innerHTML = '<div class="empty-state">Select a project</div>';
            return;
        }

        const tags = project.tags.map(t =>
            `<span class="tag-pill" style="background:${getTagColor(t)}33;color:${getTagColor(t)};border:1px solid ${getTagColor(t)}">${t}</span>`
        ).join(' ');

        const techStack = project.tech_stack.map(t =>
            `<span class="tech-badge">${t}</span>`
        ).join(' ');

        const mode = getMode();
        let actionButtons = '';
        if (mode === 'interactive') {
            actionButtons = `
                <button onclick="openClaudeCode('${project.id}')">Open Claude Code</button>
                <button onclick="openTerminal('${project.id}')">Terminal</button>
                <button onclick="rescanProject('${project.id}')">Rescan</button>
            `;
        } else {
            actionButtons = `
                <button onclick="openTerminal('${project.id}')">Open Terminal</button>
                <button onclick="rescanProject('${project.id}')">Rescan</button>
            `;
        }

        const missingDirs = project.missing_base_dirs || [];
        const scaffoldNotice = missingDirs.length > 0
            ? `<div class="scaffold-notice">
                <span>${missingDirs.length} base dir${missingDirs.length > 1 ? 's' : ''} missing: ${missingDirs.join(', ')}</span>
                <button onclick="scaffoldProject('${project.id}')">Scaffold</button>
            </div>`
            : '';

        el.innerHTML = `
            <div class="info-section">
                <div class="project-name">${project.name}</div>
                <div class="tag-row">${tags}</div>
                <div class="tech-row">${techStack}</div>
            </div>
            ${scaffoldNotice}
            <div class="info-rows">
                ${infoRow('Status', project.status)}
                ${infoRow('Git', project.git_branch ? `${project.git_branch}${project.git_dirty ? ' (uncommitted changes)' : ''}` : '—')}
                ${project.git_last_commit ? infoRow('Last commit', project.git_last_commit) : ''}
                ${infoRow('Docker', project.docker_status || 'none')}
                ${infoRow('Files', `${project.file_count} files, ${formatSize(project.dir_size_mb)}`)}
                ${infoRow('Modified', formatDate(project.last_modified))}
                ${infoRow('Scanned', formatDate(project.scanned_at))}
            </div>
            <div class="action-row">
                ${actionButtons}
            </div>
        `;
    }

    function renderUpcomingTasks(project) {
        const el = document.getElementById('panel-upcoming-content');
        const btn = document.getElementById('btn-new-task');

        if (!project) {
            el.innerHTML = '<div class="empty-state">Select a project</div>';
            if (btn) btn.disabled = true;
            return;
        }

        if (btn) btn.disabled = false;

        const mode = getMode();
        const isInteractive = mode === 'interactive';

        // Build HTML: task form (hidden by default) + task list
        let html = '';

        // Inline task creation form
        html += `<div class="task-form" id="task-form" style="display:${_taskFormVisible ? 'block' : 'none'}">
            <input type="text" id="task-title" placeholder="Task title" />
            <textarea id="task-desc" placeholder="Description — what should the agent do?"></textarea>
            <select id="task-risk">
                <option value="1">Tier 1 — Read only</option>
                <option value="2" selected>Tier 2 — Modify</option>
                <option value="3">Tier 3 — Create</option>
                <option value="4">Tier 4 — Destructive</option>
            </select>
            ${isInteractive ? `<select id="task-terminal">
                <option value="__new__">New Terminal</option>
            </select>
            <label class="plan-mode-check">
                <input type="checkbox" id="task-plan-mode" />
                Plan first
            </label>` : ''}
            <div class="task-form-buttons">
                <button onclick="Panels.toggleTaskForm()">Cancel</button>
                ${isInteractive
                    ? '<button class="run-btn" onclick="createAndOpenTask()">Create &amp; Open</button>'
                    : '<button class="run-btn" onclick="createTask()">Create</button>'}
            </div>
        </div>`;

        el.innerHTML = html + '<div id="task-list-area"><div class="empty-state">Loading tasks...</div></div>';

        // Populate terminal dropdown with sessions (interactive mode)
        if (isInteractive && _taskFormVisible) {
            _populateTerminalDropdown(project.id);
        }

        // Fetch pending + running + dispatched tasks
        _fetchTasks(project.id);
    }

    async function _populateTerminalDropdown(projectId) {
        const select = document.getElementById('task-terminal');
        if (!select) return;

        try {
            const data = await apiFetch(`/api/projects/${projectId}/sessions`);
            const sessions = data.sessions || [];
            sessions.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s.id;
                opt.textContent = s.name || s.id.substring(0, 12);
                opt.title = s.first_prompt || '';
                select.appendChild(opt);
            });
        } catch (e) {
            console.error('Failed to load sessions for dropdown:', e);
        }
    }

    async function _fetchTasks(projectId) {
        const area = document.getElementById('task-list-area');
        if (!area) return;

        const mode = getMode();
        const runLabel = mode === 'interactive' ? 'Open in Terminal' : 'Run';

        try {
            const [pending, running, dispatched] = await Promise.all([
                apiFetch(`/api/tasks?project_id=${projectId}&status=pending`),
                apiFetch(`/api/tasks?project_id=${projectId}&status=running`),
                apiFetch(`/api/tasks?project_id=${projectId}&status=dispatched`),
            ]);

            let html = '';

            // Running tasks first (with execution log area)
            running.forEach(t => {
                html += `<div class="task-item running">
                    <div class="task-title clickable" onclick="showTaskDetail('${t.id}')">${escapeHtml(t.title)} <span class="running-indicator"></span></div>
                    <div class="task-meta">Running...
                        <button class="show-terminal-btn" onclick="showTerminal()">Show Terminal</button>
                    </div>
                    <div class="execution-log" id="exec-log-${t.id}"></div>
                </div>`;
                // Auto-connect to SSE stream
                setTimeout(() => TaskStream.connect(t.id), 100);
            });

            // Dispatched tasks (sent to interactive terminal)
            dispatched.forEach(t => {
                html += `<div class="task-item dispatched">
                    <div class="task-title clickable" onclick="showTaskDetail('${t.id}')">${escapeHtml(t.title)} <span class="dispatched-indicator"></span></div>
                    <div class="task-meta">Sent to terminal | ${formatDate(t.created_at)}</div>
                    <div class="task-actions">
                        <button class="delete-btn" onclick="event.stopPropagation(); deleteTask('${t.id}')" title="Remove task">x</button>
                        <button class="done-btn" onclick="event.stopPropagation(); markTaskDone('${t.id}')">Mark Done</button>
                    </div>
                </div>`;
            });

            // Pending tasks
            pending.forEach(t => {
                html += `<div class="task-item">
                    <div class="task-title clickable" onclick="showTaskDetail('${t.id}')">${escapeHtml(t.title)}</div>
                    <div class="task-meta">Risk ${t.risk_tier} | ${formatDate(t.created_at)}</div>
                    <div class="task-actions">
                        <button class="delete-btn" onclick="event.stopPropagation(); deleteTask('${t.id}')" title="Remove task">x</button>
                        <button class="run-btn" onclick="event.stopPropagation(); executeTask('${t.id}')">${runLabel}</button>
                    </div>
                </div>`;
            });

            if (!html) {
                html = '<div class="empty-state">No pending tasks — click + Task to create one</div>';
            }

            area.innerHTML = html;
        } catch (e) {
            area.innerHTML = '<div class="empty-state">Error loading tasks</div>';
        }
    }

    function renderCompletedOrSessions(project) {
        const mode = getMode();
        if (mode === 'interactive') {
            renderSessions(project);
        } else {
            renderCompletedTasks(project);
        }
    }

    function renderSessions(project) {
        const el = document.getElementById('panel-completed-content');
        if (!project) {
            el.innerHTML = '<div class="empty-state">Select a project</div>';
            return;
        }

        el.innerHTML = '<div class="empty-state">Loading sessions...</div>';

        apiFetch(`/api/projects/${project.id}/sessions`).then(data => {
            const sessions = data.sessions || [];
            if (sessions.length === 0) {
                el.innerHTML = `<div class="session-actions">
                    <button class="run-btn" onclick="openClaudeCode('${project.id}')">New Claude Code Session</button>
                </div>
                <div class="empty-state">No Claude Code sessions found for this project</div>`;
                return;
            }

            let html = `<div class="session-actions">
                <button class="run-btn" onclick="openClaudeCode('${project.id}')">New Session</button>
                <button onclick="refreshSessions()">Refresh</button>
            </div>`;

            sessions.forEach(s => {
                const name = escapeHtml(s.name || s.id.substring(0, 12));
                const meta = [];
                if (s.message_count > 0) meta.push(`${s.message_count} msgs`);
                if (s.last_active) meta.push(formatDate(s.last_active));
                if (s.is_sidechain) meta.push('fork');

                html += `<div class="session-item" onclick="resumeSession('${project.id}', '${s.id}')" title="${escapeHtml(s.first_prompt || '')}">
                    <div class="session-name">${name}</div>
                    <div class="session-meta">${meta.join(' | ')}</div>
                </div>`;
            });

            el.innerHTML = html;
        }).catch(() => {
            el.innerHTML = '<div class="empty-state">Error loading sessions</div>';
        });
    }

    function renderCompletedTasks(project) {
        const el = document.getElementById('panel-completed-content');
        if (!project) {
            el.innerHTML = '<div class="empty-state">Select a project</div>';
            return;
        }

        Promise.all([
            apiFetch(`/api/tasks?project_id=${project.id}&status=completed`),
            apiFetch(`/api/tasks?project_id=${project.id}&status=failed`),
        ]).then(([completed, failed]) => {
            const all = [...completed, ...failed].sort(
                (a, b) => (b.completed_at || '').localeCompare(a.completed_at || '')
            );
            if (all.length === 0) {
                el.innerHTML = '<div class="empty-state">No completed tasks yet</div>';
                return;
            }
            el.innerHTML = all.map(t => {
                const isOk = t.status === 'completed';
                const tokens = t.token_input + t.token_output;
                return `<div class="task-item ${t.status} clickable" onclick="showTaskDetail('${t.id}')" title="Click to view details">
                    <div class="task-title">
                        <span style="color:${isOk ? '#66bb6a' : '#ef5350'}">${isOk ? 'OK' : 'FAIL'}</span>
                        ${escapeHtml(t.title)}
                    </div>
                    <div class="task-meta">
                        ${tokens.toLocaleString()} tokens | $${t.cost_usd.toFixed(4)} | ${formatDate(t.completed_at)}
                    </div>
                    ${t.result ? `<div class="task-result">${escapeHtml(t.result.substring(0, 300))}${t.result.length > 300 ? '...' : ''}</div>` : ''}
                    ${t.error ? `<div class="task-error">${escapeHtml(t.error)}</div>` : ''}
                </div>`;
            }).join('');
        }).catch(() => {
            el.innerHTML = '<div class="empty-state">Error loading tasks</div>';
        });
    }

    function _populateAllTasksDropdown() {
        const sel = document.getElementById('all-tasks-filter');
        if (!sel || !allProjects) return;
        // Preserve current value
        const cur = sel.value;
        // Remove project options (keep placeholder + All Projects)
        while (sel.options.length > 2) sel.remove(2);
        allProjects.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name;
            sel.appendChild(opt);
        });
        // Restore selection
        if (cur) sel.value = cur;
    }

    function onAllTasksFilterChange(value) {
        _allTasksFilter = value || null;
        renderAllTasks();
    }

    function _syncAllTasksFilter(project) {
        if (!project) return;
        // On first project selection, or if tracking a specific project, follow it
        if (_allTasksFilter === null || (_allTasksFilter !== '__all__' && _allTasksFilter !== null)) {
            _allTasksFilter = project.id;
            const sel = document.getElementById('all-tasks-filter');
            if (sel) sel.value = project.id;
        }
    }

    function renderAllTasks() {
        const el = document.getElementById('panel-progress-content');

        _populateAllTasksDropdown();

        if (!_allTasksFilter) {
            el.innerHTML = '<div class="empty-state">Select a project</div>';
            return;
        }

        const qs = _allTasksFilter === '__all__' ? '' : `&project_id=${_allTasksFilter}`;

        Promise.all([
            apiFetch(`/api/tasks?status=running${qs}`),
            apiFetch(`/api/tasks?status=pending${qs}`),
            apiFetch(`/api/tasks?status=completed${qs}`),
            apiFetch(`/api/tasks?status=failed${qs}`),
            apiFetch(`/api/tasks?status=dispatched${qs}`),
        ]).then(([running, pending, completed, failed, dispatched]) => {
            let html = '';

            // Summary counts
            const total = running.length + pending.length + completed.length + failed.length + dispatched.length;
            html += `<div class="all-tasks-summary">
                ${_countBadge(running.length, 'running', '#00bcd4')}
                ${_countBadge(dispatched.length, 'dispatched', '#4fc3f7')}
                ${_countBadge(pending.length, 'pending', '#ffa726')}
                ${_countBadge(completed.length, 'done', '#66bb6a')}
                ${_countBadge(failed.length, 'failed', '#ef5350')}
            </div>`;

            const emptyLabel = _allTasksFilter === '__all__' ? 'No tasks across any project' : 'No tasks for this project';
            if (total === 0) {
                html += `<div class="empty-state">${emptyLabel}</div>`;
                el.innerHTML = html;
                return;
            }

            const showProject = _allTasksFilter === '__all__';

            // Running tasks first
            running.forEach(t => {
                html += _allTaskRow(t, '#00bcd4', 'RUN', showProject);
            });

            // Dispatched tasks
            dispatched.forEach(t => {
                html += _allTaskRow(t, '#4fc3f7', 'SENT', showProject);
            });

            // Pending tasks
            pending.forEach(t => {
                html += _allTaskRow(t, '#ffa726', 'WAIT', showProject);
            });

            // Recent completed/failed (last 5)
            const recent = [...completed, ...failed]
                .sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || ''))
                .slice(0, 5);
            recent.forEach(t => {
                const color = t.status === 'completed' ? '#66bb6a' : '#ef5350';
                const label = t.status === 'completed' ? 'OK' : 'FAIL';
                html += _allTaskRow(t, color, label, showProject);
            });

            el.innerHTML = html;
        }).catch(() => {
            el.innerHTML = '<div class="empty-state">Error loading tasks</div>';
        });
    }

    function _countBadge(count, label, color) {
        return `<span class="count-badge" style="color:${color};border-color:${color}30">${count} ${label}</span>`;
    }

    function _allTaskRow(t, color, label, showProject) {
        const projectSpan = showProject
            ? `<span class="all-task-project" onclick="event.stopPropagation(); selectProjectById('${t.project_id}')">${escapeHtml(t.project_id)}</span>`
            : '';
        return `<div class="all-task-row" onclick="showTaskDetail('${t.id}')">
            <span class="all-task-status" style="color:${color}">${label}</span>
            ${projectSpan}
            <span class="all-task-title">${escapeHtml(t.title)}</span>
        </div>`;
    }

    function _getDismissedSuggestions() {
        try {
            return JSON.parse(localStorage.getItem('dismissed_suggestions') || '[]');
        } catch { return []; }
    }

    function _dismissKey(projectId, text) {
        return `${projectId}::${text}`;
    }

    function dismissSuggestion(projectId, text) {
        const dismissed = _getDismissedSuggestions();
        const key = _dismissKey(projectId, text);
        if (!dismissed.includes(key)) {
            dismissed.push(key);
            localStorage.setItem('dismissed_suggestions', JSON.stringify(dismissed));
        }
        // Re-render with the current project
        if (typeof selectedProject !== 'undefined' && selectedProject) {
            renderSuggestions(selectedProject);
        }
    }

    function renderSuggestions(project) {
        const el = document.getElementById('panel-suggestions-content');
        if (!project) {
            el.innerHTML = '<div class="empty-state">Select a project</div>';
            return;
        }
        const dismissed = _getDismissedSuggestions();
        const suggestions = [];
        const missing = project.missing_base_dirs || [];
        if (missing.length > 0) {
            suggestions.push({
                text: `Scaffold ${missing.length} missing base dir${missing.length > 1 ? 's' : ''}: ${missing.join(', ')}`,
                title: 'Scaffold missing base directories',
                desc: `Create the following base directories: ${missing.join(', ')}. These are part of the standard project structure.`,
                tier: 3,
                action: 'scaffold',
            });
        }
        if (project.git_dirty) {
            suggestions.push({
                text: 'Commit uncommitted changes',
                title: 'Review and commit uncommitted changes',
                desc: 'Check git status, review the uncommitted changes, and create a meaningful commit with a descriptive message.',
                tier: 2,
            });
        }
        if (project.status === 'idle') {
            suggestions.push({
                text: 'Review project — not modified recently',
                title: 'Review project status and suggest improvements',
                desc: 'Read the project README and key files, assess the current state, and suggest concrete next steps or improvements.',
                tier: 1,
            });
        }
        // Filter out dismissed suggestions
        const visible = suggestions.filter(
            s => !dismissed.includes(_dismissKey(project.id, s.text))
        );
        if (visible.length === 0) {
            el.innerHTML = '<div class="empty-state">Project is up to date</div>';
            el._suggestions = [];
            return;
        }
        el.innerHTML = visible.map((s, i) => {
            const clickAction = s.action === 'scaffold'
                ? `scaffoldProject('${project.id}')`
                : `addSuggestionAsTask(${i})`;
            const actionLabel = s.action === 'scaffold' ? 'Click to scaffold' : 'Click to add as task';
            return `<div class="suggestion-item clickable" title="${actionLabel}">
                <span class="suggestion-num" onclick="${clickAction}">${i + 1}</span>
                <span class="suggestion-text" onclick="${clickAction}">${s.text}</span>
                <button class="dismiss-btn" onclick="event.stopPropagation(); Panels.dismissSuggestion('${project.id}', '${s.text.replace(/'/g, "\\'")}')" title="Dismiss">&times;</button>
            </div>`;
        }).join('');
        // Stash suggestion data for the click handler
        el._suggestions = visible;
    }

    function renderAgentsTokens(project) {
        const el = document.getElementById('panel-agents-content');

        apiFetch('/api/agents/stats').then(stats => {
            el.innerHTML = `
                <div class="info-rows">
                    ${infoRow('Active', stats.busy_agents)}
                    ${infoRow('Total Agents', stats.total_agents)}
                    ${infoRow('Input Tokens', stats.total_tokens_in.toLocaleString())}
                    ${infoRow('Output Tokens', stats.total_tokens_out.toLocaleString())}
                    ${infoRow('Total Cost', '$' + stats.total_cost_usd.toFixed(4))}
                </div>
                <div id="live-token-display"></div>
            `;
        }).catch(() => {
            el.innerHTML = '<div class="empty-state">No agents configured</div>';
        });
    }

    function toggleTaskForm() {
        _taskFormVisible = !_taskFormVisible;
        const form = document.getElementById('task-form');
        if (form) form.style.display = _taskFormVisible ? 'block' : 'none';

        // Populate terminal dropdown when opening in interactive mode
        if (_taskFormVisible && getMode() === 'interactive' && typeof selectedProject !== 'undefined' && selectedProject) {
            _populateTerminalDropdown(selectedProject.id);
        }
    }

    function appendExecutionLog(type, text) {
        // Find any execution log container currently visible
        const logs = document.querySelectorAll('.execution-log');
        if (logs.length === 0) return;
        const logEl = logs[logs.length - 1];

        const colors = {
            thinking: '#90a4ae',
            tool_call: '#4fc3f7',
            tool_result: '#66bb6a',
            complete: '#66bb6a',
            error: '#ef5350',
        };

        const entry = document.createElement('div');
        entry.className = `log-entry log-${type}`;
        entry.innerHTML = `<span class="log-type" style="color:${colors[type] || '#90a4ae'}">[${type}]</span> ${escapeHtml(text)}`;
        logEl.appendChild(entry);
        logEl.scrollTop = logEl.scrollHeight;
    }

    function updateTokenDisplay(inputTokens, outputTokens) {
        const el = document.getElementById('live-token-display');
        if (el) {
            el.innerHTML = `<div class="info-rows" style="margin-top:0.3rem;border-top:1px solid #2a3a4a;padding-top:0.3rem;">
                ${infoRow('Live In', inputTokens.toLocaleString())}
                ${infoRow('Live Out', outputTokens.toLocaleString())}
            </div>`;
        }
    }

    function onTaskCompleted(taskId) {
        if (typeof selectedProject !== 'undefined' && selectedProject) {
            renderCompletedOrSessions(selectedProject);
            renderAgentsTokens(selectedProject);
        }
    }

    function onTaskFailed(taskId) {
        if (typeof selectedProject !== 'undefined' && selectedProject) {
            renderCompletedOrSessions(selectedProject);
            renderAgentsTokens(selectedProject);
        }
    }

    function updateAll(project) {
        renderProjectStatus(project);
        renderUpcomingTasks(project);
        renderCompletedOrSessions(project);
        _syncAllTasksFilter(project);
        renderAllTasks();
        renderSuggestions(project);
        renderAgentsTokens(project);
    }

    function infoRow(label, value) {
        return `<div class="info-row"><span class="info-label">${label}</span><span class="info-value">${value}</span></div>`;
    }

    return {
        updateAll,
        renderAllTasks,
        renderSessions,
        onAllTasksFilterChange,
        toggleTaskForm,
        appendExecutionLog,
        updateTokenDisplay,
        onTaskCompleted,
        onTaskFailed,
        dismissSuggestion,
        showTaskForm: () => { _taskFormVisible = true; toggleTaskForm(); toggleTaskForm(); },
    };
})();
