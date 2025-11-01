---
description: Run tests for a specific file
argument-hint: [test-file-path]
allowed-tools: Bash(pytest:*)
---

Run tests for the specified file: $1

!`pytest $1 -v`

Report the results and any failures.
