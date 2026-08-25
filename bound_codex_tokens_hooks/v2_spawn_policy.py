#!/usr/bin/env python3
"""PreToolUse policy for Codex v2 `spawn_agent` calls."""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import sys
from typing import Any


def deny(reason: str, max_sol: int) -> dict[str, Any]:
    message = (
        f"bound-codex-tokens blocked this subagent: {reason}. "
        "For multi_agent_v2, use fork_turns: none and a permitted subagent model "
        f"(Sol allowance: {max_sol})."
    )
    return {
        "decision": "block",
        "reason": message,
        "systemMessage": message,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        },
    }


def sol_slot(state_file: Path, session_id: str, maximum: int) -> tuple[bool, int]:
    """Atomically reserve one Sol slot for this root session."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with state_file.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        try:
            state = json.load(handle)
        except json.JSONDecodeError:
            state = {}
        count = int(state.get(session_id, 0))
        if count >= maximum:
            return False, count
        state[session_id] = count + 1
        handle.seek(0)
        handle.truncate()
        json.dump(state, handle)
        handle.flush()
        return True, count + 1


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--max-sol-subagents", type=int, default=0)
    parser.add_argument("--state-file", type=Path, required=True)
    args = parser.parse_args()
    if args.max_sol_subagents < 0:
        return 2
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") != "spawn_agent":
        print("{}")
        return 0
    tool_input = event.get("tool_input") or {}
    model = str(tool_input.get("model") or "").lower()
    if "sol" in model:
        allowed, used = sol_slot(args.state_file, str(event.get("session_id")), args.max_sol_subagents)
        if not allowed:
            print(json.dumps(deny(f"Sol-subagent allowance exhausted ({used}/{args.max_sol_subagents})", args.max_sol_subagents)))
            return 0
        message = f"bound-codex-tokens: Sol subagent {used}/{args.max_sol_subagents} allowed."
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}}))
        return 0
    if tool_input.get("fork_turns") != "none":
        print(json.dumps(deny("fork_turns must be explicitly set to none", args.max_sol_subagents)))
        return 0
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
