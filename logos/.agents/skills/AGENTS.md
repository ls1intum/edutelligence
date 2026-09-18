# AGENTS.md — logos/.agents/skills

Skills follow the [Agent Skills](https://agentskills.io) format: one directory per skill containing a `SKILL.md` with YAML frontmatter — `name` (lowercase, hyphens, matching the directory) and `description` (what it does *and* when to use it). This directory is the canonical location; instructions live here and nowhere else.

## Every skill is mirrored into `.claude/skills/`

Skill discovery paths are client-specific and no single directory covers all of them:

| Client | Scans |
|--------|-------|
| Codex | `.agents/skills/` only |
| Claude Code | `.claude/skills/` only |
| Copilot, VS Code | `.github/skills/`, `.claude/skills/`, `.agents/skills/` |

So each skill here has a counterpart at `logos/.claude/skills/<name>/SKILL.md` — a real file rather than a symlink, because Git checks symlinks out as plain text on Windows unless Developer Mode is enabled, which would leave Claude Code without the skill there.

The stub carries **only the frontmatter**, and its body points back here. That keeps the duplicated surface down to `name` and `description`:

- **Adding a skill**: create it here, then add the stub under `.claude/skills/`.
- **Changing `name` or `description`**: change both files in the same commit.
- **Changing anything else**: this directory only — the stub holds no instructions.
- **Removing a skill**: remove both directories.
