#!/usr/bin/env python3
"""A small, local session-budget supervisor for the interactive Codex TUI."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def token_limit(value: str) -> int:
    match = re.fullmatch(r"([0-9][0-9_]*(?:\.[0-9]+)?)([KkMmBb]?)", value.strip())
    if not match:
        raise argparse.ArgumentTypeError("use an integer or 10K, 10M, 1B")
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[match.group(2).lower()]
    return int(float(match.group(1).replace("_", "")) * multiplier)


def default_sessions_dir() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    return codex_home / "sessions"


def discover_logs(directory: Path) -> set[Path]:
    return set(directory.glob("*/*/*/*.jsonl")) if directory.exists() else set()


def content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(content_text(item.get("text", "")) if isinstance(item, dict) else "" for item in value)
    return ""


@dataclass
class FileState:
    offset: int = 0
    session_id: str | None = None
    parent_id: str | None = None
    source: str | None = None
    model: str | None = None
    total_tokens: int = 0
    last_cumulative: int | None = None
    excerpts: list[str] = field(default_factory=list)


class SessionWatch:
    def __init__(self, sessions_dir: Path, baseline: set[Path], deny_sol: bool, require_none: bool):
        self.sessions_dir = sessions_dir
        self.baseline = baseline
        self.states: dict[Path, FileState] = {}
        self.root_id: str | None = None
        self.related_ids: set[str] = set()
        self.deny_sol = deny_sol
        self.require_none = require_none
        self.violation: str | None = None

    def poll(self) -> None:
        for path in discover_logs(self.sessions_dir) - self.baseline:
            state = self.states.setdefault(path, FileState())
            try:
                with path.open("r", encoding="utf-8") as handle:
                    handle.seek(state.offset)
                    lines = handle.readlines()
                    state.offset = handle.tell()
            except (OSError, UnicodeDecodeError):
                continue
            for line in lines:
                try:
                    self._record(path, state, json.loads(line))
                except json.JSONDecodeError:
                    continue
        self._refresh_lineage()

    def _record(self, path: Path, state: FileState, record: dict[str, Any]) -> None:
        payload = record.get("payload", {})
        if record.get("type") == "session_meta":
            state.session_id = payload.get("session_id") or payload.get("id")
            state.parent_id = payload.get("parent_thread_id") or payload.get("forked_from_id")
            state.source = str(payload.get("thread_source") or "")
            state.model = str(payload.get("model") or payload.get("model_slug") or "")
            if self.root_id is None and state.source == "user":
                self.root_id = state.session_id
            if self.deny_sol and state.source == "subagent" and "sol" in state.model.lower():
                self.violation = f"Sol child recorded in {path.name}"

        if record.get("type") == "event_msg" and payload.get("type") == "token_count":
            usage = payload.get("info", {}).get("last_token_usage", {})
            cumulative = payload.get("info", {}).get("total_token_usage", {}).get("total_tokens")
            spent = usage.get("total_tokens")
            if isinstance(cumulative, int) and cumulative != state.last_cumulative and isinstance(spent, int):
                state.total_tokens += spent
                state.last_cumulative = cumulative

        if record.get("type") == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            text = content_text(payload.get("content"))
            if role in {"user", "assistant"} and text:
                state.excerpts.append(f"{role}: {text[:1800]}")

        # v2 spawn requests are persisted as function calls in the root transcript.
        if record.get("type") == "response_item" and payload.get("type") == "function_call":
            if payload.get("name") != "spawn_agent":
                return
            try:
                args = json.loads(payload.get("arguments", "{}"))
            except (TypeError, json.JSONDecodeError):
                return
            if self.deny_sol and "sol" in str(args.get("model", "")).lower():
                self.violation = "spawn_agent requested a Sol subagent"
            if self.require_none and args.get("fork_turns") != "none":
                self.violation = "spawn_agent did not explicitly request fork_turns: none"

    def _refresh_lineage(self) -> None:
        if not self.root_id:
            return
        related = {self.root_id}
        changed = True
        while changed:
            changed = False
            for state in self.states.values():
                if state.session_id and state.parent_id in related and state.session_id not in related:
                    related.add(state.session_id)
                    changed = True
        self.related_ids = related

    @property
    def tokens(self) -> int:
        return sum(state.total_tokens for state in self.states.values() if state.session_id in self.related_ids)

    def related_paths(self) -> list[Path]:
        return [path for path, state in self.states.items() if state.session_id in self.related_ids]


def terminate(process: subprocess.Popen[bytes], grace: float = 8.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.2)
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)


def write_bundle(output_dir: Path, watch: SessionWatch, reason: str, tokens: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle = output_dir / f"handoff-{stamp}"
    bundle.mkdir(parents=True, exist_ok=False)
    excerpts: list[str] = []
    for path in watch.related_paths():
        excerpts.extend(watch.states[path].excerpts[-30:])
    excerpts = excerpts[-100:]
    source = bundle / "selected-transcript.md"
    source.write_text(
        "# Bounded transcript selection\n\n"
        f"Reason: {reason}\n\nReported lineage tokens: {tokens:,}\n\n"
        "Only user/assistant messages are included; raw tool output and full history are excluded.\n\n"
        + "\n\n".join(excerpts),
        encoding="utf-8",
    )
    (bundle / "manifest.json").write_text(json.dumps({
        "reason": reason, "reported_tokens": tokens,
        "root_session_id": watch.root_id,
        "session_logs": [str(path) for path in watch.related_paths()],
    }, indent=2) + "\n", encoding="utf-8")
    return bundle


def run_summary(bundle: Path, model: str, effort: str, cwd: Path) -> Path:
    handoff = bundle / "HANDOFF.md"
    prompt = (
        f"Read only {bundle / 'selected-transcript.md'} and {bundle / 'manifest.json'}. "
        "Create a concise continuation handoff in the output file: goals, completed work, "
        "current state, safe next steps, and unresolved risks. Do not read any session JSONL files."
    )
    command = ["codex", "exec", "--skip-git-repo-check", "-C", str(cwd), "-s", "read-only",
               "-m", model, "-c", f"model_reasoning_effort={json.dumps(effort)}", "-o", str(handoff), prompt]
    print(f"[bound] generating bounded handoff with {model} ({effort})...", flush=True)
    subprocess.run(command, check=True)
    return handoff


def without_initial_prompt(arguments: list[str]) -> list[str]:
    """Keep common Codex flags; drop positional prompt for the fresh handoff TUI."""
    takes_value = {"-c", "--config", "-i", "--image", "-m", "--model", "-p", "--profile", "-s", "--sandbox", "-C", "--cd", "--add-dir", "-a", "--ask-for-approval", "--enable", "--disable"}
    result: list[str] = []
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item in takes_value:
            result.append(item)
            if index + 1 < len(arguments):
                result.append(arguments[index + 1])
            index += 2
        elif item.startswith("-"):
            result.append(item)
            index += 1
        else:
            break
    return result


def v2_policy_config_args(max_sol_subagents: int, state_file: Path) -> list[str]:
    """Return a process-local PreToolUse hook config, without touching config.toml."""
    from bound_codex_tokens_hooks import v2_spawn_policy

    command = shlex.join([
        sys.executable, str(Path(v2_spawn_policy.__file__).resolve()),
        "--max-sol-subagents", str(max_sol_subagents), "--state-file", str(state_file),
    ])
    # TOML inline tables use `=` rather than JSON's `:`. Build it explicitly so
    # the hook command remains safely quoted even when its path contains spaces.
    value = ('[{ matcher = "^spawn_agent$", hooks = '
             '[{ type = "command", command = ' + json.dumps(command) +
             ', timeout = 5, statusMessage = "checking v2 subagent policy" }] }]')
    return ["--enable", "multi_agent_v2", "-c", f"hooks.PreToolUse={value}"]


def self_test() -> int:
    assert token_limit("500") == 500
    assert token_limit("10M") == 10_000_000
    assert without_initial_prompt(["--yolo", "-m", "gpt-5.6-luna", "hello"]) == ["--yolo", "-m", "gpt-5.6-luna"]
    print("self-test passed: limits and Codex flag preservation")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=token_limit, default=10_000_000, help="reported-token cap; e.g. 10M")
    parser.add_argument("--compactions", type=int, default=2, help="maximum automatic fresh-TUI resumes")
    parser.add_argument("--sessions-dir", type=Path, default=default_sessions_dir())
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / ".bound-codex-tokens")
    parser.add_argument("--summary-model", default="gpt-5.6-luna", help="model used for the bounded handoff")
    parser.add_argument("--summary-effort", default="medium", help="reasoning effort used for the handoff")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--deny-sol-subagents", action="store_true")
    parser.add_argument("--require-fork-none", action="store_true")
    parser.add_argument("--v2-spawn-policy", action="store_true", help="enable pre-spawn v2 policy hook")
    parser.add_argument("--max-sol-subagents", type=int, default=0, help="Sol subagent allowance under v2 policy")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("codex_args", nargs=argparse.REMAINDER, help="pass Codex TUI flags after --")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.compactions < 0:
        parser.error("--compactions must be zero or greater")
    if args.max_sol_subagents < 0:
        parser.error("--max-sol-subagents must be zero or greater")
    codex_args = args.codex_args[1:] if args.codex_args[:1] == ["--"] else args.codex_args
    if not args.sessions_dir.exists():
        parser.error(f"sessions directory not found: {args.sessions_dir}")

    rollovers = 0
    first_launch = True
    cwd = Path.cwd()
    state_file = args.output_dir / f"v2-spawn-policy-{os.getpid()}.json"
    policy_args = v2_policy_config_args(args.max_sol_subagents, state_file) if args.v2_spawn_policy else []
    while True:
        baseline = discover_logs(args.sessions_dir)
        launch_args = (codex_args if first_launch else without_initial_prompt(codex_args) + [
            f"Read the protected handoff at {handoff}; continue from it. Do not use native resume."
        ]) + policy_args
        print(f"[bound] starting TUI segment {rollovers + 1}; cap {args.session:,} reported tokens", flush=True)
        process = subprocess.Popen(["codex", *launch_args], start_new_session=True)
        watch = SessionWatch(args.sessions_dir, baseline, args.deny_sol_subagents, args.require_fork_none)
        reason: str | None = None
        while process.poll() is None:
            time.sleep(args.poll_seconds)
            watch.poll()
            if watch.violation:
                reason = f"policy violation: {watch.violation}"
            elif watch.root_id and watch.tokens >= args.session:
                reason = f"session cap reached: {watch.tokens:,} >= {args.session:,}"
            if reason:
                print(f"[bound] {reason}; stopping TUI", flush=True)
                terminate(process)
                break
        if reason is None:
            return process.wait()
        bundle = write_bundle(args.output_dir, watch, reason, watch.tokens)
        try:
            handoff = run_summary(bundle, args.summary_model, args.summary_effort, cwd)
        except subprocess.CalledProcessError as exc:
            print(f"[bound] handoff failed ({exc.returncode}); bundle retained at {bundle}", file=sys.stderr)
            return exc.returncode
        if rollovers >= args.compactions:
            print(
                f"[bound] automatic resume limit reached; final handoff: {handoff}\n"
                "[bound] No new TUI was started. Resume manually from this handoff when ready.",
                flush=True,
            )
            return 75
        print(f"[bound] handoff written to {handoff}; reopening TUI", flush=True)
        rollovers += 1
        first_launch = False


if __name__ == "__main__":
    raise SystemExit(main())
