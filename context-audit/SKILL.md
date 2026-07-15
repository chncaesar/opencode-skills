---
name: context-audit
description: Analyze OpenCode session context for dead-weight tool output (failed calls later retried). Use when user says /context-audit or asks about context noise.
---

# /context-audit — Session Context Audit

Audit the current or specified OpenCode session for dead-weight tool output:
failed tool calls whose errors were later resolved by a successful retry.

## Workflow

1. Determine the session ID:
   - If the user provided one, use it.
   - Otherwise, default to the current session.
   - If neither is available, list the 5 most recent sessions and ask.

2. Run the script:
   ```bash
   python3 ~/.config/opencode/skills/context-audit/context_audit.py <session_id>
   ```

3. Present the output verbatim. The script handles all detection, classification,
   and recommendations. You do not need to add interpretation.
