# Context Audit Skill — Design

## Overview

`/context-audit` is an OpenCode skill that analyzes session context for dead-weight
tool output — failed commands whose errors were later fixed. It combines a Python
script for data extraction with AI-powered interpretation for judgment and advice.

## Architecture

```
/context-audit
    │
    ├── SKILL.md loads → tells AI: workflow steps, noise rules, recommendation rules
    │
    ├── AI invokes script:
    │     context_audit.py <session_id>
    │       ├── connects ~/.local/share/opencode/opencode.db (read-only)
    │       ├── queries part table for context composition (Block A)
    │       ├── queries part table for failed tool calls (Block B)
    │       └── outputs structured text
    │
    └── AI reads script output:
          ├── Section A: presents context composition table verbatim
          └── Section B: interprets failed tool calls, classifies each as
              dead weight or legitimate investigation
```

Script produces data. AI produces judgment.

## Script Output

### Block A: Context Composition

| Column | Source |
|--------|--------|
| part type | `json_extract(part.data, '$.type')` |
| count | `COUNT(*)` |
| estimated chars | sum of text length or tool output length per type |
| percentage | type bytes / total bytes |

### Block B: Failed Tool Calls

Single detection rule: `part.state.status == "error"` — tool calls that returned
an error.

Per-failure fields:

| Field | Meaning |
|-------|---------|
| `tool` | tool name (bash, read, grep, etc.) |
| `command` | the command or input that failed |
| `error` | error message or reason (truncated to 500 chars) |
| `cost` | error output bytes as % of total tool output bytes |
| `location` | turn N of M — head (old) vs tail (recent) |
| `retried` | whether the same command was attempted again in a later turn |
| `wasted` | how many turns between this failure and the retry that succeeded |
| `prunable` | whether OpenCode's built-in `compaction.prune` could clear this |

Script outputs Block A and Block B as plain text to stdout. No classification,
no recommendations — just structured data fields.

## AI Workflow (SKILL.md)

The skill is triggered manually via `/context-audit`.

### Step 1 — Session Selection

- Use the session ID provided by user, if any.
- Otherwise default to the current session.
- If neither is available, list the 5 most recent sessions and ask the user to
  pick one.

### Step 2 — Run Script

```bash
python3 ~/.config/opencode/skills/context-audit/context_audit.py <session_id>
```

### Step 3 — Produce Dual-Section Output

**Section A: Context Composition**

Present Block A verbatim. No modifications.

**Section B: Failed Tool Call Analysis**

Read Block B and classify each failed call:

```
## Noise Classification Rules

You will receive a list of failed tool calls from the script.
Classify each one as NOISE (dead weight) or INVESTIGATION (possibly useful),
using only the fields provided.

Classify as NOISE (dead weight) when:
- retried = YES → a later attempt succeeded. The failure output is dead weight
  — every byte of it is a record of a problem that no longer exists.

Classify as INVESTIGATION (possibly useful) when:
- retried = NO → the failure was never resolved. The error output may still be
  relevant to the user's current task.

Output format:

  "Found N failed tool calls, M are dead weight (X% of tool output bytes)."
  (list each with classification and one-sentence reasoning)

Recommendation:
- retried = YES, prunable = YES → suggest enabling compaction.prune to
  auto-clear these.
- retried = YES, but in recent turns → nothing urgent; they'll age out or be
  pruned later.
- retried = NO → mark as potential investigation context; do not suggest
  removal.
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Script fails (DB missing, permissions) | Tell user to check `~/.local/share/opencode/opencode.db` exists and is readable |
| Session has < 50 parts | "Session too small for meaningful audit" |
| Zero failed tool calls | "Context is clean — no failed tool calls detected" |

## File Layout

```
opencode-skills/
├── README.md
├── context-audit/
│   ├── SKILL.md           # skill definition + AI rules
│   └── context_audit.py   # data extraction script
└── docs/
    └── specs/
        └── 2026-07-15-context-audit-design.md   # this file
```

## Non-Goals

- **No automatic cleanup.** The skill is read-only. It does not modify the
  OpenCode database or mark parts as compacted.
- **No persistent report storage.** Output goes to terminal only. No files saved.
- **No real-time monitoring.** The skill is manual trigger only. It does not
  proactively warn about context bloat during normal conversation.
- **No cross-session aggregation.** Each invocation analyzes one session. No
  trend tracking across sessions.
