#!/usr/bin/env python3
"""context_audit.py — analyze OpenCode session context for dead-weight tool output.

Usage:
    python3 context_audit.py <session_id>
    python3 context_audit.py                   # auto-detect current session (most recent)

Reads ~/.local/share/opencode/opencode.db (read-only).
Outputs a plain-text context audit report to stdout.
"""

import json
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict


DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
MIN_PARTS = 50


# ── helpers ──────────────────────────────────────────────────────────────────

def part_len(part: dict) -> int:
    """Estimate byte cost of a part by its text/output length."""
    t = part.get("type", "")
    if t == "tool":
        st = part.get("state", {})
        if st.get("status") == "completed":
            return len(st.get("output", ""))
        return len(json.dumps(st.get("error", "")))
    if t == "text":
        return len(part.get("text", ""))
    if t == "reasoning":
        return len(part.get("text", ""))
    if t == "patch":
        return len(part.get("snapshot", ""))
    return 0


def tool_input_str(tool_part: dict) -> str:
    """Best-effort single-line input description for a tool call."""
    inp = tool_part.get("state", {}).get("input", "")
    if isinstance(inp, dict):
        cmd = inp.get("command", "")
        if cmd:
            return cmd[:100]
        return json.dumps(inp, ensure_ascii=False)[:100]
    return str(inp)[:100]


def tool_output_str(tool_part: dict) -> str:
    st = tool_part.get("state", {})
    if st.get("status") == "error":
        err = st.get("error", {})
        if isinstance(err, dict):
            return err.get("message", str(err))[:500]
        return str(err)[:500]
    return st.get("output", "")[:500]


def same_command(a: dict, b: dict) -> bool:
    """Heuristic: two tool calls are similar if their command strings match."""
    ia = tool_input_str(a)
    ib = tool_input_str(b)
    return ia == ib and len(ia) > 2  # must have real content


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    if not DB_PATH.exists():
        sys.stderr.write(f"Error: database not found at {DB_PATH}\n")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # ── session selection ─────────────────────────────────────────────────

    session_id = sys.argv[1] if len(sys.argv) > 1 else None

    if session_id:
        row = conn.execute("SELECT id, title FROM session WHERE id = ?", (session_id,)).fetchone()
        if not row:
            sys.stderr.write(f"Error: session {session_id} not found\n")
            sys.exit(1)
    else:
        row = conn.execute(
            "SELECT s.id, s.title FROM session s "
            "JOIN part p ON p.session_id = s.id "
            "WHERE json_extract(p.data, '$.type') NOT IN ('step-start', 'step-finish') "
            "GROUP BY s.id ORDER BY MAX(p.time_created) DESC LIMIT 1"
        ).fetchone()
        if not row:
            sys.stderr.write("Error: no sessions found\n")
            sys.exit(1)
        session_id = row["id"]

    title = row["title"] or "(untitled)"

    # ── load all parts for this session ───────────────────────────────────

    rows = conn.execute(
        "SELECT data, message_id, time_created FROM part "
        "WHERE session_id = ? ORDER BY time_created",
        (session_id,)
    ).fetchall()

    parts = []
    for r in rows:
        try:
            d = json.loads(r["data"])
            d["_message_id"] = r["message_id"]
            d["_time_created"] = r["time_created"]
            parts.append(d)
        except json.JSONDecodeError:
            continue

    conn.close()

    if len(parts) < MIN_PARTS:
        print("Session too small for meaningful audit "
              f"({len(parts)} parts, minimum {MIN_PARTS}).")
        return

    # ── Block A: context composition ──────────────────────────────────────

    type_bytes: dict[str, int] = defaultdict(int)
    type_count: dict[str, int] = defaultdict(int)

    for p in parts:
        t = p.get("type", "other")
        type_count[t] = type_count.get(t, 0) + 1
        type_bytes[t] += part_len(p)

    total = sum(type_bytes.values()) or 1

    # skip noise types
    skip = {"step-start", "step-finish"}
    display_types = sorted(
        [(t, type_count.get(t, 0), type_bytes[t]) for t in type_count if t not in skip],
        key=lambda x: x[2], reverse=True
    )

    print("=" * 60)
    print(f"CONTEXT AUDIT  —  {title}")
    print("=" * 60)
    print()
    print("SECTION A: Context Composition")
    print("-" * 40)
    print(f"{'Part type':<16} {'Count':>8} {'Bytes':>12} {'Pct':>8}")
    print("-" * 40)

    for t, cnt, bts in display_types:
        pct = bts / total * 100
        print(f"{t:<16} {cnt:>8} {bts:>12,} {pct:>7.1f}%")

    total_tool_bytes = sum(type_bytes[t] for t in type_count
                           if t == "tool")
    print(f"\nTotal tool output bytes: {total_tool_bytes:,}")

    # ── Block B: failed tool calls ────────────────────────────────────────

    failed = [p for p in parts if p.get("type") == "tool"
              and p.get("state", {}).get("status") == "error"]

    if not failed:
        print("\nContext is clean — no failed tool calls detected.")
        return

    # Build turn index: a "turn" starts with a user message
    msg_ids = []
    for p in parts:
        mid = p.get("_message_id")
        if mid and mid not in msg_ids:
            msg_ids.append(mid)
    mid_to_turn = {mid: i for i, mid in enumerate(msg_ids)}

    # Collect successful tool calls (later) for retry detection
    successful = [p for p in parts if p.get("type") == "tool"
                  and p.get("state", {}).get("status") == "completed"]

    # Build tool success set: for each tool type, all turn numbers where it succeeded
    tool_success_turns: dict[str, list[int]] = defaultdict(list)
    for s in successful:
        st = s.get("tool", "")
        smid = s.get("_message_id", "")
        sturn = mid_to_turn.get(smid, -1)
        tool_success_turns[st].append(sturn)

    # Classify each failed call
    noises = []
    investigations = []

    for f in failed:
        ftool = f.get("tool", "?")
        fmiddle = f.get("_message_id", "")
        ftime = f.get("_time_created", 0)
        fturn = mid_to_turn.get(fmiddle, -1)

        # Retry detection: first try exact command match, then fall back to
        # "same tool type succeeded later" (handles SchemaError where input is {})
        retried = False
        same_cmd_success = False
        for s in successful:
            if s.get("tool") != ftool:
                continue
            stime = s.get("_time_created", 0)
            if stime > ftime and same_command(f, s):
                same_cmd_success = True
                retried = True
                break

        if not retried and ftool in tool_success_turns:
            # Fallback: same tool type succeeded in any later turn
            later = [t for t in tool_success_turns[ftool] if t > fturn]
            if later:
                retried = True

        entry = {
            "tool": ftool,
            "input": tool_input_str(f),
            "error": tool_output_str(f),
            "turn": fturn,
            "retried": retried,
            "bytes": part_len(f),
        }

        if retried:
            noises.append(entry)
        else:
            investigations.append(entry)

    # ── print section B ───────────────────────────────────────────────────

    total_fail_bytes = sum(e["bytes"] for e in noises + investigations)
    dead_bytes = sum(e["bytes"] for e in noises)

    print()
    print("SECTION B: Failed Tool Calls")
    print("-" * 60)
    print(f"{len(failed)} failed calls found, "
          f"{len(noises)} are dead weight "
          f"({(dead_bytes / max(total_tool_bytes, 1)) * 100:.1f}% of tool output bytes)")
    print()

    def collapse(entries: list[dict]) -> list[dict]:
        """Group identical entries (same tool + same error text) into one summary line."""
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for e in entries:
            key = (e["tool"], e["error"][:80])
            groups[key].append(e)
        result = []
        for (tool, err), items in groups.items():
            entry = dict(items[0])
            entry["_group_count"] = len(items)
            result.append(entry)
        return sorted(result, key=lambda e: -(e.get("_group_count", 0)))

    max_show = 20
    for label, entries in [("NOISE (dead weight)", noises),
                            ("INVESTIGATION", investigations)]:
        if not entries:
            continue
        collapsed = collapse(entries)
        print(f"  [{label}]  ({len(entries)} calls)")
        for e in collapsed[:max_show]:
            group = e.get("_group_count", 0)
            plural = f" x{group}" if group > 1 else ""
            inp = e["input"][:80]
            print(f"    [{e['tool']:<8}] {e['bytes']:>8,} bytes{plural}  "
                  f"turn {e['turn']}")
            print(f"             {inp}")
            if e.get("retried"):
                print(f"             → retried and succeeded later.")
        if len(collapsed) > max_show:
            print(f"    ... and {len(collapsed) - max_show} more groups")
        print()

    # ── recommendations ───────────────────────────────────────────────────

    total_turns = len(msg_ids)
    recent_cutoff = total_turns - 10  # last 10 turns are "recent"

    print("RECOMMENDATION")
    print("-" * 40)
    if noises:
        recent_noise = any(n["turn"] >= recent_cutoff for n in noises)
        old_noise = any(n["turn"] < recent_cutoff for n in noises)
        if recent_noise and old_noise:
            print("- Dead-weight failures span both recent and old turns.")
            print("  Old ones: consider enabling compaction.prune to auto-clear.")
            print("  Recent ones: will age out; no urgent action.")
        elif recent_noise:
            print("- All dead-weight failures are in recent turns.  Nothing urgent; "
                  "they'll age out.")
        else:
            print("- All dead-weight failures are old.  "
                  "Consider enabling compaction.prune to auto-clear these.")
    if investigations:
        print("- Unsolved failures remain. Do not suggest removal — "
              "they may still be under investigation.")
    if not noises and not investigations:
        print("- No action needed.")


if __name__ == "__main__":
    main()
