/**
 * HA Boss Dashboard
 * Main application logic and orchestration
 */

import { APIClient } from './api-client.js';
import ChartManager from './charts.js';
import Components from './components.js';

class Dashboard {
  // Poll intervals and limits
  static PLANS_POLL_INTERVAL_MS = 300000;  // 5 minutes (plans are static)
  static ENTITIES_POLL_INTERVAL_MS = 60000;
  static PLAN_EXECUTIONS_LIMIT = 20;

  constructor() {
    this.api = new APIClient();
    this.charts = ChartManager;
    this.currentTab = 'overview';
    this.pollingIntervals = {};
    this.instances = [];
    this.currentInstance = this.api.currentInstance;
    this.statusHistory = {
      timestamps: [],
      attempted: [],
      succeeded: [],
      failed: []
    };

    // Current healing history filter ('all', 'success', 'failed')
    this.healingFilter = 'all';

    // Per-instance history cache (max 100 data points per instance)
    this.statusHistoryCache = {};
    this.maxHistoryPoints = 100;

    // WebSocket support (graceful fallback to polling if not available)
    this.ws = null;
    this.useWebSocket = true; // Try WebSocket first
    this.wsConnected = false;

    // Initialize dayjs relative time plugin
    if (typeof dayjs !== 'undefined' && dayjs.extend) {
      dayjs.extend(window.dayjs_plugin_relativeTime);
    }
  }

  /**
   * Initialize the dashboard
   */
  async init() {
    console.log('Initializing HA Boss Dashboard...');

    // Setup event listeners
    this.setupEventListeners();

    // Load instances
    await this.loadInstances();

    // Initialize WebSocket (try first)
    if (this.useWebSocket) {
      this.initWebSocket();
    }

    // Check API key and connection
    await this.checkApiKey();

    // Load initial tab
    await this.loadOverviewTab();

    // Start polling (WebSocket will reduce polling frequency)
    this.startPolling();

    console.log('Dashboard initialized successfully');
  }

  /**
   * Initialize WebSocket connection for real-time updates
   */
  initWebSocket() {
    if (typeof WebSocketClient === 'undefined') {
      console.warn('WebSocket client not available, falling back to polling');
      this.useWebSocket = false;
      return;
    }

    try {
      const baseUrl = window.location.origin;
      this.ws = new WebSocketClient(baseUrl, this.currentInstance);

      // Connection state handlers
      this.ws.onConnected = () => {
        console.log('✓ WebSocket connected');
        this.wsConnected = true;
        this.showToast('Real-time updates enabled', 'success');
        // Reduce polling frequency when WebSocket is connected
        this.adjustPollingForWebSocket();
      };

      this.ws.onDisconnected = () => {
        console.log('WebSocket disconnected, using polling');
        this.wsConnected = false;
        // Resume normal polling when WebSocket disconnects
        this.stopPolling();
        this.startPolling();
      };

      this.ws.onError = (error) => {
        console.error('WebSocket error:', error);
      };

      // Register event handlers for real-time updates
      this.setupWebSocketHandlers();

      // Connect
      this.ws.connect();

    } catch (error) {
      console.error('Failed to initialize WebSocket:', error);
      this.useWebSocket = false;
    }
  }

  /**
   * Setup WebSocket event handlers
   */
  setupWebSocketHandlers() {
    // Entity state changes
    this.ws.on('entity_state_changed', (message) => {
      console.log('Entity state changed:', message.entity_id);
      // Refresh monitoring tab if active
      if (this.currentTab === 'monitoring') {
        this.loadMonitoringTab();
      }
    });

    // Health status updates
    this.ws.on('health_status', (message) => {
      console.log('Health status update received');
      this.refreshStatus();
    });

    // Healing actions
    this.ws.on('healing_action', (message) => {
      console.log('Healing action:', message.action);
      this.showToast(`Healing action: ${message.action.entity_id}`, 'info');
      // Refresh healing tab if active
      if (this.currentTab === 'healing') {
        this.loadHealingHistory();
      }
    });

    // Instance connection status
    this.ws.on('instance_connection', (message) => {
      console.log('Instance connection status:', message.connected);
      this.showToast(
        `Instance ${message.instance_id} ${message.connected ? 'connected' : 'disconnected'}`,
        message.connected ? 'success' : 'warning'
      );
      this.loadInstances();
    });

    // Connected confirmation
    this.ws.on('connected', (message) => {
      console.log('WebSocket connected to instance:', message.instance_id);
    });
  }

  /**
   * Adjust polling intervals when WebSocket is active
   */
  adjustPollingForWebSocket() {
    // When WebSocket is connected, reduce polling frequency significantly
    // Keep minimal polling as a sanity check
    this.stopPolling();

    // Very infrequent polling as fallback (every 5 minutes)
    this.pollingIntervals.status = setInterval(() => this.refreshStatus(), 300000);

    // Tab-specific polling remains off - WebSocket handles it
  }

  /**
   * Load available instances
   */
  async loadInstances() {
    try {
      this.instances = await this.api.getInstances();
      console.log('Loaded instances:', this.instances);

      // Update instance selector
      const selector = document.getElementById('instanceSelector');
      selector.innerHTML = '';

      // Add "All Instances" option first
      const allOption = document.createElement('option');
      allOption.value = 'all';
      allOption.textContent = '🌐 All Instances';
      allOption.title = 'View aggregated data from all instances';
      if (this.currentInstance === 'all') {
        allOption.selected = true;
      }
      selector.appendChild(allOption);

      // Add separator
      const separator = document.createElement('option');
      separator.disabled = true;
      separator.textContent = '──────────';
      selector.appendChild(separator);

      // Add individual instances
      this.instances.forEach(instance => {
        const option = document.createElement('option');
        option.value = instance.instance_id;

        // Add visual state indicator
        const stateIcon = {
          connected: '🟢',
          disconnected: '🔴',
          unknown: '🟡'
        }[instance.state] || '🟡';

        option.textContent = `${stateIcon} ${instance.instance_id}`;

        // Add tooltip with instance details
        const tooltipParts = [
          `Instance: ${instance.instance_id}`,
          `Status: ${instance.state}`,
        ];
        if (instance.monitored_entities !== undefined) {
          tooltipParts.push(`Entities: ${instance.monitored_entities}`);
        }
        option.title = tooltipParts.join('\n');

        // Add data attributes for CSS styling
        option.dataset.state = instance.state;

        if (instance.instance_id === this.currentInstance) {
          option.selected = true;
        }
        selector.appendChild(option);
      });
    } catch (error) {
      console.error('Failed to load instances:', error);
      this.showToast('Failed to load instances - using All Instances view', 'error');

      // Fallback: Add All Instances option to keep dashboard functional
      const selector = document.getElementById('instanceSelector');
      selector.innerHTML = '';
      const allOption = document.createElement('option');
      allOption.value = 'all';
      allOption.textContent = '🌐 All Instances';
      allOption.title = 'View aggregated data from all instances';
      allOption.selected = true;
      selector.appendChild(allOption);

      // Ensure we're using the all instances view
      this.currentInstance = 'all';
      this.api.setInstance('all');
    }
  }

  /**
   * Handle instance selection change
   */
  async onInstanceChange(instanceId) {
    console.log('Switching to instance:', instanceId);

    // Save previous instance for error recovery
    const previousInstance = this.currentInstance;
    const selector = document.getElementById('instanceSelector');

    try {
      // Disable selector and show loading state
      selector.disabled = true;
      selector.classList.add('opacity-50', 'cursor-wait', 'loading');

      // Show loading toast
      this.showToast(`Switching to instance: ${instanceId}...`, 'info', 2000);

      // Save current instance history to cache BEFORE switching
      if (this.currentInstance) {
        this.statusHistoryCache[this.currentInstance] = {
          timestamps: [...this.statusHistory.timestamps],
          attempted: [...this.statusHistory.attempted],
          succeeded: [...this.statusHistory.succeeded],
          failed: [...this.statusHistory.failed]
        };

        // Apply cache size limit (max 100 data points per instance)
        const cache = this.statusHistoryCache[this.currentInstance];
        if (cache.timestamps.length > this.maxHistoryPoints) {
          cache.timestamps = cache.timestamps.slice(-this.maxHistoryPoints);
          cache.attempted = cache.attempted.slice(-this.maxHistoryPoints);
          cache.succeeded = cache.succeeded.slice(-this.maxHistoryPoints);
          cache.failed = cache.failed.slice(-this.maxHistoryPoints);
        }
      }

      // Stop all polling to prevent race conditions with old instance_id
      this.stopPolling();

      // Switch to new instance
      this.currentInstance = instanceId;
      this.api.setInstance(instanceId);

      // Restore history for new instance (or initialize if first time)
      this.statusHistory = this.statusHistoryCache[instanceId] || {
        timestamps: [],
        attempted: [],
        succeeded: [],
        failed: []
      };

      // Reload current tab with new instance
      await this.switchTab(this.currentTab);

      // Restart polling with new instance_id
      this.startPolling();

      // Show success toast
      this.showToast(`Switched to instance: ${instanceId}`, 'success');

    } catch (error) {
      console.error('Error switching instance:', error);
      this.showToast(`Failed to switch instance: ${error.message}`, 'error');

      // Revert to PREVIOUS instance on error
      selector.value = previousInstance;
      this.currentInstance = previousInstance;
      this.api.setInstance(previousInstance);

    } finally {
      // Re-enable selector
      selector.disabled = false;
      selector.classList.remove('opacity-50', 'cursor-wait', 'loading');
    }
  }

  /**
   * Setup all event listeners
   */
  setupEventListeners() {
    // Instance selector
    document.getElementById('instanceSelector').addEventListener('change', (e) => {
      this.onInstanceChange(e.target.value);
    });

    // Tab navigation
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.target.dataset.tab;
        this.switchTab(tab);
      });
    });

    // API Key buttons (now in Settings tab)
    document.getElementById('saveKeyBtn').addEventListener('click', () => {
      this.saveApiKey();
    });

    document.getElementById('clearKeyBtn').addEventListener('click', () => {
      this.clearApiKey();
    });

    document.getElementById('testKeyBtn').addEventListener('click', () => {
      this.testApiKey();
    });

    // Close modals on outside click
    document.getElementById('entityModal').addEventListener('click', (e) => {
      if (e.target.id === 'entityModal') {
        this.hideEntityModal();
      }
    });

    document.getElementById('closeEntityBtn').addEventListener('click', () => {
      this.hideEntityModal();
    });

    // Form submissions
    document.getElementById('analyzeForm').addEventListener('submit', (e) => {
      e.preventDefault();
      this.analyzeAutomation();
    });

    document.getElementById('healingForm').addEventListener('submit', (e) => {
      e.preventDefault();
      this.triggerHealing();
    });

    document.getElementById('suppressionForm')?.addEventListener('submit', (e) => {
      e.preventDefault();
      const entityId = document.getElementById('suppressEntityId').value.trim();
      this.suppressEntity(entityId);
    });

    // Refresh buttons
    document.getElementById('refreshEntitiesBtn').addEventListener('click', () => {
      this.loadMonitoringTab();
    });

    document.getElementById('refreshSummaryBtn').addEventListener('click', () => {
      this.loadWeeklySummary();
    });

    // Settings tab buttons
    document.getElementById('saveSettingsBtn')?.addEventListener('click', () => {
      this.saveSettings();
    });

    document.getElementById('resetSettingsBtn')?.addEventListener('click', () => {
      this.resetSettings();
    });

    document.getElementById('addInstanceBtn')?.addEventListener('click', () => {
      this.showInstanceModal();
    });

    // Instance modal
    document.getElementById('closeInstanceBtn')?.addEventListener('click', () => {
      this.hideInstanceModal();
    });

    document.getElementById('cancelInstanceBtn')?.addEventListener('click', () => {
      this.hideInstanceModal();
    });

    document.getElementById('instanceModal')?.addEventListener('click', (e) => {
      if (e.target.id === 'instanceModal') {
        this.hideInstanceModal();
      }
    });

    document.getElementById('instanceForm')?.addEventListener('submit', (e) => {
      e.preventDefault();
      this.saveInstance();
    });

    document.getElementById('testInstanceBtn')?.addEventListener('click', () => {
      this.testInstance();
    });

    // Page visibility (pause polling when hidden)
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        this.stopPolling();
      } else {
        this.startPolling();
      }
    });
  }

  // ==================== API Key Management ====================

  /**
   * Check API key and test connection
   */
  async checkApiKey() {
    // If no API key stored, show settings modal
    if (!this.api.apiKey) {
      this.updateStatusIndicator('disconnected', 'No API key');
      // Don't force modal - auth might be disabled
      return;
    }

    // Test the stored key
    try {
      await this.api.getHealth();
      this.updateStatusIndicator('connected', 'Connected');
    } catch (error) {
      console.error('API key test failed:', error);
      this.updateStatusIndicator('error', 'Connection failed');

      if (error.message.includes('Authentication failed')) {
        this.showToast('Invalid API key. Please update your settings.', 'error');
      }
    }
  }

  /**
   * Save API key
   */
  async saveApiKey() {
    const input = document.getElementById('apiKeyInput');
    const key = input.value.trim();

    if (!key) {
      this.api.setApiKey(null);
      this.showToast('API key cleared', 'info');
      return;
    }

    // Test the key
    const result = await this.api.testApiKey(key);

    if (result.success) {
      this.showToast('API key saved successfully', 'success');
      this.updateStatusIndicator('connected', 'Connected');

      // Reload current tab
      this.switchTab(this.currentTab);
    } else {
      document.getElementById('testResult').innerHTML = Components.errorAlert(result.error);
    }
  }

  /**
   * Clear API key
   */
  clearApiKey() {
    this.api.setApiKey(null);
    document.getElementById('apiKeyInput').value = '';
    this.showToast('API key cleared', 'info');
    this.updateStatusIndicator('disconnected', 'No API key');
  }

  /**
   * Test API key without saving
   */
  async testApiKey() {
    const input = document.getElementById('apiKeyInput');
    const key = input.value.trim();
    const resultDiv = document.getElementById('testResult');

    if (!key) {
      resultDiv.textContent = '';
      return;
    }

    resultDiv.innerHTML = '<span class="text-gray-600">Testing...</span>';

    const result = await this.api.testApiKey(key);

    if (result.success) {
      resultDiv.innerHTML = Components.successAlert('Connection successful!');
    } else {
      resultDiv.innerHTML = Components.errorAlert(result.error);
    }
  }

  // ==================== Status Indicator ====================

  /**
   * Update connection status indicator
   * @param {string} status - Status (connected, disconnected, error)
   * @param {string} text - Status text
   */
  updateStatusIndicator(status, text) {
    const dot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');

    const colors = {
      connected: 'bg-green-500 status-pulse',
      disconnected: 'bg-gray-400',
      error: 'bg-red-500'
    };

    dot.className = `w-3 h-3 rounded-full ${colors[status] || colors.disconnected}`;
    statusText.textContent = text;
  }

  // ==================== Tab Management ====================

  /**
   * Switch to a different tab
   * @param {string} tabName - Tab name
   */
  async switchTab(tabName) {
    // Update active tab button
    document.querySelectorAll('.tab-btn').forEach(btn => {
      if (btn.dataset.tab === tabName) {
        btn.classList.add('tab-active');
        btn.setAttribute('aria-selected', 'true');
      } else {
        btn.classList.remove('tab-active');
        btn.setAttribute('aria-selected', 'false');
      }
    });

    // Hide all tab contents
    document.querySelectorAll('.tab-content').forEach(content => {
      content.classList.add('hidden');
    });

    // Show selected tab
    const tabContent = document.getElementById(`${tabName}Tab`);
    if (tabContent) {
      tabContent.classList.remove('hidden');
    }

    // Stop tab-specific polling
    this.stopTabPolling();

    // Update current tab
    this.currentTab = tabName;

    // Load tab content
    try {
      switch (tabName) {
        case 'overview':
          await this.loadOverviewTab();
          break;
        case 'monitoring':
          await this.loadMonitoringTab();
          break;
        case 'analysis':
          await this.loadAnalysisTab();
          break;
        case 'automations':
          await this.loadAutomationsTab();
          break;
        case 'healing':
          await this.loadHealingTab();
          break;
        case 'healingPlans':
          await this.loadHealingPlansTab();
          break;
        case 'settings':
          await this.loadSettingsTab();
          break;
      }
    } catch (error) {
      console.error(`Error loading ${tabName} tab:`, error);
      this.showToast(`Failed to load ${tabName} tab: ${error.message}`, 'error');
    }

    // Start tab-specific polling
    this.startTabPolling();
  }

  // ==================== Overview Tab ====================

  /**
   * Load overview tab content
   */
  async loadOverviewTab() {
    try {
      const [status, health] = await Promise.all([
        this.api.getStatus(),
        this.api.getHealth()
      ]);

      // Update service status
      document.getElementById('serviceState').textContent = status.state;
      document.getElementById('serviceUptime').textContent = Components.formatDuration(status.uptime_seconds);

      // Extract and format discovery timestamp
      // Handle both single-instance and aggregate mode (prefixed keys)
      const findDiscoveryTimestamp = (essential) => {
        if (!essential) return null;
        // Direct match (single-instance mode)
        if (essential.entity_discovery_complete?.details?.last_refresh) {
          return essential.entity_discovery_complete.details.last_refresh;
        }
        // Prefixed match (aggregate mode) - find most recent
        const prefixedKeys = Object.keys(essential).filter(k => k.endsWith(':entity_discovery_complete'));
        let mostRecent = null;
        for (const key of prefixedKeys) {
          const timestamp = essential[key]?.details?.last_refresh;
          if (timestamp && (!mostRecent || timestamp > mostRecent)) {
            mostRecent = timestamp;
          }
        }
        return mostRecent;
      };

      const discoveryTimestamp = findDiscoveryTimestamp(health.essential);
      if (discoveryTimestamp) {
        // Format to minute granularity in local time: "Dec 28, 2025 7:57 PM"
        document.getElementById('lastDiscovery').textContent = dayjs(discoveryTimestamp).format('MMM DD, YYYY h:mm A');
      } else {
        document.getElementById('lastDiscovery').textContent = 'Never';
      }

      document.getElementById('healthChecks').textContent = status.health_checks_performed;
      document.getElementById('monitoredEntities').textContent = status.monitored_entities;

      // Update healing stats
      document.getElementById('healingsAttempted').textContent = status.healings_attempted;
      document.getElementById('healingsSucceeded').textContent = status.healings_succeeded;
      document.getElementById('healingsFailed').textContent = status.healings_failed;

      // Update health check
      document.getElementById('healthStatus').innerHTML = Components.statusBadge(health.status, health.status.toUpperCase());

      // Extract health status from nested structure
      // In aggregate mode, component names are prefixed with instance_id (e.g., "sandbox:service_state")
      // We need to find any component that ends with the base name
      const findComponentStatus = (tier, baseName) => {
        if (!tier || typeof tier !== 'object') return false;

        const keys = Object.keys(tier);

        // Direct match (single-instance mode)
        if (tier[baseName]?.status === 'healthy') return true;

        // Prefixed match (aggregate mode) - all instances must be healthy
        const prefixedKeys = keys.filter(k => k.endsWith(`:${baseName}`));
        if (prefixedKeys.length > 0) {
          const allHealthy = prefixedKeys.every(k => tier[k]?.status === 'healthy');
          return allHealthy;
        }

        return false;
      };

      const serviceRunning = findComponentStatus(health.critical, 'service_state');
      const haConnected = findComponentStatus(health.critical, 'ha_rest_connection');
      const websocketConnected = findComponentStatus(health.essential, 'websocket_connected');
      const databaseAccessible = findComponentStatus(health.critical, 'database_accessible');

      document.getElementById('healthService').innerHTML = Components.booleanIndicator(serviceRunning);
      document.getElementById('healthHA').innerHTML = Components.booleanIndicator(haConnected);
      document.getElementById('healthWS').innerHTML = Components.booleanIndicator(websocketConnected);
      document.getElementById('healthDB').innerHTML = Components.booleanIndicator(databaseAccessible);

      // Initialize or update status chart
      if (!this.charts.charts.statusChart) {
        // Initialize with current data point
        this.statusHistory.timestamps.push(new Date().toLocaleTimeString());
        this.statusHistory.attempted.push(status.healings_attempted);
        this.statusHistory.succeeded.push(status.healings_succeeded);
        this.statusHistory.failed.push(status.healings_failed);

        this.charts.createStatusChart('statusChart', this.statusHistory);
      }

    } catch (error) {
      console.error('Error loading overview:', error);
      this.showToast(`Failed to load overview: ${error.message}`, 'error');
    }
  }

  // ==================== Monitoring Tab ====================

  /**
   * Load monitoring tab content
   */
  async loadMonitoringTab() {
    const tableDiv = document.getElementById('entitiesTable');
    tableDiv.innerHTML = Components.spinner();

    try {
      const entities = await this.api.getEntities(100, 0);

      if (entities.length === 0) {
        tableDiv.innerHTML = '<p class="text-gray-500 text-center py-8">No entities found</p>';
        return;
      }

      const headers = [
        { text: 'Entity ID', key: 'entity_id' },
        { text: 'State', key: 'state' },
        { text: 'Last Updated', key: 'last_updated' }
      ];

      const rows = entities.map(e => ({
        entity_id: e.entity_id,
        state: e.state || '--',
        last_updated: Components.formatTime(e.last_updated, true)
      }));

      tableDiv.innerHTML = Components.table(headers, rows, { hoverable: true });

    } catch (error) {
      console.error('Error loading entities:', error);
      tableDiv.innerHTML = Components.errorAlert(`Failed to load entities: ${error.message}`);
    }
  }

  // ==================== Analysis Tab ====================

  /**
   * Load analysis tab content
   */
  async loadAnalysisTab() {
    await Promise.all([
      this.loadReliability(),
      this.loadFailures()
    ]);
  }

  /**
   * Load integration reliability
   */
  async loadReliability() {
    const tableDiv = document.getElementById('reliabilityTable');
    tableDiv.innerHTML = Components.spinner();

    try {
      const data = await this.api.getReliability();

      if (data.length === 0) {
        tableDiv.innerHTML = '<p class="text-gray-500 text-center py-8">No reliability data available</p>';
        return;
      }

      const headers = [
        { text: 'Integration', key: 'integration' },
        { text: 'Reliability', key: 'reliability' },
        { text: 'Failures', key: 'failure_count' },
        { text: 'Last Failure', key: 'last_failure' }
      ];

      const rows = data.map(item => ({
        integration: item.integration || 'Unknown',
        reliability: `${item.reliability_percent.toFixed(1)}%`,
        failure_count: item.failure_count || 0,
        last_failure: item.last_failure ? Components.formatTime(item.last_failure, true) : 'Never'
      }));

      tableDiv.innerHTML = Components.table(headers, rows);

    } catch (error) {
      console.error('Error loading reliability:', error);
      tableDiv.innerHTML = Components.errorAlert(`Failed to load reliability: ${error.message}`);
    }
  }

  /**
   * Load failure events
   */
  async loadFailures() {
    try {
      const failures = await this.api.getFailures(50, 24);

      if (failures.length > 0) {
        // Create failure timeline chart
        this.charts.createFailureTimelineChart('failureChart', failures);

        // Create top failing chart
        const failureCounts = {};
        failures.forEach(f => {
          const integration = f.integration || 'Unknown';
          failureCounts[integration] = (failureCounts[integration] || 0) + 1;
        });

        const topFailing = Object.entries(failureCounts)
          .map(([name, count]) => ({ name, count }))
          .sort((a, b) => b.count - a.count);

        this.charts.createTopFailingChart('topFailingChart', topFailing);
      }

    } catch (error) {
      console.error('Error loading failures:', error);
    }
  }

  /**
   * Load weekly summary
   */
  async loadWeeklySummary() {
    const summaryDiv = document.getElementById('weeklySummary');
    const aiToggle = document.getElementById('aiInsightsToggle');

    summaryDiv.innerHTML = Components.spinner();

    try {
      const summary = await this.api.getSummary(7, aiToggle.checked);

      const html = `
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="text-center">
            <div class="text-2xl font-bold text-gray-900">${summary.total_failures}</div>
            <div class="text-sm text-gray-600">Total Failures</div>
          </div>
          <div class="text-center">
            <div class="text-2xl font-bold text-gray-900">${summary.total_healings}</div>
            <div class="text-sm text-gray-600">Total Healings</div>
          </div>
          <div class="text-center">
            <div class="text-2xl font-bold text-green-600">${summary.success_rate.toFixed(1)}%</div>
            <div class="text-sm text-gray-600">Success Rate</div>
          </div>
          <div class="text-center">
            <div class="text-2xl font-bold text-gray-900">${summary.top_failing_integrations.length}</div>
            <div class="text-sm text-gray-600">Problem Integrations</div>
          </div>
        </div>
        ${summary.top_failing_integrations.length > 0 ? `
          <div class="mt-4">
            <h3 class="text-sm font-medium text-gray-700 mb-2">Top Failing Integrations:</h3>
            <ul class="list-disc list-inside text-sm text-gray-600">
              ${summary.top_failing_integrations.map(i => `<li>${i}</li>`).join('')}
            </ul>
          </div>
        ` : ''}
        ${summary.ai_insights ? `
          <div class="mt-4 p-4 bg-blue-50 rounded">
            <h3 class="text-sm font-medium text-blue-900 mb-2">AI Insights:</h3>
            <p class="text-sm text-blue-800 whitespace-pre-wrap">${summary.ai_insights}</p>
          </div>
        ` : ''}
      `;

      summaryDiv.innerHTML = html;

    } catch (error) {
      console.error('Error loading summary:', error);
      summaryDiv.innerHTML = Components.errorAlert(`Failed to load summary: ${error.message}`);
    }
  }

  // ==================== Automations Tab ====================

  /**
   * Load automations tab
   */
  async loadAutomationsTab() {
    // Clear previous results
    document.getElementById('analyzeResult').classList.add('hidden');

    // Populate automation ID datalist
    await this.populateAutomationList();
  }

  /**
   * Populate automation ID datalist with available automations
   */
  async populateAutomationList() {
    const datalist = document.getElementById('automationIdList');
    if (!datalist) {
      console.warn('automationIdList element not found');
      return;
    }

    try {
      console.log('Fetching automations list...');
      const automations = await this.api.getAutomations(500);
      console.log(`Received ${automations.length} automations`);

      if (automations.length === 0) {
        console.warn('No automations found. Has auto-discovery run?');
        datalist.innerHTML = '<option value="">No automations found</option>';
      } else {
        datalist.innerHTML = automations
          .map(a => `<option value="${a.entity_id}">${a.friendly_name || a.entity_id}</option>`)
          .join('');
        console.log('Automation list populated successfully');
      }
    } catch (error) {
      console.error('Error loading automations for dropdown:', error);
      console.error('Error details:', error.message, error.stack);
      // Don't show error toast - just leave the dropdown empty
    }
  }

  /**
   * Analyze automation
   */
  async analyzeAutomation() {
    const input = document.getElementById('automationId');
    const resultDiv = document.getElementById('analyzeResult');
    const automationId = input.value.trim();

    if (!automationId) return;

    resultDiv.innerHTML = Components.spinner();
    resultDiv.classList.remove('hidden');

    try {
      const result = await this.api.analyzeAutomation(automationId);

      const html = `
        <div class="space-y-4 p-4 bg-gray-50 rounded">
          <h3 class="font-medium text-gray-900">${result.alias}</h3>
          <div class="text-sm text-gray-700 whitespace-pre-wrap">${result.analysis}</div>
          ${result.suggestions.length > 0 ? `
            <div>
              <h4 class="text-sm font-medium text-gray-900 mb-2">Suggestions:</h4>
              <ul class="list-disc list-inside text-sm text-gray-700">
                ${result.suggestions.map(s => `<li>${s}</li>`).join('')}
              </ul>
            </div>
          ` : ''}
        </div>
      `;

      resultDiv.innerHTML = html;
      this.showToast('Automation analyzed successfully', 'success');

    } catch (error) {
      console.error('Error analyzing automation:', error);
      resultDiv.innerHTML = Components.errorAlert(`Failed to analyze: ${error.message}`);
    }
  }

  // ==================== Healing Tab ====================

  /**
   * Navigate to Healing tab with an optional filter
   * @param {string} filter - Filter type: 'all', 'success', or 'failed'
   */
  async showHealingTab(filter = 'all') {
    // Store the filter
    this.healingFilter = filter;

    // Switch to the healing tab
    await this.switchTab('healing');

    // Update the filter dropdown to reflect current filter
    const filterSelect = document.getElementById('healingFilterSelect');
    if (filterSelect) {
      filterSelect.value = filter;
    }

    // Show a toast indicating the filter
    const filterLabels = {
      'all': 'Showing all healing actions',
      'success': 'Showing successful healings only',
      'failed': 'Showing failed healings only'
    };
    this.showToast(filterLabels[filter] || filterLabels['all'], 'info', 2000);
  }

  /**
   * Handle healing filter dropdown change
   * @param {string} filter - New filter value
   */
  async onHealingFilterChange(filter) {
    this.healingFilter = filter;
    await this.loadHealingHistory(filter);
  }

  /**
   * Load healing tab
   */
  async loadHealingTab() {
    // Update the filter dropdown to reflect current filter
    const filterSelect = document.getElementById('healingFilterSelect');
    if (filterSelect && this.healingFilter) {
      filterSelect.value = this.healingFilter;
    }

    await Promise.all([
      this.loadHealingHistory(),
      this.loadSuccessRate(),
      this.populateEntityList(),
      this.loadSuppressedEntities()
    ]);
  }

  /**
   * Populate entity ID datalist with available entities
   */
  async populateEntityList() {
    const datalist = document.getElementById('entityIdList');
    if (!datalist) return;

    try {
      const entities = await this.api.getEntities(1000);
      datalist.innerHTML = entities
        .map(e => `<option value="${e.entity_id}">${e.friendly_name || e.entity_id}</option>`)
        .join('');
    } catch (error) {
      console.error('Error loading entities for dropdown:', error);
      // Don't show error toast - just leave the dropdown empty
    }
  }

  /**
   * Trigger manual healing
   */
  async triggerHealing() {
    const input = document.getElementById('entityId');
    const resultDiv = document.getElementById('healingResult');
    const entityId = input.value.trim();

    if (!entityId) return;

    resultDiv.innerHTML = Components.spinner();
    resultDiv.classList.remove('hidden');

    try {
      const result = await this.api.triggerHealing(entityId);

      if (result.success) {
        resultDiv.innerHTML = Components.successAlert(`Healing triggered for ${result.entity_id}`);
        this.showToast('Healing successful', 'success');

        // Reload healing history
        await this.loadHealingHistory();
        await this.loadSuccessRate();
      } else {
        resultDiv.innerHTML = Components.errorAlert(`Healing failed: ${result.message}`);
      }

    } catch (error) {
      console.error('Error triggering healing:', error);
      resultDiv.innerHTML = Components.errorAlert(`Failed to trigger healing: ${error.message}`);
    }
  }

  /**
   * Load healing history
   * @param {string|null} filter - Optional filter override ('all', 'success', 'failed')
   */
  async loadHealingHistory(filter = null) {
    const historyDiv = document.getElementById('healingHistory');
    historyDiv.innerHTML = Components.spinner();

    // Use provided filter or current filter state
    const activeFilter = filter || this.healingFilter || 'all';

    try {
      const history = await this.api.getHealingHistory(50, 24, null, activeFilter);

      if (history.actions.length === 0) {
        historyDiv.innerHTML = '<p class="text-gray-500 text-center py-8">No healing history found</p>';
        return;
      }

      const headers = [
        { text: 'Entity', key: 'entity_id' },
        { text: 'Integration', key: 'integration' },
        { text: 'Reason', key: 'reason' },
        { text: 'Result', key: 'result' },
        { text: 'Error', key: 'error' },
        { text: 'Time', key: 'timestamp' }
      ];

      const reasonLabels = {
        'unavailable': '⚠️ Unavailable',
        'stale': '⏱️ Stale',
        'unknown': '❓ Unknown',
        'manual_heal': '👤 Manual',
        'recovered': '✅ Recovered'
      };

      const rows = history.actions.map(action => ({
        entity_id: action.entity_id,
        integration: action.integration || '--',
        reason: reasonLabels[action.trigger_reason] || action.trigger_reason || '--',
        result: action.success
          ? '<span class="text-green-600 font-medium">✓ Success</span>'
          : '<span class="text-red-600 font-medium">✗ Failed</span>',
        error: action.error_message
          ? `<span class="text-red-600 text-xs" title="${action.error_message}">${action.error_message.substring(0, 30)}${action.error_message.length > 30 ? '...' : ''}</span>`
          : '--',
        timestamp: Components.formatTime(action.timestamp, true)
      }));

      historyDiv.innerHTML = Components.table(headers, rows, { hoverable: true, rawHtml: ['result', 'error'] });

    } catch (error) {
      console.error('Error loading healing history:', error);
      historyDiv.innerHTML = Components.errorAlert(`Failed to load history: ${error.message}`);
    }
  }

  /**
   * Load success rate gauge
   */
  async loadSuccessRate() {
    try {
      const history = await this.api.getHealingHistory(100, 168); // Last week

      const successRate = history.success_count > 0
        ? (history.success_count / history.total_count) * 100
        : 0;

      this.charts.createSuccessRateGauge('successRateChart', successRate);

    } catch (error) {
      console.error('Error loading success rate:', error);
    }
  }

  /**
   * Load suppressed entities list
   */
  async loadSuppressedEntities() {
    const listDiv = document.getElementById('suppressedEntitiesList');
    if (!listDiv) return;

    try {
      const data = await this.api.getSuppressedEntities();

      if (data.entities.length === 0) {
        listDiv.innerHTML = '<p class="text-gray-500 text-center py-4">No entities have healing suppressed</p>';
        return;
      }

      const headers = [
        { text: 'Entity', key: 'entity_id' },
        { text: 'Name', key: 'friendly_name' },
        { text: 'Instance', key: 'instance_id' },
        { text: 'Since', key: 'suppressed_since' },
        { text: 'Action', key: 'action' }
      ];

      const rows = data.entities.map(entity => ({
        entity_id: entity.entity_id,
        friendly_name: entity.friendly_name || '--',
        instance_id: entity.instance_id,
        suppressed_since: entity.suppressed_since
          ? Components.formatTime(entity.suppressed_since, true)
          : '--',
        action: `<button onclick="window.dashboard.unsuppressEntity('${entity.entity_id}', '${entity.instance_id}')"
                  class="px-3 py-1 bg-green-600 text-white text-xs font-medium rounded hover:bg-green-700">
                  Enable Healing
                </button>`
      }));

      listDiv.innerHTML = Components.table(headers, rows, { hoverable: true, rawHtml: ['action'] });

    } catch (error) {
      console.error('Error loading suppressed entities:', error);
      listDiv.innerHTML = `<p class="text-red-500 text-center py-4">Failed to load: ${error.message}</p>`;
    }
  }

  /**
   * Suppress healing for an entity
   * @param {string} entityId - Entity ID to suppress
   */
  async suppressEntity(entityId) {
    if (!entityId) return;

    // Check if we're in aggregate mode without a specific instance
    if (this.currentInstance === 'all') {
      this.showToast('Please select a specific instance to suppress healing', 'error');
      return;
    }

    try {
      await this.api.suppressHealing(entityId, this.currentInstance);
      this.showToast(`Healing suppressed for ${entityId}`, 'success');
      await this.loadSuppressedEntities();

      // Clear the input
      document.getElementById('suppressEntityId').value = '';
    } catch (error) {
      console.error('Error suppressing healing:', error);
      this.showToast(`Failed to suppress: ${error.message}`, 'error');
    }
  }

  /**
   * Remove healing suppression for an entity
   * @param {string} entityId - Entity ID to unsuppress
   * @param {string} instanceId - Instance ID
   */
  async unsuppressEntity(entityId, instanceId) {
    try {
      await this.api.unsuppressHealing(entityId, instanceId);
      this.showToast(`Healing enabled for ${entityId}`, 'success');
      await this.loadSuppressedEntities();
    } catch (error) {
      console.error('Error enabling healing:', error);
      this.showToast(`Failed to enable healing: ${error.message}`, 'error');
    }
  }

  // ==================== Healing Plans Tab ====================

  /**
   * Load healing plans tab
   */
  async loadHealingPlansTab() {
    await this.loadHealingPlansList();
    this.loadCascadeHistory();  // Non-blocking, runs in background
  }

  /**
   * Load and render the healing plans list
   */
  async loadHealingPlansList() {
    const listDiv = document.getElementById('healingPlansList');
    listDiv.innerHTML = Components.spinner();

    try {
      // Read current filter
      const filterSelect = document.getElementById('planFilterSelect');
      const filter = filterSelect ? filterSelect.value : 'all';
      let enabled = null;
      if (filter === 'enabled') enabled = true;
      if (filter === 'disabled') enabled = false;

      const data = await this.api.getHealingPlans(enabled);
      const plans = data.plans;

      if (plans.length === 0) {
        listDiv.innerHTML = '<p class="text-gray-500 text-center py-8">No healing plans found</p>';
        return;
      }

      const headers = [
        { text: 'Name', key: 'name' },
        { text: 'Status', key: 'status' },
        { text: 'Priority', key: 'priority' },
        { text: 'Source', key: 'source' },
        { text: 'Tags', key: 'tags' },
        { text: 'Action', key: 'action' }
      ];

      const rows = plans.map(plan => ({
        name: `<a href="#" onclick="window.dashboard.showPlanDetail('${Components.escapeHtml(plan.name)}'); return false;"
                class="text-blue-600 hover:text-blue-800 font-medium">${Components.escapeHtml(plan.name)}</a>`,
        status: plan.enabled
          ? Components.statusBadge('healthy', 'Enabled')
          : Components.statusBadge('error', 'Disabled'),
        priority: String(plan.priority),
        source: plan.source || '--',
        tags: plan.tags && plan.tags.length > 0
          ? plan.tags.map(t => `<span class="bg-gray-100 text-gray-700 px-2 py-0.5 rounded text-xs">${Components.escapeHtml(t)}</span>`).join(' ')
          : '--',
        action: `<button onclick="window.dashboard.togglePlan('${Components.escapeHtml(plan.name)}', this)"
                  class="px-3 py-1 text-xs font-medium rounded ${plan.enabled
                    ? 'bg-orange-100 text-orange-700 hover:bg-orange-200'
                    : 'bg-green-100 text-green-700 hover:bg-green-200'}">
                  ${plan.enabled ? 'Disable' : 'Enable'}
                </button>`
      }));

      listDiv.innerHTML = Components.table(headers, rows, { hoverable: true, rawHtml: ['name', 'status', 'tags', 'action'] });

    } catch (error) {
      console.error('Error loading healing plans:', error);
      listDiv.innerHTML = Components.errorAlert(`Failed to load healing plans: ${error.message}`);
    }
  }

  /**
   * Handle plan filter dropdown change
   * @param {string} filter - New filter value
   */
  async onPlanFilterChange(filter) {
    await this.loadHealingPlansList();
  }

  /**
   * Render match criteria section for plan detail
   * @param {Object} plan - Plan object from API
   * @returns {string} HTML string
   */
  _renderPlanMatchCriteria(plan) {
    let html = '<h3 class="text-sm font-semibold text-gray-700 mb-2">Match Criteria</h3>';
    html += '<dl class="grid grid-cols-1 sm:grid-cols-3 gap-2 text-sm mb-4">';
    html += `<div><dt class="text-gray-500">Entity Patterns</dt><dd class="font-medium">${
      plan.match_criteria.entity_patterns.length > 0
        ? plan.match_criteria.entity_patterns.map(p => Components.escapeHtml(p)).join(', ')
        : '<span class="text-gray-400">any</span>'
    }</dd></div>`;
    html += `<div><dt class="text-gray-500">Integration Domains</dt><dd class="font-medium">${
      plan.match_criteria.integration_domains.length > 0
        ? plan.match_criteria.integration_domains.map(d => Components.escapeHtml(d)).join(', ')
        : '<span class="text-gray-400">any</span>'
    }</dd></div>`;
    html += `<div><dt class="text-gray-500">Failure Types</dt><dd class="font-medium">${
      plan.match_criteria.failure_types.length > 0
        ? plan.match_criteria.failure_types.map(f => Components.escapeHtml(f)).join(', ')
        : '<span class="text-gray-400">any</span>'
    }</dd></div>`;
    html += '</dl>';
    return html;
  }

  /**
   * Render steps table for plan detail
   * @param {Object} plan - Plan object from API
   * @returns {string} HTML string
   */
  _renderPlanSteps(plan) {
    let html = '<h3 class="text-sm font-semibold text-gray-700 mb-2">Steps</h3>';
    if (plan.steps && plan.steps.length > 0) {
      const stepHeaders = [
        { text: '#', key: 'num' },
        { text: 'Name', key: 'name' },
        { text: 'Level', key: 'level' },
        { text: 'Action', key: 'action' },
        { text: 'Timeout', key: 'timeout' }
      ];
      const stepRows = plan.steps.map((s, i) => ({
        num: String(i + 1),
        name: s.name,
        level: s.level,
        action: s.action,
        timeout: `${s.timeout_seconds}s`
      }));
      html += Components.table(stepHeaders, stepRows, { hoverable: false, striped: true });
    } else {
      html += '<p class="text-gray-500 text-sm">No steps defined</p>';
    }
    return html;
  }

  /**
   * Render toggle button for plan detail
   * @param {Object} plan - Plan object from API
   * @returns {string} HTML string
   */
  _renderPlanToggleButton(plan) {
    return `
      <div class="mt-4">
        <button onclick="window.dashboard.togglePlan('${Components.escapeHtml(plan.name)}', this)"
                class="px-4 py-2 text-sm font-medium rounded ${plan.enabled
                  ? 'bg-orange-600 text-white hover:bg-orange-700'
                  : 'bg-green-600 text-white hover:bg-green-700'}">
          ${plan.enabled ? 'Disable Plan' : 'Enable Plan'}
        </button>
      </div>
    `;
  }

  /**
   * Show plan detail card
   * @param {string} planName - Plan name
   */
  async showPlanDetail(planName) {
    const card = document.getElementById('planDetailCard');
    const title = document.getElementById('planDetailTitle');
    const content = document.getElementById('planDetailContent');

    title.textContent = planName;
    content.innerHTML = Components.spinner();
    card.classList.remove('hidden');

    try {
      const plan = await this.api.getHealingPlan(planName);

      // Build match criteria section
      const matchHtml = this._renderPlanMatchCriteria(plan);

      // Build info section
      let infoHtml = '<div class="flex items-center space-x-4 text-sm mb-4">';
      infoHtml += `<span>Status: ${plan.enabled ? Components.statusBadge('healthy', 'Enabled') : Components.statusBadge('error', 'Disabled')}</span>`;
      infoHtml += `<span>Priority: <strong>${plan.priority}</strong></span>`;
      infoHtml += `<span>Version: ${plan.version}</span>`;
      if (plan.tags && plan.tags.length > 0) {
        infoHtml += `<span>Tags: ${plan.tags.map(t => `<span class="bg-gray-100 text-gray-700 px-2 py-0.5 rounded text-xs">${Components.escapeHtml(t)}</span>`).join(' ')}</span>`;
      }
      infoHtml += '</div>';
      if (plan.description) {
        infoHtml += `<p class="text-sm text-gray-600 mb-4">${Components.escapeHtml(plan.description)}</p>`;
      }

      // Build steps table
      const stepsHtml = this._renderPlanSteps(plan);

      // Toggle button
      const toggleHtml = this._renderPlanToggleButton(plan);

      // Execution history placeholder
      const execHtml = `
        <div class="mt-6">
          <h3 class="text-sm font-semibold text-gray-700 mb-2">Execution History</h3>
          <div id="planExecutionHistory">${Components.spinner('sm')}</div>
        </div>
      `;

      content.innerHTML = infoHtml + matchHtml + stepsHtml + toggleHtml + execHtml;

      // Load executions asynchronously
      this.loadPlanExecutions(planName);

    } catch (error) {
      console.error('Error loading plan detail:', error);
      content.innerHTML = `
        <div class="text-center py-8">
          <p class="text-red-600 mb-3">Failed to load plan details: ${Components.escapeHtml(error.message)}</p>
          <button onclick="window.dashboard.showPlanDetail('${Components.escapeHtml(planName)}')"
                  class="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700">
            Retry
          </button>
        </div>
      `;
    }
  }

  /**
   * Close plan detail card
   */
  closePlanDetail() {
    document.getElementById('planDetailCard').classList.add('hidden');
  }

  /**
   * Toggle a plan enabled/disabled
   * @param {string} planName - Plan name
   * @param {HTMLElement|null} btn - Button element to disable during request
   */
  async togglePlan(planName, btn = null) {
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Working…';
    }
    try {
      const result = await this.api.toggleHealingPlan(planName);
      this.showToast(result.message, 'success');
      await this.loadHealingPlansList();

      // Refresh detail card if it's showing this plan
      const title = document.getElementById('planDetailTitle');
      if (title && title.textContent === planName) {
        await this.showPlanDetail(planName);
      }
    } catch (error) {
      console.error('Error toggling plan:', error);
      if (btn) {
        btn.disabled = false;
        btn.textContent = btn.textContent.includes('Working') ? 'Toggle' : btn.textContent;
      }
      this.showToast(`Failed to toggle plan: ${error.message}`, 'error');
    }
  }

  /**
   * Load execution history for a plan (inside detail card)
   * @param {string} planName - Plan name
   */
  async loadPlanExecutions(planName) {
    const container = document.getElementById('planExecutionHistory');
    if (!container) return;

    try {
      const executions = await this.api.getHealingPlanExecutions(planName, Dashboard.PLAN_EXECUTIONS_LIMIT);

      if (executions.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">No executions recorded</p>';
        return;
      }

      const headers = [
        { text: 'Time', key: 'time' },
        { text: 'Success', key: 'success' },
        { text: 'Steps', key: 'steps' },
        { text: 'Duration', key: 'duration' },
        { text: 'Error', key: 'error' }
      ];

      const rows = executions.map(e => ({
        time: Components.formatTime(e.created_at, true),
        success: e.success
          ? '<span class="text-green-600 font-medium">Yes</span>'
          : '<span class="text-red-600 font-medium">No</span>',
        steps: `${e.steps_succeeded}/${e.steps_attempted}`,
        duration: `${e.total_duration_seconds.toFixed(1)}s`,
        error: e.error_message
          ? `<span class="text-red-600 text-xs" title="${Components.escapeHtml(e.error_message)}">${Components.escapeHtml(Components.truncate(e.error_message, 40))}</span>`
          : '--'
      }));

      container.innerHTML = Components.table(headers, rows, { hoverable: true, rawHtml: ['success', 'error'] });

    } catch (error) {
      console.error('Error loading plan executions:', error);
      container.innerHTML = Components.errorAlert(`Failed to load execution history: ${error.message}`);
    }
  }

  /**
   * Test which plan matches given entities
   */
  async testPlanMatch() {
    const entitiesInput = document.getElementById('matchTestEntities');
    const failureSelect = document.getElementById('matchTestFailureType');
    const resultDiv = document.getElementById('matchTestResult');

    const entityStr = entitiesInput.value.trim();
    if (!entityStr) {
      this.showToast('Enter at least one entity ID', 'error');
      return;
    }

    const entityIds = entityStr.split(',').map(e => e.trim()).filter(e => e);
    const invalidIds = entityIds.filter(id => !/^[a-z_]+\.[a-z0-9_]+$/i.test(id));
    if (invalidIds.length > 0) {
      this.showToast(`Invalid entity ID format: ${invalidIds.join(', ')} (expected domain.entity_name)`, 'error');
      return;
    }
    const failureType = failureSelect.value;

    resultDiv.innerHTML = Components.spinner('sm');
    resultDiv.classList.remove('hidden');

    try {
      const result = await this.api.testPlanMatch(entityIds, failureType, this.currentInstance === 'all' ? 'default' : this.currentInstance);

      if (result.matched) {
        resultDiv.innerHTML = Components.successAlert(
          `Matched plan: <strong>${Components.escapeHtml(result.plan_name)}</strong> (priority: ${result.plan_priority})`
        );
      } else {
        resultDiv.innerHTML = `
          <div class="bg-yellow-100 border border-yellow-400 text-yellow-700 px-4 py-3 rounded">
            No matching plan found for the given entities and failure type.
          </div>
        `;
      }
    } catch (error) {
      console.error('Error testing plan match:', error);
      resultDiv.innerHTML = Components.errorAlert(`Match test failed: ${error.message}`);
    }
  }

  /**
   * Validate YAML plan content
   */
  async validatePlanYaml() {
    const textarea = document.getElementById('yamlValidatorInput');
    const resultDiv = document.getElementById('yamlValidatorResult');

    const yamlContent = textarea.value.trim();
    if (!yamlContent) {
      this.showToast('Paste YAML content to validate', 'error');
      return;
    }

    resultDiv.innerHTML = Components.spinner('sm');
    resultDiv.classList.remove('hidden');

    try {
      const result = await this.api.validateHealingPlan(yamlContent);

      if (result.valid) {
        let html = Components.successAlert('Valid healing plan!');
        if (result.plan) {
          html += `
            <div class="mt-2 p-3 bg-gray-50 rounded text-sm">
              <div><strong>Name:</strong> ${Components.escapeHtml(result.plan.name)}</div>
              <div><strong>Steps:</strong> ${result.plan.steps ? result.plan.steps.length : 0}</div>
              <div><strong>Priority:</strong> ${result.plan.priority}</div>
            </div>
          `;
        }
        resultDiv.innerHTML = html;
      } else {
        let html = Components.errorAlert('Validation failed');
        if (result.errors && result.errors.length > 0) {
          html += `
            <ul class="mt-2 text-sm text-red-600 list-disc list-inside">
              ${result.errors.map(e => `<li>${Components.escapeHtml(e)}</li>`).join('')}
            </ul>
          `;
        }
        resultDiv.innerHTML = html;
      }
    } catch (error) {
      console.error('Error validating YAML:', error);
      resultDiv.innerHTML = Components.errorAlert(`Validation failed: ${error.message}`);
    }
  }

  // ==================== AI Plan Generator ====================

  /**
   * Generate a healing plan using AI
   */
  async generatePlan() {
    const entitiesInput = document.getElementById('planGenEntities');
    const failureSelect = document.getElementById('planGenFailureType');
    const domainInput = document.getElementById('planGenDomain');
    const resultDiv = document.getElementById('planGenResult');
    const yamlTextarea = document.getElementById('planGenYaml');
    const button = document.getElementById('planGenButton');
    const statusDiv = document.getElementById('planGenStatus');

    const entityStr = entitiesInput.value.trim();
    if (!entityStr) {
      this.showToast('Enter at least one entity ID', 'error');
      return;
    }

    const entityIds = entityStr.split(',').map(e => e.trim()).filter(e => e);
    const failureType = failureSelect.value;
    const domain = domainInput.value.trim() || null;

    button.disabled = true;
    button.textContent = 'Generating...';
    statusDiv.innerHTML = '';

    try {
      const instanceId = this.currentInstance === 'all' ? 'default' : this.currentInstance;
      const result = await this.api.generateHealingPlan(entityIds, failureType, domain, instanceId);

      if (result.generated && result.yaml_content) {
        yamlTextarea.value = result.yaml_content;
        resultDiv.classList.remove('hidden');
        statusDiv.innerHTML = Components.successAlert('Plan generated! Review the YAML, then save or share.');
      } else {
        statusDiv.innerHTML = Components.errorAlert(result.error || 'Plan generation failed');
        resultDiv.classList.add('hidden');
      }
    } catch (error) {
      console.error('Error generating plan:', error);
      statusDiv.innerHTML = Components.errorAlert(`Generation failed: ${error.message}`);
      resultDiv.classList.add('hidden');
    } finally {
      button.disabled = false;
      button.textContent = 'Generate Plan \u25B6';
    }
  }

  /**
   * Save the generated YAML plan to the database
   */
  async saveGeneratedPlan() {
    const yamlTextarea = document.getElementById('planGenYaml');
    const statusDiv = document.getElementById('planGenStatus');

    const yamlContent = yamlTextarea.value.trim();
    if (!yamlContent) {
      this.showToast('No plan to save', 'error');
      return;
    }

    statusDiv.innerHTML = Components.spinner('sm');

    try {
      const result = await this.api.saveHealingPlan(yamlContent);
      statusDiv.innerHTML = Components.successAlert(`Plan "${Components.escapeHtml(result.name)}" saved successfully!`);
      // Refresh the plan list
      await this.loadHealingPlansList();
      this.showToast('Plan saved!', 'success');
    } catch (error) {
      console.error('Error saving plan:', error);
      statusDiv.innerHTML = Components.errorAlert(`Save failed: ${error.message}`);
    }
  }

  /**
   * Anonymize the current plan YAML and open GitHub sharing URL
   */
  async anonymizeAndShare() {
    const yamlTextarea = document.getElementById('planGenYaml');
    const statusDiv = document.getElementById('planGenStatus');

    const yamlContent = yamlTextarea.value.trim();
    if (!yamlContent) {
      this.showToast('No plan to share', 'error');
      return;
    }

    statusDiv.innerHTML = Components.spinner('sm');

    try {
      // Step 1: Anonymize
      const anonResult = await this.api.anonymizePlan(yamlContent);

      // Update the textarea with anonymized version
      yamlTextarea.value = anonResult.yaml_content;

      // Step 2: Get community URL
      const urlResult = await this.api.getCommunityUrl(anonResult.yaml_content);

      // Open in new tab
      window.open(urlResult.url, '_blank', 'noopener,noreferrer');
      statusDiv.innerHTML = Components.successAlert(
        `Anonymized! GitHub issue opened in new tab. Repo: ${Components.escapeHtml(urlResult.repo)}`
      );
    } catch (error) {
      console.error('Error sharing plan:', error);
      statusDiv.innerHTML = Components.errorAlert(`Share failed: ${error.message}`);
    }
  }

  /**
   * Load cascade history into the cascade history section of the Healing Plans tab
   */
  async loadCascadeHistory() {
    const container = document.getElementById('cascadeHistoryContainer');
    if (!container) return;

    try {
      const cascades = await this.api.getCascades(
        this.currentInstance === 'all' ? null : this.currentInstance,
        20,
        true  // plan_suggested_only = true (cascades without matching plan)
      );

      if (!cascades || cascades.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-center py-4 text-sm">No cascades found without a matching plan.</p>';
        return;
      }

      const headers = ['Time', 'Automation', 'Outcome', ''];
      const rows = cascades.map(c => {
        // Store entity IDs in a data attribute to avoid XSS via inline event handlers
        const entitiesJson = Components.escapeHtml(JSON.stringify(c.entity_ids || []));
        return {
          'Time': Components.escapeHtml(new Date(c.created_at).toLocaleString()),
          'Automation': Components.escapeHtml(Components.truncate(c.automation_id || 'unknown', 30)),
          'Outcome': c.final_success === true
            ? '<span class="text-green-600 text-xs font-medium">Healed</span>'
            : c.final_success === false
              ? '<span class="text-red-600 text-xs font-medium">Failed</span>'
              : '<span class="text-gray-500 text-xs">In progress</span>',
          '': `<button data-entities="${entitiesJson}"
                      onclick="window.dashboard.prefillFromCascadeBtn(this)"
                      class="px-2 py-1 bg-purple-100 text-purple-700 text-xs rounded hover:bg-purple-200">
                 Generate \u2728
               </button>`,
        };
      });

      container.innerHTML = Components.table(headers, rows, { hoverable: true, rawHtml: ['Outcome', ''] });

    } catch (error) {
      console.error('Error loading cascade history:', error);
      container.innerHTML = Components.errorAlert(`Failed to load cascades: ${error.message}`);
    }
  }

  /**
   * Pre-fill the AI Plan Generator form from a cascade's entity IDs
   * @param {Array<string>} entityIds - Entity IDs to pre-fill
   */
  /**
   * Thin wrapper called from the Generate button's data-entities attribute.
   * Reads entity IDs from the button's data attribute (XSS-safe).
   * @param {HTMLElement} btn - The clicked button element
   */
  prefillFromCascadeBtn(btn) {
    try {
      const entityIds = JSON.parse(btn.dataset.entities || '[]');
      this.prefillFromCascade(entityIds);
    } catch (e) {
      console.error('Failed to parse entity IDs from button', e);
    }
  }

  prefillFromCascade(entityIds) {
    const entitiesInput = document.getElementById('planGenEntities');
    if (entitiesInput && entityIds && entityIds.length > 0) {
      entitiesInput.value = entityIds.join(', ');
      // Scroll to generator section
      entitiesInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
      entitiesInput.focus();
      this.showToast('Entity IDs pre-filled \u2014 click Generate Plan to create a plan', 'info');
    }
  }

  // ==================== Settings Tab ====================

  /**
   * Load settings tab
   */
  async loadSettingsTab() {
    // Store pending changes
    this.pendingSettings = {};
    this.restartRequired = false;

    // Populate API key input with current value
    const apiKeyInput = document.getElementById('apiKeyInput');
    if (apiKeyInput) {
      apiKeyInput.value = this.api.apiKey || '';
    }

    await Promise.all([
      this.loadConfigSettings(),
      this.loadConfigInstances()
    ]);
  }

  /**
   * Load configuration settings
   */
  async loadConfigSettings() {
    try {
      const [config, schema] = await Promise.all([
        this.api.getConfig(),
        this.api.getConfigSchema()
      ]);

      // Group settings by section
      const sections = {};
      for (const [key, metadata] of Object.entries(schema.settings)) {
        const section = metadata.section;
        if (!sections[section]) {
          sections[section] = [];
        }
        const configValue = config.settings[key];
        sections[section].push({
          ...metadata,
          value: configValue?.value,
          source: configValue?.source,
          editable: configValue?.editable ?? true
        });
      }

      // Render each section
      this.renderSettingsSection('monitoringSettings', sections.monitoring || []);
      this.renderSettingsSection('healingSettings', sections.healing || []);
      this.renderSettingsSection('notificationSettings', sections.notifications || []);
      this.renderSettingsSection('intelligenceSettings', sections.intelligence || []);
      this.renderSettingsSection('loggingSettings', sections.logging || []);
      this.renderSettingsSection('databaseSettings', sections.database || []);

    } catch (error) {
      console.error('Error loading config settings:', error);
      this.showToast(`Failed to load settings: ${error.message}`, 'error');
    }
  }

  /**
   * Render a settings section
   * @param {string} containerId - Container element ID
   * @param {Array} settings - Settings for this section
   */
  renderSettingsSection(containerId, settings) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (settings.length === 0) {
      container.innerHTML = '<p class="text-gray-500 text-sm">No settings available</p>';
      return;
    }

    const html = settings.map(setting => {
      const isDisabled = !setting.editable;
      const sourceLabel = setting.source === 'environment'
        ? '<span class="text-xs text-yellow-600 ml-2">(env override)</span>'
        : setting.source === 'database'
          ? '<span class="text-xs text-blue-600 ml-2">(customized)</span>'
          : '';

      let inputHtml = '';

      if (setting.value_type === 'bool') {
        inputHtml = `
          <label class="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" class="sr-only peer config-input"
                   data-key="${setting.key}"
                   data-type="bool"
                   ${setting.value ? 'checked' : ''}
                   ${isDisabled ? 'disabled' : ''}>
            <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600 ${isDisabled ? 'opacity-50 cursor-not-allowed' : ''}"></div>
          </label>
        `;
      } else if (setting.options && setting.options.length > 0) {
        inputHtml = `
          <select class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm config-input"
                  data-key="${setting.key}"
                  data-type="string"
                  ${isDisabled ? 'disabled' : ''}>
            ${setting.options.map(opt => `<option value="${opt}" ${setting.value === opt ? 'selected' : ''}>${opt}</option>`).join('')}
          </select>
        `;
      } else if (setting.value_type === 'int' || setting.value_type === 'float') {
        const min = setting.min_value !== null ? `min="${setting.min_value}"` : '';
        const max = setting.max_value !== null ? `max="${setting.max_value}"` : '';
        const step = setting.value_type === 'float' ? 'step="0.1"' : 'step="1"';
        inputHtml = `
          <input type="number" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm config-input"
                 data-key="${setting.key}"
                 data-type="${setting.value_type}"
                 value="${setting.value ?? ''}"
                 ${min} ${max} ${step}
                 ${isDisabled ? 'disabled' : ''}>
        `;
      } else if (setting.value_type === 'list') {
        const value = Array.isArray(setting.value) ? setting.value.join('\n') : '';
        inputHtml = `
          <textarea class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm config-input"
                    data-key="${setting.key}"
                    data-type="list"
                    rows="3"
                    placeholder="One item per line"
                    ${isDisabled ? 'disabled' : ''}>${value}</textarea>
        `;
      } else {
        inputHtml = `
          <input type="text" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm config-input"
                 data-key="${setting.key}"
                 data-type="string"
                 value="${setting.value ?? ''}"
                 ${isDisabled ? 'disabled' : ''}>
        `;
      }

      return `
        <div class="flex justify-between items-start py-2 border-b border-gray-100 last:border-0">
          <div class="flex-1 pr-4">
            <label class="text-sm font-medium text-gray-700">${setting.label}${sourceLabel}</label>
            <p class="text-xs text-gray-500">${setting.description}</p>
          </div>
          <div class="w-48 flex-shrink-0">
            ${inputHtml}
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = html;

    // Add change listeners
    container.querySelectorAll('.config-input').forEach(input => {
      input.addEventListener('change', (e) => this.onSettingChange(e.target));
    });
  }

  /**
   * Handle setting change
   * @param {HTMLElement} input - Input element that changed
   */
  onSettingChange(input) {
    const key = input.dataset.key;
    const type = input.dataset.type;
    let value;

    if (type === 'bool') {
      value = input.checked;
    } else if (type === 'int') {
      value = parseInt(input.value, 10);
    } else if (type === 'float') {
      value = parseFloat(input.value);
    } else if (type === 'list') {
      value = input.value.split('\n').map(v => v.trim()).filter(v => v);
    } else {
      value = input.value;
    }

    this.pendingSettings[key] = value;
    console.log('Setting changed:', key, '=', value);
  }

  /**
   * Save all pending settings
   */
  async saveSettings() {
    if (Object.keys(this.pendingSettings).length === 0) {
      this.showToast('No changes to save', 'info');
      return;
    }

    try {
      // Validate first
      const validation = await this.api.validateConfig(this.pendingSettings);
      if (!validation.valid) {
        this.showToast(`Validation failed: ${validation.errors.join(', ')}`, 'error');
        return;
      }

      // Save settings
      const result = await this.api.updateConfig(this.pendingSettings);

      if (result.errors.length > 0) {
        this.showToast(`Some settings failed: ${result.errors.join(', ')}`, 'warning');
      } else {
        this.showToast(`Saved ${result.updated.length} setting(s)`, 'success');
      }

      if (result.restart_required) {
        document.getElementById('restartRequiredAlert').classList.remove('hidden');
      }

      // Clear pending changes
      this.pendingSettings = {};

      // Reload settings to show new values
      await this.loadConfigSettings();

    } catch (error) {
      console.error('Error saving settings:', error);
      this.showToast(`Failed to save settings: ${error.message}`, 'error');
    }
  }

  /**
   * Reset settings to defaults (clear database overrides)
   */
  async resetSettings() {
    if (!confirm('Reset all settings to defaults? This will remove any customizations.')) {
      return;
    }

    try {
      // For now, just reload - full reset would require API endpoint
      this.pendingSettings = {};
      await this.loadConfigSettings();
      this.showToast('Settings reloaded', 'info');
    } catch (error) {
      console.error('Error resetting settings:', error);
      this.showToast(`Failed to reset: ${error.message}`, 'error');
    }
  }

  /**
   * Load HA instances configuration
   */
  async loadConfigInstances() {
    const container = document.getElementById('instancesList');
    if (!container) return;

    container.innerHTML = '<p class="text-gray-500">Loading instances...</p>';

    try {
      const instances = await this.api.getConfigInstances();

      if (instances.length === 0) {
        container.innerHTML = '<p class="text-gray-500">No instances configured in database. Instances are loaded from config.yaml.</p>';
        return;
      }

      const html = instances.map(instance => `
        <div class="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
          <div class="flex-1">
            <div class="flex items-center space-x-2">
              <span class="font-medium text-gray-900">${instance.instance_id}</span>
              ${instance.is_active
                ? '<span class="px-2 py-0.5 text-xs bg-green-100 text-green-800 rounded">Active</span>'
                : '<span class="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded">Inactive</span>'}
              <span class="text-xs text-gray-500">(${instance.source})</span>
            </div>
            <div class="text-sm text-gray-600 mt-1">${instance.url}</div>
            <div class="text-xs text-gray-400 mt-1">Token: ${instance.masked_token}</div>
          </div>
          <div class="flex items-center space-x-2">
            <button class="px-3 py-1 text-sm text-blue-600 hover:bg-blue-50 rounded"
                    onclick="window.dashboard.testConfigInstance('${instance.instance_id}')">
              Test
            </button>
            <button class="px-3 py-1 text-sm text-green-600 hover:bg-green-50 rounded"
                    onclick="window.dashboard.triggerInstanceDiscovery('${instance.instance_id}')"
                    title="Discover automations, scenes, and scripts">
              Discover
            </button>
            <button class="px-3 py-1 text-sm text-gray-600 hover:bg-gray-100 rounded"
                    onclick="window.dashboard.editInstance('${instance.instance_id}')">
              Edit
            </button>
            <button class="px-3 py-1 text-sm text-red-600 hover:bg-red-50 rounded"
                    onclick="window.dashboard.deleteInstance('${instance.instance_id}')">
              Delete
            </button>
          </div>
        </div>
      `).join('');

      container.innerHTML = html;

    } catch (error) {
      console.error('Error loading config instances:', error);
      container.innerHTML = `<p class="text-red-500">Failed to load instances: ${error.message}</p>`;
    }
  }

  /**
   * Show instance modal for adding/editing
   * @param {string|null} instanceId - Instance ID to edit, or null for new
   */
  showInstanceModal(instanceId = null) {
    const modal = document.getElementById('instanceModal');
    const title = document.getElementById('instanceModalTitle');
    const form = document.getElementById('instanceForm');
    const modeInput = document.getElementById('instanceFormMode');
    const originalIdInput = document.getElementById('instanceFormOriginalId');

    // Reset form
    form.reset();
    document.getElementById('instanceTestResult').textContent = '';

    if (instanceId) {
      title.textContent = 'Edit HA Instance';
      modeInput.value = 'edit';
      originalIdInput.value = instanceId;

      // Load existing instance data
      this.api.getConfigInstances().then(instances => {
        const instance = instances.find(i => i.instance_id === instanceId);
        if (instance) {
          document.getElementById('instanceIdInput').value = instance.instance_id;
          document.getElementById('instanceUrlInput').value = instance.url;
          document.getElementById('instanceBridgeEnabled').checked = instance.bridge_enabled;
          // Token field left empty (user must enter new token to change)
        }
      });
    } else {
      title.textContent = 'Add HA Instance';
      modeInput.value = 'add';
      originalIdInput.value = '';
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
  }

  /**
   * Hide instance modal
   */
  hideInstanceModal() {
    const modal = document.getElementById('instanceModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }

  /**
   * Edit an existing instance
   * @param {string} instanceId - Instance to edit
   */
  editInstance(instanceId) {
    this.showInstanceModal(instanceId);
  }

  /**
   * Test instance connection from modal
   */
  async testInstance() {
    const url = document.getElementById('instanceUrlInput').value.trim();
    const token = document.getElementById('instanceTokenInput').value.trim();
    const resultSpan = document.getElementById('instanceTestResult');

    if (!url) {
      resultSpan.innerHTML = '<span class="text-red-600">URL is required</span>';
      return;
    }

    resultSpan.innerHTML = '<span class="text-gray-600">Testing...</span>';

    try {
      let result;
      if (token) {
        // Test with new credentials
        result = await this.api.testNewConfigInstance(url, token);
      } else {
        // Test existing instance
        const instanceId = document.getElementById('instanceFormOriginalId').value;
        if (!instanceId) {
          resultSpan.innerHTML = '<span class="text-red-600">Token is required for new instance</span>';
          return;
        }
        result = await this.api.testConfigInstance(instanceId);
      }

      if (result.success) {
        resultSpan.innerHTML = `<span class="text-green-600">Connected! HA ${result.version || ''}</span>`;
      } else {
        resultSpan.innerHTML = `<span class="text-red-600">${result.message}</span>`;
      }
    } catch (error) {
      resultSpan.innerHTML = `<span class="text-red-600">${error.message}</span>`;
    }
  }

  /**
   * Test a configured instance
   * @param {string} instanceId - Instance to test
   */
  async testConfigInstance(instanceId) {
    this.showToast(`Testing ${instanceId}...`, 'info', 1500);

    try {
      const result = await this.api.testConfigInstance(instanceId);
      if (result.success) {
        this.showToast(`${instanceId}: Connected (HA ${result.version || 'unknown'})`, 'success');
      } else {
        this.showToast(`${instanceId}: ${result.message}`, 'error');
      }
    } catch (error) {
      this.showToast(`${instanceId}: ${error.message}`, 'error');
    }
  }

  /**
   * Trigger discovery for an instance
   * @param {string} instanceId - Instance to discover
   */
  async triggerInstanceDiscovery(instanceId) {
    this.showToast(`Starting discovery for ${instanceId}...`, 'info', 2000);

    try {
      const result = await this.api.triggerDiscovery(instanceId);

      if (result.success) {
        const summary = `Found ${result.automations_found} automations, ${result.scenes_found} scenes, ${result.scripts_found} scripts (${result.entities_discovered} entities)`;
        this.showToast(`Discovery complete: ${summary}`, 'success', 5000);

        // Refresh automation list if on automations tab
        if (this.currentTab === 'automations') {
          await this.populateAutomationList();
        }
      } else {
        this.showToast(`Discovery failed for ${instanceId}`, 'error');
      }
    } catch (error) {
      console.error('Discovery error:', error);
      this.showToast(`Discovery failed: ${error.message}`, 'error');
    }
  }

  /**
   * Save instance (add or update)
   */
  async saveInstance() {
    const mode = document.getElementById('instanceFormMode').value;
    const originalId = document.getElementById('instanceFormOriginalId').value;
    const instanceId = document.getElementById('instanceIdInput').value.trim();
    const url = document.getElementById('instanceUrlInput').value.trim();
    const token = document.getElementById('instanceTokenInput').value.trim();
    const bridgeEnabled = document.getElementById('instanceBridgeEnabled').checked;

    if (!instanceId || !url) {
      this.showToast('Instance ID and URL are required', 'error');
      return;
    }

    try {
      if (mode === 'add') {
        if (!token) {
          this.showToast('Token is required for new instance', 'error');
          return;
        }
        await this.api.addConfigInstance({
          instance_id: instanceId,
          url: url,
          token: token,
          bridge_enabled: bridgeEnabled
        });
        this.showToast('Instance added. Restart service to connect.', 'success');
      } else {
        const updates = { url, bridge_enabled: bridgeEnabled };
        if (token) updates.token = token;
        await this.api.updateConfigInstance(originalId, updates);
        this.showToast('Instance updated. Restart service to apply.', 'success');
      }

      this.hideInstanceModal();
      await this.loadConfigInstances();

    } catch (error) {
      this.showToast(`Failed to save instance: ${error.message}`, 'error');
    }
  }

  /**
   * Delete an instance
   * @param {string} instanceId - Instance to delete
   */
  async deleteInstance(instanceId) {
    if (!confirm(`Delete instance "${instanceId}"? This cannot be undone.`)) {
      return;
    }

    try {
      await this.api.deleteConfigInstance(instanceId);
      this.showToast('Instance deleted. Restart service to disconnect.', 'success');
      await this.loadConfigInstances();
    } catch (error) {
      this.showToast(`Failed to delete instance: ${error.message}`, 'error');
    }
  }

  // ==================== Polling ====================

  /**
   * Start polling for real-time updates
   */
  startPolling() {
    // High priority: Status and health (10s)
    this.pollingIntervals.status = setInterval(() => this.refreshStatus(), 10000);

    // Start tab-specific polling
    this.startTabPolling();
  }

  /**
   * Stop all polling
   */
  stopPolling() {
    Object.values(this.pollingIntervals).forEach(interval => clearInterval(interval));
    this.pollingIntervals = {};
  }

  /**
   * Start tab-specific polling
   */
  startTabPolling() {
    if (this.currentTab === 'analysis') {
      // Medium priority: Failures (30s)
      this.pollingIntervals.failures = setInterval(() => this.loadFailures(), 30000);
    } else if (this.currentTab === 'healing') {
      // Medium priority: Healing history (30s)
      this.pollingIntervals.healing = setInterval(() => this.loadHealingHistory(), 30000);
    } else if (this.currentTab === 'monitoring') {
      // Low priority: Entities (60s)
      this.pollingIntervals.entities = setInterval(() => this.loadMonitoringTab(), Dashboard.ENTITIES_POLL_INTERVAL_MS);
    } else if (this.currentTab === 'healingPlans') {
      // Low priority: Plans (60s)
      this.pollingIntervals.plans = setInterval(() => this.loadHealingPlansList(), Dashboard.PLANS_POLL_INTERVAL_MS);
    }
  }

  /**
   * Stop tab-specific polling
   */
  stopTabPolling() {
    if (this.pollingIntervals.failures) clearInterval(this.pollingIntervals.failures);
    if (this.pollingIntervals.healing) clearInterval(this.pollingIntervals.healing);
    if (this.pollingIntervals.entities) clearInterval(this.pollingIntervals.entities);
    if (this.pollingIntervals.plans) clearInterval(this.pollingIntervals.plans);
  }

  /**
   * Refresh status data
   */
  async refreshStatus() {
    try {
      const [status, health] = await Promise.all([
        this.api.getStatus(),
        this.api.getHealth()
      ]);

      // Update status display if on overview tab
      if (this.currentTab === 'overview') {
        document.getElementById('serviceState').textContent = status.state;
        document.getElementById('serviceUptime').textContent = Components.formatDuration(status.uptime_seconds);

        // Extract and format discovery timestamp
        // Handle both single-instance and aggregate mode (prefixed keys)
        const findDiscoveryTimestamp = (essential) => {
          if (!essential) return null;
          // Direct match (single-instance mode)
          if (essential.entity_discovery_complete?.details?.last_refresh) {
            return essential.entity_discovery_complete.details.last_refresh;
          }
          // Prefixed match (aggregate mode) - find most recent
          const prefixedKeys = Object.keys(essential).filter(k => k.endsWith(':entity_discovery_complete'));
          let mostRecent = null;
          for (const key of prefixedKeys) {
            const timestamp = essential[key]?.details?.last_refresh;
            if (timestamp && (!mostRecent || timestamp > mostRecent)) {
              mostRecent = timestamp;
            }
          }
          return mostRecent;
        };

        const discoveryTimestamp = findDiscoveryTimestamp(health.essential);
        if (discoveryTimestamp) {
          // Format to minute granularity in local time: "Dec 28, 2025 7:57 PM"
          document.getElementById('lastDiscovery').textContent = dayjs(discoveryTimestamp).format('MMM DD, YYYY h:mm A');
        } else {
          document.getElementById('lastDiscovery').textContent = 'Never';
        }

        document.getElementById('healthChecks').textContent = status.health_checks_performed;
        document.getElementById('monitoredEntities').textContent = status.monitored_entities;
        document.getElementById('healingsAttempted').textContent = status.healings_attempted;
        document.getElementById('healingsSucceeded').textContent = status.healings_succeeded;
        document.getElementById('healingsFailed').textContent = status.healings_failed;

        // Update chart
        this.charts.updateStatusChart('statusChart', {
          timestamp: new Date().toLocaleTimeString(),
          attempted: status.healings_attempted,
          succeeded: status.healings_succeeded,
          failed: status.healings_failed
        });
      }

      // Update last refresh time
      document.getElementById('lastRefresh').textContent = `Last refresh: ${new Date().toLocaleTimeString()}`;

      // Update status indicator if needed
      if (status.state === 'running') {
        this.updateStatusIndicator('connected', 'Connected');
      }

    } catch (error) {
      console.error('Error refreshing status:', error);
      this.updateStatusIndicator('error', 'Connection error');
    }
  }

  // ==================== UI Helpers ====================

  /**
   * Show entity detail modal
   * @param {string} entityId - Entity ID to show
   */
  async showEntityModal(entityId) {
    const modal = document.getElementById('entityModal');
    const title = document.getElementById('entityModalTitle');
    const content = document.getElementById('entityModalContent');

    title.textContent = entityId;
    content.innerHTML = Components.spinner();

    modal.classList.remove('hidden');
    modal.classList.add('flex');

    try {
      const [entity, history] = await Promise.all([
        this.api.getEntity(entityId),
        this.api.getEntityHistory(entityId, 24)
      ]);

      content.innerHTML = `
        <div class="space-y-4">
          <div>
            <label class="text-sm font-medium text-gray-700">State:</label>
            <div class="text-lg font-semibold">${entity.state}</div>
          </div>
          <div>
            <label class="text-sm font-medium text-gray-700">Attributes:</label>
            <pre class="text-xs bg-gray-100 p-2 rounded overflow-x-auto">${JSON.stringify(entity.attributes, null, 2)}</pre>
          </div>
          <div>
            <label class="text-sm font-medium text-gray-700 mb-2 block">History (24h):</label>
            <div class="chart-container" style="position: relative; height: 250px;">
              <canvas id="entityHistoryChart"></canvas>
            </div>
          </div>
        </div>
      `;

      // Create history chart if data is numeric
      if (history.history && history.history.length > 0) {
        this.charts.createEntityHistoryChart('entityHistoryChart', history.history);
      }

    } catch (error) {
      content.innerHTML = Components.errorAlert(`Failed to load entity: ${error.message}`);
    }
  }

  /**
   * Hide entity detail modal
   */
  hideEntityModal() {
    const modal = document.getElementById('entityModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }

  /**
   * Show toast notification
   * @param {string} message - Toast message
   * @param {string} type - Toast type (success, error, info)
   * @param {number} duration - Auto-dismiss duration
   */
  showToast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toastContainer');
    const toast = Components.toast(message, type, duration);
    container.appendChild(toast);
  }
}

// Initialize dashboard when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new Dashboard();
    window.dashboard.init();
  });
} else {
  window.dashboard = new Dashboard();
  window.dashboard.init();
}
