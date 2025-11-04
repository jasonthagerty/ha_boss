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

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY ha_boss/ ./ha_boss/
COPY config/config.yaml.example ./config/config.yaml.example

# Create directories for runtime data
RUN mkdir -p /app/config /app/data && \
    chown -R haboss:haboss /app

# Add health check script (Python-based, no external dependencies)
COPY --chmod=755 <<'EOF' /usr/local/bin/healthcheck.py
#!/usr/bin/env python3
"""Health check script for HA Boss container."""
import os
import sys
from pathlib import Path

def main() -> int:
    """Run health checks and return exit code."""
    # Check if database exists (indicates initialization)
    db_path = Path("/app/data/ha_boss.db")
    if not db_path.exists():
        print("Database not initialized", file=sys.stderr)
        return 1

    # Check if database is readable
    try:
        if not db_path.is_file() or not os.access(db_path, os.R_OK):
            print("Database exists but is not accessible", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"Database check failed: {e}", file=sys.stderr)
        return 1

    # All checks passed
    return 0

if __name__ == "__main__":
    sys.exit(main())
EOF

# Switch to non-root user
USER haboss

# Expose port (for future API)
EXPOSE 8080

# Add health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python3", "/usr/local/bin/healthcheck.py"]

# Set entrypoint for proper signal handling
ENTRYPOINT ["python", "-m", "ha_boss.cli.commands"]

# Default command (can be overridden)
CMD ["start", "--foreground"]
