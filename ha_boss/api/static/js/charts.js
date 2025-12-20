/**
 * Chart Manager
 * Creates and manages Chart.js visualizations
 */

export class ChartManager {
  constructor() {
    this.charts = {};
    this.defaultOptions = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom'
        }
      }
    };
  }

  /**
   * Destroy a chart by ID
   * @param {string} chartId - Chart ID to destroy
   */
  destroyChart(chartId) {
    if (this.charts[chartId]) {
      this.charts[chartId].destroy();
      delete this.charts[chartId];
    }
  }

  /**
   * Destroy all charts
   */
  destroyAll() {
    Object.keys(this.charts).forEach(id => this.destroyChart(id));
  }

  /**
   * Create status timeline chart (healings over time)
   * @param {string} canvasId - Canvas element ID
   * @param {Object} data - Chart data {timestamps, attempted, succeeded, failed}
   * @returns {Chart} Chart instance
   */
  createStatusChart(canvasId, data = null) {
    this.destroyChart(canvasId);

    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    // Initialize with empty data if none provided
    const chartData = data || {
      timestamps: [],
      attempted: [],
      succeeded: [],
      failed: []
    };

    this.charts[canvasId] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: chartData.timestamps,
        datasets: [
          {
            label: 'Attempted',
            data: chartData.attempted,
            borderColor: 'rgb(59, 130, 246)', // Blue
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            tension: 0.4
          },
          {
            label: 'Succeeded',
            data: chartData.succeeded,
            borderColor: 'rgb(34, 197, 94)', // Green
            backgroundColor: 'rgba(34, 197, 94, 0.1)',
            tension: 0.4
          },
          {
            label: 'Failed',
            data: chartData.failed,
            borderColor: 'rgb(239, 68, 68)', // Red
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            tension: 0.4
          }
        ]
      },
      options: {
        ...this.defaultOptions,
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              stepSize: 1
            }
          }
        },
        plugins: {
          ...this.defaultOptions.plugins,
          tooltip: {
            mode: 'index',
            intersect: false
          }
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * Update status chart with new data
   * @param {string} chartId - Chart ID
   * @param {Object} newData - New data point {timestamp, attempted, succeeded, failed}
   */
  updateStatusChart(chartId, newData) {
    const chart = this.charts[chartId];
    if (!chart) return;

    // Keep last 20 data points
    const maxPoints = 20;

    chart.data.labels.push(newData.timestamp);
    chart.data.datasets[0].data.push(newData.attempted);
    chart.data.datasets[1].data.push(newData.succeeded);
    chart.data.datasets[2].data.push(newData.failed);

    if (chart.data.labels.length > maxPoints) {
      chart.data.labels.shift();
      chart.data.datasets.forEach(dataset => dataset.data.shift());
    }

    chart.update();
  }

  /**
   * Create integration reliability chart (horizontal bar)
   * @param {string} canvasId - Canvas element ID
   * @param {Array} data - Reliability data [{integration, reliability_percent}]
   * @returns {Chart} Chart instance
   */
  createReliabilityChart(canvasId, data) {
    this.destroyChart(canvasId);

    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    // Sort by reliability (ascending) and take top 10
    const sortedData = data
      .sort((a, b) => a.reliability_percent - b.reliability_percent)
      .slice(0, 10);

    const labels = sortedData.map(item => item.integration);
    const values = sortedData.map(item => item.reliability_percent);

    // Color gradient: red -> yellow -> green
    const backgroundColors = values.map(value => {
      if (value >= 90) return 'rgba(34, 197, 94, 0.8)'; // Green
      if (value >= 70) return 'rgba(234, 179, 8, 0.8)'; // Yellow
      return 'rgba(239, 68, 68, 0.8)'; // Red
    });

    this.charts[canvasId] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Reliability %',
          data: values,
          backgroundColor: backgroundColors,
          borderWidth: 1
        }]
      },
      options: {
        ...this.defaultOptions,
        indexAxis: 'y', // Horizontal bars
        scales: {
          x: {
            beginAtZero: true,
            max: 100,
            ticks: {
              callback: function(value) {
                return value + '%';
              }
            }
          }
        },
        plugins: {
          ...this.defaultOptions.plugins,
          legend: {
            display: false
          },
          tooltip: {
            callbacks: {
              label: function(context) {
                return context.parsed.x.toFixed(2) + '%';
              }
            }
          }
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * Create failure timeline chart (scatter)
   * @param {string} canvasId - Canvas element ID
   * @param {Array} failures - Failure events [{timestamp, integration, resolved}]
   * @returns {Chart} Chart instance
   */
  createFailureTimelineChart(canvasId, failures) {
    this.destroyChart(canvasId);

    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    // Group by integration
    const integrations = [...new Set(failures.map(f => f.integration))];
    const resolved = failures.filter(f => f.resolved).map((f, idx) => ({
      x: new Date(f.timestamp),
      y: integrations.indexOf(f.integration)
    }));
    const unresolved = failures.filter(f => !f.resolved).map((f, idx) => ({
      x: new Date(f.timestamp),
      y: integrations.indexOf(f.integration)
    }));

    this.charts[canvasId] = new Chart(canvas, {
      type: 'scatter',
      data: {
        datasets: [
          {
            label: 'Resolved',
            data: resolved,
            backgroundColor: 'rgba(34, 197, 94, 0.6)',
            borderColor: 'rgb(34, 197, 94)',
            pointRadius: 6
          },
          {
            label: 'Unresolved',
            data: unresolved,
            backgroundColor: 'rgba(239, 68, 68, 0.6)',
            borderColor: 'rgb(239, 68, 68)',
            pointRadius: 6
          }
        ]
      },
      options: {
        ...this.defaultOptions,
        scales: {
          x: {
            type: 'time',
            time: {
              unit: 'hour',
              displayFormats: {
                hour: 'MMM D, HH:mm'
              }
            },
            title: {
              display: true,
              text: 'Time'
            }
          },
          y: {
            type: 'category',
            labels: integrations,
            title: {
              display: true,
              text: 'Integration'
            }
          }
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * Create top failing integrations pie chart
   * @param {string} canvasId - Canvas element ID
   * @param {Array} data - Top failing integrations [{name, count}]
   * @returns {Chart} Chart instance
   */
  createTopFailingChart(canvasId, data) {
    this.destroyChart(canvasId);

    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    // Take top 5
    const topData = data.slice(0, 5);
    const labels = topData.map(item => item.name || 'Unknown');
    const values = topData.map(item => item.count || 0);

    // Distinct colors
    const colors = [
      'rgba(239, 68, 68, 0.8)',   // Red
      'rgba(249, 115, 22, 0.8)',  // Orange
      'rgba(234, 179, 8, 0.8)',   // Yellow
      'rgba(59, 130, 246, 0.8)',  // Blue
      'rgba(168, 85, 247, 0.8)'   // Purple
    ];

    this.charts[canvasId] = new Chart(canvas, {
      type: 'pie',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: colors.slice(0, values.length),
          borderWidth: 2,
          borderColor: '#fff'
        }]
      },
      options: {
        ...this.defaultOptions,
        plugins: {
          ...this.defaultOptions.plugins,
          tooltip: {
            callbacks: {
              label: function(context) {
                const label = context.label || '';
                const value = context.parsed || 0;
                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                const percentage = ((value / total) * 100).toFixed(1);
                return `${label}: ${value} (${percentage}%)`;
              }
            }
          }
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * Create entity state history chart (line)
   * @param {string} canvasId - Canvas element ID
   * @param {Array} history - History data [{timestamp, state}]
   * @returns {Chart} Chart instance
   */
  createEntityHistoryChart(canvasId, history) {
    this.destroyChart(canvasId);

    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    // Extract timestamps and states
    // Only plot numeric states
    const data = history
      .map(h => ({
        x: new Date(h.timestamp),
        y: parseFloat(h.state)
      }))
      .filter(d => !isNaN(d.y));

    if (data.length === 0) {
      // No numeric data to plot
      return null;
    }

    this.charts[canvasId] = new Chart(canvas, {
      type: 'line',
      data: {
        datasets: [{
          label: 'State',
          data: data,
          borderColor: 'rgb(59, 130, 246)',
          backgroundColor: 'rgba(59, 130, 246, 0.1)',
          tension: 0.4,
          pointRadius: 3
        }]
      },
      options: {
        ...this.defaultOptions,
        scales: {
          x: {
            type: 'time',
            time: {
              unit: 'hour',
              displayFormats: {
                hour: 'MMM D, HH:mm'
              }
            },
            title: {
              display: true,
              text: 'Time'
            }
          },
          y: {
            title: {
              display: true,
              text: 'State Value'
            }
          }
        },
        plugins: {
          ...this.defaultOptions.plugins,
          legend: {
            display: false
          }
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * Create healing success rate gauge (doughnut)
   * @param {string} canvasId - Canvas element ID
   * @param {number} successRate - Success rate percentage (0-100)
   * @returns {Chart} Chart instance
   */
  createSuccessRateGauge(canvasId, successRate) {
    this.destroyChart(canvasId);

    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const rate = Math.min(100, Math.max(0, successRate));
    const remaining = 100 - rate;

    this.charts[canvasId] = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: ['Success', 'Failed', 'Remaining'],
        datasets: [{
          data: [rate, 100 - rate, 0],
          backgroundColor: [
            'rgba(34, 197, 94, 0.8)',  // Green
            'rgba(239, 68, 68, 0.8)',  // Red
            'rgba(229, 231, 235, 0.3)' // Gray
          ],
          borderWidth: 2,
          borderColor: '#fff'
        }]
      },
      options: {
        ...this.defaultOptions,
        cutout: '70%',
        plugins: {
          ...this.defaultOptions.plugins,
          legend: {
            display: false
          },
          tooltip: {
            enabled: false
          }
        }
      },
      plugins: [{
        id: 'centerText',
        beforeDraw: function(chart) {
          const { width, height, ctx } = chart;
          ctx.restore();
          const fontSize = (height / 100).toFixed(2);
          ctx.font = `${fontSize}em sans-serif`;
          ctx.textBaseline = 'middle';

          const text = `${rate.toFixed(1)}%`;
          const textX = Math.round((width - ctx.measureText(text).width) / 2);
          const textY = height / 2;

          ctx.fillStyle = '#111827';
          ctx.fillText(text, textX, textY);
          ctx.save();
        }
      }]
    });

    return this.charts[canvasId];
  }
}

export default new ChartManager();
