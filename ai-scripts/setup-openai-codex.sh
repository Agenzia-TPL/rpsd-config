#!/bin/bash

# Setup script for OpenAI Codex CLI in devcontainer
# This script installs Node.js via nvm and then installs the Codex CLI,
# then creates the AGENTS.md and ai-project.md context files if absent.
# Usage: ./ai-scripts/setup-openai-codex.sh

set -e  # Exit on any error

echo "Setting up OpenAI Codex CLI for AI-assisted development..."
echo "==========================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

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

# Check if Codex CLI is already installed
if command -v codex &> /dev/null; then
    CURRENT_VERSION=$(codex --version 2>/dev/null || echo "unknown")
    print_warning "Codex CLI is already installed (version: $CURRENT_VERSION)"
    read -p "Reinstall? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_status "Codex CLI is ready to use!"
        print_status "Run 'codex auth' if you need to authenticate."
        exit 0
    fi
fi

# Source nvm to make sure it's available in this script
if [ -s "/usr/local/share/nvm/nvm.sh" ]; then
    . /usr/local/share/nvm/nvm.sh
    print_status "Found nvm at /usr/local/share/nvm/nvm.sh"
elif [ -s "$HOME/.nvm/nvm.sh" ]; then
    export NVM_DIR="$HOME/.nvm"
    . "$NVM_DIR/nvm.sh"
    [ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
    print_status "Found nvm at $HOME/.nvm/nvm.sh"
else
    print_error "nvm is not available at expected locations."
    print_error "Tried: /usr/local/share/nvm/nvm.sh and $HOME/.nvm/nvm.sh"
    print_error "Make sure you're using a devcontainer image that includes nvm."
    exit 1
fi

if ! command -v nvm &> /dev/null; then
    print_error "nvm command is still not available after sourcing."
    exit 1
fi

# Ensure Node.js is available
if command -v node &> /dev/null && command -v npm &> /dev/null; then
    NODE_VERSION=$(node --version)
    NPM_VERSION=$(npm --version)
    print_success "Node.js already available: $NODE_VERSION"
    print_success "npm already available: $NPM_VERSION"

    print_status "Updating npm to latest version..."
    npm install -g npm@latest
    hash -r 2>/dev/null || true
    NEW_NPM_VERSION=$(npm --version)
    print_success "npm updated from $NPM_VERSION to $NEW_NPM_VERSION"
else
    print_status "Installing Node.js (latest LTS)..."
    nvm install --lts
    nvm use --lts

    NODE_VERSION=$(node --version)
    NPM_VERSION=$(npm --version)
    print_success "Node.js installed: $NODE_VERSION"
    print_success "npm installed: $NPM_VERSION"

    print_status "Updating npm to latest version..."
    npm install -g npm@latest
    hash -r 2>/dev/null || true
    NEW_NPM_VERSION=$(npm --version)
    print_success "npm updated to: $NEW_NPM_VERSION"
fi

# Install Codex CLI
print_status "Installing OpenAI Codex CLI..."
npm install -g @openai/codex

sleep 1
hash -r 2>/dev/null || true

# Verify installation
print_status "Verifying Codex CLI installation..."
CODEX_INSTALLED=false

if npm list -g @openai/codex &> /dev/null; then
    print_success "Codex CLI package is installed in npm global packages"

    NPM_PREFIX=$(npm config get prefix 2>/dev/null || echo "/usr/local")
    POSSIBLE_PATHS=(
        "$NPM_PREFIX/bin/codex"
        "$(dirname $(which npm))/codex"
        "/usr/local/bin/codex"
    )

    print_status "Checking for codex binary in common locations..."
    for path in "${POSSIBLE_PATHS[@]}"; do
        if [ -f "$path" ] && [ -x "$path" ]; then
            CODEX_INSTALLED=true
            print_success "Found Codex binary at: $path"
            if "$path" --version &> /dev/null; then
                CODEX_VERSION=$("$path" --version 2>/dev/null || echo "unknown")
                print_success "Binary is working! Version: $CODEX_VERSION"
            fi
            break
        fi
    done
fi

if command -v codex &> /dev/null; then
    CODEX_INSTALLED=true
    CODEX_VERSION=$(codex --version 2>/dev/null || echo "installed")
    print_success "codex command is available in PATH! Version: $CODEX_VERSION"
fi

if [ "$CODEX_INSTALLED" = false ]; then
    print_warning "Codex package was installed by npm, but the binary is not accessible."
    print_status "This is often a PATH issue in devcontainer environments."
    print_status "npm prefix: $(npm config get prefix 2>/dev/null || echo 'unknown')"
    print_status "Try: find /usr/local -name 'codex' 2>/dev/null"
fi

# Create context files
print_status "Setting up AI context files..."

# AGENTS.md — committed to the repo, generic, no project specifics
# This is the entry point for all agent-based tools (Codex, Amp, Cursor, Jules, etc.)
if [ ! -f "AGENTS.md" ]; then
    print_status "Creating AGENTS.md (generic agent entry point, committed to repo)..."

    cat > AGENTS.md << 'EOF'
# AGENTS.md

This file provides instructions for AI coding agents working in this repository
(OpenAI Codex, Amp, Cursor, Jules, Factory, and others).

## Project Context

Read `ai-context.md` in this repository for development guidelines, coding
standards, tool conventions, and common commands for this type of project.
EOF

    print_success "Created AGENTS.md (commit this file to share with the team)"
else
    print_status "AGENTS.md already exists, skipping."
fi

# ai-project.md — committed, project-specific
if [ ! -f "ai-project.md" ]; then
    print_status "Creating ai-project.md (project-specific context, committed to repo)..."

    cat > ai-project.md << 'EOF'
# Project Context

This file provides project-specific context for AI coding assistants.
Edit this file to describe your specific project.

## Project Overview

<!-- Describe what this project does and its purpose -->

## Technology Stack

<!-- List your main language, frameworks, package manager, test runner, linter, etc. -->
<!-- Example:
- **Language:** Python 3.13+
- **Package Manager:** uv (not pip/poetry/conda)
- **Testing:** pytest
- **Linting/Formatting:** ruff
-->

## Development Environment

<!-- Containerization, OS, etc. -->
<!-- Example:
- **Containerization:** Docker + devcontainers
-->

## Project Structure

```
project-root/
├── src/          # Source code
├── tests/        # Tests
└── README.md     # Project documentation
```

## Common Development Commands

<!-- List the commands AI assistants should use -->
<!-- Example:
- `uv sync` - Install/update all dependencies
- `uv run pytest` - Run tests
- `uv run ruff format` - Format code
- `uv run ruff check --fix` - Auto-fix linting issues
-->

## Coding Standards

<!-- Language-specific conventions and rules -->
<!-- Example:
- Follow PEP 8 for Python code style
- Use type hints where applicable
- Lines max 88 characters
-->

## Project-Specific Guidelines

<!-- Any rules or conventions specific to this project -->
<!-- Example: specific naming conventions, domain terminology, etc. -->

---
*For generic AI assistant guidelines and behavior, see `ai-context.md`.*
EOF

    print_success "Created ai-project.md (edit this file to describe your project)"
else
    print_status "ai-project.md already exists, skipping."
fi

# ai-context.md — committed, generic guidelines
if [ ! -f "ai-context.md" ]; then
    print_status "Creating ai-context.md (generic guidelines, committed to repo)..."

    cat > ai-context.md << 'EOF'
# AI Development Assistant Context

This file provides context for AI development assistants working on this project.

## Project Overview

See `ai-project.md` for project description, technology stack, and conventions.

## Guidelines for AI Assistants

### Optional Documentation Files

The project may include these optional documentation files. When present, AI assistants **MUST keep them updated** with relevant changes:

#### `ai-project.md` - Project Planning Document (Optional)
If this file exists:
- Treat it as a **project planning and decision document**, not implementation documentation
- It documents **problems, proposed solutions, and expected outcomes** BEFORE implementation
- When updating it after implementing features, use **planning language**:
  - "**Problem**" (present tense, not "Original Problem")
  - "**Proposed Solution**" (not "Implemented Solution")
  - "we'll do X" or "create Y" (future/intent, not past tense)
  - "**Expected outcome**" (not "Result")
- Keep entries **succinct** - this is a decision log, not detailed documentation
- This file captures **what** and **why**, not **how** (implementation details go in code/docs)

#### `ARCHITECTURE.md` - Technical Architecture Documentation (Optional)
If this file exists:
- Documents the **system architecture** and technical design decisions
- **Must be updated** when adding components, changing data flow, or modifying core abstractions

#### `USAGE.md` - User Guide and Usage Documentation (Optional)
If this file exists:
- Documents **how to use** the application from a user's perspective
- **Must be updated** when adding commands, changing behavior, or modifying configuration

### Git Commit Policy
**CRITICAL: NEVER create git commits without EXPLICIT user permission!**

- **ALWAYS** stage changes with `git add` but STOP before committing
- **ALWAYS** show the user what will be committed using `git status` and `git diff --cached`
- **ALWAYS** present a proposed commit message for review
- **WAIT** for explicit user approval before running `git commit`
- If user says "commit this" or "create a commit", that counts as explicit permission

### Development Guidelines
- Follow existing code patterns and structure
- Consider security implications of changes
- Write documentation for non-obvious decisions
- Add trailing newlines to all files

### Research Guidelines
Always do a web search if your knowledge of a specific subject is old or uncertain — never guess or invent.
If doubts persist, ask the user for guidance on how to proceed.

### Session Start
- Read `ai-project.md` for project-specific context, conventions, and current scope

### Before Finishing a Session
- **`ai-project.md`** — May propose updates but must respect planning language; always ask for approval
- **`ARCHITECTURE.md`** — If implementation details changed significantly, suggest updating
- Do NOT update any of these files silently — show proposed changes and ask for approval

---
*This file is generic and reusable across projects.*
*Project-specific context (stack, commands, conventions) is in `ai-project.md`.*
EOF

    print_success "Created ai-context.md (generic, reusable)"
else
    print_status "ai-context.md already exists, skipping."
fi

# Update .gitignore
print_status "Updating .gitignore for Codex local files..."

touch .gitignore

if ! grep -q "AGENTS.override.md" .gitignore; then
    echo "" >> .gitignore
    echo "# OpenAI Codex local override (personal, not shared)" >> .gitignore
    echo "AGENTS.override.md" >> .gitignore
    print_success "Added AGENTS.override.md to .gitignore"
else
    print_status "AGENTS.override.md already in .gitignore"
fi

# Ensure AGENTS.md is NOT gitignored (it should be committed)
if grep -q "^AGENTS.md$" .gitignore 2>/dev/null; then
    print_warning "AGENTS.md is listed in .gitignore — removing it (AGENTS.md should be committed)"
    sed -i '/^AGENTS\.md$/d' .gitignore
    print_success "Removed AGENTS.md from .gitignore"
fi

echo
echo "Setup Complete!"
echo "==============="
echo
print_status "Next steps:"
echo "1. Authenticate with OpenAI:"
echo -e "   ${BLUE}codex auth${NC}"
echo
echo "2. Start coding with Codex:"
echo -e "   ${BLUE}codex${NC}"
echo
echo "3. Commit the new context files to share with your team:"
echo -e "   ${BLUE}git add AGENTS.md ai-project.md${NC}"
echo -e "   ${BLUE}git commit -m 'Add AI agent context files'${NC}"
echo
print_status "Context file chain:"
echo "  AGENTS.md -> ai-context.md -> ai-project.md"
echo "  (all committed, edit ai-project.md for this project's specifics)"
echo
print_warning "Note: Your authentication will be specific to this devcontainer."
print_warning "You may need to re-authenticate if you rebuild the container."
echo
print_status "Quick tips:"
echo "• AGENTS.md is the entry point — read by Codex, Amp, Cursor, Jules, etc."
echo "• ai-project.md is project-specific — fill it in once per repository"
echo "• ai-context.md is generic — reuse it across similar projects unchanged"
echo "• AGENTS.override.md is gitignored — use it for personal/temporary overrides"
