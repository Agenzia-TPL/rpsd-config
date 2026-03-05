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

### OpenAI Codex CLI
**File:** `setup-openai-codex.sh`
**What it does:** Installs the OpenAI Codex CLI and creates `AGENTS.md` and `ai-project.md` context files
**Requirements:** OpenAI account (ChatGPT Plus/Pro/Team/Edu/Enterprise)
**Best for:** Agentic coding, multi-step tasks, code generation in the terminal

```bash
./ai-scripts/setup-openai-codex.sh
```

### GitHub Copilot CLI
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

## AI Context File Chain

The project uses a three-layer context chain (all files committed, all reusable):

```
AGENTS.md        <- entry point for agent-based tools (generic, no project specifics)
    |
    v
ai-context.md    <- development guidelines for this project type (generic, reusable)
    |
    v
ai-project.md    <- project-specific overview and architecture (edit per repository)
```

Personal/tool-specific adapters (gitignored, developer-specific):
- `CLAUDE.local.md` — references `@AGENTS.md` for Claude Code users

**To set up a new repository:** run any assistant setup script, then edit `ai-project.md`
to describe your specific project. The other two files can be copied unchanged.

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
