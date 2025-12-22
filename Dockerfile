# Multi-stage build for HA Boss
# Build stage: Install dependencies and build wheels
FROM python:3.12-slim AS builder

# Set working directory
WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files and source code
COPY pyproject.toml ./
COPY ha_boss/ ./ha_boss/

# Install dependencies to a temporary location
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefix=/install .

# Runtime stage: Minimal production image
FROM python:3.12-slim

# Set labels
LABEL org.opencontainers.image.title="HA Boss" \
      org.opencontainers.image.description="Home Assistant monitoring and auto-healing service" \
      org.opencontainers.image.vendor="Jason Hagerty" \
      org.opencontainers.image.source="https://github.com/jasonthagerty/ha_boss"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user for security
RUN groupadd -r haboss && useradd -r -g haboss -u 1000 haboss

# Set working directory
WORKDIR /app

# Copy dependency files and source code
COPY pyproject.toml ./
COPY ha_boss/ ./ha_boss/
COPY config/config.yaml.example ./config/config.yaml.example

# Copy pre-built dependencies from builder (wheels and compiled extensions)
COPY --from=builder /install /usr/local

# Install the package using pip (creates console scripts and proper site-packages structure)
RUN pip install --no-cache-dir .

# Create directories for runtime data
RUN mkdir -p /app/config /app/data && \
    chown -R haboss:haboss /app

# Add health check script (Python-based, no external dependencies)
COPY --chmod=755 <<'EOF' /usr/local/bin/healthcheck.py
#!/usr/bin/env python3
"""Health check script for HA Boss container.

Calls the comprehensive /api/health endpoint which checks 22 components
across 5 tiers (critical, essential, operational, healing, intelligence).

Exit codes:
  0 - Healthy or degraded (HTTP 200)
  1 - Unhealthy (HTTP 503) or connection failed
"""
import sys
import urllib.request
import urllib.error

def main() -> int:
    """Run health check via API endpoint and return exit code."""
    health_url = "http://localhost:8000/api/health"

    try:
        # Make request to health endpoint with 5 second timeout
        with urllib.request.urlopen(health_url, timeout=5) as response:
            status_code = response.getcode()

            # 200 OK = healthy or degraded (service still functional)
            if status_code == 200:
                return 0

            # Any other 2xx code is also acceptable
            if 200 <= status_code < 300:
                return 0

            # Non-2xx response
            print(f"Health check returned status {status_code}", file=sys.stderr)
            return 1

    except urllib.error.HTTPError as e:
        # 503 Service Unavailable = unhealthy (critical failure)
        if e.code == 503:
            print("Health check reports service unhealthy (503)", file=sys.stderr)
            return 1

        # Other HTTP errors
        print(f"Health check HTTP error: {e.code} {e.reason}", file=sys.stderr)
        return 1

    except urllib.error.URLError as e:
        # Connection failed (API not running)
        print(f"Cannot connect to API: {e.reason}", file=sys.stderr)
        return 1

    except Exception as e:
        # Unexpected error
        print(f"Health check failed: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
EOF

# Switch to non-root user
USER haboss

# Expose API port
EXPOSE 8000

# Add health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python3", "/usr/local/bin/healthcheck.py"]

# Set entrypoint to use installed console script (avoids module import warnings)
ENTRYPOINT ["haboss"]

# Default command (can be overridden)
CMD ["start", "--foreground"]
