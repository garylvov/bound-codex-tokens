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
subagents. Compaction billing is opaque. This tool caps observable lineage
tokens and restarts from a small handoff instead of native resume.

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
./bound-codex-tokens --session 10M --compactions 2 \\
  --v2-spawn-policy --max-sol-subagents 0 -- --yolo -m gpt-5.6-terra
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

* `--session` accepts `500`, `10K`, `10M`, or `1B` and measures reported total
  input plus output tokens, including reported cached input.
* `--deny-sol-subagents` fail-fast stops when a `spawn_agent` call requests a
  Sol model or a recorded child identifies itself as Sol.
* `--require-fork-none` fail-fast stops when a v2 `spawn_agent` omits
  `fork_turns: none` or asks for another value.

These two policy flags are detectors, not pre-call gates: the current stock
TUI keeps model tool calls inside Codex, so an external watcher can only stop
the root once the spawn event is written.  Native rollout budget is a useful
second guard, but it does not represent a total billed-token cap.

## Pre-spawn v2 hook

For prevention rather than detection, install the opt-in `PreToolUse` hook in
`hooks/bound-v2-spawn-policy.toml`. After `uv tool install .`, use this command
to locate the installed hook script for its `command` field:

```bash
uv tool run --from bound-codex-tokens python -c \
  'import bound_codex_tokens_hooks.v2_spawn_policy as p; print(p.__file__)'
```

It sees `spawn_agent` and its complete
arguments before execution. It blocks Sol models and every value other than
`fork_turns: none`, then returns the reason as both a tool-block reason and
additional context to the main agent. Attach this hook only to the v2 profile
or session; it does not need to run for ordinary Codex sessions.

The protector's `--v2-spawn-policy` option does this automatically as a
per-launch `-c` override and enables `multi_agent_v2`. It does not modify
`~/.codex/config.toml`. It replaces `PreToolUse` hooks for that protected
process, so do not combine it with another required PreToolUse policy until
hook-list merging is supported.

Allow two explicitly requested Sol subagents while continuing to require
`fork_turns: none`:

```bash
bound-codex-tokens --session 10M --compactions 2 \\
  --v2-spawn-policy --max-sol-subagents 2 -- --yolo -m gpt-5.6-terra
```

The hook maintains this allowance per root session locally. It tells the main
agent when it spends an allowance and blocks later Sol spawn attempts.

### Enable multi-agent v2

Pass `--enable multi_agent_v2` to Codex for a single session. The
`--v2-spawn-policy` switch already adds it.

The implementation uses the normal TUI instead of the SDK/App Server so that
the terminal remains the normal Codex terminal. A custom App Server client can
intercept calls before they are submitted.
