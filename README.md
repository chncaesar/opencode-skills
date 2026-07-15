# opencode-skills

Personal OpenCode skills collection.

## Skills

### context-audit

Analyze session context for dead-weight tool output — failed tool calls whose
errors were later fixed. Detects SchemaError failures, retried commands, and
other wasted context.

```
python3 context-audit/scripts/context_audit.py <session_id>
```

Produces: context composition table + failed call classification + actionable
recommendations.

## Install

Copy or symlink skill directories to `~/.config/opencode/skills/`:

```bash
cp -r context-audit ~/.config/opencode/skills/
```
