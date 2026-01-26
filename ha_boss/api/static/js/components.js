/**
 * UI Components Library
 * Reusable component generators for the dashboard
 */

export const Components = {
  /**
   * Create a status badge
   * @param {string} status - Status type (healthy, degraded, unhealthy, running, stopped)
   * @param {string} text - Badge text
   * @returns {string} HTML string
   */
  statusBadge(status, text) {
    const colors = {
      healthy: 'bg-green-100 text-green-800',
      degraded: 'bg-yellow-100 text-yellow-800',
      unhealthy: 'bg-red-100 text-red-800',
      running: 'bg-green-100 text-green-800',
      stopped: 'bg-red-100 text-red-800',
      error: 'bg-red-100 text-red-800'
    };

    const colorClass = colors[status] || 'bg-gray-100 text-gray-800';

    return `<span class="px-2 py-1 text-xs font-medium rounded ${colorClass}">${text}</span>`;
  },

  /**
   * Create a boolean indicator (checkmark or X)
   * @param {boolean} value - Boolean value
   * @returns {string} HTML string
   */
  booleanIndicator(value) {
    if (value) {
      return `<span class="text-green-600">✓</span>`;
    } else {
      return `<span class="text-red-600">✗</span>`;
    }
  },

  /**
   * Create a loading spinner
   * @param {string} size - Size (sm, md, lg)
   * @returns {string} HTML string
   */
  spinner(size = 'md') {
    const sizes = {
      sm: 'h-4 w-4',
      md: 'h-8 w-8',
      lg: 'h-12 w-12'
    };

    const sizeClass = sizes[size] || sizes.md;

    return `
      <div class="flex justify-center items-center p-4">
        <svg class="animate-spin ${sizeClass} text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      </div>
    `;
  },

  /**
   * Create an error alert
   * @param {string} message - Error message
   * @param {boolean} dismissible - Whether the alert can be dismissed
   * @returns {string} HTML string
   */
  errorAlert(message, dismissible = true) {
    const closeBtn = dismissible ? `
      <button onclick="this.parentElement.remove()" class="ml-auto text-red-700 hover:text-red-900">
        <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
        </svg>
      </button>
    ` : '';

    return `
      <div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded flex items-center" role="alert">
        <svg class="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"></path>
        </svg>
        <span>${message}</span>
        ${closeBtn}
      </div>
    `;
  },

  /**
   * Create a success alert
   * @param {string} message - Success message
   * @param {boolean} dismissible - Whether the alert can be dismissed
   * @returns {string} HTML string
   */
  successAlert(message, dismissible = true) {
    const closeBtn = dismissible ? `
      <button onclick="this.parentElement.remove()" class="ml-auto text-green-700 hover:text-green-900">
        <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
        </svg>
      </button>
    ` : '';

    return `
      <div class="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded flex items-center" role="alert">
        <svg class="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path>
        </svg>
        <span>${message}</span>
        ${closeBtn}
      </div>
    `;
  },

  /**
   * Create a toast notification
   * @param {string} message - Toast message
   * @param {string} type - Toast type (success, error, info)
   * @param {number} duration - Auto-dismiss duration in ms (0 = no auto-dismiss)
   * @returns {HTMLElement} Toast element
   */
  toast(message, type = 'info', duration = 3000) {
    const colors = {
      success: 'bg-green-500',
      error: 'bg-red-500',
      info: 'bg-blue-500'
    };

    const colorClass = colors[type] || colors.info;

    const toast = document.createElement('div');
    toast.className = `${colorClass} text-white px-4 py-3 rounded shadow-lg flex items-center space-x-2 transform transition-all duration-300 translate-x-0`;
    toast.innerHTML = `
      <span>${message}</span>
      <button onclick="this.parentElement.remove()" class="ml-2 text-white hover:text-gray-200">
        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
        </svg>
      </button>
    `;

    // Auto-dismiss
    if (duration > 0) {
      setTimeout(() => {
        toast.classList.add('translate-x-full', 'opacity-0');
        setTimeout(() => toast.remove(), 300);
      }, duration);
    }

    return toast;
  },

  /**
   * Create a data table
   * @param {Array} headers - Table headers [{text: string, key: string}]
   * @param {Array} rows - Table rows (array of objects)
   * @param {Object} options - Table options
   * @param {boolean} options.sortable - Enable sorting
   * @param {boolean} options.hoverable - Enable row hover effect
   * @param {boolean} options.striped - Enable alternating row colors
   * @param {Array} options.rawHtml - Array of column keys that contain raw HTML
   * @returns {string} HTML string
   */
  table(headers, rows, options = {}) {
    const { sortable = false, hoverable = true, striped = true, rawHtml = [] } = options;

    if (rows.length === 0) {
      return `<p class="text-gray-500 text-center py-8">No data available</p>`;
    }

    const hoverClass = hoverable ? 'hover:bg-gray-50' : '';
    const stripedClass = striped ? 'even:bg-gray-50' : '';

    const headerRow = headers.map(h => `
      <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
        ${h.text}
        ${sortable ? '<span class="ml-1 cursor-pointer">↕</span>' : ''}
      </th>
    `).join('');

    const bodyRows = rows.map(row => `
      <tr class="${hoverClass} ${stripedClass}">
        ${headers.map(h => {
          const value = row[h.key];
          // If this column is marked as raw HTML, don't escape it
          const cellContent = rawHtml.includes(h.key) ? (value || '--') : this.escapeHtml(String(value || '--'));
          return `<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${cellContent}</td>`;
        }).join('')}
      </tr>
    `).join('');

    return `
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>${headerRow}</tr>
          </thead>
          <tbody class="bg-white divide-y divide-gray-200">
            ${bodyRows}
          </tbody>
        </table>
      </div>
    `;
  },

  /**
   * Create pagination controls
   * @param {number} current - Current page (1-based)
   * @param {number} total - Total number of items
   * @param {number} perPage - Items per page
   * @param {function} onChange - Callback when page changes
   * @returns {string} HTML string
   */
  pagination(current, total, perPage, onChange) {
    const totalPages = Math.ceil(total / perPage);

    if (totalPages <= 1) {
      return '';
    }

    const prevDisabled = current === 1 ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:bg-gray-100';
    const nextDisabled = current === totalPages ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:bg-gray-100';

    const handleClick = (page) => {
      if (page < 1 || page > totalPages || page === current) return;
      onChange(page);
    };

    // Store the callback globally for the onclick handlers to access
    window.__paginationCallback = handleClick;

    return `
      <div class="flex items-center justify-between">
        <div class="text-sm text-gray-700">
          Showing <span class="font-medium">${(current - 1) * perPage + 1}</span> to
          <span class="font-medium">${Math.min(current * perPage, total)}</span> of
          <span class="font-medium">${total}</span> results
        </div>
        <div class="flex space-x-2">
          <button onclick="window.__paginationCallback(${current - 1})"
                  class="px-3 py-1 border border-gray-300 rounded ${prevDisabled}">
            Previous
          </button>
          <span class="px-3 py-1 text-sm text-gray-700">
            Page ${current} of ${totalPages}
          </span>
          <button onclick="window.__paginationCallback(${current + 1})"
                  class="px-3 py-1 border border-gray-300 rounded ${nextDisabled}">
            Next
          </button>
        </div>
      </div>
    `;
  },

  /**
   * Format a timestamp for display
   * @param {string} timestamp - ISO timestamp
   * @param {boolean} relative - Show relative time (e.g., "2 hours ago")
   * @returns {string} Formatted time
   */
  formatTime(timestamp, relative = false) {
    if (!timestamp) return '--';

    const date = dayjs(timestamp);

    if (relative) {
      return date.fromNow();
    }

    return date.format('YYYY-MM-DD HH:mm:ss');
  },

  /**
   * Format duration in seconds to human-readable format
   * @param {number} seconds - Duration in seconds
   * @returns {string} Formatted duration
   */
  formatDuration(seconds) {
    if (!seconds || seconds < 0) return '--';

    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    const parts = [];
    if (days > 0) parts.push(`${days}d`);
    if (hours > 0) parts.push(`${hours}h`);
    if (minutes > 0) parts.push(`${minutes}m`);
    if (secs > 0 || parts.length === 0) parts.push(`${secs}s`);

    return parts.join(' ');
  },

  /**
   * Escape HTML to prevent XSS
   * @param {string} text - Text to escape
   * @returns {string} Escaped text
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  /**
   * Truncate text with ellipsis
   * @param {string} text - Text to truncate
   * @param {number} maxLength - Maximum length
   * @returns {string} Truncated text
   */
  truncate(text, maxLength = 50) {
    if (!text || text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  }
};

export default Components;
