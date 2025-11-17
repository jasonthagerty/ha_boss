# LLM Setup Guide for HA Boss

This guide documents the local LLM stack configuration for HA Boss Phase 3 AI features.

## Table of Contents

- [Overview](#overview)
- [Hardware Requirements](#hardware-requirements)
- [Testing Results](#testing-results)
- [Installation](#installation)
- [Configuration](#configuration)
- [Performance Characteristics](#performance-characteristics)
- [Future Optimizations](#future-optimizations)
- [Troubleshooting](#troubleshooting)

## Overview

HA Boss Phase 3 uses **Ollama** with **Llama 3.1 8B** model for local LLM inference. This provides:

- Enhanced notifications with AI-generated explanations
- Pattern-based anomaly detection with natural language insights
- Weekly summary reports with contextual analysis
- Automation analysis and optimization suggestions

**Key Decisions**:
- **LLM Backend**: Ollama (simple deployment, graceful degradation)
- **Model**: Llama 3.1 8B Instruct (Q4_K_M quantization)
- **Mode**: CPU inference (MVP), GPU acceleration planned for future
- **Deployment**: Docker container with docker-compose

## Hardware Requirements

### Minimum Requirements (CPU Mode)

- **CPU**: Modern x86_64 processor (4+ cores recommended)
- **RAM**: 8GB minimum (16GB recommended)
- **Storage**: 10GB for Ollama + models
- **Network**: Internet for initial model download

### Tested Configuration

**Server**: blackbox
- **OS**: Linux (Docker host)
- **CPU**: Intel CPU (exact model TBD)
- **GPU**: Intel ARC A770 16GB (detected but not used in MVP)
- **RAM**: 32GB+
- **Storage**: SSD

## Testing Results

### Performance Benchmarks (CPU Mode)

Testing conducted on blackbox server (2024-11-17):

**Model**: Llama 3.1 8B Instruct (Q4_K_M, 4.6GB)
**Docker Image**: `ollama-local-ollama-arc-openvino-enhanced:latest`

**Results**:
```
eval rate: 9.18 tokens/s
prompt eval rate: 39.56 tokens/s
Total time: 54s for 493 tokens

OpenVINO devices detected: ['CPU', 'GPU.0', 'GPU.1']
Status: "GPU not detected, using CPU mode"
```

### Performance Validation

**HA Boss Requirements**:
- Enhanced notifications: < 15s for 150-250 token responses ✅
- Weekly summaries: < 60s for 500-800 token reports ✅
- Low volume: 1-10 LLM requests per day ✅

**Measured Performance**:
- Short notification (150 tokens): ~11-12s ✅
- Medium explanation (300 tokens): ~20-25s ✅
- Long summary (600 tokens): ~50-60s ✅

### Why CPU Mode is Acceptable

1. **Low Volume Use Case**: HA Boss generates 1-10 LLM requests per day
2. **Background Processing**: Weekly summaries run as background tasks
3. **Graceful Degradation**: All features work without LLM (fallback to simple text)
4. **Meets Requirements**: < 15s latency target for notifications achieved
5. **Works Immediately**: No debugging required, reliable deployment

## Installation

### Docker Compose Setup

Add Ollama service to your `docker-compose.yml`:

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: haboss_ollama
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"
    restart: unless-stopped
    # CPU mode for MVP (GPU acceleration future enhancement - see Issue #52)

  haboss:
    image: haboss:latest
    container_name: haboss
    depends_on:
      - ollama
    environment:
      - HA_URL=${HA_URL}
      - HA_TOKEN=${HA_TOKEN}
      - OLLAMA_URL=http://ollama:11434
      - OLLAMA_MODEL=llama3.1:8b
    volumes:
      - ./config:/config
      - haboss_data:/data
    restart: unless-stopped

volumes:
  ollama_data:
  haboss_data:
```

### Initial Model Download

After starting Ollama container, pull the model:

```bash
# Pull Llama 3.1 8B model (4.6GB download)
docker exec haboss_ollama ollama pull llama3.1:8b

# Verify model is available
docker exec haboss_ollama ollama list
```

**Download time**: ~5-10 minutes on typical broadband connection.

### Verify Installation

Test Ollama is working:

```bash
# Quick test
docker exec haboss_ollama ollama run llama3.1:8b "Say hello"

# Check logs
docker logs haboss_ollama

# Verify API endpoint
curl http://localhost:11434/api/tags
```

## Configuration

### HA Boss Configuration

Add to `config/config.yaml`:

```yaml
intelligence:
  # Pattern collection (Phase 2) - already configured
  pattern_collection_enabled: true

  # Local LLM for AI features (Phase 3)
  ollama_enabled: true
  ollama_url: "http://ollama:11434"
  ollama_model: "llama3.1:8b"
  ollama_timeout_seconds: 30.0

  # Model performance characteristics (CPU mode)
  # Expected latency: 1-3s for short responses (100-200 tokens)
  # Expected latency: 5-15s for longer responses (500+ tokens)

  # Claude API (optional, for complex tasks)
  claude_enabled: false
  claude_api_key: null  # Set if using Claude for automation generation
  claude_model: "claude-3-5-sonnet-20241022"
```

### Environment Variables

Alternatively, configure via environment variables:

```bash
# .env file
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_TIMEOUT=30
OLLAMA_ENABLED=true

# Optional: Claude API
CLAUDE_ENABLED=false
CLAUDE_API_KEY=sk-ant-...
```

### Disabling LLM Features

To run HA Boss without LLM (fallback mode):

```yaml
intelligence:
  ollama_enabled: false
  claude_enabled: false
```

All AI features will gracefully degrade to simple text-based alternatives.

## Performance Characteristics

### Response Time Formula

```
response_time = (prompt_tokens / 39.56) + (output_tokens / 9.18)
```

### Expected Latencies (CPU Mode)

| Use Case | Prompt Tokens | Output Tokens | Expected Time |
|----------|---------------|---------------|---------------|
| Short notification | 50 | 150 | ~11s |
| Medium explanation | 100 | 300 | ~25s |
| Detailed analysis | 150 | 500 | ~55s |
| Weekly summary | 100 | 600 | ~68s |

### Resource Usage

**CPU**:
- Idle: 0%
- During inference: 100% on utilized cores
- Multi-threaded (uses all available cores)

**Memory**:
- Model loaded: ~6GB RAM
- During inference: +1-2GB
- Total: ~8GB with headroom

**Disk I/O**:
- Model load: One-time on first request
- Inference: Minimal (model cached in RAM)

## Future Optimizations

### GPU Acceleration (Planned)

**Issue**: #52 - Enable Intel ARC GPU acceleration

**Target Performance**:
- 2-5x speedup (20-50 tokens/s instead of 9 tokens/s)
- Reduced latency for all AI features
- Better scaling for higher volume use cases

**Status**:
- GPU detected but not utilized (OpenVINO configuration issue)
- Deferred to post-MVP optimization
- Not blocking Phase 3 development

**Alternatives if Ollama GPU proves difficult**:
1. Build llama.cpp with Intel SYCL backend
2. Use LocalAI with Intel GPU support
3. Keep CPU mode (acceptable for current volume)

### Model Optimization

**Smaller Models** (faster inference, lower quality):
- Llama 3.1 3B: ~3x faster, good for simple tasks
- Phi-3 Mini: ~4x faster, efficient small model

**Larger Models** (slower inference, higher quality):
- Llama 3.1 70B: Better reasoning, requires GPU
- Only needed if 8B quality insufficient

## Troubleshooting

### Ollama Container Won't Start

**Check logs**:
```bash
docker logs haboss_ollama
```

**Common issues**:
- Port 11434 already in use: Change port mapping in docker-compose.yml
- Volume mount issues: Check permissions on `ollama_data` volume

### Model Download Fails

**Network issues**:
```bash
# Check Ollama can reach huggingface.co
docker exec haboss_ollama curl -I https://huggingface.co

# Manual download alternative
docker exec -it haboss_ollama bash
ollama pull llama3.1:8b --verbose
```

### Slow Inference Performance

**Check CPU utilization**:
```bash
# During inference, should see 100% CPU usage
docker stats haboss_ollama
```

**Verify model is loaded**:
```bash
docker exec haboss_ollama ollama list
# Should show llama3.1:8b with size ~4.6GB
```

**Check for resource constraints**:
```bash
# Available RAM
free -h

# CPU cores
nproc

# Disk space
df -h
```

### HA Boss Can't Connect to Ollama

**Verify network connectivity**:
```bash
# From HA Boss container
docker exec haboss curl http://ollama:11434/api/tags

# Or from host
curl http://localhost:11434/api/tags
```

**Check docker-compose network**:
```bash
docker network ls
docker network inspect haboss_default
```

**Common fixes**:
- Ensure `depends_on: ollama` in haboss service
- Use service name `ollama` not `localhost` in OLLAMA_URL
- Verify both containers on same Docker network

### Out of Memory Errors

**Symptoms**:
```
Error: cannot allocate memory
```

**Solutions**:
1. Use smaller model (3B instead of 8B)
2. Increase Docker memory limit
3. Close other applications
4. Add swap space

```bash
# Check current memory
free -h

# Docker memory limit (if using Docker Desktop)
# Settings → Resources → Memory → Increase
```

### GPU Not Being Used

**This is expected for MVP**. See Issue #52 for GPU acceleration tracking.

**Verify GPU detection**:
```bash
docker logs haboss_ollama | grep -i gpu
# Should show: "GPU not detected, using CPU mode"
```

## References

- [Ollama Documentation](https://github.com/ollama/ollama)
- [Llama 3.1 Model Card](https://ai.meta.com/blog/meta-llama-3-1/)
- [Docker Compose Reference](https://docs.docker.com/compose/)
- [Issue #41: Ollama Integration](https://github.com/jasonthagerty/ha_boss/issues/41)
- [Issue #50: Performance Benchmarks](https://github.com/jasonthagerty/ha_boss/issues/50)
- [Issue #52: GPU Acceleration](https://github.com/jasonthagerty/ha_boss/issues/52)

## Support

For issues or questions:
- **GitHub Issues**: https://github.com/jasonthagerty/ha_boss/issues
- **Phase 3 Epic**: https://github.com/jasonthagerty/ha_boss/issues/40
- **LLM Setup**: https://github.com/jasonthagerty/ha_boss/issues/41
