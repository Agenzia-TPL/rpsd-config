#!/bin/bash

# Setup script for GitHub Copilot CLI in devcontainer
# This script installs GitHub CLI and the Copilot CLI extension
# Note: This is different from the GitHub Copilot VS Code extension
# Usage: ./scripts/setup-github-copilot.sh

set -e  # Exit on any error

echo "🔧 Setting up GitHub Copilot CLI for terminal AI assistance..."
echo "============================================================="
echo
echo "📝 Note: This installs the CLI version of GitHub Copilot for terminal use."
echo "   It's separate from the VS Code extension that provides code completions."
echo

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

# Check if GitHub Copilot CLI is already installed
if gh extension list 2>/dev/null | grep -q "gh-copilot"; then
    print_warning "GitHub Copilot CLI extension is already installed"
    read -p "Reinstall? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_status "GitHub Copilot CLI is ready to use!"
        print_status "Run 'gh auth login' if you need to authenticate with GitHub."
        exit 0
    fi
fi

# GitHub Copilot CLI doesn't require Node.js - it's a GitHub CLI extension
print_status "GitHub Copilot CLI doesn't require Node.js - proceeding with GitHub CLI setup..."

# Check if GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    print_status "Installing GitHub CLI..."
    # Install GitHub CLI
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt update
    sudo apt install gh -y
    print_success "GitHub CLI installed: $(gh --version)"
else
    print_success "GitHub CLI already installed: $(gh --version | head -n1)"
fi

# Install GitHub Copilot CLI extension
print_status "Installing GitHub Copilot CLI extension..."
gh extension install github/gh-copilot

# Verify installation
if gh extension list | grep -q "gh-copilot"; then
    print_success "GitHub Copilot CLI extension installed successfully!"
else
    print_error "GitHub Copilot CLI extension installation failed."
    exit 1
fi

# Setup instructions
echo
echo "🎉 Setup Complete!"
echo "=================="
echo
print_status "Next steps:"
echo "1. Authenticate with GitHub:"
echo -e "   ${BLUE}gh auth login${NC}"
echo
echo "2. Test Copilot CLI:"
echo -e "   ${BLUE}gh copilot suggest \"create a python function to sort a list\"${NC}"
echo -e "   ${BLUE}gh copilot explain \"git rebase -i HEAD~3\"${NC}"
echo
print_status "Common commands:"
echo -e "• ${BLUE}gh copilot suggest${NC} - Get command suggestions"
echo -e "• ${BLUE}gh copilot explain${NC} - Explain commands"
echo
print_status "For more information, visit: https://docs.github.com/en/copilot/github-copilot-in-the-cli"
echo
print_warning "Note: Requires GitHub Copilot subscription and authentication."

# Create the generic ai-context.md for team documentation (same as Claude Code script)
if [ ! -f "ai-context.md" ]; then
    print_status "Creating ai-context.md (team documentation for AI assistants)..."

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

    print_success "Created ai-context.md (shared team documentation)"
    print_status "This file can be committed for team use, or added to .gitignore if preferred"
fi

# Create GitHub Copilot specific files if VS Code integration is desired
if [ ! -d ".github" ]; then
    print_status "Creating .github directory for GitHub Copilot integration..."
    mkdir -p .github
fi

if [ ! -f ".github/copilot-instructions.md" ]; then
    print_status "Creating .github/copilot-instructions.md (for VS Code Copilot integration)..."

    cat > .github/copilot-instructions.md << 'EOF'
# GitHub Copilot Instructions

This file provides context to GitHub Copilot when working in VS Code or other supported editors.

## Project Context
This is a Python project using uv for package management with a workspace structure.

## Key Guidelines
- **IMPORTANT:** Always use `uv` commands, never `pip`, `poetry`, or `conda`
- Run `uv sync` after adding/removing dependencies
- Use `uv run pytest` to run tests
- Use `uv run ruff format` and `uv run ruff check --fix` for code quality
- For workspace projects, use `--package <member>` when targeting specific packages

## Project Structure
- `packages/` - Contains workspace member packages
- `pyproject.toml` - Workspace configuration
- `uv.lock` - Dependency lock file
- `tests/` - Test files

## Coding Standards
- Follow PEP 8 for Python code style
- Use type hints where applicable
- Write comprehensive docstrings
- Follow existing code patterns and structure

For more details, see `ai-context.md` in the project root.
EOF

    print_success "Created .github/copilot-instructions.md (for VS Code integration)"
    print_status "This enables GitHub Copilot context in VS Code and other supported editors"
fi

echo
print_status "Additional notes:"
echo "• The GitHub Copilot CLI doesn't automatically read context files"
echo "• For VS Code integration, enable custom instructions in Copilot settings"
echo "• You can manually reference ai-context.md when asking Copilot questions"
echo "• Both ai-context.md and .github/copilot-instructions.md serve the same purpose"
echo
