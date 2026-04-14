#!/bin/bash

# Setup script for Claude Code in devcontainer
# This script installs Claude Code using the native installer
# Usage: ./ai-scripts/setup-claude-code.sh

set -e  # Exit on any error

# Pin to v2.1.89 — later versions have a broken auth paste flow in
# devcontainer terminals (bracketed paste not handled).
# See: https://github.com/anthropics/claude-code/issues/47745
# Update this once the upstream bug is fixed.
CLAUDE_VERSION="2.1.89"

echo "🔧 Setting up Claude Code for AI-assisted development..."
echo "=================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in a devcontainer
if [ ! -f /.dockerenv ] && [ "$DEVCONTAINER" != "true" ]; then
    print_warning "This script is designed for devcontainer environments."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check if Claude Code is already installed
if command -v claude &> /dev/null; then
    CURRENT_VERSION=$(claude --version 2>/dev/null || echo "unknown")
    print_warning "Claude Code is already installed (version: $CURRENT_VERSION)"
    read -p "Reinstall? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_status "Claude Code is ready to use!"
        print_status "Run 'claude auth' if you need to authenticate."
        exit 0
    fi
fi

# Check that curl is available
if ! command -v curl &> /dev/null; then
    print_error "curl is required but not installed."
    exit 1
fi

# Install Claude Code using the native installer
print_status "Installing Claude Code v${CLAUDE_VERSION}..."
curl -fsSL https://claude.ai/install.sh | bash -s "$CLAUDE_VERSION"

# Verify installation
print_status "Verifying Claude Code installation..."
if command -v claude &> /dev/null; then
    CLAUDE_VERSION=$(claude --version 2>/dev/null || echo "unknown")
    print_success "Claude Code installed successfully! Version: $CLAUDE_VERSION"
else
    print_error "Claude Code binary not found after installation."
    print_status "You may need to restart your shell or source your profile."
    exit 1
fi

# Create sample context files if they don't exist
print_status "Setting up Claude Code context files..."

# Create .claude directory if it doesn't exist
mkdir -p .claude

# Create local settings file for project-specific, non-committed settings
if [ ! -f ".claude/settings.local.json" ]; then
    print_status "Creating .claude/settings.local.json..."

    cat > .claude/settings.local.json << 'EOF'
{
  "permissions": {
    "allow": [
      "Edit",
      "Bash(uv run pytest)",
      "Bash(uv run ruff format)",
      "Bash(uv run ruff check)",
      "Bash(uv sync)",
      "Bash(uv add:*)",
      "Bash(uv remove:*)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Read",
      "WebSearch",
      "Fetch",
      "Fetch(domain:*)"
    ]
  }
}
EOF
    print_success "Created .claude/settings.local.json (git-ignored)"
fi

# Create CLAUDE.local.md - this is git-ignored and personal to each developer
if [ ! -f "CLAUDE.local.md" ]; then
    print_status "Creating CLAUDE.local.md (personal, git-ignored)..."

    cat > CLAUDE.local.md << 'EOF'
# Personal Claude Code Context

## Shared Project Context
Read @ai-context.md for shared project context and development guidelines.

## Personal Instructions for Claude Code
- **FIRST:** Always read @ai-context.md for current project guidelines
- Follow all instructions in the shared context file

## Personal Notes
<!-- Add your own project-specific notes, overrides, or customizations here -->
<!-- Examples:
- Personal preferences for code organization
- Notes about specific parts of the codebase you're working on
- Reminders about debugging approaches that work well for you
- Personal shortcuts or aliases you use
-->

---
*This file is personal to you and git-ignored. Add your own customizations above.*
*All shared project context is in ai-context.md (which may or may not be committed).*
EOF

    print_success "Created CLAUDE.local.md (personal, git-ignored)"
fi

# Ensure .gitignore includes the local files
print_status "Updating .gitignore to exclude Claude Code local files..."

# Create .gitignore if it doesn't exist
touch .gitignore

# Add Claude Code local files to .gitignore if not already present
if ! grep -q "CLAUDE.local.md" .gitignore; then
    echo "" >> .gitignore
    echo "# Claude Code local files (personal, not shared)" >> .gitignore
    echo "CLAUDE.local.md" >> .gitignore
    echo ".claude/settings.local.json" >> .gitignore
    print_success "Added Claude Code local files to .gitignore"
else
    print_status "Claude Code local files already in .gitignore"
fi

# Create the generic ai-context.md for team documentation (optional)
if [ ! -f "ai-context.md" ]; then
    print_status "Creating ai-context.md (optional team documentation)..."

    cat > ai-context.md << 'EOF'
# AI Development Assistant Context

This file provides context for AI development assistants (Claude Code, GitHub Copilot, etc.) working on this project.

## Project Overview
<!-- Brief description of your project -->
This is a Python project using uv for package management...

## Technology Stack
- **Language:** Python 3.11+
- **Package Manager:** uv
- **Project Structure:** uv workspace with packages in `packages/` folder
- **Testing:** pytest
- **Linting/Formatting:** ruff

## Development Environment
- **Containerization:** Docker + devcontainers
- **Package Management:** uv (not pip/poetry/conda)

## Coding Standards
- Follow PEP 8 for Python code style
- Use type hints where applicable
- Use ruff for formatting and linting
- Write docstrings for all public functions and classes

## Common Development Commands (for AI assistants)
- `uv sync` - Install/update all dependencies
- `uv add <package>` - Add a dependency
- `uv run pytest` - Run tests
- `uv run ruff format` - Format code
- `uv run ruff check --fix` - Auto-fix linting issues

## Project Structure (uv workspace)
```
project-root/
├── pyproject.toml       # Workspace configuration
├── uv.lock             # Lock file
├── packages/           # Workspace members
│   ├── package-a/      # Individual package
│   └── package-b/      # Another package
├── tests/              # Test files
└── README.md           # Project documentation
```

## Guidelines for AI Assistants
- **IMPORTANT:** Always use `uv` commands, never `pip`, `poetry`, or `conda`
- Run `uv sync` after adding/removing dependencies
- Use `uv run pytest` to run tests after making changes
- Use `uv run ruff format` and `uv run ruff check --fix` for code quality
- For workspace projects, use `--package <member>` when targeting specific packages
- Follow existing code patterns and structure
- Consider security implications of changes
- Write comprehensive documentation

---
*This file can be used by any AI coding assistant to understand the project context.*
*Individual developers may have their own tool-specific context files (e.g., CLAUDE.local.md)*
EOF

    print_success "Created ai-context.md (optional team documentation)"
    print_status "This file can be committed for team use, or added to .gitignore if preferred"
fi

echo

# Setup instructions
echo
echo "🎉 Setup Complete!"
echo "=================="
echo
print_status "Next steps:"
echo "1. Authenticate with Claude Code:"
echo -e "   ${BLUE}claude auth${NC}"
echo
echo "2. Initialize Claude Code in your project (optional):"
echo -e "   ${BLUE}claude init${NC}"
echo
echo "3. Start coding with AI assistance:"
echo -e "   ${BLUE}claude${NC}"
echo
print_status "For more information, visit: https://docs.anthropic.com/en/docs/claude-code"
echo
print_warning "Note: Your authentication will be specific to this devcontainer."
print_warning "You may need to re-authenticate if you rebuild the container."
echo
print_status "Quick tips:"
echo "• Claude automatically finds CLAUDE.local.md files (git-ignored)"
echo "• Use /init command to let Claude analyze your project"
echo "• Use /clear command to start fresh conversations"
echo "• Use /config to manage Claude Code settings"
echo "• Your CLAUDE.local.md is personal and won't affect other developers"
echo "• Version is pinned to v${CLAUDE_VERSION} due to an upstream auth bug"
