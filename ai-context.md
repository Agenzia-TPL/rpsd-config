# AI Development Assistant Context

This file provides context for AI development assistants (Claude Code, GitHub Copilot, etc.) working on this project.

## Project Overview

See `ai-project.md` for project description, technology stack, and conventions.

## Guidelines for AI Assistants

### Agent Skills

**For conversational AI assistants:** If you have file exploration capabilities, proactively check the `ai-skills/` directory at the start of new conversations to discover available skills.

Each subdirectory of `ai-skills/` represents an Agent Skill - a specialized tool with its own documentation and scripts. Examples: accessibility auditing, code generation, testing automation, etc.

**When to use skills:**
- Use relevant skills automatically when tasks match their capabilities
- Read the skill's `SKILL.md` file to understand usage, commands, and modes
- Skills may have additional reference documentation in their directories

**Pattern:** Explore → Read SKILL.md → Use when relevant

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
- Think of it as: "This is what I'm asking the AI to build" rather than "This is what was built"

#### `ARCHITECTURE.md` - Technical Architecture Documentation (Optional)
If this file exists:
- Documents the **system architecture** and technical design decisions
- Contains: component descriptions, data flow diagrams, class hierarchies, design patterns
- Explains **how the system works internally** (modules, layers, interactions)
- Target audience: developers who need to understand the codebase structure
- **Must be updated** when:
  - Adding new components or layers
  - Changing data flow or communication patterns
  - Modifying core abstractions or design patterns
  - Implementing features that affect system architecture
- Use **technical language** and focus on implementation details

#### `USAGE.md` - User Guide and Usage Documentation (Optional)
If this file exists:
- Documents **how to use** the application from a user's perspective
- Contains: CLI commands, configuration options, examples, workflows
- Explains **what the system does** and **how to operate it**
- Target audience: end users, operators, and administrators
- **Must be updated** when:
  - Adding new CLI commands or flags
  - Changing command behavior or options
  - Adding new features visible to users
  - Modifying configuration or environment variables
  - Changing execution modes or operational procedures
- Use **user-friendly language** and focus on practical usage

### Git Commit Policy
**CRITICAL: NEVER create git commits without EXPLICIT user permission!**

- **ALWAYS** stage changes with `git add` but STOP before committing
- **ALWAYS** show the user what will be committed using `git status` and `git diff --cached`
- **ALWAYS** present a proposed commit message for review
- **WAIT** for explicit user approval before running `git commit`
- **NEVER** assume permission based on previous commits in the same session
- If user says "commit this" or "create a commit", that counts as explicit permission
- If unclear, ASK: "Would you like me to create a commit for these changes?"

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

When the user indicates a session is ending (or before a large body of work is committed):

- **`ai-project.md`** — This file is written by the developer as a specification *before* asking the AI to work. The AI may propose updates, but must respect its nature:
  - **Do:** Mark completed items as done, note what was deferred, suggest new future work entries
  - **Do NOT:** Rewrite specifications, change the developer's intent, or turn planning language into past-tense documentation
  - Always show proposed changes and ask for approval
- **`ARCHITECTURE.md`** — If implementation details were added or changed significantly, suggest creating or updating this file
- **`DECISIONS.md`** — If an architectural decision was made during the session, propose an addition in the same style as existing entries
- Do NOT update any of these files silently — show the proposed changes and ask for approval

---
*This file is generic and reusable across projects.*
*Project-specific context (stack, commands, conventions) is in `ai-project.md`.*
*Individual developers may have their own tool-specific context files (e.g., `CLAUDE.local.md`).*
