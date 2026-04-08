/**
 * Version Control Approval Workflow UI
 * Standalone application for managing MCP server version approvals
 */

class VersionControlApp {
    constructor() {
        this.apiUrl = localStorage.getItem('apiUrl') || 'http://localhost:4444';
        this.bearerToken = localStorage.getItem('bearerToken') || '';
        this.pendingVersions = [];
        this.activeVersions = [];
        this.deactivatedVersions = [];
        this.modal = null;
        this.currentAction = null;
        
        this.init();
    }

    init() {
        // Load saved settings
        this.loadSettings();
        
        // Initialize event listeners
        this.initEventListeners();
        
        // Load data if token is configured
        if (this.bearerToken) {
            this.loadAllData();
        } else {
            this.showSettings();
            this.showNotification('Please configure your API settings', 'warning');
        }
        
        // Auto-refresh every 30 seconds
        setInterval(() => {
            if (this.bearerToken) {
                this.loadAllData();
            }
        }, 30000);
    }

    initEventListeners() {
        // Settings form
        document.getElementById('settingsForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveSettings();
        });

        // Test connection button
        document.getElementById('testConnectionBtn').addEventListener('click', () => {
            this.testConnection();
        });

        // Refresh button
        document.getElementById('refreshBtn').addEventListener('click', () => {
            this.loadAllData();
        });

        // Navigation links
        document.querySelectorAll('.bx--header__menu-item').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const target = e.target.getAttribute('href').substring(1);
                if (target === 'settings') {
                    this.toggleSettings();
                } else {
                    document.getElementById('settingsPanel').style.display = 'none';
                    document.getElementById(target).scrollIntoView({ behavior: 'smooth' });
                }
            });
        });

        // Modal close buttons
        document.querySelectorAll('[data-modal-close]').forEach(btn => {
            btn.addEventListener('click', () => this.closeModal());
        });

        // Notification close button
        document.querySelector('#notificationToast .bx--toast-notification__close-button').addEventListener('click', () => {
            document.getElementById('notificationToast').style.display = 'none';
        });
    }

    loadSettings() {
        document.getElementById('apiUrl').value = this.apiUrl;
        document.getElementById('bearerToken').value = this.bearerToken;
    }

    saveSettings() {
        this.apiUrl = document.getElementById('apiUrl').value.trim();
        this.bearerToken = document.getElementById('bearerToken').value.trim();
        
        localStorage.setItem('apiUrl', this.apiUrl);
        localStorage.setItem('bearerToken', this.bearerToken);
        
        this.showNotification('Settings saved successfully', 'success');
        this.loadAllData();
    }

    toggleSettings() {
        const panel = document.getElementById('settingsPanel');
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }

    showSettings() {
        document.getElementById('settingsPanel').style.display = 'block';
    }

    async testConnection() {
        const statusDiv = document.getElementById('connectionStatus');
        statusDiv.innerHTML = '<div class="bx--loading bx--loading--small"><svg class="bx--loading__svg" viewBox="0 0 100 100"><circle class="bx--loading__stroke" cx="50%" cy="50%" r="44"></circle></svg></div> Testing connection...';
        
        try {
            const response = await fetch(`${this.apiUrl}/api/version-control/pending`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${this.bearerToken}`,
                    'Content-Type': 'application/json'
                }
            });

            if (response.ok) {
                statusDiv.innerHTML = '<div class="connection-success">✓ Connection successful!</div>';
                setTimeout(() => {
                    statusDiv.innerHTML = '';
                }, 3000);
            } else {
                const error = await response.text();
                statusDiv.innerHTML = `<div class="connection-error">✗ Connection failed: ${response.status} ${response.statusText}</div>`;
            }
        } catch (error) {
            statusDiv.innerHTML = `<div class="connection-error">✗ Connection failed: ${error.message}</div>`;
        }
    }

    async loadAllData() {
        await Promise.all([
            this.loadPendingVersions(),
            this.loadActiveVersions(),
            this.loadDeactivatedVersions()
        ]);
        
        this.updateStatistics();
        this.updateLastUpdated();
    }

    async loadPendingVersions() {
        try {
            const response = await this.apiRequest('/api/version-control/pending');
            const data = await response.json();
            
            // All versions from /pending endpoint are pending status
            this.pendingVersions = data.versions;
            this.renderPendingVersions();
        } catch (error) {
            this.showError('pendingVersions', 'Failed to load pending versions: ' + error.message);
        }
    }

    async loadActiveVersions() {
        try {
            const response = await this.apiRequest('/api/version-control/active');
            const data = await response.json();
            
            // All versions from /active endpoint are active status
            this.activeVersions = data.versions;
            this.renderActiveVersions();
        } catch (error) {
            this.showError('activeVersions', 'Failed to load active versions: ' + error.message);
        }
    }

    async loadDeactivatedVersions() {
        try {
            const response = await this.apiRequest('/api/version-control/deactivated');
            const data = await response.json();
            
            // All versions from /deactivated endpoint are deactivated status
            this.deactivatedVersions = data.versions;
            this.renderDeactivatedVersions();
        } catch (error) {
            this.showError('deactivatedVersions', 'Failed to load deactivated versions: ' + error.message);
        }
    }

    renderPendingVersions() {
        const container = document.getElementById('pendingVersions');
        
        if (this.pendingVersions.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg width="64" height="64" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M16 2L16 30M2 16L30 16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                    <h4>No pending approvals</h4>
                    <p>All server versions are up to date</p>
                </div>
            `;
            return;
        }

        container.innerHTML = this.pendingVersions.map(version => this.renderVersionCard(version, true)).join('');
        
        // Attach event listeners to action buttons
        this.attachVersionActionListeners();
    }

    renderActiveVersions() {
        const container = document.getElementById('activeVersions');
        
        if (this.activeVersions.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg width="64" height="64" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M16 2L16 30M2 16L30 16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                    <h4>No active versions</h4>
                    <p>No server versions are currently active</p>
                </div>
            `;
            return;
        }

        container.innerHTML = this.activeVersions.map(version => this.renderVersionCard(version, false, true)).join('');
        
        // Attach event listeners to action buttons
        this.attachVersionActionListeners();
    }

    renderDeactivatedVersions() {
        const container = document.getElementById('deactivatedVersions');
        
        if (this.deactivatedVersions.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg width="64" height="64" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M16 2L16 30M2 16L30 16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                    <h4>No deactivated versions</h4>
                    <p>No versions have been rejected</p>
                </div>
            `;
            return;
        }

        container.innerHTML = this.deactivatedVersions.map(version => this.renderVersionCard(version, false, false)).join('');
        
        // Attach event listeners to action buttons
        this.attachVersionActionListeners();
    }

    renderVersionCard(version, isPending, isActive = false) {
        const statusClass = version.status === 'pending' ? 'status-pending' : 'status-deactivated';
        const createdDate = new Date(version.created_at).toLocaleString();
        
        return `
            <div class="bx--tile version-card ${statusClass}">
                <div class="version-header">
                    <div class="version-title">
                        <h4>${version.server_name}</h4>
                        <div class="version-badges">
                            <span class="version-badge">v${version.version_number}</span>
                            <span class="status-badge status-${version.status}">${version.status}</span>
                        </div>
                    </div>
                </div>
                
                <div class="version-details">
                    <div class="detail-row">
                        <span class="detail-label">Server Version:</span>
                        <span class="detail-value">${version.server_version}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Tools Count:</span>
                        <span class="detail-value">${version.tools_count}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Created:</span>
                        <span class="detail-value">${createdDate}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Created By:</span>
                        <span class="detail-value">${version.created_by}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Version ID:</span>
                        <span class="detail-value version-id">${version.id}</span>
                    </div>
                </div>
                
                ${isPending ? `
                    <div class="version-actions">
                        <button class="bx--btn bx--btn--primary bx--btn--sm approve-btn" data-version-id="${version.id}" data-server-name="${version.server_name}">
                            <svg focusable="false" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="16" height="16" viewBox="0 0 32 32" aria-hidden="true" style="margin-right: 8px;">
                                <path d="M13 24L4 15 5.414 13.586 13 21.171 26.586 7.586 28 9 13 24z"></path>
                            </svg>
                            Approve
                        </button>
                        <button class="bx--btn bx--btn--danger bx--btn--sm reject-btn" data-version-id="${version.id}" data-server-name="${version.server_name}">
                            <svg focusable="false" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="16" height="16" viewBox="0 0 32 32" aria-hidden="true" style="margin-right: 8px;">
                                <path d="M24 9.4L22.6 8 16 14.6 9.4 8 8 9.4 14.6 16 8 22.6 9.4 24 16 17.4 22.6 24 24 22.6 17.4 16 24 9.4z"></path>
                            </svg>
                            Reject
                        </button>
                    </div>
                ` : isActive ? `
                    <div class="version-actions">
                        <button class="bx--btn bx--btn--danger bx--btn--sm deactivate-btn" data-version-id="${version.id}" data-server-name="${version.server_name}">
                            <svg focusable="false" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="16" height="16" viewBox="0 0 32 32" aria-hidden="true" style="margin-right: 8px;">
                                <path d="M24 9.4L22.6 8 16 14.6 9.4 8 8 9.4 14.6 16 8 22.6 9.4 24 16 17.4 22.6 24 24 22.6 17.4 16 24 9.4z"></path>
                            </svg>
                            Deactivate
                        </button>
                    </div>
                ` : `
                    <div class="version-actions">
                        <button class="bx--btn bx--btn--primary bx--btn--sm reactivate-active-btn" data-version-id="${version.id}" data-server-name="${version.server_name}">
                            <svg focusable="false" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="16" height="16" viewBox="0 0 32 32" aria-hidden="true" style="margin-right: 8px;">
                                <path d="M13 24L4 15 5.414 13.586 13 21.171 26.586 7.586 28 9 13 24z"></path>
                            </svg>
                            Reactivate to Active
                        </button>
                        <button class="bx--btn bx--btn--secondary bx--btn--sm reactivate-pending-btn" data-version-id="${version.id}" data-server-name="${version.server_name}">
                            <svg focusable="false" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="16" height="16" viewBox="0 0 32 32" aria-hidden="true" style="margin-right: 8px;">
                                <path d="M18,28A12,12,0,1,0,6,16v6.2L2.4,18.6,1,20l6,6,6-6-1.4-1.4L8,22.2V16A10,10,0,1,1,18,26Z"></path>
                            </svg>
                            Reactivate to Pending
                        </button>
                    </div>
                `}
            </div>
        `;
    }

    attachVersionActionListeners() {
        // Approve buttons
        document.querySelectorAll('.approve-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const versionId = e.currentTarget.getAttribute('data-version-id');
                const serverName = e.currentTarget.getAttribute('data-server-name');
                this.confirmAction('approve', versionId, serverName);
            });
        });

        // Reject buttons
        document.querySelectorAll('.reject-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const versionId = e.currentTarget.getAttribute('data-version-id');
                const serverName = e.currentTarget.getAttribute('data-server-name');
                this.confirmAction('reject', versionId, serverName);
            });
        });

        // Deactivate buttons (for active versions)
        document.querySelectorAll('.deactivate-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const versionId = e.currentTarget.getAttribute('data-version-id');
                const serverName = e.currentTarget.getAttribute('data-server-name');
                this.confirmAction('deactivate', versionId, serverName);
            });
        });

        // Reactivate to Active buttons
        document.querySelectorAll('.reactivate-active-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const versionId = e.currentTarget.getAttribute('data-version-id');
                const serverName = e.currentTarget.getAttribute('data-server-name');
                this.confirmAction('reactivate-active', versionId, serverName);
            });
        });

        // Reactivate to Pending buttons
        document.querySelectorAll('.reactivate-pending-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const versionId = e.currentTarget.getAttribute('data-version-id');
                const serverName = e.currentTarget.getAttribute('data-server-name');
                this.confirmAction('reactivate-pending', versionId, serverName);
            });
        });
    }

    confirmAction(action, versionId, serverName) {
        const messages = {
            approve: `Are you sure you want to approve this version for <strong>${serverName}</strong>? This will activate the new version and allow tool calls to proceed.`,
            reject: `Are you sure you want to reject this version for <strong>${serverName}</strong>? This will deactivate the version and block tool calls.`,
            deactivate: `Are you sure you want to deactivate this version for <strong>${serverName}</strong>? This will block tool calls until reactivated.`,
            'reactivate-active': `Are you sure you want to reactivate this version for <strong>${serverName}</strong> to <strong>active</strong> status? Tool calls will be allowed immediately.`,
            'reactivate-pending': `Are you sure you want to reactivate this version for <strong>${serverName}</strong> to <strong>pending</strong> status? It will require approval before tool calls are allowed.`
        };

        document.getElementById('confirmModalMessage').innerHTML = messages[action];
        document.getElementById('confirmModalHeading').textContent = `Confirm ${action.charAt(0).toUpperCase() + action.slice(1)}`;
        
        this.currentAction = { action, versionId, serverName };
        this.showModal();
    }

    showModal() {
        const modal = document.getElementById('confirmModal');
        modal.classList.add('is-visible');
        
        // Set up confirm button
        const confirmBtn = document.getElementById('confirmModalAction');
        confirmBtn.onclick = () => this.executeAction();
    }

    closeModal() {
        const modal = document.getElementById('confirmModal');
        modal.classList.remove('is-visible');
        this.currentAction = null;
    }

    async executeAction() {
        if (!this.currentAction) return;

        const { action, versionId, serverName } = this.currentAction;
        this.closeModal();

        const statusMap = {
            approve: 'active',
            reject: 'deactivated',
            deactivate: 'deactivated',
            'reactivate-active': 'active',
            'reactivate-pending': 'pending'
        };

        try {
            const response = await this.apiRequest(
                `/api/version-control/versions/${versionId}/update-status`,
                'PUT',
                { new_status: statusMap[action] }
            );

            const result = await response.json();
            
            if (result.success) {
                this.showNotification(
                    `Successfully ${action}d version for ${serverName}`,
                    'success'
                );
                this.loadAllData();
            } else {
                throw new Error(result.message || 'Update failed');
            }
        } catch (error) {
            this.showNotification(
                `Failed to ${action} version: ${error.message}`,
                'error'
            );
        }
    }

    async apiRequest(endpoint, method = 'GET', body = null) {
        const options = {
            method,
            headers: {
                'Authorization': `Bearer ${this.bearerToken}`,
                'Content-Type': 'application/json'
            }
        };

        if (body) {
            options.body = JSON.stringify(body);
        }

        const response = await fetch(`${this.apiUrl}${endpoint}`, options);
        
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText}`);
        }

        return response;
    }

    showError(containerId, message) {
        const container = document.getElementById(containerId);
        container.innerHTML = `
            <div class="error-state">
                <svg width="64" height="64" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M16 2C8.3 2 2 8.3 2 16s6.3 14 14 14 14-6.3 14-14S23.7 2 16 2zm0 26C9.4 28 4 22.6 4 16S9.4 4 16 4s12 5.4 12 12-5.4 12-12 12z" fill="currentColor"/>
                    <path d="M21.4 23L16 17.6 10.6 23 9 21.4l5.4-5.4L9 10.6 10.6 9l5.4 5.4L21.4 9 23 10.6 17.6 16l5.4 5.4z" fill="currentColor"/>
                </svg>
                <h4>Error Loading Data</h4>
                <p>${message}</p>
                <button class="bx--btn bx--btn--primary bx--btn--sm" onclick="app.loadAllData()">Retry</button>
            </div>
        `;
    }

    showNotification(message, type = 'success') {
        const toast = document.getElementById('notificationToast');
        const title = document.getElementById('notificationTitle');
        const messageEl = document.getElementById('notificationMessage');
        
        // Set type class
        toast.className = `bx--toast-notification bx--toast-notification--${type}`;
        
        // Set content
        const titles = {
            success: 'Success',
            error: 'Error',
            warning: 'Warning',
            info: 'Information'
        };
        title.textContent = titles[type] || 'Notification';
        messageEl.textContent = message;
        
        // Show toast
        toast.style.display = 'flex';
        
        // Auto-hide after 5 seconds
        setTimeout(() => {
            toast.style.display = 'none';
        }, 5000);
    }

    updateStatistics() {
        document.getElementById('pendingCount').textContent = this.pendingVersions.length;
        document.getElementById('activeCount').textContent = this.activeVersions.length;
        document.getElementById('deactivatedCount').textContent = this.deactivatedVersions.length;
    }

    updateLastUpdated() {
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        document.getElementById('lastUpdated').textContent = timeString;
    }
}

// Initialize app when DOM is ready
let app;
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        app = new VersionControlApp();
    });
} else {
    app = new VersionControlApp();
}

// Made with Bob
