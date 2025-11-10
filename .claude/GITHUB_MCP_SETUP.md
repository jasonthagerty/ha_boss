# GitHub MCP Server Setup & Testing Guide

This guide walks through setting up and testing the GitHub MCP server for HA Boss.

## Quick Setup Checklist

- [ ] Node.js installed (for `npx`)
- [ ] GitHub Personal Access Token created with `repo` and `issues` scopes
- [ ] MCP configuration file created in user config directory
- [ ] Claude Code restarted to load MCP configuration
- [ ] Test issue creation successful

## Step-by-Step Setup

### 1. Install Node.js (if not installed)

```bash
# Check if Node.js is installed
node --version
npx --version

# If not installed:
# macOS
brew install node

# Ubuntu/Debian
sudo apt update && sudo apt install nodejs npm

# Windows
# Download from https://nodejs.org/
```

### 2. Create GitHub Personal Access Token

1. Go to https://github.com/settings/tokens
2. Click "Generate new token (classic)"
3. Name: `Claude Code MCP - HA Boss`
4. Select scopes:
   - ✅ `repo` (Full control of private repositories)
   - ✅ `issues` (Access issues)
   - ✅ `workflow` (Update GitHub Action workflows - optional)
5. Set expiration (recommend 90 days and rotate)
6. Click "Generate token"
7. **IMPORTANT**: Copy token immediately - you cannot view it again!

### 3. Configure MCP Server

**Linux/Mac:**
```bash
# Create config directory if it doesn't exist
mkdir -p ~/.config/claude

# Create MCP configuration file
cat > ~/.config/claude/mcp.json << 'EOF'
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "ghp_your_actual_token_here"
      }
    }
  }
}
EOF

# Edit the file and replace the placeholder token
nano ~/.config/claude/mcp.json
```

**Windows (PowerShell):**
```powershell
# Create config directory if it doesn't exist
New-Item -Path "$env:APPDATA\Claude" -ItemType Directory -Force

# Create MCP configuration file
@"
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "ghp_your_actual_token_here"
      }
    }
  }
}
"@ | Out-File -FilePath "$env:APPDATA\Claude\mcp.json" -Encoding UTF8

# Edit the file and replace the placeholder token
notepad "$env:APPDATA\Claude\mcp.json"
```

### 4. Restart Claude Code

- If using Claude Code CLI: Exit and restart
- If using Claude Code in browser: Refresh the page
- If using Claude Desktop: Quit and relaunch

### 5. Verify MCP Tools Are Available

Once Claude Code restarts, you should have access to GitHub tools. You can verify by asking Claude:

```
"What GitHub tools do you have access to?"
```

Expected response should list tools like:
- `create_issue`
- `update_issue`
- `create_pull_request`
- `add_comment`
- etc.

## Testing Issue Creation

### Test 1: Simple Issue Creation

Ask Claude Code:

```
"Create a test GitHub issue in the ha_boss repository titled 'Test: MCP Integration' with the following body:

This is a test issue to verify GitHub MCP server integration is working correctly.

Label it with 'test' and 'documentation'."
```

**Expected Result:**
- Issue created successfully
- Returns issue number (e.g., #26)
- Issue visible at https://github.com/jasonthagerty/ha_boss/issues

### Test 2: Issue with Multiple Labels

```
"Create an issue titled 'feat: add automated health reports' with labels 'enhancement', 'phase-2', and 'claude-task'."
```

**Expected Result:**
- Issue created with all specified labels
- Properly formatted issue

### Test 3: Add Comment to Existing Issue

```
"Add a comment to issue #XX saying 'GitHub MCP integration test successful!'"
```

**Expected Result:**
- Comment appears on the specified issue

### Test 4: Create Issue from Code Context

```
"I found a bug where the config validation doesn't handle empty strings properly. Create an issue documenting this with appropriate labels."
```

**Expected Result:**
- Claude analyzes the bug
- Creates well-formatted issue with:
  - Clear title
  - Detailed description
  - Reproduction steps
  - Appropriate labels (bug, priority)

## Troubleshooting

### Error: "GitHub MCP server not found"

**Cause**: `npx` not available or Node.js not installed

**Solution**:
```bash
# Verify Node.js installation
node --version
npx --version

# If not installed, install Node.js (see step 1)
```

### Error: "Authentication failed"

**Cause**: Invalid or expired GitHub token, or insufficient scopes

**Solution**:
1. Verify token in `~/.config/claude/mcp.json` is correct (no extra spaces)
2. Check token hasn't been revoked at https://github.com/settings/tokens
3. Ensure token has `repo` and `issues` scopes
4. Generate new token if needed and update config

### Error: "Permission denied to repository"

**Cause**: Token doesn't have access to the ha_boss repository

**Solution**:
1. Ensure token was created from an account with write access to the repository
2. For organization repos, ensure token has organization access enabled
3. Check repository isn't archived or read-only

### MCP configuration not loading

**Cause**: Config file in wrong location or syntax error

**Solution**:
```bash
# Verify config file exists
# Linux/Mac
ls -la ~/.config/claude/mcp.json
cat ~/.config/claude/mcp.json | python -m json.tool  # Validate JSON

# Windows
dir $env:APPDATA\Claude\mcp.json
Get-Content "$env:APPDATA\Claude\mcp.json" | ConvertFrom-Json  # Validate JSON

# Check for common issues:
# - Trailing commas in JSON
# - Incorrect token format (should start with ghp_)
# - Wrong file encoding (should be UTF-8)
```

### First connection slow

**Cause**: `npx` downloading the GitHub MCP server package on first use

**Solution**: This is normal. Subsequent connections will be faster as the package is cached.

## Security Best Practices

1. **Token Storage**:
   - Never commit the actual `mcp.json` to git (already in .gitignore)
   - Use file permissions to restrict access:
     ```bash
     chmod 600 ~/.config/claude/mcp.json
     ```

2. **Token Rotation**:
   - Rotate tokens every 90 days
   - Immediately revoke tokens if compromised
   - Use separate tokens for different environments (local vs CI)

3. **Scope Minimization**:
   - Only grant necessary scopes (`repo`, `issues`)
   - Avoid granting admin or delete permissions unless absolutely needed

4. **Audit Trail**:
   - Review token activity at https://github.com/settings/tokens
   - Monitor repository audit log for unexpected actions

## Alternative: Using GitHub CLI

If you prefer not to use MCP, you can use the GitHub CLI (`gh`):

```bash
# Install gh
brew install gh  # macOS
# or see https://cli.github.com/ for other platforms

# Authenticate
gh auth login

# Create issue
gh issue create --title "Title" --body "Body" --label "bug"
```

**Note**: The GitHub CLI may not be available in all environments (containers, CI/CD). MCP is recommended for consistent cross-environment support.

## Success Criteria

You've successfully set up GitHub MCP when:
- ✅ Claude Code can create issues without errors
- ✅ Created issues appear in GitHub repository
- ✅ Labels are applied correctly
- ✅ Comments can be added to existing issues
- ✅ No authentication errors in Claude Code logs

## Next Steps

Once GitHub MCP is working:
1. Test automated CI failure issue creation
2. Use Claude to triage and manage existing issues
3. Automate PR creation and review workflows
4. Integrate with project board automation

## References

- GitHub MCP Server: https://github.com/modelcontextprotocol/servers/tree/main/src/github
- MCP Documentation: https://modelcontextprotocol.io/
- GitHub API: https://docs.github.com/en/rest
- Claude Code Docs: https://docs.claude.com/en/docs/claude-code
