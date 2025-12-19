# Wiki Upload Guide

This guide explains how to upload the documentation from `docs/wiki/` to the GitHub Wiki.

## Overview

The wiki documentation has been reorganized from the main repository into separate, focused pages:

- **Home.md** - Wiki landing page with navigation
- **Installation.md** - Complete installation guide (Docker + local)
- **CLI-Commands.md** - Comprehensive CLI reference
- **Configuration.md** - All configuration options
- **Architecture.md** - System design and components
- **AI-Features.md** - LLM integration and capabilities
- **Development.md** - Contributing and testing guide
- **Troubleshooting.md** - Common issues and solutions

## Upload Methods

### Method 1: GitHub Web Interface (Recommended)

1. **Clone the wiki repository:**
   ```bash
   git clone https://github.com/jasonthagerty/ha_boss.wiki.git
   cd ha_boss.wiki
   ```

2. **Copy wiki files:**
   ```bash
   cp ../ha_boss/docs/wiki/*.md .
   ```

3. **Commit and push:**
   ```bash
   git add .
   git commit -m "docs: comprehensive wiki documentation

   - Add concise Home page with navigation
   - Add detailed Installation guide
   - Add complete CLI Commands reference
   - Add Configuration reference
   - Add Architecture documentation
   - Add AI Features guide
   - Add Development guide
   - Add Troubleshooting guide

   Reorganized from 697-line README to focused wiki pages."
   git push origin master
   ```

### Method 2: GitHub Web UI (Alternative)

1. Go to https://github.com/jasonthagerty/ha_boss/wiki
2. Click "Create the first page" or "New Page"
3. For each file in `docs/wiki/`:
   - Create a new page with the filename (without .md)
   - Copy the content from the file
   - Save the page

**Page order to create:**
1. Home (this becomes the landing page)
2. Installation
3. CLI-Commands
4. Configuration
5. Architecture
6. AI-Features
7. Development
8. Troubleshooting

## Verification

After uploading, verify:

1. **Navigation works:**
   - All links in Home.md work correctly
   - Cross-references between pages work

2. **Formatting is correct:**
   - Code blocks render properly
   - Tables display correctly
   - Diagrams show up

3. **Images (if any):**
   - Upload images to wiki
   - Update image paths if needed

## Updating the Wiki

To update wiki content in the future:

```bash
# 1. Edit files in docs/wiki/
vim docs/wiki/Configuration.md

# 2. Clone wiki if not already cloned
git clone https://github.com/jasonthagerty/ha_boss.wiki.git wiki-repo

# 3. Copy updated files
cp docs/wiki/*.md wiki-repo/

# 4. Commit and push
cd wiki-repo
git add .
git commit -m "docs: update configuration guide"
git push origin master
```

## Link Updates

After uploading, you may need to update links in the main repository:

- **README.md** - Wiki links are already correct
- **CONTRIBUTING.md** - Update if it references old locations
- **Issue templates** - Update documentation links

## Sidebar (Optional)

Create a `_Sidebar.md` file in the wiki repo for easy navigation:

```markdown
## HA Boss Wiki

**Getting Started**
- [Home](Home)
- [Installation](Installation)
- [Configuration](Configuration)

**Usage**
- [CLI Commands](CLI-Commands)
- [AI Features](AI-Features)

**Technical**
- [Architecture](Architecture)
- [Development](Development)
- [Troubleshooting](Troubleshooting)
```

## Notes

- Wiki pages use GitHub-flavored markdown
- The wiki is a separate git repository
- Changes to wiki don't require PRs (direct push to master)
- Wiki has its own git history separate from main repo
- Page names should match filenames without .md extension

## Maintenance

Keep the wiki in sync with code changes:

1. Update `docs/wiki/` files in main repo
2. Push wiki updates when releasing new versions
3. Review wiki for accuracy during major releases
4. Keep CLI-Commands.md in sync with actual commands
5. Update Configuration.md when adding new options

---

**Questions?** See [GitHub Wiki Documentation](https://docs.github.com/en/communities/documenting-your-project-with-wikis/about-wikis)
