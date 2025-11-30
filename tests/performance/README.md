# Performance Tests

This directory contains performance benchmarks for HA Boss AI/LLM operations and database queries.

## Overview

Performance tests validate that AI features meet response time requirements and don't degrade user experience. Tests are marked with `@pytest.mark.performance` and can be run selectively.

## Test Files

### `test_ai_performance.py`
Benchmarks for AI/LLM operations including:
- **Ollama response times**: < 2s for simple prompts
- **Claude API response times**: < 10s for complex tasks
- **Enhanced notifications**: < 3s total time
- **Anomaly detection**: < 5s for 30-day scan
- **Weekly summaries**: < 15s
- **Automation analysis**: < 5s
- **Automation generation**: < 15s

### `test_pattern_performance.py`
Benchmarks for database pattern collection:
- Pattern recording latency: < 5ms
- Healing attempt recording: < 5ms
- Query performance with 10k events: < 100ms
- Concurrent recording performance
- Database growth impact

## Running Performance Tests

### Run All Performance Tests

```bash
# Run all performance tests (requires LLMs to be available)
pytest -m performance -v

# Run with live output
pytest -m performance -v -s
```

### Run Specific Test Categories

```bash
# Run only database/pattern tests (no LLM required)
pytest tests/performance/test_pattern_performance.py -v

# Run only AI tests (requires Ollama/Claude)
pytest tests/performance/test_ai_performance.py -v

# Run only tests that don't require LLMs
pytest tests/performance/test_ai_performance.py -v -k "anomaly"
```

### Skip Performance Tests

```bash
# Skip all performance tests during normal test runs
pytest -m "not performance"
```

## Environment Configuration

Performance tests use environment variables to determine LLM availability:

```bash
# Enable Ollama tests (requires Ollama running)
export TEST_OLLAMA_AVAILABLE=true
export TEST_OLLAMA_URL=http://localhost:11434
export TEST_OLLAMA_MODEL=llama3.1:8b

# Enable Claude tests (requires API key)
export TEST_CLAUDE_AVAILABLE=true
export TEST_CLAUDE_API_KEY=sk-ant-...
export TEST_CLAUDE_MODEL=claude-3-5-sonnet-20241022
```

### LLM Test Behavior

- **Ollama tests**: Skipped if `TEST_OLLAMA_AVAILABLE != "true"`
- **Claude tests**: Skipped if `TEST_CLAUDE_AVAILABLE != "true"`
- **Database tests**: Always run (no LLM required)

## Performance Targets

| Operation | Target | Max Acceptable | Status |
|-----------|--------|----------------|--------|
| Ollama simple prompt | 1s | 2s | ✅ |
| Ollama concurrent (3x) | 2s | 3s avg | ✅ |
| Claude complex task | 5s | 10s | ✅ |
| Claude simple task | 3s | 5s | ✅ |
| Enhanced notification | 2s | 3s | ✅ |
| Anomaly detection (30d) | 3s | 5s | ✅ |
| Weekly summary | 10s | 15s | ✅ |
| Automation analysis | 3s | 5s | ✅ |
| Automation generation | 8s | 15s | ✅ |
| Pattern recording | 3ms | 5ms | ✅ |
| Healing recording | 3ms | 5ms | ✅ |
| Query (10k events) | 50ms | 100ms | ✅ |

## CI Integration

Performance tests are **not** run in CI by default due to:
- LLM API costs (Claude)
- Infrastructure requirements (Ollama)
- Longer execution time

To run in CI:
```yaml
# Add to GitHub Actions workflow
- name: Run performance tests
  run: |
    pytest -m performance -v
  env:
    TEST_OLLAMA_AVAILABLE: true
    TEST_CLAUDE_AVAILABLE: true
    TEST_CLAUDE_API_KEY: ${{ secrets.CLAUDE_API_KEY }}
```

## Interpreting Results

### Successful Test
```
✓ Ollama simple prompt: 1.23s (target: < 2s)
✓ Claude complex task: 6.45s (target: < 10s)
```

### Failed Test
```
AssertionError: Ollama took 2.34s (expected < 2s)
```

### Skipped Test
```
SKIPPED [1] Ollama not available
```

## Troubleshooting

### All Ollama tests skipped
- Set `TEST_OLLAMA_AVAILABLE=true`
- Ensure Ollama is running: `curl http://localhost:11434/api/tags`
- Check model is available: `ollama list`

### All Claude tests skipped
- Set `TEST_CLAUDE_AVAILABLE=true`
- Provide valid API key: `TEST_CLAUDE_API_KEY=sk-ant-...`
- Verify API key has credits

### Tests timeout
- Increase pytest timeout: `pytest --timeout=300`
- Check LLM service health
- Verify network connectivity

### Performance degradation
- Check system resources (CPU, memory, network)
- Verify LLM service health and load
- Review recent code changes
- Compare against baseline metrics

## Development Workflow

When adding new AI features:

1. **Add performance test**: Create test in `test_ai_performance.py`
2. **Set target times**: Based on UX requirements
3. **Run locally**: Verify performance meets targets
4. **Document results**: Update this README with new targets
5. **Monitor trends**: Track performance over time

## Best Practices

1. **Warm-up calls**: First LLM request may be slower (model loading)
2. **Multiple iterations**: Average results over multiple runs
3. **Realistic data**: Use representative test data sizes
4. **Isolated tests**: Each test should be independent
5. **Clear assertions**: Include both target and max acceptable times
6. **Print results**: Always print timing results for visibility

## Related Documentation

- [LLM Setup](../../docs/LLM_SETUP.md) - LLM infrastructure details
- [CLAUDE.md](../../CLAUDE.md) - Project development guide
- [pytest markers](../../pyproject.toml) - Test marker configuration
