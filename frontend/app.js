/**
 * Dimension — Autonomous Data & Schema Studio
 * Frontend Application Controller
 * Multi-Chat Sessions, Schema Cartography, Executable SQL Runner, Interactive Data Grid
 */

document.addEventListener('DOMContentLoaded', () => {
    // DOM Element References
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const statusMsg = document.getElementById('upload-status');
    const chatForm = document.getElementById('chat-form');
    const queryInput = document.getElementById('query-input');
    const chatBox = document.getElementById('chat-box');
    const sendBtn = document.getElementById('send-btn');
    const keyHint = document.getElementById('key-hint');
    const documentsList = document.getElementById('documents-list');
    const docCount = document.getElementById('doc-count');
    const clearAllBtn = document.getElementById('clear-all-btn');
    const newChatBtn = document.getElementById('new-chat-btn');
    const sidebarNewChatBtn = document.getElementById('sidebar-new-chat-btn');
    const sessionsList = document.getElementById('sessions-list');
    const chatCount = document.getElementById('chat-count');
    const activeChatTitle = document.getElementById('active-chat-title');
    const modelSelect = document.getElementById('model-select');
    const effortSelect = document.getElementById('effort-select');
    const safetyModeSelect = document.getElementById('safety-mode-select');
    const activeModelBadge = document.getElementById('active-model-badge');
    const sidebar = document.getElementById('sidebar');
    const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
    const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    const themeIcon = document.getElementById('theme-icon');
    const themeLabel = document.getElementById('theme-label');
    const focusToggleBtn = document.getElementById('focus-toggle-btn');
    const appContainer = document.querySelector('.app-container') || document.body;

    // Data Studio Schema & Modal References
    const connectDbBtn = document.getElementById('connect-db-btn');
    const dbModal = document.getElementById('db-modal');
    const dbModalCloseBtn = document.getElementById('db-modal-close-btn');
    const dbModalCancelBtn = document.getElementById('db-modal-cancel-btn');
    const dbModalConnectBtn = document.getElementById('db-modal-connect-btn');
    const dbConnectionInput = document.getElementById('db-connection-input');
    const dbModalStatus = document.getElementById('db-modal-status');
    const tablesList = document.getElementById('tables-list');
    const tableCount = document.getElementById('table-count');
    const refreshTablesBtn = document.getElementById('refresh-tables-btn');
    const sidebarEngineName = document.getElementById('sidebar-engine-name');
    const sidebarTelemetryText = document.getElementById('sidebar-telemetry-text');

    // Focus Mode Engine (Distraction-Free Deep Canvas)
    let isFocusMode = localStorage.getItem('dimension_focus_mode') === '1';
    const applyFocusMode = (enabled) => {
        isFocusMode = enabled;
        try {
            localStorage.setItem('dimension_focus_mode', isFocusMode ? '1' : '0');
        } catch (e) {}

        const expandIcon = focusToggleBtn ? focusToggleBtn.querySelector('.focus-icon-expand') : null;
        const shrinkIcon = focusToggleBtn ? focusToggleBtn.querySelector('.focus-icon-shrink') : null;

        if (isFocusMode) {
            appContainer.classList.add('focus-mode');
            if (focusToggleBtn) {
                focusToggleBtn.classList.add('active');
                focusToggleBtn.title = 'Exit Focus Mode (Cmd+Shift+F)';
            }
            if (expandIcon) expandIcon.classList.add('hidden');
            if (shrinkIcon) shrinkIcon.classList.remove('hidden');
        } else {
            appContainer.classList.remove('focus-mode');
            if (focusToggleBtn) {
                focusToggleBtn.classList.remove('active');
                focusToggleBtn.title = 'Toggle Focus Mode (Cmd+Shift+F)';
            }
            if (expandIcon) expandIcon.classList.remove('hidden');
            if (shrinkIcon) shrinkIcon.classList.add('hidden');
        }
    };
    applyFocusMode(isFocusMode);

    if (focusToggleBtn) {
        focusToggleBtn.addEventListener('click', () => {
            applyFocusMode(!isFocusMode);
        });
    }

    // Theme Engine: Light & Dark
    let currentTheme = localStorage.getItem('dimension_theme') || 'light';
    const applyTheme = (theme) => {
        currentTheme = theme;
        document.documentElement.setAttribute('data-theme', theme);
        if (document.body) {
            document.body.setAttribute('data-theme', theme);
        }
        try {
            localStorage.setItem('dimension_theme', theme);
        } catch (e) {}
        if (themeIcon) {
            themeIcon.textContent = theme === 'light' ? '☀️' : '🌙';
        }
        if (themeLabel) {
            themeLabel.textContent = theme === 'light' ? 'Light' : 'Dark';
        }
        if (themeToggleBtn) {
            const nextLabel = theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode';
            themeToggleBtn.title = nextLabel;
            themeToggleBtn.setAttribute('aria-label', nextLabel);
        }
        if (typeof CustomEvent !== 'undefined') {
            window.dispatchEvent(new CustomEvent('dimension:themechange', { detail: { theme } }));
        }
    };
    applyTheme(currentTheme);

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            applyTheme(currentTheme === 'light' ? 'dark' : 'light');
        });
    }

    // Application State
    let activeSessionId = null;
    let currentAbortController = null;
    let selectedModel = 'llama3';
    let selectedEffort = 'medium';
    let selectedSafetyMode = 'read_only';
    let currentSchema = null;

    // SVG Micro-Icon Library (Lucide/Phosphor Style)
    const ICONS = {
        bot: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
            <line x1="8" y1="21" x2="16" y2="21"></line>
            <line x1="12" y1="17" x2="12" y2="21"></line>
        </svg>`,
        user: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
        </svg>`,
        chat: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>`,
        table: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
            <line x1="3" y1="9" x2="21" y2="9"></line>
            <line x1="9" y1="21" x2="9" y2="9"></line>
        </svg>`,
        key: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="7.5" cy="15.5" r="5.5"></circle>
            <path d="m21 2-9.6 9.6"></path>
            <path d="m15.5 7.5 3 3L22 7l-3-3"></path>
        </svg>`,
        docPdf: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f87171" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
        </svg>`,
        docData: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
        </svg>`,
        routeLocal: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
        </svg>`,
        routeWeb: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="2" y1="12" x2="22" y2="12"></line>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
        </svg>`,
        externalLink: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
            <polyline points="15 3 21 3 21 9"></polyline>
            <line x1="10" y1="14" x2="21" y2="3"></line>
        </svg>`,
        pencil: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
        </svg>`,
        pin: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="17" x2="12" y2="22"></line>
            <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"></path>
        </svg>`,
        archive: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="21 8 21 21 3 21 3 8"></polyline>
            <rect x="1" y="3" width="22" height="5"></rect>
            <line x1="10" y1="12" x2="14" y2="12"></line>
        </svg>`,
        trash: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>`,
        dots: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="1.5"></circle>
            <circle cx="19" cy="12" r="1.5"></circle>
            <circle cx="5" cy="12" r="1.5"></circle>
        </svg>`
    };

    // Utilities
    const escapeHtml = (str) => {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    const formatSessionTitle = (title, maxLen = 18) => {
        if (!title) return 'New Chat';
        const trimmed = title.trim();
        if (trimmed.length <= maxLen) return trimmed;
        return trimmed.substring(0, maxLen).trimEnd() + '...';
    };

    const formatBytes = (bytes) => {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    };

    // Stream Interruption & Generating State
    const setGenerating = (isGenerating) => {
        if (isGenerating) {
            sendBtn.classList.add('is-generating');
            sendBtn.title = 'Stop generating (Esc)';
            if (keyHint) keyHint.innerHTML = '<kbd class="kbd-badge">Esc</kbd>';
        } else {
            sendBtn.classList.remove('is-generating');
            sendBtn.title = 'Send query (Enter)';
            if (keyHint) keyHint.innerHTML = '<kbd class="kbd-badge">↵</kbd>';
            currentAbortController = null;
        }
    };

    // Sidebar Collapse / Expand Functionality
    const toggleSidebar = () => {
        if (!sidebar) return;
        const isCollapsed = sidebar.classList.toggle('collapsed');
        try {
            localStorage.setItem('sidebar_collapsed', isCollapsed ? '1' : '0');
        } catch (e) {}
        if (sidebarToggleBtn) {
            sidebarToggleBtn.classList.toggle('active', isCollapsed);
        }
    };

    if (sidebarToggleBtn) sidebarToggleBtn.addEventListener('click', toggleSidebar);
    if (sidebarCollapseBtn) sidebarCollapseBtn.addEventListener('click', toggleSidebar);

    try {
        if (localStorage.getItem('sidebar_collapsed') === '1' && sidebar) {
            sidebar.classList.add('collapsed');
            if (sidebarToggleBtn) sidebarToggleBtn.classList.add('active');
        }
    } catch (e) {}

    // Global Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            startNewChat();
        }
        if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'f') {
            e.preventDefault();
            applyFocusMode(!isFocusMode);
        }
        if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'b') {
            e.preventDefault();
            toggleSidebar();
        }
        if (e.key === 'Escape') {
            if (dbModal && !dbModal.classList.contains('hidden')) {
                closeDbModal();
                return;
            }
            if (activeDropdownMenu) {
                closeAllDropdowns();
                return;
            }
            if (currentAbortController) {
                e.preventDefault();
                currentAbortController.abort();
            }
        }
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.session-dropdown-menu') && !e.target.closest('.session-menu-trigger')) {
            closeAllDropdowns();
        }
    });

    // ==========================================================================
    // 1. Model, Effort & Safety Settings
    // ==========================================================================
    const fetchModels = async () => {
        try {
            const res = await fetch('/api/models');
            if (!res.ok) return;
            const data = await res.json();
            if (data.models && data.models.length > 0) {
                modelSelect.innerHTML = '';
                data.models.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m;
                    opt.textContent = m;
                    if (m === data.default_model) opt.selected = true;
                    modelSelect.appendChild(opt);
                });
                selectedModel = data.default_model;
                updateModelBadge();
            }
        } catch (err) {
            console.warn('Could not fetch models from server:', err);
        }
    };

    const updateModelBadge = () => {
        if (activeModelBadge) {
            activeModelBadge.textContent = `${selectedModel} · ${selectedEffort}`;
        }
    };

    if (modelSelect) {
        modelSelect.addEventListener('change', (e) => {
            selectedModel = e.target.value;
            updateModelBadge();
            if (activeSessionId) {
                fetch(`/api/sessions/${activeSessionId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model: selectedModel })
                }).catch(() => {});
            }
        });
    }

    if (effortSelect) {
        effortSelect.addEventListener('change', (e) => {
            selectedEffort = e.target.value;
            updateModelBadge();
            if (activeSessionId) {
                fetch(`/api/sessions/${activeSessionId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ effort: selectedEffort })
                }).catch(() => {});
            }
        });
    }

    // Safety Mode Selector
    if (safetyModeSelect) {
        const selectorGroup = safetyModeSelect.closest ? safetyModeSelect.closest('.selector-safety') : null;
        safetyModeSelect.addEventListener('change', (e) => {
            selectedSafetyMode = e.target.value;
            if (selectorGroup) {
                selectorGroup.classList.toggle('mutation-mode', selectedSafetyMode === 'mutation');
            }
        });
    }

    // ==========================================================================
    // 2. Database Connection Modal & Introspection
    // ==========================================================================
    const openDbModal = () => {
        if (!dbModal) return;
        dbModal.classList.remove('hidden');
        dbModal.setAttribute('aria-hidden', 'false');
        if (dbConnectionInput) {
            dbConnectionInput.focus();
        }
    };

    const closeDbModal = () => {
        if (!dbModal) return;
        dbModal.classList.add('hidden');
        dbModal.setAttribute('aria-hidden', 'true');
        if (dbModalStatus) {
            dbModalStatus.classList.add('hidden');
            dbModalStatus.textContent = '';
        }
    };

    if (connectDbBtn) connectDbBtn.addEventListener('click', openDbModal);
    if (dbModalCloseBtn) dbModalCloseBtn.addEventListener('click', closeDbModal);
    if (dbModalCancelBtn) dbModalCancelBtn.addEventListener('click', closeDbModal);

    // Click outside modal card to close
    if (dbModal) {
        dbModal.addEventListener('click', (e) => {
            if (e.target === dbModal) closeDbModal();
        });
    }

    // Quick Presets
    document.querySelectorAll('.preset-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            if (dbConnectionInput && pill.dataset.preset) {
                dbConnectionInput.value = pill.dataset.preset;
                dbConnectionInput.focus();
            }
        });
    });

    // Connect & Introspect Submission handled by Studio Workbench v2
    // Expose renderTables for Studio Workbench synchronization
    window.DimensionRenderTables = (tables) => renderTables(tables);

    const showModalStatus = (msg, type) => {
        if (!dbModalStatus) return;
        dbModalStatus.textContent = msg;
        dbModalStatus.className = `status-message ${type}`;
        dbModalStatus.classList.remove('hidden');
    };

    const updateEngineTelemetry = (engine, dbName) => {
        // Redundant Vault/Telemetry labels removed per design requirements
    };

    // ==========================================================================
    // 3. Schema & Tables Tree Management
    // ==========================================================================
    const fetchSchema = async () => {
        try {
            const res = await fetch('/api/db/schema');
            if (!res.ok) {
                // If service initializing or no active connection, show clean placeholder
                renderTables([]);
                return;
            }
            const data = await res.json();
            currentSchema = data;
            updateEngineTelemetry(data.engine, data.database_name);
            renderTables(data.tables || []);
        } catch (err) {
            renderTables([]);
        }
    };

    if (refreshTablesBtn) {
        refreshTablesBtn.addEventListener('click', () => {
            fetchSchema();
        });
    }

    const renderTables = (tables) => {
        if (tableCount) tableCount.textContent = tables.length;
        if (!tablesList) return;

        if (tables.length === 0) {
            tablesList.innerHTML = `
                <div class="empty-tables-placeholder">
                    No tables connected yet.<br>
                    <span class="empty-sub" style="font-size: 10px; color: var(--text-subtle);">Upload dataset or connect database</span>
                </div>
            `;
            return;
        }

        tablesList.innerHTML = '';
        tables.forEach(tbl => {
            const item = document.createElement('div');
            item.className = 'table-item';

            const formattedRowCount = tbl.row_count >= 1000 
                ? (tbl.row_count / 1000).toFixed(1) + 'k' 
                : tbl.row_count;

            item.innerHTML = `
                <div class="table-item-header">
                    <div class="table-item-left">
                        <span class="table-icon">${ICONS.table}</span>
                        <span class="table-name" title="${tbl.name}">${escapeHtml(tbl.name)}</span>
                    </div>
                    <div class="table-item-right">
                        <span class="table-row-count-badge">${formattedRowCount} rows</span>
                        <span class="table-chevron">▸</span>
                    </div>
                </div>
                <div class="table-columns-drawer hidden">
                    <div class="columns-list">
                        ${(tbl.columns || []).map(col => `
                            <div class="column-row" title="${col.name} (${col.data_type})">
                                <div class="column-name-group">
                                    ${col.primary_key ? `<span class="column-pk-icon" title="Primary Key">🔑</span>` : ''}
                                    <span class="column-name">${escapeHtml(col.name)}</span>
                                </div>
                                <div class="column-meta-group">
                                    <span class="column-type">${escapeHtml(col.data_type)}</span>
                                    <span class="column-null-pill">${col.nullable ? 'null' : 'req'}</span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                    <div class="table-drawer-actions">
                        <button type="button" class="table-drawer-btn query-sample-btn" title="Run sample query">
                            <span>Sample 10</span>
                        </button>
                        <button type="button" class="table-drawer-btn profile-table-btn" title="Run anomaly & hygiene scan">
                            <span>Profile</span>
                        </button>
                    </div>
                </div>
            `;

            const header = item.querySelector('.table-item-header');
            const drawer = item.querySelector('.table-columns-drawer');
            header.addEventListener('click', () => {
                const isOpen = item.classList.toggle('open');
                drawer.classList.toggle('hidden', !isOpen);
            });

            // Action: Sample 10 rows
            const sampleBtn = item.querySelector('.query-sample-btn');
            sampleBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (queryInput && chatForm) {
                    queryInput.value = `SELECT * FROM ${tbl.name} LIMIT 10;`;
                    chatForm.dispatchEvent(new Event('submit', { cancelable: true }));
                }
            });

            // Action: Profile table
            const profileBtn = item.querySelector('.profile-table-btn');
            profileBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (queryInput && chatForm) {
                    queryInput.value = `Profile table ${tbl.name} and detect any anomalies, distribution skew, or PII risks.`;
                    chatForm.dispatchEvent(new Event('submit', { cancelable: true }));
                }
            });

            tablesList.appendChild(item);
        });
    };

    // ==========================================================================
    // 4. File Upload & Data Ingestion (.csv, .tsv, .parquet, .sqlite, .db)
    // ==========================================================================
    const handleFile = async (file) => {
        if (!file) return;
        const fileName = file.name.toLowerCase();

        const dbExtensions = ['.csv', '.tsv', '.parquet', '.pq', '.sqlite', '.sqlite3', '.db'];
        const isDbFile = dbExtensions.some(ext => fileName.endsWith(ext));

        if (!isDbFile) {
            showStatus(`Format not supported: "${file.name}". Dimension Data Studio only accepts structured database & tabular files (.csv, .tsv, .parquet, .sqlite, .db). Document formats (.pdf, .docx, .txt, .md) are not supported.`, 'error');
            return;
        }

        showStatus(`Ingesting and introspecting ${file.name}...`, 'success');
        dropZone.style.pointerEvents = 'none';
        dropZone.style.opacity = '0.6';

        const formData = new FormData();
        formData.append('file', file);

        try {
            // Ingest directly into active SQL database engine
            const response = await fetch('/api/db/connect', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();
            if (response.ok) {
                showStatus(`Successfully attached dataset ${file.name}!`, 'success');
                currentSchema = data;
                renderTables(data.tables || []);
                updateEngineTelemetry(data.engine, file.name);
            } else {
                showStatus(data.detail || data.error || 'Dataset ingestion failed.', 'error');
            }
        } catch (error) {
            showStatus('Network error during ingestion.', 'error');
        } finally {
            dropZone.style.pointerEvents = 'auto';
            dropZone.style.opacity = '1';
        }
    };

    const showStatus = (msg, type) => {
        if (!statusMsg) return;
        statusMsg.textContent = msg;
        statusMsg.className = `status-message ${type}`;
        statusMsg.classList.remove('hidden');
    };

    // Drag-and-drop events
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        if (dropZone) dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    if (dropZone) {
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
        });

        dropZone.addEventListener('drop', (e) => {
            const file = e.dataTransfer.files[0];
            handleFile(file);
        });

        dropZone.addEventListener('click', () => fileInput && fileInput.click());
    }

    if (fileInput) {
        fileInput.addEventListener('change', function () {
            handleFile(this.files[0]);
        });
    }

    // ==========================================================================
    // 5. Multi-Chat Sessions & Options Menu
    // ==========================================================================
    let activeDropdownMenu = null;

    const closeAllDropdowns = () => {
        if (activeDropdownMenu) {
            activeDropdownMenu.remove();
            activeDropdownMenu = null;
        }
        document.querySelectorAll('.session-item.menu-active').forEach(el => {
            el.classList.remove('menu-active');
        });
    };

    const updateSessionProperty = async (sessionId, updates) => {
        try {
            const res = await fetch(`/api/sessions/${sessionId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            });
            if (res.ok) {
                await fetchSessions();
            }
        } catch (err) {
            console.error('Failed to update session properties:', err);
        }
    };

    const startInlineRename = (sessionItem, s) => {
        const titleSpan = sessionItem.querySelector('.session-title-text');
        if (!titleSpan) return;

        const currentTitle = s.title;
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'session-inline-rename-input';
        input.value = currentTitle;

        titleSpan.replaceWith(input);
        input.focus();
        input.select();

        let isSaved = false;

        const saveRename = async () => {
            if (isSaved) return;
            isSaved = true;
            const newTitle = input.value.trim() || currentTitle;
            if (newTitle !== currentTitle) {
                await updateSessionProperty(s.id, { title: newTitle });
            } else {
                fetchSessions();
            }
        };

        const cancelRename = () => {
            if (isSaved) return;
            isSaved = true;
            fetchSessions();
        };

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                input.blur();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                cancelRename();
            }
        });

        input.addEventListener('blur', saveRename);
    };

    const toggleSessionDropdown = (sessionItem, s) => {
        const isCurrentOpen = sessionItem.classList.contains('menu-active');
        closeAllDropdowns();
        if (isCurrentOpen) return;

        sessionItem.classList.add('menu-active');

        const menu = document.createElement('div');
        menu.className = 'session-dropdown-menu';
        menu.innerHTML = `
            <button class="session-dropdown-item rename-opt" type="button">
                ${ICONS.pencil}
                <span>Rename</span>
            </button>
            <button class="session-dropdown-item pin-opt" type="button">
                ${ICONS.pin}
                <span>${s.pinned ? 'Unpin' : 'Pin to Top'}</span>
            </button>
            <button class="session-dropdown-item archive-opt" type="button">
                ${ICONS.archive}
                <span>${s.archived ? 'Unarchive' : 'Archive'}</span>
            </button>
            <div class="session-dropdown-separator"></div>
            <button class="session-dropdown-item danger delete-opt" type="button">
                ${ICONS.trash}
                <span>Delete</span>
            </button>
        `;

        menu.querySelector('.rename-opt').addEventListener('click', (e) => {
            e.stopPropagation();
            closeAllDropdowns();
            startInlineRename(sessionItem, s);
        });

        menu.querySelector('.pin-opt').addEventListener('click', async (e) => {
            e.stopPropagation();
            closeAllDropdowns();
            await updateSessionProperty(s.id, { pinned: !s.pinned });
        });

        menu.querySelector('.archive-opt').addEventListener('click', async (e) => {
            e.stopPropagation();
            closeAllDropdowns();
            await updateSessionProperty(s.id, { archived: !s.archived });
        });

        menu.querySelector('.delete-opt').addEventListener('click', async (e) => {
            e.stopPropagation();
            closeAllDropdowns();
            deleteSession(s.id);
        });

        sessionItem.appendChild(menu);
        activeDropdownMenu = menu;
    };

    const startNewChat = () => {
        activeSessionId = null;
        try {
            sessionStorage.removeItem('dimension_active_session');
        } catch (e) {}

        document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
        if (activeChatTitle) activeChatTitle.textContent = 'New Thread';
        updateModelBadge();

        chatBox.innerHTML = renderWelcomeHero();
        if (queryInput) {
            queryInput.value = '';
            queryInput.focus();
        }
    };

    const fetchSessions = async () => {
        try {
            const res = await fetch('/api/sessions');
            if (!res.ok) return;
            const data = await res.json();
            const sessions = data.sessions || [];
            renderSessions(sessions);
            
            const savedSession = sessionStorage.getItem('dimension_active_session');
            if (savedSession && sessions.some(s => s.id === savedSession)) {
                if (activeSessionId !== savedSession) {
                    loadSession(savedSession);
                }
            } else if (!activeSessionId) {
                startNewChat();
            }
        } catch (err) {
            console.error('Failed to load chat sessions:', err);
        }
    };

    const renderSessions = (sessions) => {
        if (!sessionsList) return;

        const activeSessions = sessions.filter(s => !s.archived);
        const archivedSessions = sessions.filter(s => s.archived);

        if (chatCount) chatCount.textContent = activeSessions.length;

        if (sessions.length === 0) {
            sessionsList.innerHTML = '<div class="empty-docs-placeholder" style="padding: 10px;">No saved threads</div>';
            return;
        }

        sessionsList.innerHTML = '';

        const renderRow = (s) => {
            const item = document.createElement('div');
            item.className = `session-item ${s.id === activeSessionId ? 'active' : ''} ${s.pinned ? 'pinned' : ''}`;
            item.dataset.sessionId = s.id;
            item.title = s.title;

            const shortTitle = formatSessionTitle(s.title, 18);
            const pinIconHtml = s.pinned ? `<span class="session-pin-indicator" title="Pinned to top">📌</span>` : '';

            item.innerHTML = `
                <div class="session-item-left">
                    <div class="session-icon">${ICONS.chat}</div>
                    ${pinIconHtml}
                    <span class="session-title-text" data-session-id="${s.id}">${escapeHtml(shortTitle)}</span>
                </div>
                <button class="session-menu-trigger" data-session-id="${s.id}" title="Thread options" aria-label="Thread options">
                    ${ICONS.dots}
                </button>
            `;

            item.addEventListener('click', (e) => {
                if (e.target.closest('.session-menu-trigger') || e.target.closest('.session-dropdown-menu') || e.target.closest('.session-inline-rename-input')) {
                    return;
                }
                if (s.id !== activeSessionId) {
                    loadSession(s.id);
                }
            });

            const menuTrigger = item.querySelector('.session-menu-trigger');
            menuTrigger.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleSessionDropdown(item, s);
            });

            return item;
        };

        activeSessions.forEach(s => {
            sessionsList.appendChild(renderRow(s));
        });

        if (archivedSessions.length > 0) {
            const archiveSection = document.createElement('div');
            archiveSection.className = 'archived-sessions-wrapper';
            archiveSection.innerHTML = `
                <button class="archived-toggle-btn" type="button">
                    <span class="archived-toggle-label">${ICONS.archive} Archived (${archivedSessions.length})</span>
                    <span class="archived-toggle-arrow">▸</span>
                </button>
                <div class="archived-sessions-container hidden"></div>
            `;
            const toggleBtn = archiveSection.querySelector('.archived-toggle-btn');
            const container = archiveSection.querySelector('.archived-sessions-container');
            const arrow = archiveSection.querySelector('.archived-toggle-arrow');

            toggleBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const isHidden = container.classList.toggle('hidden');
                arrow.textContent = isHidden ? '▸' : '▾';
            });

            archivedSessions.forEach(s => {
                container.appendChild(renderRow(s));
            });
            sessionsList.appendChild(archiveSection);
        }
    };

    const createNewChat = async (initialTitle = 'New Chat') => {
        try {
            const res = await fetch('/api/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: initialTitle,
                    model: selectedModel,
                    effort: selectedEffort
                })
            });
            if (res.ok) {
                const session = await res.json();
                activeSessionId = session.id;
                try {
                    sessionStorage.setItem('dimension_active_session', session.id);
                } catch (e) {}
                await fetchSessions();
                return session;
            }
        } catch (err) {
            console.error('Failed to create new session:', err);
        }
        return null;
    };

    // ==========================================================================
    // 6. Welcome Hero with Data Studio Instant Workflows
    // ==========================================================================
    const renderWelcomeHero = () => {
        return `
            <div class="welcome-hero-container">
                <h1 class="welcome-hero-title">
                    All your data &amp; schemas,<br><span class="welcome-gradient-text">instantly introspected.</span>
                </h1>
                <p class="welcome-hero-desc">
                    Autonomous schema cartography, anomaly hygiene scans, and dialect-tuned SQL queries powered by in-memory DuckDB, PostgreSQL, MySQL, and SQLite engines.
                </p>
                <div class="capability-card">
                    <div class="capability-header">Instant Studio Capabilities</div>
                    <div class="capability-row" data-prompt="Run schema cartography on active tables, detect foreign key relationships, and identify orphan tables.">
                        <div class="capability-row-left">
                            <span class="capability-index">01</span>
                            <div>
                                <div class="capability-name">Schema Cartography &amp; Orphan Detection</div>
                                <div class="capability-sub">Introspect active tables, detect relational edges, and build schema dependency graphs.</div>
                            </div>
                        </div>
                        <span class="capability-arrow">→</span>
                    </div>
                    <div class="capability-row" data-prompt="Perform an anomaly and PII hygiene scan across tables to detect null bursts and sensitive data leaks.">
                        <div class="capability-row-left">
                            <span class="capability-index">02</span>
                            <div>
                                <div class="capability-name">Anomaly &amp; PII Hygiene Scan</div>
                                <div class="capability-sub">Continuous telemetry on null rates, distribution skew, and unmasked PII columns.</div>
                            </div>
                        </div>
                        <span class="capability-arrow">→</span>
                    </div>
                    <div class="capability-row" data-prompt="Generate an optimized SQL query to extract the top active records with aggregations.">
                        <div class="capability-row-left">
                            <span class="capability-index">03</span>
                            <div>
                                <div class="capability-name">Instant SQL Query &amp; Data Extraction</div>
                                <div class="capability-sub">Dialect-tuned queries with 1-click execution and interactive data grid analytics.</div>
                            </div>
                        </div>
                        <span class="capability-arrow">→</span>
                    </div>
                </div>
            </div>
        `;
    };

    if (chatBox) {
        chatBox.addEventListener('click', (e) => {
            const row = e.target.closest('.capability-row');
            if (row && row.dataset.prompt && queryInput) {
                queryInput.value = row.dataset.prompt;
                if (chatForm) {
                    chatForm.dispatchEvent(new Event('submit', { cancelable: true }));
                }
            }
        });
    }

    const loadSession = async (sessionId) => {
        activeSessionId = sessionId;
        try {
            sessionStorage.setItem('dimension_active_session', sessionId);
        } catch (e) {}
        
        document.querySelectorAll('.session-item').forEach(el => {
            el.classList.toggle('active', el.dataset.sessionId === sessionId);
        });
        
        try {
            const res = await fetch(`/api/sessions/${sessionId}`);
            if (!res.ok) return;
            const data = await res.json();
            
            const session = data.session;
            const messages = data.messages || [];

            if (activeChatTitle) activeChatTitle.textContent = session.title;
            if (session.model && modelSelect) {
                modelSelect.value = session.model;
                selectedModel = session.model;
            }
            if (session.effort && effortSelect) {
                effortSelect.value = session.effort;
                selectedEffort = session.effort;
            }
            updateModelBadge();

            chatBox.innerHTML = '';
            if (messages.length === 0) {
                chatBox.innerHTML = renderWelcomeHero();
            } else {
                messages.forEach(msg => {
                    appendMessage(msg.content, msg.role, msg.sources, msg.route, false);
                });
            }
            chatBox.scrollTop = chatBox.scrollHeight;
            
            document.querySelectorAll('.session-item').forEach(el => {
                el.classList.toggle('active', el.dataset.sessionId === sessionId);
            });
        } catch (err) {
            console.error('Failed to load session details:', err);
        }
    };

    const deleteSession = async (sessionId) => {
        if (!confirm('Delete this conversation thread?')) return;
        try {
            const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
            if (res.ok) {
                if (activeSessionId === sessionId) {
                    startNewChat();
                }
                await fetchSessions();
            }
        } catch (err) {
            console.error('Failed to delete session:', err);
        }
    };

    if (newChatBtn) newChatBtn.addEventListener('click', startNewChat);
    if (sidebarNewChatBtn) sidebarNewChatBtn.addEventListener('click', startNewChat);

    // ==========================================================================
    // 7. Backward-Compatible Document Helpers
    // ==========================================================================
    const fetchDocuments = async () => {
        try {
            const res = await fetch('/api/documents');
            if (!res.ok) return;
            const data = await res.json();
            if (docCount) docCount.textContent = (data.documents || []).length;
        } catch (err) {}
    };

    // ==========================================================================
    // 8. Citations & Message Rendering
    // ==========================================================================
    const attachSourcesToBubble = (contentDiv, sources, route = 'local_context') => {
        if (!sources || sources.length === 0) return;

        const isWeb = route === 'web_search' || sources.some(s => s.url);
        const sourcesContainer = document.createElement('div');
        sourcesContainer.className = 'sources-container';

        const toggleBtn = document.createElement('button');
        toggleBtn.className = 'sources-toggle-btn';
        toggleBtn.type = 'button';
        toggleBtn.innerHTML = `
            ${isWeb ? ICONS.routeWeb : ICONS.routeLocal}
            <span>${isWeb ? 'Web Sources' : 'Context Citations'} (${sources.length})</span>
            <svg class="arrow-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
        `;

        const sourcesList = document.createElement('div');
        sourcesList.className = 'sources-list hidden';

        sources.forEach((src, idx) => {
            const card = document.createElement('div');
            card.className = 'source-card';
            
            const citationNum = `[${idx + 1}]`;
            let titleHtml = '';
            if (src.url) {
                titleHtml = `<a class="source-link" href="${src.url}" target="_blank" rel="noopener noreferrer">
                    <span class="source-index">${citationNum}</span>
                    <span>${src.source}</span>
                    ${ICONS.externalLink}
                </a>`;
            } else {
                titleHtml = `<span class="source-title-row" title="${src.source}">
                    <span class="source-index">${citationNum}</span>
                    ${ICONS.docPdf}
                    <span>${src.source}</span>
                </span>`;
            }

            card.innerHTML = `
                <div class="source-card-header">
                    ${titleHtml}
                    ${src.page !== null && src.page !== undefined ? `<span class="source-page-badge">Page ${src.page}</span>` : ''}
                </div>
                <div class="source-snippet">"${escapeHtml(src.snippet)}"</div>
            `;
            sourcesList.appendChild(card);
        });

        toggleBtn.addEventListener('click', () => {
            const isHidden = sourcesList.classList.toggle('hidden');
            toggleBtn.classList.toggle('open', !isHidden);
            chatBox.scrollTop = chatBox.scrollHeight;
        });

        sourcesContainer.appendChild(toggleBtn);
        sourcesContainer.appendChild(sourcesList);
        contentDiv.appendChild(sourcesContainer);
        chatBox.scrollTop = chatBox.scrollHeight;
    };

    const getRouteBadgeHtml = (route, isSearching = false) => {
        if (route === 'web_search') {
            return `${ICONS.routeWeb} <span>${isSearching ? 'Searching web...' : 'Web Search'}</span>`;
        }
        return `${ICONS.routeLocal} <span>Schema &amp; Data Engine</span>`;
    };

    const appendMessage = (content, sender, sources = [], route = null, autoScroll = true) => {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}-message`;
        
        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.innerHTML = sender === 'user' ? ICONS.user : ICONS.bot;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        if (sender === 'assistant' && route) {
            const badge = document.createElement('div');
            badge.className = `route-badge ${route === 'web_search' ? 'web' : 'local'}`;
            badge.innerHTML = getRouteBadgeHtml(route, false);
            contentDiv.appendChild(badge);
        }

        const textSpan = document.createElement('div');
        textSpan.className = 'message-text';

        // Render Markdown with Executable SQL Runners if assistant
        if (sender === 'assistant' && window.DimensionSqlRunner) {
            window.DimensionSqlRunner.renderMarkdownWithSql(content, textSpan);
        } else {
            textSpan.textContent = content;
        }

        contentDiv.appendChild(textSpan);

        if (sender === 'assistant' && sources && sources.length > 0) {
            attachSourcesToBubble(contentDiv, sources, route || 'local_context');
        }

        msgDiv.appendChild(avatar);
        msgDiv.appendChild(contentDiv);
        chatBox.appendChild(msgDiv);
        if (autoScroll) chatBox.scrollTop = chatBox.scrollHeight;
    };

    const createStreamingAssistantBubble = (route = null, isSearching = false) => {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant-message';

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.innerHTML = ICONS.bot;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';

        let badgeEl = null;
        if (route) {
            badgeEl = document.createElement('div');
            badgeEl.className = `route-badge ${route === 'web_search' ? 'web' : 'local'}`;
            badgeEl.innerHTML = getRouteBadgeHtml(route, isSearching);
            contentDiv.appendChild(badgeEl);
        }

        const textSpan = document.createElement('div');
        textSpan.className = 'message-text';
        textSpan.textContent = '';
        contentDiv.appendChild(textSpan);

        msgDiv.appendChild(avatar);
        msgDiv.appendChild(contentDiv);
        chatBox.appendChild(msgDiv);
        chatBox.scrollTop = chatBox.scrollHeight;

        return { container: contentDiv, textSpan, badgeEl };
    };

    const appendTypingIndicator = () => {
        const msgDiv = document.createElement('div');
        msgDiv.id = 'typing-indicator';
        msgDiv.className = `message assistant-message`;
        
        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.innerHTML = ICONS.bot;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        const indicator = document.createElement('div');
        indicator.className = 'typing-indicator';
        indicator.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';

        contentDiv.appendChild(indicator);
        msgDiv.appendChild(avatar);
        msgDiv.appendChild(contentDiv);
        chatBox.appendChild(msgDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    };

    const removeTypingIndicator = () => {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) {
            indicator.remove();
        }
    };

    // ==========================================================================
    // 9. Query Submission & Autonomous Streaming
    // ==========================================================================
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (currentAbortController) {
            currentAbortController.abort();
            return;
        }

        const query = queryInput.value.trim();
        if (!query) return;

        if (!activeSessionId) {
            await createNewChat(query);
        }

        if (chatBox.querySelector('.welcome-hero-container')) {
            chatBox.innerHTML = '';
        }

        appendMessage(query, 'user');
        queryInput.value = '';
        appendTypingIndicator();

        currentAbortController = new AbortController();
        setGenerating(true);

        let fullAnswer = '';
        let detectedRoute = null;
        let detectedSources = [];

        // Check if query is an immediate raw SQL execution request
        const isDirectSql = /^\s*(SELECT|WITH|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|PRAGMA|DESCRIBE)\b/i.test(query);

        try {
            // If user typed raw SQL directly into the prompt dock, execute against /api/db/query
            if (isDirectSql) {
                removeTypingIndicator();
                const bubbleData = createStreamingAssistantBubble('db_query', false);
                const assistantMsgBubble = bubbleData.container;
                const textElement = bubbleData.textSpan;

                if (window.DimensionSqlRunner) {
                    const runnerCard = window.DimensionSqlRunner.createSqlRunnerCard(query);
                    textElement.appendChild(runnerCard);
                    // Automatically trigger execution
                    const runBtn = runnerCard.querySelector('.sql-run-btn');
                    if (runBtn) runBtn.click();
                } else {
                    textElement.textContent = `Executing SQL: ${query}`;
                }
                setGenerating(false);
                return;
            }

            // Determine stream source: Studio v2 Runs or legacy endpoints
            let activeConnId = window.DimensionStudioWorkbench 
                ? window.DimensionStudioWorkbench.state.activeConnectionId 
                : localStorage.getItem('dimension_active_connection_id');

            let response = null;
            let isV2StudioStream = false;

            if (activeConnId) {
                try {
                    const runInit = await fetch('/api/v2/runs', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            session_id: activeSessionId || 'default',
                            connection_id: activeConnId,
                            mode: 'ask',
                            effort: selectedEffort,
                            message: query,
                            model_name: selectedModel
                        }),
                        signal: currentAbortController.signal
                    });
                    if (runInit.ok) {
                        const runJson = await runInit.json();
                        const rId = runJson.run_id;
                        response = await fetch(`/api/v2/runs/${rId}/events`, {
                            signal: currentAbortController.signal
                        });
                        if (response.ok) {
                            isV2StudioStream = true;
                        }
                    }
                } catch (e) {
                    console.warn('Studio v2 run fallback:', e);
                }
            }

            if (!response || !response.ok) {
                let streamUrl = '/api/agent/stream';
                let streamPayload = {
                    prompt: query,
                    table_context: currentSchema && currentSchema.tables ? currentSchema.tables.map(t => t.name) : [],
                    model: selectedModel,
                    safety_mode: selectedSafetyMode
                };

                response = await fetch(streamUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(streamPayload),
                    signal: currentAbortController.signal
                }).catch(() => null);

                // Fallback to /api/query/stream if /api/agent/stream returns 404/503
                if (!response || !response.ok) {
                    streamUrl = '/api/query/stream';
                    streamPayload = {
                        query,
                        session_id: activeSessionId,
                        model: selectedModel,
                        effort: selectedEffort
                    };
                    response = await fetch(streamUrl, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(streamPayload),
                        signal: currentAbortController.signal
                    });
                }
            }

            if (!response || !response.ok) {
                removeTypingIndicator();
                setGenerating(false);
                const errData = await response.json().catch(() => ({}));
                appendMessage('Error: ' + (errData.detail || 'Failed to connect to agent.'), 'assistant');
                return;
            }

            let assistantMsgBubble = null;
            let textElement = null;
            let badgeElement = null;

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';
            let currentEventName = 'message';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed) continue;

                    if (trimmed.startsWith('event: ')) {
                        currentEventName = trimmed.substring(7).trim();
                        continue;
                    }

                    if (!trimmed.startsWith('data: ')) continue;
                    const jsonStr = trimmed.substring(6);

                    if (jsonStr === '[DONE]') {
                        removeTypingIndicator();
                        setGenerating(false);
                        if (assistantMsgBubble && textElement && window.DimensionSqlRunner && fullAnswer) {
                            window.DimensionSqlRunner.renderMarkdownWithSql(fullAnswer, textElement);
                        }
                        continue;
                    }

                    try {
                        const payload = JSON.parse(jsonStr);

                        // If Studio v2 Typed SSE Stream
                        if (isV2StudioStream) {
                            if (!assistantMsgBubble) {
                                removeTypingIndicator();
                                const bubbleData = createStreamingAssistantBubble('schema_engine', false);
                                assistantMsgBubble = bubbleData.container;
                                textElement = bubbleData.textSpan;
                                badgeElement = bubbleData.badgeEl;
                            }

                            if (currentEventName === 'tool.called') {
                                const toolPill = document.createElement('div');
                                toolPill.className = 'agent-step-pill';
                                toolPill.textContent = `⚡ [${payload.tool}] Running...`;
                                assistantMsgBubble.insertBefore(toolPill, textElement);
                            } else if (currentEventName === 'token') {
                                fullAnswer += (payload.delta || '');
                                textElement.textContent = fullAnswer;
                                chatBox.scrollTop = chatBox.scrollHeight;
                            } else if (currentEventName === 'sql.suggested') {
                                if (window.DimensionSqlRunner && payload.sql) {
                                    const card = window.DimensionSqlRunner.createSqlRunnerCard(payload.sql, payload.query_token);
                                    assistantMsgBubble.appendChild(card);
                                }
                            } else if (currentEventName === 'evidence.added') {
                                detectedSources.push({
                                    source: payload.title || 'Studio Evidence',
                                    snippet: payload.body || ''
                                });
                            } else if (currentEventName === 'run.completed') {
                                removeTypingIndicator();
                                setGenerating(false);
                                if (window.DimensionSqlRunner && fullAnswer) {
                                    window.DimensionSqlRunner.renderMarkdownWithSql(fullAnswer, textElement);
                                }
                                if (detectedSources.length > 0) {
                                    attachSourcesToBubble(assistantMsgBubble, detectedSources, 'schema_engine');
                                }
                            } else if (currentEventName === 'run.failed') {
                                removeTypingIndicator();
                                setGenerating(false);
                                textElement.textContent += `\n\n[Run Failed: ${payload.message}]`;
                            }
                            continue;
                        }

                        if (payload.route && !detectedRoute) {
                            detectedRoute = payload.route;
                            if (!assistantMsgBubble && detectedRoute === 'web_search') {
                                removeTypingIndicator();
                                const bubbleData = createStreamingAssistantBubble(detectedRoute, true);
                                assistantMsgBubble = bubbleData.container;
                                textElement = bubbleData.textSpan;
                                badgeElement = bubbleData.badgeEl;
                            } else if (badgeElement) {
                                badgeElement.className = `route-badge ${detectedRoute === 'web_search' ? 'web' : 'local'}`;
                                badgeElement.innerHTML = getRouteBadgeHtml(detectedRoute, false);
                            }
                        }

                        if (payload.token) {
                            if (!assistantMsgBubble) {
                                removeTypingIndicator();
                                const bubbleData = createStreamingAssistantBubble(detectedRoute, false);
                                assistantMsgBubble = bubbleData.container;
                                textElement = bubbleData.textSpan;
                                badgeElement = bubbleData.badgeEl;
                            } else if (badgeElement && detectedRoute === 'web_search') {
                                badgeElement.innerHTML = getRouteBadgeHtml(detectedRoute, false);
                            }
                            fullAnswer += payload.token;
                            textElement.textContent = fullAnswer.replace(/<!--\s*suggestions:[\s\S]*?-->/gi, '').trimEnd();
                            chatBox.scrollTop = chatBox.scrollHeight;
                        }

                        if (payload.sources && payload.sources.length > 0) {
                            detectedSources = payload.sources;
                        }

                        if (payload.done) {
                            removeTypingIndicator();
                            setGenerating(false);
                            if (!assistantMsgBubble) {
                                const bubbleData = createStreamingAssistantBubble(detectedRoute || payload.route);
                                assistantMsgBubble = bubbleData.container;
                                textElement = bubbleData.textSpan;
                            }

                            // Finalize: Render Markdown with interactive SQL Runner cards
                            if (window.DimensionSqlRunner && fullAnswer) {
                                window.DimensionSqlRunner.renderMarkdownWithSql(fullAnswer, textElement);
                            } else {
                                textElement.textContent = fullAnswer || 'No response generated.';
                            }

                            const activeRoute = detectedRoute || payload.route || 'local_context';
                            const finalSources = payload.sources || detectedSources;
                            if (finalSources && finalSources.length > 0) {
                                attachSourcesToBubble(assistantMsgBubble, finalSources, activeRoute);
                            }
                        }

                        if (payload.error) {
                            removeTypingIndicator();
                            setGenerating(false);
                            if (!assistantMsgBubble) {
                                appendMessage('Error: ' + payload.error, 'assistant');
                            } else {
                                textElement.textContent += '\n\n[Error: ' + payload.error + ']';
                            }
                        }
                    } catch (parseErr) {
                        console.error('Error parsing SSE chunk:', parseErr);
                    }
                }
            }

            // Stream reader finished
            if (assistantMsgBubble && textElement && window.DimensionSqlRunner && fullAnswer) {
                window.DimensionSqlRunner.renderMarkdownWithSql(fullAnswer, textElement);
            }
        } catch (error) {
            removeTypingIndicator();
            if (error.name === 'AbortError') {
                if (fullAnswer.trim()) {
                    fetch('/api/chat/stop', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            session_id: activeSessionId,
                            content: fullAnswer,
                            route: detectedRoute,
                            sources: detectedSources
                        })
                    }).catch(() => {});
                }
            } else {
                appendMessage('Network error while querying the agent.', 'assistant');
            }
        } finally {
            setGenerating(false);
            fetchSessions();
        }
    });

    // Initialize Application
    if (chatBox) {
        chatBox.innerHTML = renderWelcomeHero();
    }
    fetchModels();
    fetchSchema();
    fetchSessions();
});
