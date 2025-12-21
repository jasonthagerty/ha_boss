# Home Assistant Addon (Future)

This directory will contain the Home Assistant addon configuration for HA Boss.

## Current Status

**Not yet implemented.** HA Boss currently runs as a standalone Docker container.

## Planned Implementation

When implemented, the addon will provide:

### Features
- ✅ One-click installation from HA addon store
- ✅ Automatic discovery of Home Assistant instance
- ✅ Integrated authentication (no manual token needed)
- ✅ Configuration UI in Home Assistant
- ✅ Supervisor API integration
- ✅ Add-on logs visible in HA UI
- ✅ Start/stop/restart from HA UI

### Required Files

```
addon/
├── config.yaml           # Addon manifest (name, version, architectures)
├── Dockerfile           # Addon-specific Dockerfile
├── build.yaml           # Multi-arch build configuration
├── run.sh              # Addon entrypoint script
├── icon.png            # Addon icon (256x256)
├── logo.png            # Addon logo (128x128)
├── README.md           # This file
└── DOCS.md             # User-facing documentation
```

### Architecture Support

Must match Home Assistant's supported architectures:
- `amd64` - Intel/AMD 64-bit
- `aarch64` - ARM 64-bit (arm64)
- `armv7` - ARM 32-bit
- `armhf` - ARM hard float (optional)
- `i386` - Intel 32-bit (optional)

### Integration Requirements

1. **Supervisor API Access**
   - Auto-discover HA instance via Supervisor
   - Use Supervisor auth tokens
   - Report health status

2. **Configuration Schema**
   - Define options in config.yaml
   - Validate user input
   - Provide sensible defaults

3. **Ingress Support (Optional)**
   - Embed UI panel in HA
   - Single sign-on via Supervisor

4. **Service Discovery**
   - Auto-configure HA_URL
   - Auto-configure HA_TOKEN
   - Detect database path

### References

- [HA Addon Development](https://developers.home-assistant.io/docs/add-ons)
- [Addon Configuration](https://developers.home-assistant.io/docs/add-ons/configuration)
- [Addon Testing](https://developers.home-assistant.io/docs/add-ons/testing)

## Timeline

Addon development will begin after:
1. ✅ Core monitoring and healing functionality is stable
2. ✅ Multi-architecture Docker images are tested
3. ⏳ User feedback and feature requests stabilize
4. ⏳ Integration testing with various HA installations

## Contributing

If you'd like to help develop the HA addon integration, please:
1. Review the [HA Addon Developer Docs](https://developers.home-assistant.io/docs/add-ons)
2. Open an issue to discuss your approach
3. Reference existing addons for examples

---

**Note:** The current Docker Compose setup provides equivalent functionality and will remain supported alongside the addon.
