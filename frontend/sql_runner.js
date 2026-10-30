/**
 * Dimension Data & Schema Studio — SQL Runner & Executable Block Mount
 * Component: Agent-UI-SQL-Runner (frontend/sql_runner.js)
 * 
 * Handles ```sql:executable blocks:
 * - Renders sleek frosted glass card with JetBrains Mono syntax view
 * - "Run on DB" action with real-time latency measurement and Safety Mode enforcement
 * - "Copy SQL" with clipboard checkmark feedback
 * - "Explain" action to prompt the autonomous data agent
 * - Mounts interactive DimensionDataGrid upon query completion
 */

(function (window) {
    'use strict';

    // SVG Icons
    const ICONS = {
        play: `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
        </svg>`,
        copy: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
        </svg>`,
        check: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
        </svg>`,
        sparkles: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"></path>
            <path d="M5 3v4"></path><path d="M19 17v4"></path><path d="M3 5h4"></path><path d="M17 19h4"></path>
        </svg>`,
        database: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
        </svg>`,
        shield: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
        </svg>`
    };

    /**
     * Helper to execute a query against /api/db/query
     */
    async function executeDbQuery(queryText, mode = 'read_only', limit = 100) {
        const startTime = performance.now();
        try {
            const res = await fetch('/api/db/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: queryText.trim(),
                    mode: mode,
                    limit: limit
                })
            });

            const elapsedMs = Math.round(performance.now() - startTime);

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                return {
                    status: 'error',
                    columns: [],
                    rows: [],
                    row_count: 0,
                    execution_time_ms: elapsedMs,
                    error: errData.detail || errData.error || `Server responded with HTTP ${res.status}`
                };
            }

            const data = await res.json();
            if (data.execution_time_ms === 0 || data.execution_time_ms === null || data.execution_time_ms === undefined) {
                data.execution_time_ms = elapsedMs;
            }
            return data;
        } catch (err) {
            const elapsedMs = Math.round(performance.now() - startTime);
            return {
                status: 'error',
                columns: [],
                rows: [],
                row_count: 0,
                execution_time_ms: elapsedMs,
                error: err.message || 'Network failure while contacting database engine.'
            };
        }
    }

    /**
     * Get active safety mode from dock selector
     */
    function getActiveSafetyMode() {
        const select = document.getElementById('safety-mode-select');
        return select ? select.value : 'read_only';
    }

    /**
     * Syntax highlighter for SQL keywords
     */
    function highlightSQL(sql) {
        const keywords = [
            'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN', 'FULL JOIN', 'CROSS JOIN',
            'GROUP BY', 'ORDER BY', 'HAVING', 'LIMIT', 'OFFSET', 'UNION', 'ALL', 'AS', 'ON', 'AND', 'OR', 'NOT',
            'IN', 'IS', 'NULL', 'LIKE', 'ILIKE', 'BETWEEN', 'EXISTS', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
            'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DISTINCT', 'OVER', 'PARTITION BY', 'COALESCE', 'CAST',
            'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'TABLE', 'VIEW', 'INDEX',
            'DESC', 'ASC', 'TRUE', 'FALSE'
        ];

        // Escape HTML first
        let escaped = String(sql)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        // Highlight strings ('...')
        escaped = escaped.replace(/'([^'\\]*(\\.[^'\\]*)*)'/g, '<span class="sql-token-string">\'$1\'</span>');

        // Highlight numbers
        escaped = escaped.replace(/\b(\d+(\.\d+)?)\b/g, '<span class="sql-token-number">$1</span>');

        // Highlight comments (-- ...)
        escaped = escaped.replace(/(--[^\n]*)/g, '<span class="sql-token-comment">$1</span>');

        // Highlight keywords
        const kwRegex = new RegExp(`\\b(${keywords.join('|')})\\b`, 'gi');
        escaped = escaped.replace(kwRegex, (match) => `<span class="sql-token-kw">${match.toUpperCase()}</span>`);

        return escaped;
    }

    /**
     * Create an interactive SQL Runner card DOM node
     */
    function createSqlRunnerCard(rawSql, options = {}) {
        const sql = rawSql.trim();
        const card = document.createElement('div');
        card.className = 'sql-runner-card';

        const isMutation = /\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b/i.test(sql);

        card.innerHTML = `
            <div class="sql-runner-header">
                <div class="sql-runner-badge-group">
                    <span class="sql-pill-badge">
                        ${ICONS.database}
                        <span>SQL:EXECUTABLE</span>
                    </span>
                    <span class="sql-safety-pill ${isMutation ? 'safety-mutation' : 'safety-safe'}">
                        ${ICONS.shield}
                        <span>${isMutation ? 'Mutation Statement' : 'Safe Read'}</span>
                    </span>
                    <span class="sql-latency-pill hidden"></span>
                </div>
                <div class="sql-runner-actions">
                    <button type="button" class="sql-action-btn sql-explain-btn" title="Ask agent to explain this query plan">
                        ${ICONS.sparkles}
                        <span>Explain</span>
                    </button>
                    <button type="button" class="sql-action-btn sql-copy-btn" title="Copy SQL statement">
                        ${ICONS.copy}
                        <span>Copy</span>
                    </button>
                    <button type="button" class="sql-action-btn sql-run-btn" title="Execute query on database engine">
                        ${ICONS.play}
                        <span>Run on DB</span>
                    </button>
                </div>
            </div>
            <div class="sql-runner-body">
                <pre class="sql-code-block"><code>${highlightSQL(sql)}</code></pre>
            </div>
            <div class="sql-execution-mount hidden">
                <div class="sql-loading-row hidden">
                    <span class="sql-spinner"></span>
                    <span class="sql-loading-text">Executing query on active engine...</span>
                </div>
                <div class="sql-grid-target"></div>
            </div>
        `;

        const runBtn = card.querySelector('.sql-run-btn');
        const copyBtn = card.querySelector('.sql-copy-btn');
        const explainBtn = card.querySelector('.sql-explain-btn');
        const latencyPill = card.querySelector('.sql-latency-pill');
        const mount = card.querySelector('.sql-execution-mount');
        const loadingRow = card.querySelector('.sql-loading-row');
        const gridTarget = card.querySelector('.sql-grid-target');

        // Copy button action
        copyBtn.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(sql);
                copyBtn.innerHTML = `${ICONS.check} <span>Copied!</span>`;
                copyBtn.classList.add('copied');
                setTimeout(() => {
                    copyBtn.innerHTML = `${ICONS.copy} <span>Copy</span>`;
                    copyBtn.classList.remove('copied');
                }, 2000);
            } catch (e) {
                // Fallback for older browsers/sandboxes
                const ta = document.createElement('textarea');
                ta.value = sql;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                copyBtn.innerHTML = `${ICONS.check} <span>Copied!</span>`;
                setTimeout(() => {
                    copyBtn.innerHTML = `${ICONS.copy} <span>Copy</span>`;
                }, 2000);
            }
        });

        // Explain button action: populates queryInput and submits
        explainBtn.addEventListener('click', () => {
            const queryInput = document.getElementById('query-input');
            const chatForm = document.getElementById('chat-form');
            if (queryInput && chatForm) {
                queryInput.value = `Explain the following SQL query, including execution strategy and performance implications:\n\n\`\`\`sql\n${sql}\n\`\`\``;
                chatForm.dispatchEvent(new Event('submit', { cancelable: true }));
            }
        });

        // Run on DB action
        runBtn.addEventListener('click', async () => {
            const safetyMode = getActiveSafetyMode();

            // Check client-side safety guardrail for immediate feedback
            if (safetyMode === 'read_only' && isMutation) {
                mount.classList.remove('hidden');
                loadingRow.classList.add('hidden');
                gridTarget.innerHTML = `
                    <div class="data-grid-error-card">
                        <div class="data-grid-error-header">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <circle cx="12" cy="12" r="10"></circle>
                                <line x1="12" y1="8" x2="12" y2="12"></line>
                                <line x1="12" y1="16" x2="12.01" y2="16"></line>
                            </svg>
                            <span class="data-grid-error-title">Safety Mode Block</span>
                        </div>
                        <div class="data-grid-error-body">
                            Mutating statements (INSERT, UPDATE, DELETE, DROP, ALTER) are blocked in <strong>Read-Only [Safe]</strong> mode.
                            Switch Safety Mode to <strong>Mutation Allowed</strong> in the Command Dock to execute write queries.
                        </div>
                    </div>
                `;
                return;
            }

            // Start Execution
            runBtn.disabled = true;
            runBtn.classList.add('running');
            runBtn.innerHTML = `<span class="sql-spinner-btn"></span> <span>Running...</span>`;

            mount.classList.remove('hidden');
            loadingRow.classList.remove('hidden');
            gridTarget.innerHTML = '';

            try {
                const result = await executeDbQuery(sql, safetyMode);

                loadingRow.classList.add('hidden');

                // Update latency indicator
                if (result.execution_time_ms !== null && result.execution_time_ms !== undefined) {
                    latencyPill.textContent = `⚡ ${Number(result.execution_time_ms).toFixed(1)}ms`;
                    latencyPill.classList.remove('hidden');
                }

                if (result.status === 'error' || result.error) {
                    gridTarget.innerHTML = `
                        <div class="data-grid-error-card">
                            <div class="data-grid-error-header">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <circle cx="12" cy="12" r="10"></circle>
                                    <line x1="12" y1="8" x2="12" y2="12"></line>
                                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                                </svg>
                                <span class="data-grid-error-title">Query Execution Error</span>
                            </div>
                            <div class="data-grid-error-body">${result.error}</div>
                        </div>
                    `;
                } else {
                    // Success: Mount DimensionDataGrid
                    if (window.renderDataGrid) {
                        window.renderDataGrid(gridTarget, result);
                    } else {
                        gridTarget.innerHTML = `<pre>${JSON.stringify(result, null, 2)}</pre>`;
                    }
                }
            } catch (err) {
                loadingRow.classList.add('hidden');
                gridTarget.innerHTML = `
                    <div class="data-grid-error-card">
                        <div class="data-grid-error-header">
                            <span class="data-grid-error-title">Client Exception</span>
                        </div>
                        <div class="data-grid-error-body">${err.message}</div>
                    </div>
                `;
            } finally {
                runBtn.disabled = false;
                runBtn.classList.remove('running');
                runBtn.innerHTML = `${ICONS.play} <span>Run on DB</span>`;
            }
        });

        return card;
    }

    /**
     * Scans a message text or markdown for ```sql:executable blocks and standard code blocks,
     * converting them into DOM structures, and renders interactive suggestion chips.
     */
    function renderMarkdownWithSql(rawText, targetContainer) {
        if (!targetContainer) return;
        targetContainer.innerHTML = '';

        if (!rawText) return;

        // Detect and extract executive suggestions: <!-- suggestions: [...] -->
        const suggestionsRegex = /<!--\s*suggestions:\s*(\[[\s\S]*?\])\s*-->/i;
        const suggestionsMatch = rawText.match(suggestionsRegex);
        let suggestions = [];
        let textToRender = rawText;

        if (suggestionsMatch) {
            try {
                suggestions = JSON.parse(suggestionsMatch[1]);
                textToRender = rawText.replace(suggestionsRegex, '').trim();
            } catch (err) {
                console.warn('Failed to parse suggestions JSON:', err);
            }
        }

        // Split by code block markers (```lang ... ```) with flexible whitespace and line endings
        const codeBlockRegex = /```([a-zA-Z0-9_:-]*)[^\S\r\n]*\r?\n([\s\S]*?)```/g;
        let lastIndex = 0;
        let match;

        while ((match = codeBlockRegex.exec(textToRender)) !== null) {
            const textBefore = textToRender.substring(lastIndex, match.index);
            if (textBefore.trim()) {
                const proseEl = document.createElement('div');
                proseEl.className = 'message-prose';
                proseEl.innerHTML = formatProseMarkdown(textBefore);
                targetContainer.appendChild(proseEl);
            }

            const lang = (match[1] || '').trim().toLowerCase();
            const codeContent = match[2];

            if (lang === 'sql:executable' || lang === 'sql') {
                const sqlCard = createSqlRunnerCard(codeContent);
                targetContainer.appendChild(sqlCard);
            } else {
                // Standard code block with copy button
                const preCard = document.createElement('div');
                preCard.className = 'standard-code-card';
                preCard.innerHTML = `
                    <div class="standard-code-header">
                        <span class="code-lang-label">${lang || 'code'}</span>
                        <button type="button" class="sql-action-btn code-copy-btn">
                            ${ICONS.copy} <span>Copy</span>
                        </button>
                    </div>
                    <pre class="code-body"><code>${escapeHtml(codeContent.trim())}</code></pre>
                `;
                const cBtn = preCard.querySelector('.code-copy-btn');
                cBtn.addEventListener('click', async () => {
                    await navigator.clipboard.writeText(codeContent.trim()).catch(() => {});
                    cBtn.innerHTML = `${ICONS.check} <span>Copied!</span>`;
                    setTimeout(() => {
                        cBtn.innerHTML = `${ICONS.copy} <span>Copy</span>`;
                    }, 2000);
                });
                targetContainer.appendChild(preCard);
            }

            lastIndex = codeBlockRegex.lastIndex;
        }

        const remainingText = textToRender.substring(lastIndex);
        if (remainingText.trim()) {
            const proseEl = document.createElement('div');
            proseEl.className = 'message-prose';
            proseEl.innerHTML = formatProseMarkdown(remainingText);
            targetContainer.appendChild(proseEl);
        }

        // Mount interactive frosted suggestion pills at the bottom
        if (Array.isArray(suggestions) && suggestions.length > 0) {
            const pillContainer = document.createElement('div');
            pillContainer.className = 'suggestion-pills-container';

            const label = document.createElement('div');
            label.className = 'suggestion-pills-label';
            label.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                </svg>
                <span>Suggested Next Actions</span>
            `;
            pillContainer.appendChild(label);

            const pillsRow = document.createElement('div');
            pillsRow.className = 'suggestion-pills-row';

            suggestions.forEach(suggestionText => {
                if (!suggestionText || typeof suggestionText !== 'string') return;
                const pill = document.createElement('button');
                pill.type = 'button';
                pill.className = 'suggestion-pill';
                pill.innerHTML = `
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="9 18 15 12 9 6"></polyline>
                    </svg>
                    <span>${escapeHtml(suggestionText)}</span>
                `;
                pill.addEventListener('click', (e) => {
                    e.preventDefault();
                    const queryInput = document.getElementById('query-input');
                    const chatForm = document.getElementById('chat-form');
                    if (queryInput && chatForm) {
                        queryInput.value = suggestionText;
                        queryInput.focus();
                        chatForm.dispatchEvent(new Event('submit', { cancelable: true }));
                    }
                });
                pillsRow.appendChild(pill);
            });

            pillContainer.appendChild(pillsRow);
            targetContainer.appendChild(pillContainer);
        }
    }

    /**
     * Simple, safe Markdown formatter for headers, bold, italics, lists, and inline code
     */
    function formatProseMarkdown(text) {
        let escaped = escapeHtml(text);

        // Headers
        escaped = escaped.replace(/^### (.*$)/gim, '<h3 class="prose-h3">$1</h3>');
        escaped = escaped.replace(/^## (.*$)/gim, '<h2 class="prose-h2">$1</h2>');
        escaped = escaped.replace(/^# (.*$)/gim, '<h1 class="prose-h1">$1</h1>');

        // Bold and Italics
        escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        escaped = escaped.replace(/\*(.*?)\*/g, '<em>$1</em>');

        // Inline code
        escaped = escaped.replace(/`([^`]+)`/g, '<code class="prose-inline-code">$1</code>');

        // Unordered list items
        escaped = escaped.replace(/^\s*-\s+(.*$)/gim, '<li class="prose-li">$1</li>');
        escaped = escaped.replace(/(<li class="prose-li">.*<\/li>(\n|$) *)+/g, '<ul class="prose-ul">$&</ul>');

        // Convert linebreaks into paragraphs if double-spaced
        const paragraphs = escaped.split(/\n{2,}/);
        return paragraphs.map(p => {
            const trimmed = p.trim();
            if (!trimmed) return '';
            if (trimmed.startsWith('<h') || trimmed.startsWith('<ul') || trimmed.startsWith('<div')) {
                return trimmed;
            }
            return `<p class="prose-p">${trimmed.replace(/\n/g, '<br/>')}</p>`;
        }).join('');
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // Export module
    window.DimensionSqlRunner = {
        executeDbQuery,
        createSqlRunnerCard,
        renderMarkdownWithSql,
        highlightSQL
    };
})(window);
