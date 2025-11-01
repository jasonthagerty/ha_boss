---
description: Run full CI checks locally before pushing
allowed-tools: Bash(pytest:*), Bash(black:*), Bash(ruff:*), Bash(mypy:*)
---

Run complete CI pipeline locally:

1. Format check:
!`black --check .`

2. Lint check:
!`ruff check .`

3. Type check:
!`mypy ha_boss`

4. Run tests with coverage:
!`pytest --cov=ha_boss --cov-report=term -v`

Provide a summary:
- ✓ All checks passed (ready to push)
- ✗ Issues found (list them with suggestions to fix)
