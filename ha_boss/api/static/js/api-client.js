/**
 * HA Boss API Client
 * Handles all communication with the HA Boss REST API
 */

export class APIClient {
  constructor(baseURL = '/api') {
    this.baseURL = baseURL;
    this.apiKey = localStorage.getItem('ha_boss_api_key');
    this.currentInstance = localStorage.getItem('ha_boss_instance') || 'default';
  }

  /**
   * Set current instance
   * @param {string} instanceId - Instance identifier
   */
  setInstance(instanceId) {
    this.currentInstance = instanceId;
    localStorage.setItem('ha_boss_instance', instanceId);
  }

  /**
   * Add instance_id to URLSearchParams if provided
   * @param {URLSearchParams} params - URL parameters
   * @param {string|null} instanceId - Instance ID (null to use current)
   */
  addInstanceParam(params, instanceId = null) {
    const instance = instanceId !== null ? instanceId : this.currentInstance;
    if (instance) {
      params.set('instance_id', instance);
    }
  }

  /**
   * Set or clear the API key
   * @param {string|null} key - API key to set, or null to clear
   */
  setApiKey(key) {
    this.apiKey = key;
    if (key) {
      localStorage.setItem('ha_boss_api_key', key);
    } else {
      localStorage.removeItem('ha_boss_api_key');
    }
  }

  /**
   * Make an HTTP request to the API
   * @param {string} method - HTTP method (GET, POST, etc.)
   * @param {string} endpoint - API endpoint path
   * @param {Object} options - Fetch options
   * @returns {Promise<Object>} Response data
   */
  async request(method, endpoint, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers
    };

    // Add API key if available
    if (this.apiKey) {
      headers['X-API-Key'] = this.apiKey;
    }

    const url = `${this.baseURL}${endpoint}`;

    try {
      const response = await fetch(url, {
        method,
        headers,
        ...options
      });

      // Handle 401 Unauthorized - clear invalid API key
      if (response.status === 401) {
        this.setApiKey(null);
        throw new Error('Authentication failed. Please enter a valid API key.');
      }

      // Handle other errors
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `API error: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      if (error instanceof TypeError && error.message === 'Failed to fetch') {
        throw new Error('Unable to connect to API. Please check your connection.');
      }
      throw error;
    }
  }

  // ==================== Status & Health Endpoints ====================

  /**
   * Get list of all configured instances
   * GET /api/instances
   */
  async getInstances() {
    return this.request('GET', '/instances');
  }

  /**
   * Get current service status and statistics
   * GET /api/status
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async getStatus(instanceId = null) {
    const params = new URLSearchParams();
    this.addInstanceParam(params, instanceId);
    return this.request('GET', `/status?${params}`);
  }

  /**
   * Health check endpoint
   * GET /api/health
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async getHealth(instanceId = null) {
    const params = new URLSearchParams();
    this.addInstanceParam(params, instanceId);
    return this.request('GET', `/health?${params}`);
  }

  // ==================== Monitoring Endpoints ====================

  /**
   * List all monitored entities
   * GET /api/entities
   * @param {number} limit - Maximum entities to return (1-1000, default: 100)
   * @param {number} offset - Pagination offset (default: 0)
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async getEntities(limit = 100, offset = 0, instanceId = null) {
    const params = new URLSearchParams({ limit, offset });
    this.addInstanceParam(params, instanceId);
    return this.request('GET', `/entities?${params}`);
  }

  /**
   * Get current state of a specific entity
   * GET /api/entities/{entity_id}
   * @param {string} entityId - Entity ID (e.g., 'sensor.temperature')
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async getEntity(entityId, instanceId = null) {
    const params = new URLSearchParams();
    this.addInstanceParam(params, instanceId);
    return this.request('GET', `/entities/${encodeURIComponent(entityId)}?${params}`);
  }

  /**
   * Get state history for a specific entity
   * GET /api/entities/{entity_id}/history
   * @param {string} entityId - Entity ID
   * @param {number} hours - Hours of history to retrieve (1-168, default: 24)
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async getEntityHistory(entityId, hours = 24, instanceId = null) {
    const params = new URLSearchParams({ hours });
    this.addInstanceParam(params, instanceId);
    return this.request('GET', `/entities/${encodeURIComponent(entityId)}/history?${params}`);
  }

  // ==================== Pattern Analysis Endpoints ====================

  /**
   * Get integration reliability statistics
   * GET /api/patterns/reliability
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async getReliability(instanceId = null) {
    const params = new URLSearchParams();
    this.addInstanceParam(params, instanceId);
    return this.request('GET', `/patterns/reliability?${params}`);
  }

  /**
   * Get failure event timeline
   * GET /api/patterns/failures
   * @param {number} limit - Maximum failures to return (1-500, default: 50)
   * @param {number} hours - Hours of history (1-168, default: 24)
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async getFailures(limit = 50, hours = 24, instanceId = null) {
    const params = new URLSearchParams({ limit, hours });
    this.addInstanceParam(params, instanceId);
    return this.request('GET', `/patterns/failures?${params}`);
  }

  /**
   * Get weekly summary statistics
   * GET /api/patterns/summary
   * @param {number} days - Days to summarize (1-30, default: 7)
   * @param {boolean} ai - Include AI-generated insights (default: false)
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async getSummary(days = 7, ai = false, instanceId = null) {
    const params = new URLSearchParams({ days, ai });
    this.addInstanceParam(params, instanceId);
    return this.request('GET', `/patterns/summary?${params}`);
  }

  // ==================== Automation Management Endpoints ====================

  /**
   * Analyze an existing automation with AI
   * POST /api/automations/analyze
   * @param {string} automationId - Automation ID to analyze
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async analyzeAutomation(automationId, instanceId = null) {
    const params = new URLSearchParams();
    this.addInstanceParam(params, instanceId);
    return this.request('POST', `/automations/analyze?${params}`, {
      body: JSON.stringify({ automation_id: automationId })
    });
  }

  /**
   * Generate a new automation from natural language
   * POST /api/automations/generate
   * @param {string} description - Natural language description
   * @param {string} mode - Automation mode (default: 'single')
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async generateAutomation(description, mode = 'single', instanceId = null) {
    const params = new URLSearchParams();
    this.addInstanceParam(params, instanceId);
    return this.request('POST', `/automations/generate?${params}`, {
      body: JSON.stringify({ description, mode })
    });
  }

  /**
   * Create an automation in Home Assistant
   * POST /api/automations/create
   * @param {string} automationYaml - Automation YAML content
   */
  async createAutomation(automationYaml) {
    return this.request('POST', '/automations/create', {
      body: JSON.stringify({ automation_yaml: automationYaml })
    });
  }

  // ==================== Healing Endpoints ====================

  /**
   * Manually trigger healing for a specific entity
   * POST /api/healing/{entity_id}
   * @param {string} entityId - Entity ID to heal
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async triggerHealing(entityId, instanceId = null) {
    const params = new URLSearchParams();
    this.addInstanceParam(params, instanceId);
    return this.request('POST', `/healing/${encodeURIComponent(entityId)}?${params}`);
  }

  /**
   * Get healing action history
   * GET /api/healing/history
   * @param {number} limit - Maximum actions to return (1-500, default: 50)
   * @param {number} hours - Hours of history (1-168, default: 24)
   * @param {string|null} instanceId - Instance ID (null to use current instance)
   */
  async getHealingHistory(limit = 50, hours = 24, instanceId = null) {
    const params = new URLSearchParams({ limit, hours });
    this.addInstanceParam(params, instanceId);
    return this.request('GET', `/healing/history?${params}`);
  }

  // ==================== Helper Methods ====================

  /**
   * Test API key by making a health check request
   * @param {string} key - API key to test
   * @returns {Promise<{success: boolean, error?: string}>}
   */
  async testApiKey(key) {
    const originalKey = this.apiKey;

    try {
      // Temporarily set the key
      this.apiKey = key;

      // Try to make a request
      await this.getHealth();

      // Success!
      this.setApiKey(key);
      return { success: true };

    } catch (error) {
      // Restore original key
      this.apiKey = originalKey;

      if (error.message.includes('Authentication failed')) {
        return { success: false, error: 'Invalid API key' };
      }

      return { success: false, error: error.message };
    }
  }

  /**
   * Check if the API is accessible
   * @returns {Promise<boolean>}
   */
  async isAvailable() {
    try {
      await this.getHealth();
      return true;
    } catch {
      return false;
    }
  }
}

// Create and export a default instance
export default new APIClient();
