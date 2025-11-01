# HA Boss - Setup Guide

Complete guide to setting up the HA Boss development infrastructure and integrations.

## Initial Development Setup

### 1. Clone and Install

```bash
# Clone the repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Or use make
make install
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your Home Assistant details
# HA_URL=http://your-ha-instance:8123
# HA_TOKEN=your_token_here
```

### 3. Verify Installation

```bash
# Run basic tests
make test

# Run CI checks
make ci-check
```

## GitHub Integration Setup

### 1. Create GitHub Repository

```bash
# Initialize git (if not already done)
git init
git add .
git commit -m "Initial commit: development infrastructure"

# Add remote and push
git remote add origin https://github.com/jasonthagerty/ha_boss.git
git branch -M main
git push -u origin main
```

### 2. Configure GitHub Labels

```bash
# Install GitHub CLI if needed
# https://cli.github.com/

# Sync labels from configuration
gh label sync -f .github/labels.yml
```

### 3. Set Up GitHub Secrets

Add the following secrets to your repository (Settings → Secrets and variables → Actions):

- `ANTHROPIC_API_KEY`: Your Claude API key for GitHub Actions

```bash
# Using GitHub CLI
gh secret set ANTHROPIC_API_KEY
# Then paste your API key when prompted
```

### 4. Install Claude Code GitHub App

**Option 1: Via Claude Code CLI (Recommended)**
```bash
# In Claude Code terminal
/install-github-app
```

**Option 2: Manual Installation**
1. Visit https://github.com/apps/claude
2. Click "Install"
3. Select your repository
4. Grant required permissions:
   - Read access to metadata
   - Read and write access to code, issues, and pull requests

## GitHub Projects Setup

### 1. Create Project

1. Go to your repository on GitHub
2. Click "Projects" tab → "New Project"
3. Choose "Board" template
4. Name it "HA Boss Development"

### 2. Configure Project Views

**Board View (Default)**:
- Columns: Backlog, Todo, In Progress, In Review, Done
- Group by: Status
- Filter by labels for specialized views

**Backlog View**:
- Filter: `is:issue is:open -label:in-progress`
- Sort by: Priority (use priority labels)

**Claude Tasks View**:
- Filter: `is:open label:claude-task`
- Shows all tasks assigned to Claude

### 3. Automation

Add these workflows to your project:

1. **Auto-add items**:
   - When: Issue is created or PR is opened
   - Then: Add to project in "Backlog"

2. **Auto-move to In Progress**:
   - When: Issue is assigned or PR is in draft
   - Then: Move to "In Progress"

3. **Auto-move to In Review**:
   - When: PR is ready for review
   - Then: Move to "In Review"

4. **Auto-close**:
   - When: Issue is closed or PR is merged
   - Then: Move to "Done"

### 4. Link Project to Repository

```bash
# Edit repository settings
# Settings → Features → Check "Projects"
```

## Claude Code Remote Development

### Option 1: VS Code DevContainer (Local Docker)

1. Install Docker Desktop
2. Install "Dev Containers" extension in VS Code
3. Open repository in VS Code
4. Click "Reopen in Container" when prompted
5. Container will build with Python 3.11 and all dependencies

### Option 2: GitHub Codespaces (Cloud)

1. Go to repository on GitHub
2. Click "Code" → "Codespaces" → "New codespace"
3. Wait for environment to build
4. Development environment ready in browser or VS Code

### Option 3: Claude Code Web

1. Visit https://claude.com/code
2. Connect to GitHub repository
3. Claude Code will use the `.devcontainer` configuration
4. Full development environment available in browser

## CI/CD Verification

### 1. Test CI Pipeline

Create a test branch and push:

```bash
git checkout -b test/ci-pipeline
# Make a small change
echo "# Test" >> README.md
git add README.md
git commit -m "test: verify CI pipeline"
git push -u origin test/ci-pipeline
```

Check that CI runs:
- Go to Actions tab
- Verify "CI" workflow runs
- All checks should pass

### 2. Test Claude Integration

Create a test issue:

1. Go to Issues → New Issue
2. Use "Bug Report" or "Feature Request" template
3. In the issue description, add: `@claude please analyze this`
4. Submit issue

Claude should respond within a few minutes.

### 3. Test Automated Issue Creation

Force a CI failure:

```bash
# Create failing test
cat > tests/test_fail.py << 'EOF'
def test_will_fail():
    assert False, "This test intentionally fails"
EOF

git add tests/test_fail.py
git commit -m "test: verify CI failure handling"
git push origin main
```

Check that:
- CI fails
- Issue is automatically created
- Issue has `ci-failure` and `claude-task` labels
- Issue mentions `@claude`

Clean up:
```bash
git rm tests/test_fail.py
git commit -m "test: remove failing test"
git push origin main
```

## Pre-commit Hooks (Optional)

Install pre-commit hooks for automatic code quality checks:

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Test hooks
pre-commit run --all-files
```

Now hooks run automatically before each commit.

## Verification Checklist

- [ ] Repository created on GitHub
- [ ] GitHub labels synchronized
- [ ] `ANTHROPIC_API_KEY` secret added
- [ ] Claude GitHub App installed
- [ ] CI pipeline runs successfully
- [ ] GitHub Project created and linked
- [ ] Project automation configured
- [ ] DevContainer works (if using)
- [ ] Test issue with `@claude` works
- [ ] CI failure creates issue automatically
- [ ] Pre-commit hooks installed (optional)

## Troubleshooting

### Claude doesn't respond to @claude mentions

- Verify Claude GitHub App is installed
- Check `ANTHROPIC_API_KEY` secret is set
- Ensure `.github/workflows/claude.yml` is present
- Check Actions tab for workflow errors

### CI doesn't run

- Verify `.github/workflows/ci.yml` exists
- Check branch protection rules
- Ensure Actions are enabled in repository settings

### Tests fail locally

```bash
# Verify Python version
python --version  # Should be 3.11+

# Reinstall dependencies
pip install -e ".[dev]"

# Clear cache and retry
make clean
make test
```

## Next Steps

1. Read [CLAUDE.md](CLAUDE.md) for architecture and development guidelines
2. Review [CONTRIBUTING.md](CONTRIBUTING.md) for contribution workflow
3. Explore custom slash commands in `.claude/commands/`
4. Start planning your Home Assistant management features!

## Support

- **Documentation**: See CLAUDE.md and README.md
- **Issues**: https://github.com/jasonthagerty/ha_boss/issues
- **Claude Code Docs**: https://docs.claude.com/claude-code
