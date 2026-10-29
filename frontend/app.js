/**
 * Agentic Document Q&A - Frontend Application Controller
 * Multi-Chat Sessions, Dynamic Model/Effort Selection & Stream Interruption
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
    const activeModelBadge = document.getElementById('active-model-badge');
    const sidebar = document.getElementById('sidebar');
    const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
    const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    const themeIcon = document.getElementById('theme-icon');
    const themeLabel = document.getElementById('theme-label');
    const focusToggleBtn = document.getElementById('focus-toggle-btn');
    const appContainer = document.querySelector('.app-container') || document.body;

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
        window.dispatchEvent(new CustomEvent('dimension:themechange', { detail: { theme } }));
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
        docPdf: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f87171" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
        </svg>`,
        docWord: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="8" y1="13" x2="16" y2="13"></line>
            <line x1="8" y1="17" x2="16" y2="17"></line>
        </svg>`,
        docText: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
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
        summarize: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
        </svg>`,
        trash: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
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
        dots: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="1.5"></circle>
            <circle cx="19" cy="12" r="1.5"></circle>
            <circle cx="5" cy="12" r="1.5"></circle>
        </svg>`
    };

    // Utilities: HTML escape & Session Title Formatter (Fixed length with ellipsis)
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

    // Utility: Format bytes cleanly
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

    // Restore persistent sidebar state
    try {
        if (localStorage.getItem('sidebar_collapsed') === '1' && sidebar) {
            sidebar.classList.add('collapsed');
            if (sidebarToggleBtn) sidebarToggleBtn.classList.add('active');
        }
    } catch (e) {}

    // Global Keyboard Shortcuts & Click-Outside Handlers
    window.addEventListener('keydown', (e) => {
        // Cmd+K / Ctrl+K: New Chat Window / Welcome Page
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            startNewChat();
        }
        // Cmd+Shift+F / Ctrl+Shift+F: Toggle Focus Mode
        if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'f') {
            e.preventDefault();
            applyFocusMode(!isFocusMode);
        }
        // Cmd+B / Ctrl+B: Toggle Sidebar
        if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'b') {
            e.preventDefault();
            toggleSidebar();
        }
        // Escape: Close open session dropdown or stop generation
        if (e.key === 'Escape') {
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

    // Close any active 3-dot dropdown menu when clicking anywhere outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.session-dropdown-menu') && !e.target.closest('.session-menu-trigger')) {
            closeAllDropdowns();
        }
    });

    // ==========================================================================
    // 1. Model & Effort Settings
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

    // ==========================================================================
    // 2. Multi-Chat Sessions, Pinned Threads & Inline Options Menu
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

        input.addEventListener('blur', () => {
            saveRename();
        });
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

        // Rename click
        menu.querySelector('.rename-opt').addEventListener('click', (e) => {
            e.stopPropagation();
            closeAllDropdowns();
            startInlineRename(sessionItem, s);
        });

        // Pin / Unpin click
        menu.querySelector('.pin-opt').addEventListener('click', async (e) => {
            e.stopPropagation();
            closeAllDropdowns();
            await updateSessionProperty(s.id, { pinned: !s.pinned });
        });

        // Archive / Unarchive click
        menu.querySelector('.archive-opt').addEventListener('click', async (e) => {
            e.stopPropagation();
            closeAllDropdowns();
            await updateSessionProperty(s.id, { archived: !s.archived });
        });

        // Delete click
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
            
            // Check if user previously had an active thread in this browser session
            const savedSession = sessionStorage.getItem('dimension_active_session');
            if (savedSession && sessions.some(s => s.id === savedSession)) {
                if (activeSessionId !== savedSession) {
                    loadSession(savedSession);
                }
            } else if (!activeSessionId) {
                // Default to Welcome Page on fresh start
                startNewChat();
            }
        } catch (err) {
            console.error('Failed to load chat sessions:', err);
        }
    };

    const renderSessions = (sessions) => {
        if (!sessionsList) return;

        // Separate active vs archived sessions
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

            // Select thread when clicking row (ignoring menu or inline rename clicks)
            item.addEventListener('click', (e) => {
                if (e.target.closest('.session-menu-trigger') || e.target.closest('.session-dropdown-menu') || e.target.closest('.session-inline-rename-input')) {
                    return;
                }
                if (s.id !== activeSessionId) {
                    loadSession(s.id);
                }
            });

            // 3-dot options trigger
            const menuTrigger = item.querySelector('.session-menu-trigger');
            menuTrigger.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleSessionDropdown(item, s);
            });

            return item;
        };

        // Render active (and pinned) sessions
        activeSessions.forEach(s => {
            sessionsList.appendChild(renderRow(s));
        });

        // Collapsible archived threads section if any exist
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

    // Dimension Welcome Hero Component with Clickable Instant Capabilities
    const renderWelcomeHero = () => {
        return `
            <div class="welcome-hero-container">
                <h1 class="welcome-hero-title">
                    All your documents,<br><span class="welcome-gradient-text">one search away.</span>
                </h1>
                <p class="welcome-hero-desc">
                    Connect your engineering whitepapers, architecture specifications, and code repositories. The agent searches local ChromaDB vectors with autonomous web fallbacks.
                </p>
                <div class="capability-card">
                    <div class="capability-header">Instant Capabilities</div>
                    <div class="capability-row" data-prompt="Explain the hybrid retrieval strategy between local ChromaDB and autonomous web search.">
                        <div class="capability-row-left">
                            <span class="capability-index">01</span>
                            <div>
                                <div class="capability-name">Cross-Document Hybrid Retrieval</div>
                                <div class="capability-sub">Vector embeddings cross-referenced against real-time web intelligence.</div>
                            </div>
                        </div>
                        <span class="capability-arrow">→</span>
                    </div>
                    <div class="capability-row" data-prompt="How does the streaming query pipeline handle user stream interruption with AbortController?">
                        <div class="capability-row-left">
                            <span class="capability-index">02</span>
                            <div>
                                <div class="capability-name">Zero-Latency Stream Cancellation</div>
                                <div class="capability-sub">Instant SSE socket termination with partial token persistence.</div>
                            </div>
                        </div>
                        <span class="capability-arrow">→</span>
                    </div>
                    <div class="capability-row" data-prompt="Summarize system_architecture.pdf and identify key bottlenecks.">
                        <div class="capability-row-left">
                            <span class="capability-index">03</span>
                            <div>
                                <div class="capability-name">Context Graph Evidence Nodes</div>
                                <div class="capability-sub">Every assertion verified with source page and cosine distance scores.</div>
                            </div>
                        </div>
                        <span class="capability-arrow">→</span>
                    </div>
                </div>
            </div>
        `;
    };

    // Delegate clicks on Instant Capability Rows to populate and auto-submit prompt
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
        
        // Highlight active session item in sidebar
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

            // Render messages (Show Welcome Hero if empty thread)
            chatBox.innerHTML = '';
            if (messages.length === 0) {
                chatBox.innerHTML = renderWelcomeHero();
            } else {
                messages.forEach(msg => {
                    appendMessage(msg.content, msg.role, msg.sources, msg.route, false);
                });
            }
            chatBox.scrollTop = chatBox.scrollHeight;
            
            // Re-affirm active highlight in sidebar
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
    // 3. Document Management Logic
    // ==========================================================================
    const fetchDocuments = async () => {
        try {
            const res = await fetch('/api/documents');
            if (!res.ok) return;
            const data = await res.json();
            renderDocuments(data.documents || []);
        } catch (err) {
            console.error('Failed to load documents:', err);
        }
    };

    const renderDocuments = (docs) => {
        if (docCount) docCount.textContent = docs.length;
        if (!documentsList) return;

        if (docs.length === 0) {
            documentsList.innerHTML = '<div class="empty-docs-placeholder">No documents indexed yet.</div>';
            return;
        }

        documentsList.innerHTML = '';
        docs.forEach(doc => {
            const item = document.createElement('div');
            item.className = 'doc-item';

            const ext = doc.filename.split('.').pop().toLowerCase();
            let iconSvg = ICONS.docText;
            if (ext === 'pdf') iconSvg = ICONS.docPdf;
            else if (ext === 'docx') iconSvg = ICONS.docWord;

            item.innerHTML = `
                <div class="doc-icon">${iconSvg}</div>
                <div class="doc-info" title="${doc.filename}">
                    <div class="doc-name">${doc.filename}</div>
                    <div class="doc-meta">
                        <span class="doc-badge">${doc.chunk_count} chunks</span>
                        <span>${formatBytes(doc.size_bytes)}</span>
                    </div>
                </div>
                <div class="doc-actions">
                    <button class="doc-action-btn doc-summarize-btn" title="Summarize document">
                        ${ICONS.summarize}
                    </button>
                    <button class="doc-action-btn doc-delete-btn" title="Delete document">
                        ${ICONS.trash}
                    </button>
                </div>
            `;

            const sumBtn = item.querySelector('.doc-summarize-btn');
            sumBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                triggerDocumentSummary(doc.filename);
            });

            const delBtn = item.querySelector('.doc-delete-btn');
            delBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                deleteDocument(doc.filename);
            });

            documentsList.appendChild(item);
        });
    };

    const deleteDocument = async (filename) => {
        if (!confirm(`Delete "${filename}" and its vector embeddings?`)) return;

        showStatus(`Deleting ${filename}...`, 'success');
        try {
            const res = await fetch(`/api/documents/${encodeURIComponent(filename)}`, {
                method: 'DELETE'
            });
            const data = await res.json();
            if (res.ok) {
                showStatus(data.message, 'success');
                await fetchDocuments();
            } else {
                showStatus(data.detail || 'Failed to delete document.', 'error');
            }
        } catch (err) {
            showStatus('Network error while deleting document.', 'error');
        }
    };

    const clearAllDocuments = async () => {
        if (!confirm('Are you sure you want to delete ALL indexed documents and reset the Chroma database?')) return;

        showStatus('Clearing all documents...', 'success');
        try {
            const res = await fetch('/api/documents/clear', {
                method: 'POST'
            });
            const data = await res.json();
            if (res.ok) {
                showStatus(data.message, 'success');
                await fetchDocuments();
            } else {
                showStatus(data.detail || 'Failed to clear documents.', 'error');
            }
        } catch (err) {
            showStatus('Network error while clearing documents.', 'error');
        }
    };

    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', clearAllDocuments);
    }

    // ==========================================================================
    // 4. File Upload & Drag-and-Drop
    // ==========================================================================
    const handleFile = async (file) => {
        if (!file) return;
        const validExtensions = ['.pdf', '.docx', '.txt', '.md'];
        const fileName = file.name.toLowerCase();
        const isValid = validExtensions.some(ext => fileName.endsWith(ext));

        if (!isValid) {
            showStatus('Please upload a valid PDF, DOCX, TXT, or MD file.', 'error');
            return;
        }

        showStatus(`Uploading and embedding ${file.name}...`, 'success');
        dropZone.style.pointerEvents = 'none';
        dropZone.style.opacity = '0.6';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                showStatus(data.message, 'success');
                await fetchDocuments();
            } else {
                showStatus(data.detail || 'Upload failed.', 'error');
            }
        } catch (error) {
            showStatus('Network error during upload.', 'error');
        } finally {
            dropZone.style.pointerEvents = 'auto';
            dropZone.style.opacity = '1';
        }
    };

    const showStatus = (msg, type) => {
        statusMsg.textContent = msg;
        statusMsg.className = `status-message ${type}`;
        statusMsg.classList.remove('hidden');
    };

    // Drag-and-drop events
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

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

    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', function() {
        handleFile(this.files[0]);
    });

    // ==========================================================================
    // 5. Document Summaries with Stream Interruption
    // ==========================================================================
    const triggerDocumentSummary = async (filename) => {
        if (!activeSessionId) await createNewChat();

        const queryText = `Summarize "${filename}"`;
        appendMessage(queryText, 'user');
        appendTypingIndicator();

        currentAbortController = new AbortController();
        setGenerating(true);

        try {
            const response = await fetch(`/api/documents/${encodeURIComponent(filename)}/summarize/stream`, {
                method: 'POST',
                signal: currentAbortController.signal
            });

            if (!response.ok) {
                removeTypingIndicator();
                setGenerating(false);
                const errData = await response.json().catch(() => ({}));
                appendMessage('Error: ' + (errData.detail || 'Failed to generate summary.'), 'assistant');
                return;
            }

            let assistantMsgBubble = null;
            let textElement = null;
            let fullSummary = '';

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed || !trimmed.startsWith('data: ')) continue;
                    const jsonStr = trimmed.substring(6);
                    try {
                        const payload = JSON.parse(jsonStr);

                        if (payload.token) {
                            if (!assistantMsgBubble) {
                                removeTypingIndicator();
                                const bubbleData = createStreamingAssistantBubble();
                                assistantMsgBubble = bubbleData.container;
                                textElement = bubbleData.textSpan;
                            }
                            fullSummary += payload.token;
                            textElement.textContent = fullSummary;
                            chatBox.scrollTop = chatBox.scrollHeight;
                        }

                        if (payload.done) {
                            removeTypingIndicator();
                            setGenerating(false);
                            if (!assistantMsgBubble) {
                                const bubbleData = createStreamingAssistantBubble();
                                assistantMsgBubble = bubbleData.container;
                                textElement = bubbleData.textSpan;
                                textElement.textContent = fullSummary || 'Document summary complete.';
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
                        console.error('Error parsing summary SSE chunk:', parseErr);
                    }
                }
            }
        } catch (error) {
            removeTypingIndicator();
            setGenerating(false);
            if (error.name === 'AbortError') {
                console.log('Summary stream stopped by user.');
            } else {
                appendMessage('Network error while requesting document summary.', 'assistant');
            }
        } finally {
            setGenerating(false);
            fetchSessions();
        }
    };

    // ==========================================================================
    // 6. Citations, Provenance & Chat Rendering
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
            <span>${isWeb ? 'Web Sources' : 'Document Sources'} (${sources.length})</span>
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
                <div class="source-snippet">"${src.snippet}"</div>
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
        return `${ICONS.routeLocal} <span>Local Knowledge</span>`;
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
        textSpan.textContent = content;
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
    // 7. Chat Submission & Real-Time Stream Interruption
    // ==========================================================================
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // If currently generating, clicking the button triggers STOP
        if (currentAbortController) {
            currentAbortController.abort();
            return;
        }

        const query = queryInput.value.trim();
        if (!query) return;

        if (!activeSessionId) {
            await createNewChat(query);
        }

        // Clear welcome hero if present on initial query
        if (chatBox.querySelector('.welcome-hero-container')) {
            chatBox.innerHTML = '';
        }

        // 1. Display user query
        appendMessage(query, 'user');
        queryInput.value = '';
        appendTypingIndicator();

        // 2. Setup AbortController for stream cancellation
        currentAbortController = new AbortController();
        setGenerating(true);

        let fullAnswer = '';
        let detectedRoute = null;
        let detectedSources = [];

        try {
            const response = await fetch('/api/query/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    query,
                    session_id: activeSessionId,
                    model: selectedModel,
                    effort: selectedEffort
                }),
                signal: currentAbortController.signal
            });

            if (!response.ok) {
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

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed || !trimmed.startsWith('data: ')) continue;
                    const jsonStr = trimmed.substring(6);
                    try {
                        const payload = JSON.parse(jsonStr);

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
                            textElement.textContent = fullAnswer;
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
        } catch (error) {
            removeTypingIndicator();
            if (error.name === 'AbortError') {
                // Generation stopped by user via button or Escape key
                if (fullAnswer.trim()) {
                    // Save partial response to session storage
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
            // Refresh sessions list to update active title and message counts
            fetchSessions();
        }
    });

    // Initialize Application
    if (chatBox) {
        chatBox.innerHTML = renderWelcomeHero();
    }
    fetchModels();
    fetchDocuments();
    fetchSessions();
});
