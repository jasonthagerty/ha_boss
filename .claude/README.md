# Claude Code Configuration

This directory contains configuration files and documentation for working with Claude Code in the HA Boss project.

## Files

### `settings.json`
Project-specific Claude Code settings including:
- Model preferences (Sonnet)
- Auto-approval settings for bash/edit/write operations
- Pre-commit hooks configuration
- Context file patterns (include/exclude)

**Note**: This file is checked into git and shared across the team.

### `mcp.json.example`
Example MCP (Model Context Protocol) server configuration for GitHub integration.

**Usage**:
1. Copy to your user-level Claude config directory:
   - Linux/Mac: `~/.config/claude/mcp.json`
   - Windows: `%APPDATA%\Claude\mcp.json`
2. Replace `ghp_your_token_here` with your actual GitHub token
3. Restart Claude Code

**Security**: Never commit the actual `mcp.json` file with real tokens!

### `GITHUB_MCP_SETUP.md`
Comprehensive guide for setting up and testing GitHub MCP server integration.

**Contents**:
- Step-by-step setup instructions
- GitHub token creation guide
- Testing procedures
- Troubleshooting common issues
- Security best practices

**When to use**: Setting up Claude Code for the first time or troubleshooting GitHub integration issues.

## Directory Purpose

The `.claude/` directory serves as the central configuration location for:

1. **Project Settings**: Shared team preferences (checked into git)
2. **Examples**: Reference configurations (checked into git)
3. **Documentation**: Setup and usage guides (checked into git)
4. **User Secrets**: Personal configuration files (NOT checked into git)

## What Gets Committed?

✅ **Committed to Git**:
- `settings.json` - Project settings
- `*.example` - Example configurations
- `*.md` - Documentation files
- `README.md` - This file

❌ **NOT Committed (in .gitignore)**:
- `mcp.json` - Contains GitHub token (secret)
- Any files with actual credentials

## Getting Started

If you're new to this project:

1. Read `../CLAUDE.md` for complete project documentation
2. Follow `GITHUB_MCP_SETUP.md` to set up GitHub integration
3. Review `settings.json` to understand project preferences
4. Copy `mcp.json.example` to your user config and configure

## Additional Resources

- **Main Documentation**: `../CLAUDE.md`
- **Slash Commands**: See `../CLAUDE.md` section "Slash Commands"
- **Project Structure**: See `../CLAUDE.md` section "Architecture"
- **Development Workflow**: See `../CLAUDE.md` section "Feature Branch Workflow"
