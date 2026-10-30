/**
 * Dimension — Autonomous Data & Schema Studio
 * Workbench UI Controller (v2.0)
 * 
 * Manages the 6-View Studio Architecture:
 * 1. [Chat] AI Conversational Assistant & Guarded SQL Runner
 * 2. [Map] Interactive ERD Schema Cartography & Inferred Topology
 * 3. [Findings] Data Hygiene Anomaly Inbox (Orphans, Sentinels, PII, Sentinels)
 * 4. [Changes] Shadow Migrations, Lock Linting & Safe Approvals
 * 5. [Glossary] Schema Memory Flywheel, Markdown & dbt Sources Export
 * 6. [Seeds] Kahn's Topological Seed Generator with Zero FK Violations
 */

(function() {
    'use strict';

    // State
    const state = {
        connections: [],
        activeConnectionId: null,
        activeConnection: null,
        activeView: 'chat',
        findingsFilter: 'all',
        allFindings: [],
        selectedFindingIndex: 0,
        currentGraph: null,
        currentSeedPlan: null
    };

    // DOM References
    let dom = {};

    function initDomReferences() {
        dom = {
            viewTabs: document.querySelectorAll('.studio-tab-btn'),
            views: {
                chat: document.getElementById('view-chat'),
                map: document.getElementById('view-map'),
                findings: document.getElementById('view-findings'),
                changes: document.getElementById('view-changes'),
                glossary: document.getElementById('view-glossary'),
                seeds: document.getElementById('view-seeds'),
            },
            connSelect: document.getElementById('active-connection-select'),
            connPulseDot: document.getElementById('conn-tier-indicator'),
            findingsBadge: document.getElementById('findings-count-badge'),

            // Map
            mapConnBadge: document.getElementById('map-conn-badge'),
            mapStatsBadge: document.getElementById('map-stats-badge'),
            mapInferBtn: document.getElementById('map-infer-btn'),
            mapDiffBtn: document.getElementById('map-diff-btn'),
            mapExportMermaidBtn: document.getElementById('map-export-mermaid-btn'),
            mapZoomFitBtn: document.getElementById('map-zoom-fit-btn'),
            mapDriftBanner: document.getElementById('map-drift-banner'),
            mapDriftText: document.getElementById('map-drift-text'),
            mapDriftDismissBtn: document.getElementById('map-drift-dismiss-btn'),
            mapViewport: document.getElementById('map-viewport'),
            erdSvg: document.getElementById('erd-svg-canvas'),
            erdNodesLayer: document.getElementById('erd-nodes-layer'),

            // Findings
            findingsContainer: document.getElementById('findings-container'),
            findingsRunAuditBtn: document.getElementById('findings-run-audit-btn'),
            findingsFilterTabs: document.querySelectorAll('.filter-tab-btn'),
            findingsAllCount: document.getElementById('findings-all-count'),
            findingsOpenCount: document.getElementById('findings-open-count'),
            findingsCriticalCount: document.getElementById('findings-critical-count'),
            findingsWarningCount: document.getElementById('findings-warning-count'),
            findingsDismissedCount: document.getElementById('findings-dismissed-count'),

            // Changes
            changesTierPill: document.getElementById('changes-tier-pill'),
            changesSafetyAdvisory: document.getElementById('changes-safety-advisory'),
            newProposalBtn: document.getElementById('new-proposal-btn'),
            proposalsContainer: document.getElementById('proposals-container'),

            // Glossary
            glossaryContainer: document.getElementById('glossary-container'),
            glossarySearchInput: document.getElementById('glossary-search-input'),
            newGlossaryBtn: document.getElementById('new-glossary-btn'),
            glossaryExportMarkdownBtn: document.getElementById('glossary-export-markdown-btn'),
            glossaryExportDbtBtn: document.getElementById('glossary-export-dbt-btn'),

            // Seeds
            seedsDagCountBadge: document.getElementById('seeds-dag-count-badge'),
            seedsDagFlow: document.getElementById('seeds-dag-flow'),
            seedsTableConfigs: document.getElementById('seeds-table-configs'),
            seedsGenerateSqlBtn: document.getElementById('seeds-generate-sql-btn'),
            seedsApplySandboxBtn: document.getElementById('seeds-apply-sandbox-btn'),
            seedsPreviewCard: document.getElementById('seeds-preview-card'),
            seedsSqlCode: document.getElementById('seeds-sql-code'),
            seedsCopySqlBtn: document.getElementById('seeds-copy-sql-btn'),

            // Modals
            dbModal: document.getElementById('db-modal'),
            dbNameInput: document.getElementById('db-name-input'),
            dbTierSelect: document.getElementById('db-tier-select'),
            dbConnectionInput: document.getElementById('db-connection-input'),
            dbModalStatus: document.getElementById('db-modal-status'),
            dbModalConnectBtn: document.getElementById('db-modal-connect-btn'),
            dbModalCancelBtn: document.getElementById('db-modal-cancel-btn'),
            dbModalCloseBtn: document.getElementById('db-modal-close-btn'),

            newProposalModal: document.getElementById('new-proposal-modal'),
            proposalGoalInput: document.getElementById('proposal-goal-input'),
            proposalUpSql: document.getElementById('proposal-up-sql'),
            proposalDownSql: document.getElementById('proposal-down-sql'),
            proposalModalStatus: document.getElementById('proposal-modal-status'),
            newProposalSubmitBtn: document.getElementById('new-proposal-submit-btn'),
            newProposalCancelBtn: document.getElementById('new-proposal-cancel-btn'),
            newProposalCloseBtn: document.getElementById('new-proposal-close-btn'),

            approvalModal: document.getElementById('approval-modal'),
            approvalSubtitle: document.getElementById('approval-modal-subtitle'),
            approvalDecisionSelect: document.getElementById('approval-decision-select'),
            approvalTypedGroup: document.getElementById('approval-typed-confirm-group'),
            approvalExpectedText: document.getElementById('approval-expected-text'),
            approvalTypedInput: document.getElementById('approval-typed-input'),
            approvalCommentInput: document.getElementById('approval-comment-input'),
            approvalModalStatus: document.getElementById('approval-modal-status'),
            approvalModalSubmitBtn: document.getElementById('approval-modal-submit-btn'),
            approvalModalCancelBtn: document.getElementById('approval-modal-cancel-btn'),
            approvalModalCloseBtn: document.getElementById('approval-modal-close-btn'),

            newGlossaryModal: document.getElementById('new-glossary-modal'),
            glossaryTargetKind: document.getElementById('glossary-target-kind'),
            glossaryKind: document.getElementById('glossary-kind'),
            glossaryTargetInput: document.getElementById('glossary-target-input'),
            glossaryBodyInput: document.getElementById('glossary-body-input'),
            glossaryModalStatus: document.getElementById('glossary-modal-status'),
            newGlossarySubmitBtn: document.getElementById('new-glossary-submit-btn'),
            newGlossaryCancelBtn: document.getElementById('new-glossary-cancel-btn'),
            newGlossaryCloseBtn: document.getElementById('new-glossary-close-btn'),

            codeViewerModal: document.getElementById('code-viewer-modal'),
            codeViewerTitle: document.getElementById('code-viewer-title'),
            codeViewerSubtitle: document.getElementById('code-viewer-subtitle'),
            codeViewerContent: document.getElementById('code-viewer-content'),
            codeViewerCopyBtn: document.getElementById('code-viewer-copy-btn'),
            codeViewerDoneBtn: document.getElementById('code-viewer-done-btn'),
            codeViewerCloseBtn: document.getElementById('code-viewer-close-btn')
        };
    }

    // =========================================================================
    // 1. View Navigation Engine & Keyboard Shortcuts
    // =========================================================================

    function switchView(targetView) {
        if (!dom.views[targetView]) return;
        state.activeView = targetView;

        dom.viewTabs.forEach(tab => {
            tab.classList.toggle('active', tab.dataset.view === targetView);
        });

        Object.keys(dom.views).forEach(v => {
            const el = dom.views[v];
            if (el) {
                el.classList.toggle('hidden', v !== targetView);
                el.classList.toggle('active', v === targetView);
            }
        });

        // Trigger view-specific data refresh
        if (state.activeConnectionId) {
            if (targetView === 'map') loadMap(state.activeConnectionId);
            else if (targetView === 'findings') loadFindings(state.activeConnectionId);
            else if (targetView === 'changes') loadProposals(state.activeConnectionId);
            else if (targetView === 'glossary') loadGlossary(state.activeConnectionId);
            else if (targetView === 'seeds') loadSeedPlan(state.activeConnectionId);
        }
    }

    function selectFindingIndex(idx) {
        if (!dom.findingsContainer) return;
        const cards = dom.findingsContainer.querySelectorAll('.finding-card');
        if (cards.length === 0) return;

        state.selectedFindingIndex = Math.max(0, Math.min(idx, cards.length - 1));
        cards.forEach((c, i) => {
            c.classList.toggle('selected', i === state.selectedFindingIndex);
        });

        const activeCard = cards[state.selectedFindingIndex];
        if (activeCard) {
            activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

    function initKeyboardShortcuts() {
        window.addEventListener('keydown', (e) => {
            // View navigation shortcuts: Cmd+1 .. Cmd+6
            if ((e.metaKey || e.ctrlKey) && !e.shiftKey) {
                const keyMap = { '1': 'chat', '2': 'map', '3': 'findings', '4': 'changes', '5': 'glossary', '6': 'seeds' };
                if (keyMap[e.key]) {
                    e.preventDefault();
                    switchView(keyMap[e.key]);
                    return;
                }
            }

            // Keyboard-driven Findings Triage: J/K navigate, A accept, D dismiss
            const isEditing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) ||
                              document.querySelector('.modal-backdrop:not(.hidden)');

            if (!isEditing && state.activeView === 'findings') {
                const cards = dom.findingsContainer ? dom.findingsContainer.querySelectorAll('.finding-card') : [];
                if (cards.length > 0) {
                    if (e.key === 'j' || e.key === 'J') {
                        e.preventDefault();
                        selectFindingIndex(state.selectedFindingIndex + 1);
                    } else if (e.key === 'k' || e.key === 'K') {
                        e.preventDefault();
                        selectFindingIndex(state.selectedFindingIndex - 1);
                    } else if (e.key === 'a' || e.key === 'A') {
                        e.preventDefault();
                        const activeCard = cards[state.selectedFindingIndex];
                        const acceptBtn = activeCard ? activeCard.querySelector('.accept-finding-btn') : null;
                        if (acceptBtn) acceptBtn.click();
                    } else if (e.key === 'd' || e.key === 'D') {
                        e.preventDefault();
                        const activeCard = cards[state.selectedFindingIndex];
                        const dismissBtn = activeCard ? activeCard.querySelector('.dismiss-finding-btn') : null;
                        if (dismissBtn) dismissBtn.click();
                    }
                }
            }
        });
    }

    // =========================================================================
    // 2. Connection Selector & Vault Lifecycle
    // =========================================================================

    async function fetchConnections() {
        try {
            const res = await fetch('/api/v2/connections');
            if (!res.ok) return;
            const data = await res.json();
            state.connections = data.connections || [];
            renderConnectionDropdown();
        } catch (err) {
            console.error('Failed to load connections:', err);
        }
    }

    function renderConnectionDropdown() {
        if (!dom.connSelect) return;
        dom.connSelect.innerHTML = '';

        if (state.connections.length === 0) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = 'No connections available';
            dom.connSelect.appendChild(opt);
            return;
        }

        state.connections.forEach(conn => {
            const opt = document.createElement('option');
            opt.value = conn.id;
            const tierBadge = conn.tier ? conn.tier.toUpperCase() : 'SANDBOX';
            opt.textContent = `${conn.name} [${conn.engine} · ${tierBadge}]`;
            dom.connSelect.appendChild(opt);
        });

        // Auto-select saved or first connection
        const savedConnId = localStorage.getItem('dimension_active_connection_id');
        const match = state.connections.find(c => c.id === savedConnId);
        if (match) {
            dom.connSelect.value = match.id;
            setActiveConnection(match.id);
        } else if (state.connections.length > 0) {
            dom.connSelect.value = state.connections[0].id;
            setActiveConnection(state.connections[0].id);
        }
    }

    function setActiveConnection(connId) {
        state.activeConnectionId = connId;
        state.activeConnection = state.connections.find(c => c.id === connId) || null;
        try {
            localStorage.setItem('dimension_active_connection_id', connId);
        } catch (e) {}

        // Update Pulse Dot Tier
        if (dom.connPulseDot && state.activeConnection) {
            dom.connPulseDot.className = 'conn-pulse-dot';
            const tier = (state.activeConnection.tier || 'sandbox').toLowerCase();
            dom.connPulseDot.classList.add(`tier-${tier}`);
        }

        // Update Changes Tier Banner
        if (dom.changesTierPill && state.activeConnection) {
            const tier = (state.activeConnection.tier || 'sandbox').toUpperCase();
            dom.changesTierPill.textContent = `Tier: ${tier}`;
            if (dom.changesSafetyAdvisory) {
                if (tier === 'PROD') {
                    dom.changesSafetyAdvisory.textContent = 'Decision D5: Production writes strictly blocked — Export scripts only';
                    dom.changesSafetyAdvisory.style.borderColor = 'rgba(239, 68, 68, 0.4)';
                    dom.changesSafetyAdvisory.style.color = '#ef4444';
                } else {
                    dom.changesSafetyAdvisory.textContent = 'Direct execution enabled with two-way shadow rollback verification';
                    dom.changesSafetyAdvisory.style.borderColor = 'rgba(16, 185, 129, 0.4)';
                    dom.changesSafetyAdvisory.style.color = '#10b981';
                }
            }
        }

        // Refresh current active view
        if (state.activeView === 'map') loadMap(connId);
        else if (state.activeView === 'findings') loadFindings(connId);
        else if (state.activeView === 'changes') loadProposals(connId);
        else if (state.activeView === 'glossary') loadGlossary(connId);
        else if (state.activeView === 'seeds') loadSeedPlan(connId);

        // Synchronize sidebar tables list
        refreshSidebarTables(connId);
    }

    async function refreshSidebarTables(connId) {
        try {
            const res = await fetch(`/api/v2/connections/${connId}/snapshots/latest`);
            if (res.ok) {
                const data = await res.json();
                const structure = data.snapshot ? data.snapshot.structure : null;
                if (structure && structure.tables && window.DimensionRenderTables) {
                    const adapted = structure.tables.map(t => ({
                        name: t.name,
                        row_count: t.row_count || 0,
                        columns: (t.columns || []).map(c => ({
                            name: c.name,
                            data_type: c.type || 'TEXT',
                            primary_key: c.primary_key || false,
                            nullable: c.nullable !== false
                        }))
                    }));
                    window.DimensionRenderTables(adapted);
                }
            }
        } catch (e) {
            console.warn('Could not sync sidebar tables:', e);
        }
    }

    // =========================================================================
    // 3. Database Connection Modal
    // =========================================================================

    function initDbModal() {
        if (!dom.dbModal) return;

        // Presets click
        document.querySelectorAll('.preset-pill').forEach(pill => {
            pill.addEventListener('click', () => {
                if (dom.dbConnectionInput && pill.dataset.preset) {
                    dom.dbConnectionInput.value = pill.dataset.preset;
                }
                if (dom.dbNameInput) {
                    dom.dbNameInput.value = pill.textContent.trim();
                }
                if (dom.dbTierSelect && pill.dataset.tier) {
                    dom.dbTierSelect.value = pill.dataset.tier;
                }
            });
        });

        // Submit Connection
        if (dom.dbModalConnectBtn) {
            dom.dbModalConnectBtn.addEventListener('click', async () => {
                const uri = (dom.dbConnectionInput ? dom.dbConnectionInput.value : '').trim();
                const name = (dom.dbNameInput && dom.dbNameInput.value.trim()) || 'Database Connection';
                const tier = (dom.dbTierSelect && dom.dbTierSelect.value) || 'sandbox';

                if (!uri) {
                    showStatus(dom.dbModalStatus, 'Please enter a valid connection string URI or path.', 'error');
                    return;
                }

                // Determine engine
                let engine = 'sqlite';
                if (uri.startsWith('postgresql') || uri.startsWith('postgres')) engine = 'postgresql';
                else if (uri.startsWith('duckdb')) engine = 'duckdb';

                dom.dbModalConnectBtn.disabled = true;
                const spinner = dom.dbModalConnectBtn.querySelector('.btn-spinner');
                if (spinner) spinner.classList.remove('hidden');

                showStatus(dom.dbModalStatus, 'Testing credentials and capturing baseline snapshot...', 'success');

                try {
                    const res = await fetch('/api/v2/connections', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name,
                            engine,
                            dsn_template: uri,
                            tier
                        })
                    });
                    const data = await res.json();
                    if (res.ok) {
                        showStatus(dom.dbModalStatus, `Connected successfully! Privilege Grade: ${data.privilege_grade}`, 'success');
                        await fetchConnections();
                        if (data.connection_id) {
                            setActiveConnection(data.connection_id);
                            if (dom.connSelect) dom.connSelect.value = data.connection_id;
                        }
                        setTimeout(() => {
                            closeModal(dom.dbModal);
                        }, 800);
                    } else {
                        showStatus(dom.dbModalStatus, data.detail || 'Connection failed.', 'error');
                    }
                } catch (err) {
                    showStatus(dom.dbModalStatus, 'Network error while connecting.', 'error');
                } finally {
                    dom.dbModalConnectBtn.disabled = false;
                    if (spinner) spinner.classList.add('hidden');
                }
            });
        }
    }

    // =========================================================================
    // 4. View 2: Schema Cartography & Interactive ERD
    // =========================================================================

    async function loadMap(connId) {
        if (!dom.erdNodesLayer || !connId) return;

        if (dom.mapConnBadge && state.activeConnection) {
            dom.mapConnBadge.textContent = `${state.activeConnection.name} (${state.activeConnection.tier.toUpperCase()})`;
        }

        try {
            const res = await fetch(`/api/v2/connections/${connId}/graph?include_inferred=true`);
            if (!res.ok) {
                dom.erdNodesLayer.innerHTML = `<div class="empty-tables-placeholder">No snapshot found. Click "Check Drift" to capture initial snapshot.</div>`;
                if (dom.erdSvg) dom.erdSvg.innerHTML = '';
                return;
            }

            const data = await res.json();
            state.currentGraph = data.graph;
            renderErdGraph(data.graph);
        } catch (err) {
            console.error('Failed to load ERD graph:', err);
        }
    }

    function renderErdGraph(graph) {
        if (!dom.erdNodesLayer || !graph) return;
        dom.erdNodesLayer.innerHTML = '';
        if (dom.erdSvg) dom.erdSvg.innerHTML = '';

        if (dom.mapStatsBadge) {
            dom.mapStatsBadge.textContent = `${graph.node_count || 0} tables · ${graph.edge_count || 0} relationships`;
        }

        const nodes = graph.nodes || [];
        const edges = graph.edges || [];

        if (nodes.length === 0) {
            dom.erdNodesLayer.innerHTML = `<div class="empty-tables-placeholder">No tables introspected for this connection.</div>`;
            return;
        }

        // Render Table Cards
        nodes.forEach(n => {
            const card = document.createElement('div');
            card.className = 'erd-table-card';
            card.dataset.tableName = n.id;

            card.innerHTML = `
                <div class="erd-table-header">
                    <div class="erd-table-title">
                        <span>📦</span>
                        <span>${escapeHtml(n.label)}</span>
                    </div>
                    <span class="erd-table-row-count">${(n.columns || []).length} cols</span>
                </div>
                <div class="erd-columns-list">
                    ${(n.columns || []).map(col => `
                        <div class="erd-col-row" data-col-name="${escapeHtml(col.name)}">
                            <div class="erd-col-left">
                                ${col.is_pk ? '<span class="erd-pk-badge" title="Primary Key">🔑</span>' : ''}
                                <span>${escapeHtml(col.name)}</span>
                            </div>
                            <div class="erd-col-right">
                                <span class="erd-col-type">${escapeHtml(col.type)}</span>
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
            dom.erdNodesLayer.appendChild(card);
        });

        // Delay SVG edge calculation until layout stabilizes
        requestAnimationFrame(() => {
            drawErdEdges(edges);
        });
    }

    function drawErdEdges(edges) {
        if (!dom.erdSvg || !dom.mapViewport) return;
        dom.erdSvg.innerHTML = '';

        const vpRect = dom.mapViewport.getBoundingClientRect();
        dom.erdSvg.setAttribute('width', dom.mapViewport.scrollWidth);
        dom.erdSvg.setAttribute('height', dom.mapViewport.scrollHeight);

        // Define SVG Arrow Markers
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        defs.innerHTML = `
            <marker id="arrow-solid" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 1 L 10 5 L 0 9 z" fill="#0284c7" />
            </marker>
            <marker id="arrow-inferred" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 1 L 10 5 L 0 9 z" fill="#06b6d4" />
            </marker>
        `;
        dom.erdSvg.appendChild(defs);

        edges.forEach(e => {
            const sourceCard = dom.erdNodesLayer.querySelector(`[data-table-name="${e.source}"]`);
            const targetCard = dom.erdNodesLayer.querySelector(`[data-table-name="${e.target}"]`);
            if (!sourceCard || !targetCard) return;

            const sRect = sourceCard.getBoundingClientRect();
            const tRect = targetCard.getBoundingClientRect();

            // Compute relative center positions
            const x1 = sRect.left - vpRect.left + dom.mapViewport.scrollLeft + sRect.width / 2;
            const y1 = sRect.top - vpRect.top + dom.mapViewport.scrollTop + sRect.height / 2;
            const x2 = tRect.left - vpRect.left + dom.mapViewport.scrollLeft + tRect.width / 2;
            const y2 = tRect.top - vpRect.top + dom.mapViewport.scrollTop + tRect.height / 2;

            // Draw Curved Bezier Path
            const dx = (x2 - x1) * 0.5;
            const pathData = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', pathData);
            path.setAttribute('fill', 'none');

            if (e.kind === 'inferred') {
                path.setAttribute('stroke', '#06b6d4');
                path.setAttribute('stroke-width', '2.5');
                path.setAttribute('stroke-dasharray', '6,4');
                path.setAttribute('marker-end', 'url(#arrow-inferred)');
                path.setAttribute('opacity', '0.9');
            } else {
                path.setAttribute('stroke', '#0284c7');
                path.setAttribute('stroke-width', '2');
                path.setAttribute('marker-end', 'url(#arrow-solid)');
                path.setAttribute('opacity', '0.75');
            }

            dom.erdSvg.appendChild(path);
        });
    }

    // Map Action: Detect Inferred Foreign Keys
    function initMapControls() {
        if (dom.mapInferBtn) {
            dom.mapInferBtn.addEventListener('click', async () => {
                if (!state.activeConnectionId) return;
                dom.mapInferBtn.disabled = true;
                const spinner = dom.mapInferBtn.querySelector('.btn-spinner');
                if (spinner) spinner.classList.remove('hidden');

                try {
                    const res = await fetch(`/api/v2/connections/${state.activeConnectionId}/relationships/infer`, { method: 'POST' });
                    const data = await res.json();
                    if (res.ok) {
                        await loadMap(state.activeConnectionId);
                        alert(`Inference Engine Complete!\nDiscovered ${data.count} implicit foreign key relationships with >= 85% mathematical containment.`);
                    } else {
                        alert('Inference error: ' + (data.detail || 'Failed to infer relationships.'));
                    }
                } catch (err) {
                    alert('Network error while inferring relationships.');
                } finally {
                    dom.mapInferBtn.disabled = false;
                    if (spinner) spinner.classList.add('hidden');
                }
            });
        }

        // Map Action: Check Drift
        if (dom.mapDiffBtn) {
            dom.mapDiffBtn.addEventListener('click', async () => {
                if (!state.activeConnectionId) return;
                try {
                    const res = await fetch(`/api/v2/connections/${state.activeConnectionId}/diff`);
                    const data = await res.json();
                    if (res.ok && dom.mapDriftBanner && dom.mapDriftText) {
                        const diff = data.diff || {};
                        const hasDrift = diff.has_drift;
                        if (hasDrift) {
                            dom.mapDriftText.textContent = `Drift Detected: Added Tables [${(diff.added_tables || []).join(', ') || 'none'}], Dropped [${(diff.dropped_tables || []).join(', ') || 'none'}], Altered [${(diff.altered_tables || []).join(', ') || 'none'}]`;
                            dom.mapDriftBanner.classList.remove('hidden');
                        } else {
                            dom.mapDriftText.textContent = 'Live schema perfectly matches baseline snapshot (0 drift detected).';
                            dom.mapDriftBanner.classList.remove('hidden');
                        }
                    }
                } catch (err) {
                    alert('Could not compute schema diff.');
                }
            });
        }

        if (dom.mapDriftDismissBtn) {
            dom.mapDriftDismissBtn.addEventListener('click', () => {
                if (dom.mapDriftBanner) dom.mapDriftBanner.classList.add('hidden');
            });
        }

        // Map Action: Export Mermaid
        if (dom.mapExportMermaidBtn) {
            dom.mapExportMermaidBtn.addEventListener('click', () => {
                if (!state.currentGraph) return;
                const g = state.currentGraph;
                let mermaid = 'erDiagram\n';

                (g.nodes || []).forEach(n => {
                    mermaid += `    ${n.id} {\n`;
                    (n.columns || []).forEach(c => {
                        const pkTag = c.is_pk ? 'PK' : '';
                        mermaid += `        ${c.type || 'text'} ${c.name} ${pkTag}\n`;
                    });
                    mermaid += `    }\n`;
                });

                (g.edges || []).forEach(e => {
                    const rel = e.kind === 'inferred' ? '..|>' : '}o--||';
                    mermaid += `    ${e.target} ${rel} ${e.source} : "${e.target_column || ''}"\n`;
                });

                openCodeViewer('Mermaid ERD Diagram', 'Diagram markup ready for Mermaid.js live rendering or Markdown embedding', mermaid);
            });
        }
    }

    // =========================================================================
    // 5. View 3: Data Hygiene & Anomaly Inbox
    // =========================================================================

    async function loadFindings(connId) {
        if (!dom.findingsContainer || !connId) return;

        try {
            const res = await fetch(`/api/v2/connections/${connId}/findings`);
            if (!res.ok) {
                dom.findingsContainer.innerHTML = '<div class="empty-tables-placeholder">No hygiene findings recorded yet. Click "Run Hygiene Audit" above.</div>';
                return;
            }

            const data = await res.json();
            state.allFindings = data.findings || [];
            updateFindingsCounts();
            renderFindingsList();
        } catch (err) {
            console.error('Failed to load findings:', err);
        }
    }

    function updateFindingsCounts() {
        const findings = state.allFindings;
        const open = findings.filter(f => f.status === 'open');
        const crit = findings.filter(f => f.severity === 'critical');
        const warn = findings.filter(f => f.severity === 'warning');
        const dism = findings.filter(f => f.status === 'dismissed');

        if (dom.findingsAllCount) dom.findingsAllCount.textContent = findings.length;
        if (dom.findingsOpenCount) dom.findingsOpenCount.textContent = open.length;
        if (dom.findingsCriticalCount) dom.findingsCriticalCount.textContent = crit.length;
        if (dom.findingsWarningCount) dom.findingsWarningCount.textContent = warn.length;
        if (dom.findingsDismissedCount) dom.findingsDismissedCount.textContent = dism.length;

        if (dom.findingsBadge) {
            dom.findingsBadge.textContent = open.length;
            dom.findingsBadge.classList.toggle('hidden', open.length === 0);
        }
    }

    function renderFindingsList() {
        if (!dom.findingsContainer) return;
        dom.findingsContainer.innerHTML = '';

        const filter = state.findingsFilter;
        let filtered = state.allFindings;

        if (filter === 'open') filtered = filtered.filter(f => f.status === 'open');
        else if (filter === 'critical') filtered = filtered.filter(f => f.severity === 'critical');
        else if (filter === 'warning') filtered = filtered.filter(f => f.severity === 'warning');
        else if (filter === 'dismissed') filtered = filtered.filter(f => f.status === 'dismissed');

        if (filtered.length === 0) {
            dom.findingsContainer.innerHTML = `<div class="empty-tables-placeholder">No findings matching "${filter}" filter.</div>`;
            return;
        }

        filtered.forEach(f => {
            const card = document.createElement('div');
            card.className = `finding-card severity-${f.severity || 'info'}`;

            const evidenceStr = JSON.stringify(f.evidence || {}, null, 2);
            const fixText = f.fix && f.fix.suggested_action ? f.fix.suggested_action : 'Review anomaly and standardize values.';

            card.innerHTML = `
                <div class="finding-header-row">
                    <div class="finding-title-group">
                        <span class="finding-target-badge">${escapeHtml(f.target || 'Database')}</span>
                        <span class="severity-pill ${f.severity || 'info'}">${escapeHtml(f.severity || 'INFO')}</span>
                        <span class="finding-kind-pill">${escapeHtml(f.kind || 'hygiene')}</span>
                    </div>
                    <span class="badge-pill secondary">${f.status === 'dismissed' ? 'Dismissed' : 'Open'}</span>
                </div>
                <div class="finding-summary-text">${escapeHtml(f.summary)}</div>
                <div class="finding-evidence-box">${escapeHtml(evidenceStr)}</div>
                <div class="finding-fix-box">
                    <span>💡</span>
                    <span><strong>Suggested Fix:</strong> ${escapeHtml(fixText)}</span>
                </div>
                <div class="finding-actions-row">
                    ${f.status === 'dismissed' ? `
                        <span class="form-hint">Dismiss reason: ${escapeHtml(f.dismiss_reason || 'Known test anomaly')}</span>
                    ` : `
                        <button class="toolbar-btn dismiss-finding-btn" data-id="${f.id}">✕ Dismiss</button>
                        <button class="toolbar-btn primary accept-finding-btn" data-id="${f.id}">✓ Accept Finding</button>
                    `}
                </div>
            `;

            // Action: Dismiss
            const dismissBtn = card.querySelector('.dismiss-finding-btn');
            if (dismissBtn) {
                dismissBtn.addEventListener('click', async () => {
                    const reason = prompt('Please enter a reason for dismissing this hygiene finding:', 'Intentional business edge-case');
                    if (!reason) return;
                    await updateFindingStatus(f.id, 'dismissed', reason);
                });
            }

            // Action: Accept
            const acceptBtn = card.querySelector('.accept-finding-btn');
            if (acceptBtn) {
                acceptBtn.addEventListener('click', async () => {
                    await updateFindingStatus(f.id, 'accepted');
                });
            }

            // Select card on click
            card.addEventListener('click', () => {
                const allCards = dom.findingsContainer ? Array.from(dom.findingsContainer.querySelectorAll('.finding-card')) : [];
                const idx = allCards.indexOf(card);
                if (idx !== -1) selectFindingIndex(idx);
            });

            dom.findingsContainer.appendChild(card);
        });

        // Initialize selection on first card
        selectFindingIndex(Math.min(state.selectedFindingIndex, filtered.length - 1));
    }

    async function updateFindingStatus(findingId, status, dismissReason = null) {
        try {
            const res = await fetch(`/api/v2/findings/${findingId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status, dismiss_reason: dismissReason })
            });
            if (res.ok) {
                await loadFindings(state.activeConnectionId);
            }
        } catch (err) {
            alert('Failed to update finding status.');
        }
    }

    // Findings Filter Tabs
    function initFindingsControls() {
        dom.findingsFilterTabs.forEach(btn => {
            btn.addEventListener('click', () => {
                dom.findingsFilterTabs.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state.findingsFilter = btn.dataset.filter || 'all';
                renderFindingsList();
            });
        });

        // Run Hygiene Audit Button
        if (dom.findingsRunAuditBtn) {
            dom.findingsRunAuditBtn.addEventListener('click', async () => {
                if (!state.activeConnectionId) return;
                dom.findingsRunAuditBtn.disabled = true;
                const spinner = dom.findingsRunAuditBtn.querySelector('.btn-spinner');
                if (spinner) spinner.classList.remove('hidden');

                try {
                    const res = await fetch(`/api/v2/connections/${state.activeConnectionId}/hygiene`, { method: 'POST' });
                    const data = await res.json();
                    if (res.ok) {
                        await loadFindings(state.activeConnectionId);
                        alert(`Hygiene Audit Completed!\nFound ${data.count} anomalies across orphaned records, sentinel values, and format inconsistencies.`);
                    } else {
                        alert('Hygiene audit error: ' + (data.detail || 'Audit execution failed.'));
                    }
                } catch (err) {
                    alert('Network error while running hygiene audit.');
                } finally {
                    dom.findingsRunAuditBtn.disabled = false;
                    if (spinner) spinner.classList.add('hidden');
                }
            });
        }
    }

    // =========================================================================
    // 6. View 4: Shadow Migrations, Lock Linting & Safe Approvals
    // =========================================================================

    async function loadProposals(connId) {
        if (!dom.proposalsContainer || !connId) return;

        try {
            const res = await fetch(`/api/v2/connections/${connId}/proposals`);
            if (!res.ok) {
                dom.proposalsContainer.innerHTML = '<div class="empty-tables-placeholder">No migration proposals submitted yet. Click "New Proposal" to create one.</div>';
                return;
            }

            const data = await res.json();
            renderProposalsList(data.proposals || []);
        } catch (err) {
            console.error('Failed to load proposals:', err);
        }
    }

    function renderProposalsList(proposals) {
        if (!dom.proposalsContainer) return;
        dom.proposalsContainer.innerHTML = '';

        if (proposals.length === 0) {
            dom.proposalsContainer.innerHTML = '<div class="empty-tables-placeholder">No migration proposals submitted yet. Click "New Proposal" to create one.</div>';
            return;
        }

        proposals.forEach(p => {
            const card = document.createElement('div');
            card.className = 'proposal-card';

            const shadow = p.shadow || {};
            const lint = p.lint || {};
            const isClean = shadow.rollback_clean;
            const isProd = state.activeConnection && state.activeConnection.tier.toLowerCase() === 'prod';

            card.innerHTML = `
                <div class="proposal-header">
                    <div class="proposal-goal-title">⚡ ${escapeHtml(p.goal)}</div>
                    <div class="proposal-badges-row">
                        <span class="badge-pill tier-pill">${escapeHtml(p.status || 'draft')}</span>
                        <span class="shadow-verified-badge">
                            <span>${isClean ? '✓' : '✕'}</span>
                            <span>Shadow Rollback: ${isClean ? 'Clean (Verified)' : 'Failed'}</span>
                        </span>
                    </div>
                </div>

                ${lint.is_risky ? `
                    <div class="lock-risk-alert-box">
                        <strong>⚠️ Lock Risk Warning:</strong>
                        ${(lint.warnings || []).map(w => `<div>• ${escapeHtml(w)}</div>`).join('')}
                    </div>
                ` : ''}

                <div class="code-split-view">
                    <div class="code-split-col">
                        <span class="code-col-label">Forward UP SQL</span>
                        <pre class="code-preview-block">${escapeHtml(p.up_sql)}</pre>
                    </div>
                    <div class="code-split-col">
                        <span class="code-col-label">Rollback DOWN SQL</span>
                        <pre class="code-preview-block">${escapeHtml(p.down_sql)}</pre>
                    </div>
                </div>

                <div class="proposal-actions-row">
                    <div class="toolbar-left">
                        <button class="toolbar-btn export-alembic-btn" data-id="${p.id}">Export Alembic</button>
                        <button class="toolbar-btn export-flyway-btn" data-id="${p.id}">Export Flyway</button>
                    </div>
                    <div class="toolbar-right">
                        ${p.status === 'approved' ? `
                            <button class="toolbar-btn primary apply-proposal-btn" data-id="${p.id}">
                                <span>🚀 Apply to ${isProd ? 'PROD (Blocked)' : 'Target'}</span>
                            </button>
                        ` : p.status === 'applied' ? `
                            <span class="shadow-verified-badge">✓ Applied</span>
                        ` : `
                            <button class="toolbar-btn reject-proposal-btn" data-id="${p.id}">Reject</button>
                            <button class="toolbar-btn primary approve-proposal-btn" data-id="${p.id}">Approve Proposal</button>
                        `}
                    </div>
                </div>
            `;

            // Actions
            const approveBtn = card.querySelector('.approve-proposal-btn');
            if (approveBtn) {
                approveBtn.addEventListener('click', () => {
                    openApprovalModal(p);
                });
            }

            const rejectBtn = card.querySelector('.reject-proposal-btn');
            if (rejectBtn) {
                rejectBtn.addEventListener('click', async () => {
                    await submitProposalDecision(p.id, 'rejected');
                });
            }

            const applyBtn = card.querySelector('.apply-proposal-btn');
            if (applyBtn) {
                applyBtn.addEventListener('click', async () => {
                    if (isProd) {
                        alert('Decision D5 Strict Guardrail: Direct execution on PROD connections is strictly disabled.\nPlease use the "Export Alembic" or "Export Flyway" buttons to review and deploy via CI/CD.');
                        return;
                    }
                    if (!confirm(`Apply migration "${p.goal}" directly to target database?`)) return;
                    await applyProposal(p.id);
                });
            }

            const alembicBtn = card.querySelector('.export-alembic-btn');
            if (alembicBtn) {
                alembicBtn.addEventListener('click', () => exportProposal(p.id, 'alembic'));
            }

            const flywayBtn = card.querySelector('.export-flyway-btn');
            if (flywayBtn) {
                flywayBtn.addEventListener('click', () => exportProposal(p.id, 'flyway'));
            }

            dom.proposalsContainer.appendChild(card);
        });
    }

    // New Proposal Submission
    function initProposalControls() {
        if (dom.newProposalBtn) {
            dom.newProposalBtn.addEventListener('click', () => {
                openModal(dom.newProposalModal);
            });
        }

        if (dom.newProposalSubmitBtn) {
            dom.newProposalSubmitBtn.addEventListener('click', async () => {
                const goal = (dom.proposalGoalInput ? dom.proposalGoalInput.value : '').trim();
                const upSql = (dom.proposalUpSql ? dom.proposalUpSql.value : '').trim();
                const downSql = (dom.proposalDownSql ? dom.proposalDownSql.value : '').trim();

                if (!goal || !upSql || !downSql) {
                    showStatus(dom.proposalModalStatus, 'Please fill in Goal, UP SQL, and DOWN SQL.', 'error');
                    return;
                }

                dom.newProposalSubmitBtn.disabled = true;
                const spinner = dom.newProposalSubmitBtn.querySelector('.btn-spinner');
                if (spinner) spinner.classList.remove('hidden');

                showStatus(dom.proposalModalStatus, 'Executing two-way shadow rollback check on scratch clone...', 'success');

                try {
                    const res = await fetch('/api/v2/proposals', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            connection_id: state.activeConnectionId,
                            goal,
                            up_sql: upSql,
                            down_sql: downSql
                        })
                    });
                    const data = await res.json();
                    if (res.ok) {
                        showStatus(dom.proposalModalStatus, 'Verified & Created proposal!', 'success');
                        await loadProposals(state.activeConnectionId);
                        setTimeout(() => closeModal(dom.newProposalModal), 600);
                    } else {
                        showStatus(dom.proposalModalStatus, data.detail || 'Proposal verification failed.', 'error');
                    }
                } catch (err) {
                    showStatus(dom.proposalModalStatus, 'Network error submitting proposal.', 'error');
                } finally {
                    dom.newProposalSubmitBtn.disabled = false;
                    if (spinner) spinner.classList.add('hidden');
                }
            });
        }
    }

    // Approval Modal Logic
    let activeApprovalProposal = null;

    function openApprovalModal(proposal) {
        activeApprovalProposal = proposal;
        if (!dom.approvalModal) return;

        const isDevOrProd = state.activeConnection && ['dev', 'prod'].includes(state.activeConnection.tier.toLowerCase());
        if (dom.approvalTypedGroup) {
            dom.approvalTypedGroup.classList.toggle('hidden', !isDevOrProd);
        }
        if (dom.approvalExpectedText) {
            dom.approvalExpectedText.textContent = state.activeConnection ? state.activeConnection.name : 'CONFIRM';
        }

        openModal(dom.approvalModal);
    }

    function initApprovalModal() {
        if (dom.approvalModalSubmitBtn) {
            dom.approvalModalSubmitBtn.addEventListener('click', async () => {
                if (!activeApprovalProposal) return;

                const decision = dom.approvalDecisionSelect ? dom.approvalDecisionSelect.value : 'approved';
                const typed = dom.approvalTypedInput ? dom.approvalTypedInput.value.trim() : '';
                const comment = dom.approvalCommentInput ? dom.approvalCommentInput.value.trim() : '';

                const isDevOrProd = state.activeConnection && ['dev', 'prod'].includes(state.activeConnection.tier.toLowerCase());
                const expectedText = state.activeConnection ? state.activeConnection.name : 'CONFIRM';

                if (isDevOrProd && decision === 'approved' && typed !== expectedText) {
                    showStatus(dom.approvalModalStatus, `Typed confirmation must exactly match "${expectedText}".`, 'error');
                    return;
                }

                dom.approvalModalSubmitBtn.disabled = true;
                try {
                    await submitProposalDecision(activeApprovalProposal.id, decision, typed, comment);
                    closeModal(dom.approvalModal);
                } finally {
                    dom.approvalModalSubmitBtn.disabled = false;
                }
            });
        }
    }

    async function submitProposalDecision(proposalId, decision, typedConfirmation = null, comment = null) {
        try {
            const res = await fetch(`/api/v2/proposals/${proposalId}/decision`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    decision,
                    typed_confirmation: typedConfirmation,
                    comment
                })
            });
            if (res.ok) {
                await loadProposals(state.activeConnectionId);
            }
        } catch (err) {
            alert('Failed to record approval decision.');
        }
    }

    async function applyProposal(proposalId) {
        try {
            const res = await fetch(`/api/v2/proposals/${proposalId}/apply`, { method: 'POST' });
            const data = await res.json();
            if (res.ok) {
                alert('Migration applied successfully to target database! Post-migration snapshot captured and audit chain updated.');
                await loadProposals(state.activeConnectionId);
            } else {
                alert('Apply error: ' + (data.detail || 'Execution failed.'));
            }
        } catch (err) {
            alert('Network error applying proposal.');
        }
    }

    async function exportProposal(proposalId, format) {
        try {
            const res = await fetch(`/api/v2/proposals/${proposalId}/export?format=${format}`);
            const data = await res.json();
            if (res.ok) {
                openCodeViewer(`${format.toUpperCase()} Migration Script`, `Exported migration for proposal ${proposalId}`, data.content);
            }
        } catch (err) {
            alert('Export failed.');
        }
    }

    // =========================================================================
    // 7. View 5: Schema Memory & Semantic Glossary
    // =========================================================================

    async function loadGlossary(connId) {
        if (!dom.glossaryContainer || !connId) return;

        try {
            const res = await fetch(`/api/v2/connections/${connId}/glossary`);
            if (!res.ok) {
                dom.glossaryContainer.innerHTML = '<div class="empty-tables-placeholder">No glossary entries recorded yet. Click "Add Term".</div>';
                return;
            }

            const data = await res.json();
            renderGlossaryGrid(data.entries || []);
        } catch (err) {
            console.error('Failed to load glossary:', err);
        }
    }

    function renderGlossaryGrid(entries) {
        if (!dom.glossaryContainer) return;
        dom.glossaryContainer.innerHTML = '';

        if (entries.length === 0) {
            dom.glossaryContainer.innerHTML = '<div class="empty-tables-placeholder">No business glossary definitions recorded yet. Click "Add Term" above.</div>';
            return;
        }

        const grid = document.createElement('div');
        grid.className = 'glossary-grid';

        entries.forEach(e => {
            const card = document.createElement('div');
            card.className = 'glossary-card';

            card.innerHTML = `
                <div class="glossary-header">
                    <span class="glossary-target-name">${escapeHtml(e.target)}</span>
                    <span class="glossary-kind-badge">${escapeHtml(e.kind || 'rule')}</span>
                </div>
                <div class="glossary-body-text">${escapeHtml(e.body)}</div>
                <div class="glossary-footer">
                    <span>Author: ${escapeHtml(e.author_kind || 'user')}</span>
                    <span class="badge-pill secondary">${escapeHtml(e.status || 'suggested')}</span>
                </div>
            `;
            grid.appendChild(card);
        });

        dom.glossaryContainer.appendChild(grid);
    }

    function initGlossaryControls() {
        if (dom.newGlossaryBtn) {
            dom.newGlossaryBtn.addEventListener('click', () => {
                openModal(dom.newGlossaryModal);
            });
        }

        if (dom.newGlossarySubmitBtn) {
            dom.newGlossarySubmitBtn.addEventListener('click', async () => {
                const targetKind = dom.glossaryTargetKind ? dom.glossaryTargetKind.value : 'column';
                const kind = dom.glossaryKind ? dom.glossaryKind.value : 'description';
                const target = (dom.glossaryTargetInput ? dom.glossaryTargetInput.value : '').trim();
                const body = (dom.glossaryBodyInput ? dom.glossaryBodyInput.value : '').trim();

                if (!target || !body) {
                    showStatus(dom.glossaryModalStatus, 'Please fill in Target Name and Business Definition.', 'error');
                    return;
                }

                dom.newGlossarySubmitBtn.disabled = true;
                try {
                    const res = await fetch(`/api/v2/connections/${state.activeConnectionId}/glossary`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ target_kind: targetKind, target, kind, body })
                    });
                    if (res.ok) {
                        await loadGlossary(state.activeConnectionId);
                        closeModal(dom.newGlossaryModal);
                    } else {
                        const data = await res.json();
                        showStatus(dom.glossaryModalStatus, data.detail || 'Failed to save definition.', 'error');
                    }
                } catch (err) {
                    showStatus(dom.glossaryModalStatus, 'Network error saving definition.', 'error');
                } finally {
                    dom.newGlossarySubmitBtn.disabled = false;
                }
            });
        }

        if (dom.glossaryExportMarkdownBtn) {
            dom.glossaryExportMarkdownBtn.addEventListener('click', async () => {
                if (!state.activeConnectionId) return;
                try {
                    const res = await fetch(`/api/v2/connections/${state.activeConnectionId}/export/docs?format=markdown`);
                    const data = await res.json();
                    if (res.ok) {
                        openCodeViewer('Markdown Data Dictionary', 'Semantic catalog export ready for README or GitHub Wiki', data.content);
                    }
                } catch (err) {
                    alert('Failed to export markdown catalog.');
                }
            });
        }

        if (dom.glossaryExportDbtBtn) {
            dom.glossaryExportDbtBtn.addEventListener('click', async () => {
                if (!state.activeConnectionId) return;
                try {
                    const res = await fetch(`/api/v2/connections/${state.activeConnectionId}/export/docs?format=dbt_sources`);
                    const data = await res.json();
                    if (res.ok) {
                        openCodeViewer('dbt sources.yml Export', 'Includes unique, not_null, and foreign key relationships tests', data.content);
                    }
                } catch (err) {
                    alert('Failed to export dbt sources.');
                }
            });
        }
    }

    // =========================================================================
    // 8. View 6: Topological Seed Generator
    // =========================================================================

    async function loadSeedPlan(connId) {
        if (!dom.seedsDagFlow || !connId) return;

        try {
            const res = await fetch(`/api/v2/connections/${connId}/seed-plans`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            if (!res.ok) return;

            const data = await res.json();
            state.currentSeedPlan = data.plan;
            renderSeedPlan(data.plan);
        } catch (err) {
            console.error('Failed to load seed plan:', err);
        }
    }

    function renderSeedPlan(plan) {
        if (!dom.seedsDagFlow || !dom.seedsTableConfigs || !plan) return;
        dom.seedsDagFlow.innerHTML = '';
        dom.seedsTableConfigs.innerHTML = '';

        const order = plan.topological_order || [];
        if (dom.seedsDagCountBadge) {
            dom.seedsDagCountBadge.textContent = `${order.length} tables in DAG sequence`;
        }

        // Render DAG Steps Flow
        order.forEach((tbl, idx) => {
            const node = document.createElement('div');
            node.className = 'dag-step-node';
            node.innerHTML = `
                <span class="dag-step-index">${idx + 1}</span>
                <span>${escapeHtml(tbl)}</span>
            `;
            dom.seedsDagFlow.appendChild(node);

            if (idx < order.length - 1) {
                const arrow = document.createElement('span');
                arrow.className = 'dag-arrow';
                arrow.textContent = '➔';
                dom.seedsDagFlow.appendChild(arrow);
            }
        });

        // Render Per-Table Row Inputs
        const tables = plan.tables || [];
        tables.forEach(t => {
            const rowBox = document.createElement('div');
            rowBox.className = 'seed-table-row-config';
            rowBox.innerHTML = `
                <span class="seed-table-label">${escapeHtml(t.table)}</span>
                <input type="number" class="seed-row-input" data-table="${escapeHtml(t.table)}" value="${t.target_rows || 25}" min="1" max="10000" />
            `;
            dom.seedsTableConfigs.appendChild(rowBox);
        });
    }

    function collectRowCounts() {
        const counts = {};
        if (!dom.seedsTableConfigs) return counts;
        dom.seedsTableConfigs.querySelectorAll('.seed-row-input').forEach(inp => {
            const tbl = inp.dataset.table;
            const val = parseInt(inp.value, 10) || 10;
            if (tbl) counts[tbl] = val;
        });
        return counts;
    }

    function initSeedControls() {
        if (dom.seedsGenerateSqlBtn) {
            dom.seedsGenerateSqlBtn.addEventListener('click', async () => {
                if (!state.activeConnectionId) return;
                const rowCounts = collectRowCounts();

                try {
                    const res = await fetch(`/api/v2/connections/${state.activeConnectionId}/seed-plans/generate`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ target: 'sql', row_counts: rowCounts })
                    });
                    const data = await res.json();
                    if (res.ok && dom.seedsPreviewCard && dom.seedsSqlCode) {
                        dom.seedsSqlCode.textContent = data.sql_inserts || '-- No inserts generated.';
                        dom.seedsPreviewCard.classList.remove('hidden');
                        dom.seedsPreviewCard.scrollIntoView({ behavior: 'smooth' });
                    }
                } catch (err) {
                    alert('Failed to generate SQL inserts.');
                }
            });
        }

        if (dom.seedsCopySqlBtn) {
            dom.seedsCopySqlBtn.addEventListener('click', () => {
                if (!dom.seedsSqlCode) return;
                navigator.clipboard.writeText(dom.seedsSqlCode.textContent).then(() => {
                    dom.seedsCopySqlBtn.textContent = '✓ Copied!';
                    setTimeout(() => dom.seedsCopySqlBtn.textContent = '📋 Copy SQL', 1500);
                });
            });
        }

        if (dom.seedsApplySandboxBtn) {
            dom.seedsApplySandboxBtn.addEventListener('click', async () => {
                if (!state.activeConnectionId) return;
                if (state.activeConnection && state.activeConnection.tier.toLowerCase() === 'prod') {
                    alert('Direct seed loading is blocked on PROD tier databases.');
                    return;
                }
                if (!confirm('Load synthetic seeds into active database?')) return;

                const rowCounts = collectRowCounts();
                dom.seedsApplySandboxBtn.disabled = true;
                const spinner = dom.seedsApplySandboxBtn.querySelector('.btn-spinner');
                if (spinner) spinner.classList.remove('hidden');

                try {
                    const res = await fetch(`/api/v2/connections/${state.activeConnectionId}/seed-plans/generate`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ target: 'apply', row_counts: rowCounts })
                    });
                    const data = await res.json();
                    if (res.ok) {
                        alert(`Seeds Loaded Successfully!\nInserted ${data.inserted_statements} records with 0 constraint violations!`);
                    } else {
                        alert('Seeding error: ' + (data.detail || 'Failed to insert seeds.'));
                    }
                } catch (err) {
                    alert('Network error while applying seeds.');
                } finally {
                    dom.seedsApplySandboxBtn.disabled = false;
                    if (spinner) spinner.classList.add('hidden');
                }
            });
        }
    }

    // =========================================================================
    // 9. Code Viewer Modal Utility
    // =========================================================================

    function openCodeViewer(title, subtitle, content) {
        if (!dom.codeViewerModal) return;
        if (dom.codeViewerTitle) dom.codeViewerTitle.textContent = title;
        if (dom.codeViewerSubtitle) dom.codeViewerSubtitle.textContent = subtitle;
        if (dom.codeViewerContent) dom.codeViewerContent.textContent = content;

        if (dom.codeViewerCopyBtn) {
            dom.codeViewerCopyBtn.onclick = () => {
                navigator.clipboard.writeText(content).then(() => {
                    dom.codeViewerCopyBtn.innerHTML = '<span>✓ Copied to Clipboard</span>';
                    setTimeout(() => {
                        dom.codeViewerCopyBtn.innerHTML = '<span>📋 Copy to Clipboard</span>';
                    }, 1500);
                });
            };
        }

        openModal(dom.codeViewerModal);
    }

    // Modal Helpers
    function openModal(modalEl) {
        if (!modalEl) return;
        modalEl.classList.remove('hidden');
        modalEl.setAttribute('aria-hidden', 'false');
    }

    function closeModal(modalEl) {
        if (!modalEl) return;
        modalEl.classList.add('hidden');
        modalEl.setAttribute('aria-hidden', 'true');
    }

    function showStatus(el, msg, type) {
        if (!el) return;
        el.textContent = msg;
        el.className = `status-message ${type}`;
        el.classList.remove('hidden');
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

    // Close Modals on cancel / backdrop
    function initModalClosers() {
        [
            [dom.dbModalCloseBtn, dom.dbModalCancelBtn, dom.dbModal],
            [dom.newProposalCloseBtn, dom.newProposalCancelBtn, dom.newProposalModal],
            [dom.approvalModalCloseBtn, dom.approvalModalCancelBtn, dom.approvalModal],
            [dom.newGlossaryCloseBtn, dom.newGlossaryCancelBtn, dom.newGlossaryModal],
            [dom.codeViewerCloseBtn, dom.codeViewerDoneBtn, dom.codeViewerModal]
        ].forEach(([closeBtn, cancelBtn, modal]) => {
            if (closeBtn) closeBtn.addEventListener('click', () => closeModal(modal));
            if (cancelBtn) cancelBtn.addEventListener('click', () => closeModal(modal));
            if (modal) {
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) closeModal(modal);
                });
            }
        });
    }

    // =========================================================================
    // 10. Bootstrap Workbench
    // =========================================================================

    function init() {
        initDomReferences();
        initModalClosers();
        initKeyboardShortcuts();
        initDbModal();
        initMapControls();
        initFindingsControls();
        initProposalControls();
        initApprovalModal();
        initGlossaryControls();
        initSeedControls();

        // View Tabs Click
        dom.viewTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetView = tab.dataset.view;
                if (targetView) switchView(targetView);
            });
        });

        // Connection Select Change
        if (dom.connSelect) {
            dom.connSelect.addEventListener('change', (e) => {
                setActiveConnection(e.target.value);
            });
        }

        // Load connections on startup
        fetchConnections();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Export for debugging or programmatic access
    window.DimensionStudioWorkbench = {
        state,
        switchView,
        setActiveConnection,
        loadMap,
        loadFindings,
        loadProposals,
        loadGlossary,
        loadSeedPlan,
        openCodeViewer
    };
})();
