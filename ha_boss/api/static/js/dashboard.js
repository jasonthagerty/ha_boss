/**
 * HA Boss Dashboard
 * Main application logic and orchestration
 */

import { APIClient } from './api-client.js';
import ChartManager from './charts.js';
import Components from './components.js';

class Dashboard {
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
      this.showToast('Failed to load instances - using default', 'error');

      // Fallback: Add default instance to keep dashboard functional
      const selector = document.getElementById('instanceSelector');
      selector.innerHTML = '';
      const defaultOption = document.createElement('option');
      defaultOption.value = 'default';
      defaultOption.textContent = '🟡 default';
      defaultOption.title = 'Instance: default\nStatus: unknown';
      defaultOption.dataset.state = 'unknown';
      defaultOption.selected = true;
      selector.appendChild(defaultOption);

      // Ensure we're using the default instance
      this.currentInstance = 'default';
      this.api.setInstance('default');
    }
  }

  /**
   * Handle instance selection change
   */
  async onInstanceChange(instanceId) {
    console.log('Switching to instance:', instanceId);

    const selector = document.getElementById('instanceSelector');

    try {
      // Disable selector and show loading state
      selector.disabled = true;
      selector.classList.add('opacity-50', 'cursor-wait');

      // Show loading toast
      this.showToast(`Switching to instance: ${instanceId}...`, 'info', 2000);

      // Stop all polling to prevent race conditions with old instance_id
      this.stopPolling();

      // Switch to new instance
      this.currentInstance = instanceId;
      this.api.setInstance(instanceId);

      // Clear status history when switching instances
      this.statusHistory = {
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

      // Revert selector to previous instance on error
      selector.value = this.currentInstance;

    } finally {
      // Re-enable selector
      selector.disabled = false;
      selector.classList.remove('opacity-50', 'cursor-wait');
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

    // Settings modal
    document.getElementById('settingsBtn').addEventListener('click', () => {
      this.showSettingsModal();
    });

    document.getElementById('closeSettingsBtn').addEventListener('click', () => {
      this.hideSettingsModal();
    });

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
    document.getElementById('settingsModal').addEventListener('click', (e) => {
      if (e.target.id === 'settingsModal') {
        this.hideSettingsModal();
      }
    });

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

    document.getElementById('generateForm').addEventListener('submit', (e) => {
      e.preventDefault();
      this.generateAutomation();
    });

    document.getElementById('healingForm').addEventListener('submit', (e) => {
      e.preventDefault();
      this.triggerHealing();
    });

    // Refresh buttons
    document.getElementById('refreshEntitiesBtn').addEventListener('click', () => {
      this.loadMonitoringTab();
    });

    document.getElementById('refreshSummaryBtn').addEventListener('click', () => {
      this.loadWeeklySummary();
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
   * Show settings modal
   */
  showSettingsModal() {
    const modal = document.getElementById('settingsModal');
    const input = document.getElementById('apiKeyInput');

    // Pre-fill with current key if exists
    input.value = this.api.apiKey || '';

    modal.classList.remove('hidden');
    modal.classList.add('flex');
  }

  /**
   * Hide settings modal
   */
  hideSettingsModal() {
    const modal = document.getElementById('settingsModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }

  /**
   * Save API key
   */
  async saveApiKey() {
    const input = document.getElementById('apiKeyInput');
    const key = input.value.trim();

    if (!key) {
      this.api.setApiKey(null);
      this.hideSettingsModal();
      this.showToast('API key cleared', 'info');
      return;
    }

    // Test the key
    const result = await this.api.testApiKey(key);

    if (result.success) {
      this.hideSettingsModal();
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
      const discoveryTimestamp = health.essential?.entity_discovery_complete?.details?.last_refresh;
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
      const serviceRunning = health.critical?.service_state?.status === 'healthy';
      const haConnected = health.critical?.ha_rest_connection?.status === 'healthy';
      const websocketConnected = health.essential?.websocket_connected?.status === 'healthy';
      const databaseAccessible = health.critical?.database_accessible?.status === 'healthy';

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
    document.getElementById('generateResult').classList.add('hidden');
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

  /**
   * Generate automation
   */
  async generateAutomation() {
    const description = document.getElementById('automationDescription').value.trim();
    const mode = document.getElementById('automationMode').value;
    const resultDiv = document.getElementById('generateResult');

    if (!description) return;

    resultDiv.innerHTML = Components.spinner();
    resultDiv.classList.remove('hidden');

    try {
      const result = await this.api.generateAutomation(description, mode);

      const html = `
        <div class="space-y-4 p-4 bg-gray-50 rounded">
          <div class="flex items-center justify-between">
            <h3 class="font-medium text-gray-900">${result.alias}</h3>
            ${result.is_valid ? Components.statusBadge('healthy', 'Valid') : Components.statusBadge('error', 'Invalid')}
          </div>
          <pre class="text-xs bg-gray-900 text-gray-100 p-3 rounded overflow-x-auto">${result.yaml_content}</pre>
          ${result.validation_errors && result.validation_errors.length > 0 ? `
            <div>
              <h4 class="text-sm font-medium text-red-900 mb-2">Validation Errors:</h4>
              <ul class="list-disc list-inside text-sm text-red-700">
                ${result.validation_errors.map(e => `<li>${e}</li>`).join('')}
              </ul>
            </div>
          ` : ''}
        </div>
      `;

      resultDiv.innerHTML = html;
      this.showToast('Automation generated successfully', 'success');

    } catch (error) {
      console.error('Error generating automation:', error);
      resultDiv.innerHTML = Components.errorAlert(`Failed to generate: ${error.message}`);
    }
  }

  // ==================== Healing Tab ====================

  /**
   * Load healing tab
   */
  async loadHealingTab() {
    await Promise.all([
      this.loadHealingHistory(),
      this.loadSuccessRate()
    ]);
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
   */
  async loadHealingHistory() {
    const historyDiv = document.getElementById('healingHistory');
    historyDiv.innerHTML = Components.spinner();

    try {
      const history = await this.api.getHealingHistory(50, 24);

      if (history.actions.length === 0) {
        historyDiv.innerHTML = '<p class="text-gray-500 text-center py-8">No healing history found</p>';
        return;
      }

      const headers = [
        { text: 'Entity', key: 'entity_id' },
        { text: 'Integration', key: 'integration' },
        { text: 'Result', key: 'result' },
        { text: 'Time', key: 'timestamp' }
      ];

      const rows = history.actions.map(action => ({
        entity_id: action.entity_id,
        integration: action.integration || '--',
        result: action.success ? '✓ Success' : '✗ Failed',
        timestamp: Components.formatTime(action.timestamp, true)
      }));

      historyDiv.innerHTML = Components.table(headers, rows);

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
      this.pollingIntervals.entities = setInterval(() => this.loadMonitoringTab(), 60000);
    }
  }

  /**
   * Stop tab-specific polling
   */
  stopTabPolling() {
    if (this.pollingIntervals.failures) clearInterval(this.pollingIntervals.failures);
    if (this.pollingIntervals.healing) clearInterval(this.pollingIntervals.healing);
    if (this.pollingIntervals.entities) clearInterval(this.pollingIntervals.entities);
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
        const discoveryTimestamp = health.essential?.entity_discovery_complete?.details?.last_refresh;
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
    const dashboard = new Dashboard();
    dashboard.init();
  });
} else {
  const dashboard = new Dashboard();
  dashboard.init();
}
