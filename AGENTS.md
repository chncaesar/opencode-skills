# AGENTS.md

## Skill directory convention

Each skill is a directory with at minimum a `SKILL.md`:

```
skill-name/
├── SKILL.md          # YAML frontmatter (name, description) + markdown body
└── scripts/          # executable scripts (optional)
```

- **SKILL.md must have YAML frontmatter** with `name` and `description` keys.
- **Executable scripts go in `scripts/`**, never in the skill root.
- Install: `cp -r skill-name ~/.config/opencode/skills/`
- This is a public repo. No secrets, no proprietary content, no user-specific paths in code.

## context-audit

- The Python script reads `~/.local/share/opencode/opencode.db` read-only.
- It detects failed tool calls (`$.state.status == "error"`), classifies each as NOISE (retried later) or INVESTIGATION (never retried).
- The skill is a thin wrapper: the AI runs the script and presents output verbatim.
- No AI interpretation step — all logic is in `context_audit.py`.
