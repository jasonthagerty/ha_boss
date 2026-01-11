/**
 * WebSocket client for real-time dashboard updates.
 *
 * Manages WebSocket connection, automatic reconnection with exponential backoff,
 * and event dispatching to dashboard components.
 */
class WebSocketClient {
    constructor(baseUrl, instanceId = 'default') {
        this.baseUrl = baseUrl.replace('http://', 'ws://').replace('https://', 'wss://');
        this.instanceId = instanceId;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000; // Start at 1 second
        this.maxReconnectDelay = 30000; // Max 30 seconds
        this.reconnectTimer = null;
        this.pingInterval = null;
        this.pingIntervalMs = 30000; // Ping every 30 seconds
        this.connected = false;
        this.intentionallyClosed = false;

        // Event listeners: {eventType: [callback1, callback2, ...]}
        this.listeners = {};

        // Connection state listeners
        this.onConnected = null;
        this.onDisconnected = null;
        this.onError = null;
    }

    /**
     * Connect to WebSocket server.
     */
    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
            console.log('WebSocket already connected or connecting');
            return;
        }

        this.intentionallyClosed = false;
        const wsUrl = `${this.baseUrl}/api/ws?instance_id=${encodeURIComponent(this.instanceId)}`;

        console.log(`Connecting to WebSocket: ${wsUrl}`);

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = (event) => {
                console.log('WebSocket connected');
                this.connected = true;
                this.reconnectAttempts = 0;
                this.reconnectDelay = 1000;

                // Start ping interval
                this.startPingInterval();

                // Notify connected
                if (this.onConnected) {
                    this.onConnected(event);
                }
            };

            this.ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    this.handleMessage(message);
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error, event.data);
                }
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                if (this.onError) {
                    this.onError(error);
                }
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket disconnected:', event.code, event.reason);
                this.connected = false;
                this.stopPingInterval();

                // Notify disconnected
                if (this.onDisconnected) {
                    this.onDisconnected(event);
                }

                // Attempt reconnection if not intentionally closed
                if (!this.intentionallyClosed) {
                    this.scheduleReconnect();
                }
            };

        } catch (error) {
            console.error('Error creating WebSocket:', error);
            this.scheduleReconnect();
        }
    }

    /**
     * Disconnect from WebSocket server.
     */
    disconnect() {
        console.log('Intentionally closing WebSocket');
        this.intentionallyClosed = true;
        this.stopPingInterval();

        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        this.connected = false;
    }

    /**
     * Switch to a different instance.
     */
    switchInstance(instanceId) {
        console.log(`Switching to instance: ${instanceId}`);
        this.instanceId = instanceId;

        if (this.connected && this.ws) {
            // Send switch message to server
            this.send({
                type: 'switch_instance',
                instance_id: instanceId
            });
        } else {
            // Reconnect with new instance
            this.disconnect();
            this.connect();
        }
    }

    /**
     * Schedule reconnection with exponential backoff.
     */
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('Max reconnection attempts reached. Please reload the page.');
            return;
        }

        this.reconnectAttempts++;
        const delay = Math.min(this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelay);

        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

        this.reconnectTimer = setTimeout(() => {
            this.connect();
        }, delay);
    }

    /**
     * Start ping interval to keep connection alive.
     */
    startPingInterval() {
        this.stopPingInterval();

        this.pingInterval = setInterval(() => {
            if (this.connected && this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.send({
                    type: 'ping',
                    timestamp: new Date().toISOString()
                });
            }
        }, this.pingIntervalMs);
    }

    /**
     * Stop ping interval.
     */
    stopPingInterval() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    /**
     * Send message to server.
     */
    send(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
            return true;
        } else {
            console.warn('Cannot send message: WebSocket not connected');
            return false;
        }
    }

    /**
     * Handle incoming message from server.
     */
    handleMessage(message) {
        const messageType = message.type;

        // Log non-pong messages
        if (messageType !== 'pong') {
            console.log('WebSocket message received:', messageType, message);
        }

        // Dispatch to registered listeners
        if (this.listeners[messageType]) {
            for (const callback of this.listeners[messageType]) {
                try {
                    callback(message);
                } catch (error) {
                    console.error(`Error in ${messageType} listener:`, error);
                }
            }
        }

        // Dispatch to generic listeners
        if (this.listeners['*']) {
            for (const callback of this.listeners['*']) {
                try {
                    callback(message);
                } catch (error) {
                    console.error('Error in generic listener:', error);
                }
            }
        }
    }

    /**
     * Register event listener.
     *
     * @param {string} eventType - Event type to listen for ('*' for all events)
     * @param {function} callback - Callback function (receives message object)
     */
    on(eventType, callback) {
        if (!this.listeners[eventType]) {
            this.listeners[eventType] = [];
        }
        this.listeners[eventType].push(callback);
    }

    /**
     * Unregister event listener.
     */
    off(eventType, callback) {
        if (this.listeners[eventType]) {
            this.listeners[eventType] = this.listeners[eventType].filter(cb => cb !== callback);
        }
    }

    /**
     * Update subscriptions.
     */
    subscribe(subscriptions) {
        this.send({
            type: 'subscribe',
            subscriptions: subscriptions
        });
    }

    /**
     * Get connection status.
     */
    isConnected() {
        return this.connected && this.ws && this.ws.readyState === WebSocket.OPEN;
    }
}

// Export for use in other modules
window.WebSocketClient = WebSocketClient;
