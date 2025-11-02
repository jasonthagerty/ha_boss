.PHONY: help install test lint format clean ci-check setup

help:
	@echo "HA Boss - Development Commands"
	@echo ""
	@echo "  make setup       - Set up development environment (uv + venv)"
	@echo "  make install     - Install package with dev dependencies"
	@echo "  make test        - Run tests with coverage"
	@echo "  make lint        - Run linters (ruff, mypy)"
	@echo "  make format      - Format code with black"
	@echo "  make ci-check    - Run all CI checks locally"
	@echo "  make clean       - Remove build artifacts and cache files"
	@echo ""

setup:
	@echo "Setting up development environment..."
	@if command -v uv >/dev/null 2>&1; then \
		echo "Using uv to create virtual environment with Python 3.12..."; \
		uv venv --python 3.12; \
		echo "✓ Virtual environment created at .venv"; \
		echo ""; \
		echo "Activate with: source .venv/bin/activate"; \
		echo "Then run: make install"; \
	else \
		echo "uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo "Or create venv manually: python3.12 -m venv venv && source venv/bin/activate"; \
	fi

install:
	@if command -v uv >/dev/null 2>&1; then \
		echo "Using uv to install dependencies..."; \
		uv pip install -e ".[dev]"; \
	else \
		echo "Using pip to install dependencies..."; \
		pip install -e ".[dev]"; \
	fi

test:
	pytest --cov=ha_boss --cov-report=html --cov-report=term -v

lint:
	ruff check .
	mypy ha_boss

format:
	black .
	ruff check --fix .

ci-check:
	@echo "Running CI checks..."
	@echo "1. Format check..."
	black --check .
	@echo "2. Lint check..."
	ruff check .
	@echo "3. Type check..."
	mypy ha_boss
	@echo "4. Running tests..."
	pytest --cov=ha_boss --cov-report=term
	@echo ""
	@echo "✓ All CI checks passed!"

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf .mypy_cache
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
