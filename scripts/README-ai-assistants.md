# AI Development Assistants Setup

This directory contains setup scripts for various AI-powered development assistants that can be optionally installed in the devcontainer environment.

## Available Assistants

### 🤖 Claude Code
**File:** `setup-claude-code.sh`
**What it does:** Installs Node.js via nvm and Claude Code CLI for AI-assisted coding
**Requirements:** Anthropic API access
**Best for:** Code generation, refactoring, debugging, and conversational programming

```bash
./scripts/setup-claude-code.sh
```

### 🐙 GitHub Copilot CLI
**File:** `setup-github-copilot.sh`
**What it does:** Installs GitHub CLI and Copilot CLI extension
**Requirements:** GitHub Copilot subscription
**Best for:** Command suggestions and explanations in terminal

```bash
./scripts/setup-github-copilot.sh
```

## Usage Philosophy

These scripts are **completely optional** and designed for individual developer preference:

- ✅ **Zero impact** on team members who don't want to use AI assistants
- ✅ **No changes** to the base devcontainer configuration
- ✅ **Easy sharing** - colleagues can use the same scripts when they're ready
- ✅ **Manual execution** - install only what you need, when you need it

## General Setup Pattern

1. **After devcontainer starts:** Run any setup script you want
2. **Authenticate:** Each tool requires its own authentication
3. **Start coding:** Tools integrate with your existing workflow
4. **Optional sharing:** Share your `ai-context.md` file for better AI assistance

## Creating AI Context

Consider creating an `ai-context.md` file (or similar) that helps AI assistants understand your project:

```markdown
# Project Development Context

## Overview
[Brief description of your project]

## Architecture
[Key architectural decisions and patterns]

## Coding Standards
[Style guides, conventions, best practices]

## Common Tasks
[Frequent development workflows]
```

This file can benefit any team member using any AI assistant.

## Adding New Assistants

To add support for other AI tools, follow this pattern:

1. **Create setup script:** `setup-{tool-name}.sh`
2. **Use consistent structure:** Error handling, colored output, verification
3. **Include usage instructions:** Show next steps after installation
4. **Update this README:** Add entry to the available assistants list

### Template Structure
```bash
#!/bin/bash
set -e

# Tool-specific setup logic
# - Check prerequisites
# - Install dependencies
# - Install the tool
# - Verify installation
# - Show next steps
```

## Notes

- **Persistence:** Installations persist until devcontainer rebuild
- **Authentication:** Usually needs to be done once per container
- **Performance:** Minimal impact on container size/startup time
- **Compatibility:** Scripts designed for Microsoft devcontainer Python images

---

*These tools are optional developer productivity enhancements. The project builds and runs perfectly without any AI assistants.*
