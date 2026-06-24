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
"""Liveness check for HA Boss container.

HA Boss runs as a headless monitor-and-notify service with no HTTP server, so
this verifies the main service process is alive by scanning /proc for the
``haboss`` process. Dependency-free.

Exit codes:
  0 - Service process running
  1 - Service process not found
"""
import os
import sys

def main() -> int:
    """Return 0 if the haboss service process is running, else 1."""
    self_pid = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == self_pid:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read().replace(b"\x00", b" ").decode("utf-8", "ignore")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if "haboss" in cmdline or "ha_boss" in cmdline:
            return 0

    print("HA Boss service process not found", file=sys.stderr)
    return 1

if __name__ == "__main__":
    sys.exit(main())
EOF

# Switch to non-root user
USER haboss

# Add health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python3", "/usr/local/bin/healthcheck.py"]

# Set entrypoint to use installed console script (avoids module import warnings)
ENTRYPOINT ["haboss"]

# Default command (can be overridden)
CMD ["start", "--foreground"]
