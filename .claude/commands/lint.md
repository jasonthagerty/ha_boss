---
description: Run all code quality checks (black, ruff, mypy)
allowed-tools: Bash(black:*), Bash(ruff:*), Bash(mypy:*)
---

Run all code quality checks:

1. Format check:
!`black --check .`

2. Linting:
!`ruff check .`

3. Type checking:
!`mypy ha_boss`

Analyze the results and either:
- Report that all checks passed
- List specific issues found and offer to fix them
