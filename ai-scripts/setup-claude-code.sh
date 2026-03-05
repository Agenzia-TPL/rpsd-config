#!/bin/bash

# Setup script for Claude Code in devcontainer
# This script installs Node.js via nvm and then installs Claude Code
# Usage: ./scripts/setup-claude-code.sh

set -e  # Exit on any error

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

# Source nvm to make sure it's available in this script
# Try multiple common nvm locations for different devcontainer setups
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

# Check if nvm command is now available
if ! command -v nvm &> /dev/null; then
    print_error "nvm command is still not available after sourcing."
    print_error "There might be an issue with the nvm installation."
    exit 1
fi

# Check if Node.js is already installed and usable
if command -v node &> /dev/null && command -v npm &> /dev/null; then
    NODE_VERSION=$(node --version)
    NPM_VERSION=$(npm --version)
    print_success "Node.js already available: $NODE_VERSION"
    print_success "npm already available: $NPM_VERSION"

    # Update npm to latest version
    print_status "Updating npm to latest version..."
    npm install -g npm@latest

    # Refresh PATH and verify npm update
    hash -r 2>/dev/null || true
    NEW_NPM_VERSION=$(npm --version)
    print_success "npm updated from $NPM_VERSION to $NEW_NPM_VERSION"
else
    # Install Node.js (latest LTS)
    print_status "Installing Node.js (latest LTS)..."
    nvm install --lts
    nvm use --lts

    # Verify Node.js installation
    NODE_VERSION=$(node --version)
    NPM_VERSION=$(npm --version)
    print_success "Node.js installed: $NODE_VERSION"
    print_success "npm installed: $NPM_VERSION"

    # Update npm to latest version
    print_status "Updating npm to latest version..."
    npm install -g npm@latest

    # Refresh PATH and verify npm update
    hash -r 2>/dev/null || true
    NEW_NPM_VERSION=$(npm --version)
    print_success "npm updated to: $NEW_NPM_VERSION"
fi

# Install Claude Code
print_status "Installing Claude Code..."
npm install -g @anthropic-ai/claude-code

# Give it a moment and refresh PATH
sleep 1
hash -r 2>/dev/null || true

# Verify Claude Code installation with more robust checking
print_status "Verifying Claude Code installation..."

# Check multiple ways - the binary is actually named 'claude', not 'claude-code'
CLAUDE_INSTALLED=false

# Method 1: Check npm global packages first
if npm list -g @anthropic-ai/claude-code &> /dev/null; then
    print_success "Claude Code package is installed in npm global packages"

    # Find where npm installs global binaries
    NPM_PREFIX=$(npm config get prefix 2>/dev/null || echo "/usr/local")
    POSSIBLE_PATHS=(
        "$NPM_PREFIX/bin/claude"
        "$NPM_PREFIX/bin/claude-code"
        "$(dirname $(which npm))/claude"
        "$(dirname $(which npm))/claude-code"
        "/usr/local/bin/claude"
        "/usr/local/bin/claude-code"
    )

    print_status "Checking for claude binary in common locations..."
    for path in "${POSSIBLE_PATHS[@]}"; do
        print_status "  Checking: $path"
        if [ -f "$path" ] && [ -x "$path" ]; then
            CLAUDE_INSTALLED=true
            print_success "Found Claude binary at: $path"

            # Test if it works
            if "$path" --version &> /dev/null; then
                CLAUDE_VERSION=$("$path" --version 2>/dev/null || echo "unknown")
                print_success "Binary is working! Version: $CLAUDE_VERSION"
            else
                print_warning "Binary found but may not be working properly"
            fi
            break
        fi
    done

    if [ "$CLAUDE_INSTALLED" = false ]; then
        print_warning "Package installed but binary not found in expected locations"
        print_status "npm prefix: $NPM_PREFIX"
        print_status "Searching for claude..."
        find "$NPM_PREFIX" -name "claude" -type f 2>/dev/null || true
        find "$NPM_PREFIX" -name "claude-code" -type f 2>/dev/null || true
    fi
else
    print_error "Claude Code package not found in npm global packages"
fi

# Method 2: Try both command names directly (might work even if we can't find the path)
for cmd in claude claude-code; do
    if command -v $cmd &> /dev/null; then
        CLAUDE_INSTALLED=true
        CLAUDE_VERSION=$($cmd --version 2>/dev/null || echo "installed")
        print_success "$cmd command is available in PATH!"
        break
    fi
done

if [ "$CLAUDE_INSTALLED" = true ]; then
    print_success "Claude Code installation verified!"
    if [ -n "$CLAUDE_VERSION" ]; then
        print_success "Version: $CLAUDE_VERSION"
    fi
else
    print_warning "Claude Code package was installed by npm, but the binary is not accessible."
    print_status "This is often a PATH issue in devcontainer environments."
    print_status ""
    print_status "Diagnostic information:"
    print_status "  npm prefix: $(npm config get prefix 2>/dev/null || echo 'unknown')"
    print_status "  Current PATH: $PATH"
    print_status ""
    print_status "Try these manual steps:"
    echo "  1. Check where npm installed it:"
    echo -e "     ${BLUE}npm list -g @anthropic-ai/claude-code${NC}"
    echo "  2. Find the binary:"
    echo -e "     ${BLUE}find /usr/local -name 'claude*' 2>/dev/null${NC}"
    echo "  3. Try using 'claude' instead of 'claude-code'"
    echo "  4. Add to PATH if found, or restart your shell"
    echo
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
      "Read"
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
Read @AGENTS.md for shared project context and development guidelines.

## Personal Instructions for Claude Code
- **FIRST:** Always read @AGENTS.md for current project guidelines
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
*Shared project context chain: AGENTS.md -> ai-context.md -> ai-project.md*
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
*Individual developers may have their own tool-specific context files (e.g., `CLAUDE.local.md`).*
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
print_status "Note: The command is 'claude', not 'claude-code'"
echo
print_status "For more information, visit: https://docs.claude.com/en/docs/claude-code"
echo
print_warning "Note: Your authentication will be specific to this devcontainer."
print_warning "You may need to re-authenticate if you rebuild the container."
echo
print_status "Quick tips:"
echo "• Claude automatically finds CLAUDE.local.md files (git-ignored)"
echo "• CLAUDE.local.md -> AGENTS.md -> ai-context.md -> ai-project.md"
echo "• Edit ai-project.md to describe your project (committed, shared)"
echo "• Use /init command to let Claude analyze your project"
echo "• Use /clear command to start fresh conversations"
echo "• Use /config to manage Claude Code settings"
echo "• Your CLAUDE.local.md is personal and won't affect other developers"
