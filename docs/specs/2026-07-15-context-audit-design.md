# Context Audit Skill — Design

## Overview

`/context-audit` is an OpenCode skill that analyzes session context composition,
identifies noise (oversized tool outputs, failed commands, redundant reads), and
produces actionable recommendations. It combines a Python script for data
extraction with AI-powered interpretation for judgment and advice.

## Architecture

```
/context-audit
    │
    ├── SKILL.md loads → tells AI: workflow steps, noise rules, recommendation rules
    │
    ├── AI invokes script:
    │     context_audit.py <session_id>
    │       ├── connects ~/.local/share/opencode/opencode.db (read-only)
    │       ├── queries message table for token budgets
    │       ├── queries part table grouped by type
    │       └── outputs structured text (Block A + Block B)
    │
    └── AI reads script output:
          ├── Section A: presents context composition table verbatim
          └── Section B: interprets noise candidates, synthesizes recommendations
```

Script produces data. AI produces judgment. The script has zero knowledge of what
"noise" means — it just extracts and ranks candidates by measurable signals.
The AI, guided by SKILL.md, applies semantic rules to determine real noise from
false positives and to generate recommendations.

## Script Output

### Block A: Context Composition

| Column | Source |
|--------|--------|
| part type | `json_extract(part.data, '$.type')` |
| count | `COUNT(*)` |
| estimated chars | sum of text length or tool output length per type |
| percentage | type bytes / total bytes |

### Block B: Noise Candidates

Three noise signals, detected mechanically:

| Signal | Detection Rule | Data Source |
|--------|---------------|-------------|
| `OVERSIZED` | tool output > 4,000 chars | `part.state.output` length |
| `FAILED` | `part.state.status == "error"` | `json_extract(part.data, '$.state.status')` |
| `DUPLICATE` | same read/glob target appears ≥ 2 times | group by target, count ≥ 2 |

Per-candidate interpretability fields:

| Field | Meaning |
|-------|---------|
| `cost` | candidate bytes as % of total tool output bytes |
| `location` | turn N of M — head (old) vs tail (recent) |
| `prunable` | whether OpenCode's built-in `compaction.prune` could clear this |
| `appears_after` (OVERSIZED only) | turns since last successful similar command |
| `retried` / `wasted` (FAILED only) | whether a fix attempt followed, how many wasted turns |
| `interval` (DUPLICATE only) | turns between repeated reads of same file |
| `severity` | HIGH / MEDIUM / LOW — composite of cost, location, and harm |

Script outputs Block A and Block B as plain text to stdout. No recommendations,
no interpretation — just structured data fields.

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

Script output enters context directly.

### Step 3 — Produce Dual-Section Output

**Section A: Context Composition**

Present Block A verbatim. No modifications.

**Section B: Noise Analysis + Recommendations**

Read Block B and synthesize:

1. **Summary verdict** — one sentence. Example: "62% of tool output is noise —
   3 oversized build dumps and 2 failed commands that were later retried."
2. **Per-category interpretation** — sort by severity, one sentence per
   candidate category:
   - HIGH severity: call out explicitly, explain why.
   - LOW severity DUPLICATE with large interval: mark as "likely justified
     re-read, not noise."
3. **Actionable recommendations** — map findings to concrete actions:
   - Multiple HIGH severity in recent turns → suggest using tester subagent to
     isolate test/build output.
   - Multiple HIGH severity in old turns, prunable=YES → suggest enabling
     `compaction.prune` in OpenCode config.
   - Failed commands since fixed → "dead weight, no action needed."
   - Tool ratio >70% but all LOW severity → accept, no action recommended.

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Script fails (DB missing, permissions) | Tell user to check `~/.local/share/opencode/opencode.db` exists and is readable |
| Session has < 50 parts | "Session too small for meaningful audit" |
| Zero noise candidates | "Context is clean — no noise signals detected" |

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
