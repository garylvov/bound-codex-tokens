# bound-codex-tokens

Local, terminal-first protection for long-running Codex workflows. It lets
Codex keep working overnight, while placing a finite boundary around one
workflow and its delegated work.

## The three controls

1. **Bounded rollovers.** `--session` is a reported-token cap and
   `--compactions` is the finite number of automatic fresh-TUI resumes. At
   each cap, the wrapper writes a small handoff, starts a fresh normal Codex
   TUI, and preserves the flags passed after `--`. After the allowed rollovers,
   it writes one final handoff and stops.
2. **Configurable handoffs.** The handoff uses Luna by default, but its model,
   reasoning effort, and prompt are independent of the interactive TUI. The
   prompt is a top-level option so the continuation format is predictable.
3. **Guarded v2 delegation.** `--v2-spawn-policy` turns on
   `--enable multi_agent_v2` and adds a temporary per-launch hook. It requires
   `fork_turns: none`, blocks Sol by default, can allow a finite number of Sol
   children, and can restrict children to an explicit model list.

This is intentionally a safety wrapper, not a substitute for Codex: the TUI
stays attached, so a long-running workflow can still make progress while the
wrapper bounds its lifecycle.

## Install

```bash
uv tool install bound-codex-tokens
bound-codex-tokens --help
```

From a checkout, use `uv tool install .`.

## Examples

Run the normal TUI with any positive token cap (`K`, `M`, and `B` are accepted)
and two automatic rollovers:

```bash
bound-codex-tokens --session 10M --compactions 2 -- --yolo -m gpt-5.6-terra
```

`--yolo` is passed straight through to Codex and gives it broad authority to
act without asking. Use it only in a workspace and environment you are willing
to let the unattended TUI change.

Customize the bounded handoff (also called a compaction here) independently:

```bash
bound-codex-tokens --session 10M --compactions 2 \
  --compaction-model gpt-5.6-terra --compaction-effort high \
  --compaction-prompt 'List completed work, tests, blockers, and the next exact action.' \
  -- --yolo
```

The wrapper does not use a copied native Codex compaction prompt. Compaction
output is intentionally opaque in the upstream API, so this tool uses an
explicit prompt and only supplies selected user/assistant messages plus a
small manifest to the handoff model.

Enable guarded multi-agent v2, permit only Terra or Luna children, and permit
no Sol children:

```bash
bound-codex-tokens --session 10M --compactions 2 \
  --v2-spawn-policy --max-sol-subagents 0 \
  --allowed-subagent-model gpt-5.6-terra \
  --allowed-subagent-model gpt-5.6-luna \
  -- --yolo -m gpt-5.6-terra
```

`--v2-spawn-policy` automatically supplies the full Codex flag
`--enable multi_agent_v2`; do not add it again. `fork_turns: none` means a
child starts without a copy of the parent conversation history. It prevents a
large main context from being charged again to every delegated child. Use
`--max-sol-subagents 2` to allow exactly two Sol children. Without a v2 policy,
Sol is still denied by default; use `--allow-sol-subagents` only when that is
intentional.

The v2 hook also blocks nested `codex exec` calls, because their separate
sessions would evade the wrapper's root-lineage accounting.

## Notes

* The cap measures token totals reported in the fresh root-session lineage;
  it is a local guardrail, not a claim about final provider billing categories.
* The wrapper uses the regular Codex TUI, not a replacement client. It does not
  change `~/.codex/config.toml`.
* Run the no-cost checks with `bound-codex-tokens --self-test`.
