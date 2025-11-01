---
description: Set up development environment
allowed-tools: Bash(python:*), Bash(pip:*)
---

Guide the user through setting up the development environment:

1. Check Python version:
!`python --version`

2. Create and activate virtual environment if needed
3. Install development dependencies:
!`pip install -e ".[dev]"`

4. Verify installation by running basic tests:
!`pytest tests/test_basic.py -v`

Provide setup status and next steps.
