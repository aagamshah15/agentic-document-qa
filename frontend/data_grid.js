/**
 * Dimension Data & Schema Studio — High-Performance Interactive Data Grid
 * Component: Agent-UI-Data-Grid (frontend/data_grid.js)
 * 
 * Renders QueryResponse payloads (columns + rows) with:
 * - Sortable columns (smart type detection for numeric, string, date)
 * - Real-time client-side search filtering across all columns
 * - Multi-page pagination (10, 25, 50, all rows per page)
 * - CSV and JSON export buttons
 * - Obsidian & Carbon / Frosted Glass aesthetics with DM Sans & JetBrains Mono
 */

(function (window) {
    'use strict';

    class DimensionDataGrid {
        constructor(container, data, options = {}) {
            if (!container) {
                console.error('[DataGrid] Container element is required');
                return;
            }
            this.container = container;
            this.rawColumns = Array.isArray(data?.columns) ? data.columns : [];
            this.rawRows = Array.isArray(data?.rows) ? data.rows : [];
            this.rowCount = typeof data?.row_count === 'number' ? data.row_count : this.rawRows.length;
            this.executionTimeMs = data?.execution_time_ms ?? null;
            this.truncated = Boolean(data?.truncated);
            this.error = data?.error || null;

            this.options = Object.assign({
                defaultPageSize: 10,
                pageSizes: [10, 25, 50, 100],
                maxTableHeight: '440px',
                title: options.title || 'Query Results'
            }, options);

            // Grid state
            this.sortColIdx = null;
            this.sortDir = 'asc'; // 'asc' | 'desc'
            this.searchQuery = '';
            this.currentPage = 1;
            this.pageSize = this.options.defaultPageSize;

            this.init();
        }

        init() {
            this.container.innerHTML = '';
            this.container.classList.add('dimension-data-grid-wrapper');

            if (this.error) {
                this.renderError();
                return;
            }

            if (this.rawColumns.length === 0 && this.rawRows.length === 0) {
                this.renderEmpty('Empty Result Set (0 columns, 0 rows)');
                return;
            }

            this.renderStructure();
            this.update();
        }

        renderError() {
            this.container.innerHTML = `
                <div class="data-grid-error-card">
                    <div class="data-grid-error-header">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="8" x2="12" y2="12"></line>
                            <line x1="12" y1="16" x2="12.01" y2="16"></line>
                        </svg>
                        <span class="data-grid-error-title">Query Execution Failed</span>
                    </div>
                    <div class="data-grid-error-body">${this.escapeHtml(this.error)}</div>
                </div>
            `;
        }

        renderEmpty(msg = 'No data returned') {
            this.container.innerHTML = `
                <div class="data-grid-empty-state">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                        <line x1="3" y1="9" x2="21" y2="9"></line>
                        <line x1="9" y1="21" x2="9" y2="9"></line>
                    </svg>
                    <span>${this.escapeHtml(msg)}</span>
                </div>
            `;
        }

        renderStructure() {
            const gridCard = document.createElement('div');
            gridCard.className = 'data-grid-card';

            // Top Toolbar
            const toolbar = document.createElement('div');
            toolbar.className = 'data-grid-toolbar';
            toolbar.innerHTML = `
                <div class="data-grid-toolbar-left">
                    <div class="data-grid-search-box">
                        <svg class="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="11" cy="11" r="8"></circle>
                            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                        </svg>
                        <input type="text" class="data-grid-search-input" placeholder="Filter ${this.rawRows.length} rows..." />
                        <button type="button" class="data-grid-search-clear hidden" title="Clear filter">✕</button>
                    </div>
                    <div class="data-grid-meta-badges">
                        <span class="grid-badge grid-rows-badge">${this.rawRows.length} rows</span>
                        <span class="grid-badge grid-cols-badge">${this.rawColumns.length} cols</span>
                        ${this.executionTimeMs !== null ? `<span class="grid-badge grid-latency-badge">⚡ ${Number(this.executionTimeMs).toFixed(1)}ms</span>` : ''}
                        ${this.truncated ? `<span class="grid-badge grid-truncated-badge" title="Query result truncated by server limit">Truncated</span>` : ''}
                    </div>
                </div>
                <div class="data-grid-toolbar-right">
                    <button type="button" class="grid-btn grid-export-csv-btn" title="Download results as CSV">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                        </svg>
                        <span>Export CSV</span>
                    </button>
                    <button type="button" class="grid-btn grid-export-json-btn" title="Download results as JSON">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                            <polyline points="14 2 14 8 20 8"></polyline>
                            <line x1="16" y1="13" x2="8" y2="13"></line>
                        </svg>
                        <span>Export JSON</span>
                    </button>
                </div>
            `;

            // Scrollable Table Container
            const tableContainer = document.createElement('div');
            tableContainer.className = 'data-grid-table-container';
            tableContainer.style.maxHeight = this.options.maxTableHeight;

            const table = document.createElement('table');
            table.className = 'data-grid-table';
            table.innerHTML = `
                <thead>
                    <tr class="data-grid-header-row">
                        <th class="grid-th-index">#</th>
                        ${this.rawColumns.map((col, idx) => `
                            <th class="grid-th-col" data-col-idx="${idx}" title="Click to sort by ${this.escapeHtml(col)}">
                                <div class="grid-th-content">
                                    <span class="grid-th-name">${this.escapeHtml(col)}</span>
                                    <span class="grid-sort-indicator" data-sort="none">⇅</span>
                                </div>
                            </th>
                        `).join('')}
                    </tr>
                </thead>
                <tbody class="data-grid-tbody">
                </tbody>
            `;
            tableContainer.appendChild(table);

            // Pagination Footer
            const footer = document.createElement('div');
            footer.className = 'data-grid-footer';
            footer.innerHTML = `
                <div class="data-grid-footer-left">
                    <span class="grid-pagination-range">Showing 0-0 of 0</span>
                </div>
                <div class="data-grid-footer-center">
                    <label class="grid-page-size-label">
                        <span>Rows per page:</span>
                        <select class="grid-page-size-select">
                            ${this.options.pageSizes.map(size => `
                                <option value="${size}" ${size === this.pageSize ? 'selected' : ''}>${size}</option>
                            `).join('')}
                            <option value="all">All</option>
                        </select>
                    </label>
                </div>
                <div class="data-grid-footer-right">
                    <button type="button" class="grid-page-btn grid-first-page-btn" title="First page">«</button>
                    <button type="button" class="grid-page-btn grid-prev-page-btn" title="Previous page">‹</button>
                    <span class="grid-page-indicator">Page 1 of 1</span>
                    <button type="button" class="grid-page-btn grid-next-page-btn" title="Next page">›</button>
                    <button type="button" class="grid-page-btn grid-last-page-btn" title="Last page">»</button>
                </div>
            `;

            gridCard.appendChild(toolbar);
            gridCard.appendChild(tableContainer);
            gridCard.appendChild(footer);
            this.container.appendChild(gridCard);

            // Cache element references
            this.tableEl = table;
            this.tbodyEl = table.querySelector('.data-grid-tbody');
            this.searchInput = toolbar.querySelector('.data-grid-search-input');
            this.searchClearBtn = toolbar.querySelector('.data-grid-search-clear');
            this.rangeEl = footer.querySelector('.grid-pagination-range');
            this.pageIndicatorEl = footer.querySelector('.grid-page-indicator');
            this.pageSizeSelect = footer.querySelector('.grid-page-size-select');
            this.firstBtn = footer.querySelector('.grid-first-page-btn');
            this.prevBtn = footer.querySelector('.grid-prev-page-btn');
            this.nextBtn = footer.querySelector('.grid-next-page-btn');
            this.lastBtn = footer.querySelector('.grid-last-page-btn');

            this.bindEvents(gridCard);
        }

        bindEvents(gridCard) {
            // Sort header click
            const headers = gridCard.querySelectorAll('.grid-th-col');
            headers.forEach(th => {
                th.addEventListener('click', () => {
                    const idx = parseInt(th.dataset.colIdx, 10);
                    if (this.sortColIdx === idx) {
                        this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
                    } else {
                        this.sortColIdx = idx;
                        this.sortDir = 'asc';
                    }
                    this.currentPage = 1;
                    this.update();
                });
            });

            // Search filter input
            this.searchInput.addEventListener('input', (e) => {
                this.searchQuery = e.target.value.trim().toLowerCase();
                this.searchClearBtn.classList.toggle('hidden', !this.searchQuery);
                this.currentPage = 1;
                this.update();
            });

            this.searchClearBtn.addEventListener('click', () => {
                this.searchInput.value = '';
                this.searchQuery = '';
                this.searchClearBtn.classList.add('hidden');
                this.currentPage = 1;
                this.update();
            });

            // Page size change
            this.pageSizeSelect.addEventListener('change', (e) => {
                const val = e.target.value;
                this.pageSize = val === 'all' ? Infinity : parseInt(val, 10);
                this.currentPage = 1;
                this.update();
            });

            // Pagination button navigation
            this.firstBtn.addEventListener('click', () => {
                if (this.currentPage > 1) {
                    this.currentPage = 1;
                    this.update();
                }
            });
            this.prevBtn.addEventListener('click', () => {
                if (this.currentPage > 1) {
                    this.currentPage--;
                    this.update();
                }
            });
            this.nextBtn.addEventListener('click', () => {
                const totalPages = this.getTotalPages(this.getFilteredRows());
                if (this.currentPage < totalPages) {
                    this.currentPage++;
                    this.update();
                }
            });
            this.lastBtn.addEventListener('click', () => {
                const totalPages = this.getTotalPages(this.getFilteredRows());
                if (this.currentPage < totalPages) {
                    this.currentPage = totalPages;
                    this.update();
                }
            });

            // Export CSV
            const csvBtn = gridCard.querySelector('.grid-export-csv-btn');
            if (csvBtn) {
                csvBtn.addEventListener('click', () => this.exportCSV());
            }

            // Export JSON
            const jsonBtn = gridCard.querySelector('.grid-export-json-btn');
            if (jsonBtn) {
                jsonBtn.addEventListener('click', () => this.exportJSON());
            }
        }

        getFilteredRows() {
            if (!this.searchQuery) {
                return this.rawRows.slice();
            }
            return this.rawRows.filter(row => {
                return row.some(cell => {
                    if (cell === null || cell === undefined) return false;
                    return String(cell).toLowerCase().includes(this.searchQuery);
                });
            });
        }

        getSortedRows(rows) {
            if (this.sortColIdx === null) return rows;

            const idx = this.sortColIdx;
            const dirMultiplier = this.sortDir === 'asc' ? 1 : -1;

            return rows.slice().sort((a, b) => {
                const valA = a[idx];
                const valB = b[idx];

                if (valA === valB) return 0;
                if (valA === null || valA === undefined) return 1;
                if (valB === null || valB === undefined) return -1;

                // Numeric sort
                const numA = Number(valA);
                const numB = Number(valB);
                if (!isNaN(numA) && !isNaN(numB)) {
                    return (numA - numB) * dirMultiplier;
                }

                // Date sort attempt
                const dateA = Date.parse(valA);
                const dateB = Date.parse(valB);
                if (!isNaN(dateA) && !isNaN(dateB) && typeof valA === 'string' && valA.length > 5) {
                    return (dateA - dateB) * dirMultiplier;
                }

                // String fallback
                return String(valA).localeCompare(String(valB)) * dirMultiplier;
            });
        }

        getTotalPages(filteredRows) {
            if (this.pageSize === Infinity) return 1;
            return Math.max(1, Math.ceil(filteredRows.length / this.pageSize));
        }

        update() {
            const filteredRows = this.getFilteredRows();
            const sortedRows = this.getSortedRows(filteredRows);
            const totalRows = sortedRows.length;
            const totalPages = this.getTotalPages(filteredRows);

            if (this.currentPage > totalPages) {
                this.currentPage = totalPages;
            }

            // Update header sort indicators
            const headers = this.tableEl.querySelectorAll('.grid-th-col');
            headers.forEach(th => {
                const colIdx = parseInt(th.dataset.colIdx, 10);
                const indicator = th.querySelector('.grid-sort-indicator');
                if (colIdx === this.sortColIdx) {
                    indicator.textContent = this.sortDir === 'asc' ? '▲' : '▼';
                    indicator.setAttribute('data-sort', this.sortDir);
                    th.classList.add('sorted');
                } else {
                    indicator.textContent = '⇅';
                    indicator.setAttribute('data-sort', 'none');
                    th.classList.remove('sorted');
                }
            });

            // Calculate page slice
            let startIdx = 0;
            let endIdx = totalRows;
            if (this.pageSize !== Infinity) {
                startIdx = (this.currentPage - 1) * this.pageSize;
                endIdx = Math.min(startIdx + this.pageSize, totalRows);
            }
            const pageRows = sortedRows.slice(startIdx, endIdx);

            // Render tbody
            if (pageRows.length === 0) {
                this.tbodyEl.innerHTML = `
                    <tr class="grid-empty-row">
                        <td colspan="${this.rawColumns.length + 1}" class="grid-empty-cell">
                            No matching records found.
                        </td>
                    </tr>
                `;
            } else {
                this.tbodyEl.innerHTML = pageRows.map((row, rIdx) => {
                    const rowNum = startIdx + rIdx + 1;
                    return `
                        <tr class="grid-row">
                            <td class="grid-td-index">${rowNum}</td>
                            ${row.map(cell => this.formatCell(cell)).join('')}
                        </tr>
                    `;
                }).join('');
            }

            // Update footer controls
            const displayStart = totalRows === 0 ? 0 : startIdx + 1;
            this.rangeEl.textContent = `Showing ${displayStart}–${endIdx} of ${totalRows} rows${this.searchQuery ? ` (filtered from ${this.rawRows.length})` : ''}`;
            this.pageIndicatorEl.textContent = `Page ${this.currentPage} of ${totalPages}`;

            this.firstBtn.disabled = this.currentPage <= 1;
            this.prevBtn.disabled = this.currentPage <= 1;
            this.nextBtn.disabled = this.currentPage >= totalPages;
            this.lastBtn.disabled = this.currentPage >= totalPages;
        }

        formatCell(val) {
            if (val === null || val === undefined) {
                return `<td class="grid-td grid-td-null"><span class="cell-null">NULL</span></td>`;
            }
            if (typeof val === 'boolean') {
                return `<td class="grid-td"><span class="cell-bool ${val ? 'bool-true' : 'bool-false'}">${val ? 'TRUE' : 'FALSE'}</span></td>`;
            }
            if (typeof val === 'number') {
                return `<td class="grid-td grid-td-number">${val.toLocaleString()}</td>`;
            }
            if (typeof val === 'object') {
                try {
                    return `<td class="grid-td grid-td-json" title="${this.escapeHtml(JSON.stringify(val))}">${this.escapeHtml(JSON.stringify(val))}</td>`;
                } catch (e) {
                    return `<td class="grid-td">${this.escapeHtml(String(val))}</td>`;
                }
            }
            const str = String(val);
            return `<td class="grid-td" title="${this.escapeHtml(str)}">${this.escapeHtml(str)}</td>`;
        }

        exportCSV() {
            const rows = this.getFilteredRows();
            const headers = this.rawColumns;

            const escapeCSV = (val) => {
                if (val === null || val === undefined) return '';
                let s = String(val);
                if (typeof val === 'object') {
                    try { s = JSON.stringify(val); } catch (e) {}
                }
                if (s.includes('"') || s.includes(',') || s.includes('\n') || s.includes('\r')) {
                    return `"${s.replace(/"/g, '""')}"`;
                }
                return s;
            };

            const csvLines = [];
            csvLines.push(headers.map(escapeCSV).join(','));
            rows.forEach(r => {
                csvLines.push(r.map(escapeCSV).join(','));
            });

            const csvContent = csvLines.join('\r\n');
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `dimension_query_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        exportJSON() {
            const rows = this.getFilteredRows();
            const headers = this.rawColumns;

            const jsonObjects = rows.map(row => {
                const obj = {};
                headers.forEach((h, idx) => {
                    obj[h] = row[idx];
                });
                return obj;
            });

            const jsonStr = JSON.stringify(jsonObjects, null, 2);
            const blob = new Blob([jsonStr], { type: 'application/json;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `dimension_query_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
    }

    // Export helpers globally
    window.DimensionDataGrid = DimensionDataGrid;
    window.renderDataGrid = function (container, data, options) {
        return new DimensionDataGrid(container, data, options);
    };
})(window);
