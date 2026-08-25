# bound-codex-tokens

Local, terminal-first protection for long-running Codex workflows.

It launches the normal Codex TUI, watches only sessions created after launch,
and totals `token_count.last_token_usage` across the root session and its v2
subagent lineage. On a limit it stops the TUI, asks a configurable summary
model for a **bounded**
handoff based on selected JSONL records, then starts a fresh TUI with the same
Codex flags and the handoff path.  It deliberately does not use `codex resume`.

## Why bound token usage?

`fork_turns: all` can multiply input usage by copying parent context into many
subagents. This preserves overnight progress with bounded handoffs instead of
allowing an unbounded session. Compaction billing is opaque.

## Status

This is a prototype for Codex CLI 0.147.0.  Run the no-cost checks first:

```bash
python3 bound_codex_tokens.py --self-test
```

Install it with `uv`:

```bash
uv tool install .
bound-codex-tokens --help
```

Then run a deliberately small live summary test from a real terminal (not a CI
shell), where it can keep the TUI attached:

```bash
./bound-codex-tokens --session 500 --compactions 1 -- --yolo -m gpt-5.6-luna
```

`--` separates protector options from flags passed directly to `codex`; thus
`--yolo`, model, sandbox, config, and other normal Codex flags survive each
fresh TUI launch.  Do not pass an initial Codex prompt during the live test;
type it into the TUI.  Later versions can preserve one safely.

For production, begin with a small cap and then use e.g.:

```bash
./bound-codex-tokens --session 10000000 --compactions 2 \\
  --v2-spawn-policy --max-sol-subagents 0 -- \\
  --enable multi_agent_v2 --yolo -m gpt-5.6-terra
```

`--compactions 2` means at most two automatic fresh-TUI resumes. On the next
cap it still produces one final handoff, prints its path, and stops.

The handoff defaults to Luna at medium effort. Customize it independently of
the TUI model:

```bash
bound-codex-tokens --session 10M --compactions 2 \\
  --summary-model gpt-5.6-terra --summary-effort high -- --yolo
```

## Enforcement model

* `--session` accepts any positive token count, optionally using `K`, `M`, or
  `B` suffixes, and measures reported input plus output tokens.
* `--deny-sol-subagents` fail-fast stops when a `spawn_agent` call requests a
  Sol model or a recorded child identifies itself as Sol.
* `--require-fork-none` fail-fast stops when a v2 `spawn_agent` omits
  `fork_turns: none` or asks for another value.

These two policy flags are detectors, not pre-call gates: the current stock
TUI keeps model tool calls inside Codex, so an external watcher can only stop
the root once the spawn event is written.  Native rollout budget is a useful
second guard, but it does not represent a total billed-token cap.

## V2 policy

`--v2-spawn-policy` automatically installs a per-launch `PreToolUse` hook and
enables `multi_agent_v2`; it does not modify `~/.codex/config.toml`. The hook
requires `fork_turns: none`, enforces the Sol allowance, and blocks nested
`codex exec` commands that would bypass lineage accounting.

Allow two explicitly requested Sol subagents while continuing to require
`fork_turns: none`:

```bash
bound-codex-tokens --session 10M --compactions 2 \\
  --v2-spawn-policy --max-sol-subagents 2 -- --yolo -m gpt-5.6-terra
```

The hook maintains this allowance per root session locally. It tells the main
agent when it spends an allowance and blocks later Sol spawn attempts.

The implementation uses the normal TUI instead of the SDK/App Server so that
the terminal remains the normal Codex terminal. A custom App Server client can
intercept calls before they are submitted.
