---
description: Run pytest with coverage reporting
allowed-tools: Bash(pytest:*)
---

Run the test suite with coverage:

!`pytest --cov=ha_boss --cov-report=term --cov-report=html -v`

Analyze the results and report:
1. Number of tests passed/failed
2. Current code coverage percentage
3. Any failures or errors that need attention
4. Suggestions for improving test coverage
