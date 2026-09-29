# SAEngine Project Rules

## Rule #1: Never Reinvent the Wheel

**If an existing, proven product or library can do the job — USE IT.**

Do NOT build custom implementations of:
- Code editors (VS Code, Monaco, QScintilla exist)
- Terminals (VS Code integrated terminal, xterm.js exist)
- File explorers (VS Code, OS-native explorers exist)
- Git GUIs (VS Code source control, GitLens exist)
- Build systems, linters, formatters (existing tooling)

Before writing ANY new component, ask:
1. Does an existing product already solve this? → **Use it.**
2. Does an existing library provide this as a widget/component? → **Use it.**
3. Can we extend an existing platform (VS Code extension, plugin)? → **Do that.**
4. Is there truly nothing that fits? → Only then build it yourself.

**SAEngine should focus ONLY on what doesn't already exist:**
- 3D structural modeling viewport
- Structural analysis engine integration (OpenSeesPy)
- CAE-specific UI (grid/story dialogs, structural property editors)
- Design code checking
- Engineering-domain logic

Everything else (editing, terminal, git, file management) is provided by VS Code.
