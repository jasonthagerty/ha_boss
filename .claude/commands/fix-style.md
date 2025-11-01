---
description: Auto-fix code formatting and style issues
allowed-tools: Bash(black:*), Bash(ruff:*)
---

Fix code formatting and auto-fixable style issues:

1. Format code with black:
!`black .`

2. Fix auto-fixable linting issues:
!`ruff check --fix .`

Report what was fixed.
