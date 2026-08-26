# bound-codex-tokens

Local, terminal-first protection for long-running Codex workflows. It lets
Codex keep working overnight, while placing a finite boundary around one
workflow and its delegated work.

## The three controls

1. **Separate root and child compact thresholds.** All four controls are required:
   `--total-tokens` is the hard combined cap; `--root-compact-every` triggers
   a root-TUI handoff only from root usage; `--subagent-compact-every` triggers
   that same handoff when children in the active segment hit their aggregate
   budget; `--max-compacts-num` is the number of allowed handoff-and-restart
   cycles.

The compact count permits one more TUI segment than its value. The effective
ceiling is therefore:

```text
min(total-tokens, (root-compact-every + subagent-compact-every) × (1 + max-compacts-num))
```

For example, root `800K`, subagents `1M`, and two compacts permit three
segments and an effective ceiling of `5.4M`; `10M` remains the global hard cap.
2. **Configurable handoffs.** The handoff uses Luna by default, but its model,
   reasoning effort, and prompt are independent of the interactive TUI. The
   prompt is a top-level versioned Markdown file so the continuation format is
   predictable. Every TUI segment also receives a visible token-budget prompt.
3. **Guarded v2 delegation.** `--no-fork` turns on
   `--enable multi_agent_v2` and adds a temporary per-launch hook. It requires
   `fork_turns: none`, blocks Sol by default, can allow a finite number of Sol
   children, and can restrict children to an explicit model list.

This is intentionally a safety wrapper, not a substitute for Codex: the TUI
stays attached, so a long-running workflow can still make progress while the
wrapper bounds its lifecycle.

## Dollar and credit estimates

Use a dollar estimate in place of `--total-tokens`:

```bash
bound-codex-tokens --budget-usd 200 --cost-model gpt-5.6-terra \
  --root-compact-every 800K --subagent-compact-every 500K \
  --max-compacts-num 2 -- --yolo -m gpt-5.6-terra
```

The default is the official **standard** API list-price row and a deliberately
explicit estimate of 90% input / 10% output. At that mix, `$200` is about
`133.3M` reported tokens for Terra (`~120M` input, `~13.3M` output), `71.4M`
for Sol, or `1.33B` for Luna. Select `--price-tier fast`,
`--long-context-pricing`, or `--estimated-input-share 0.95` when those better
match the planned workload. Inspect the bundled table with `--show-pricing`.

The table is a versioned snapshot of the official [OpenAI pricing
page](https://developers.openai.com/api/docs/pricing), retrieved 2026-08-25.
It is an API-list-price planning conversion, not a guaranteed Codex charge:
the session logs report total tokens but do not expose cached input, reasoning,
tool charges, service tier, or any plan-specific credit conversion.

For an internal credit system, state the local conversion explicitly:

```bash
bound-codex-tokens --budget-credits 200 --usd-per-credit 1 \
  --cost-model gpt-5.6-terra --root-compact-every 800K \
  --subagent-compact-every 500K --max-compacts-num 2 -- --yolo
```

There is no universal public `Codex credit → dollar` rate, so
`--budget-credits` intentionally requires `--usd-per-credit`. A provider-side
spend limit is still needed for a true money ceiling.

## Install

```bash
uv tool install bound-codex-tokens
bound-codex-tokens --help
```

From a checkout, use `uv tool install .`.

## Examples

Run the normal TUI with explicit limits. `K`, `M`, and `B` are accepted:

```bash
bound-codex-tokens --total-tokens 10M --root-compact-every 800K \
  --subagent-compact-every 500K --max-compacts-num 2 \
  -- --yolo -m gpt-5.6-terra
```

```bash
# Exactly two root compacts means: initial TUI → handoff/restart → handoff/restart → final handoff.
# 245K applies only to root usage; children compact at 500K combined per segment.
# It is also 90% of Codex Sol's 272K default context window.
bound-codex-tokens --total-tokens 10M --root-compact-every 245K \
  --subagent-compact-every 500K --max-compacts-num 2 -- --yolo
```

`--yolo` is passed straight through to Codex and gives it broad authority to
act without asking. Use it only in a workspace and environment you are willing
to let the unattended TUI change.

Customize the bounded handoff (also called a compaction here) independently:

```bash
bound-codex-tokens --total-tokens 10M --root-compact-every 800K \
  --subagent-compact-every 500K --max-compacts-num 2 \
  --compaction-model gpt-5.6-terra --compaction-effort high \
  --compaction-prompt-file ./my-handoff-prompt.md \
  -- --yolo
```

The default prompt is the versioned
[`compaction.md`](bound_codex_tokens_assets/compaction.md) shipped with the
release; the current upstream copy is also available at
`https://raw.githubusercontent.com/garylvov/bound-codex-tokens/main/bound_codex_tokens_assets/compaction.md`.
Use `--compaction-prompt-file` to pin a project-specific prompt. The wrapper
does not use a copied native Codex compaction prompt: native compaction output
is opaque, so this tool supplies only selected user/assistant messages plus a
small manifest to the handoff model.

The TUI’s budget instruction is also a top-level Markdown asset:
[`session.md`](bound_codex_tokens_assets/session.md). It tells Codex the
per-segment budget, remaining total budget, and remaining automatic compacts.

Enable guarded multi-agent v2, permit only Terra or Luna children, and permit
no Sol children:

```bash
bound-codex-tokens --total-tokens 10M --root-compact-every 800K \
  --subagent-compact-every 500K --max-compacts-num 2 \
  --no-fork --max-sol-subagents 0 \
  --allowed-subagent-models gpt-5.6-terra gpt-5.6-luna \
  -- --enable multi_agent_v2 --disable auto_review --yolo -m gpt-5.6-terra \
  -c 'model_reasoning_effort="medium"'
```

`--no-fork` enables `multi_agent_v2` when it is absent and is
idempotent when the normal Codex flag `--enable multi_agent_v2` is already
present. `fork_turns: none` means a child starts without a copy of the parent
conversation history. It prevents a large main context from being charged again
to every delegated child. Use `--max-sol-subagents 2` to allow exactly two Sol
children. Without a v2 policy, Sol is still denied by default; use
`--allow-sol-subagents` only when that is intentional.

`--disable auto_review` is passed to Codex and makes that choice explicit for
these long-running sessions. It is separate from `--yolo`, which controls
approval and sandbox bypass.

The v2 hook also blocks nested `codex exec` calls, because their separate
sessions would evade the wrapper's root-lineage accounting.

## Notes

* `--total-tokens` sums the root TUI and every discovered child session in its
  lineage, including previous TUI segments. The root compact budget counts only
  the active root TUI; the subagent compact budget counts children in the active
  segment. The final handoff is a separate Luna/Terra call and is not part of this total.
  Under `--no-fork`, nested `codex exec` calls are blocked because they would
  evade this lineage. This is a local guardrail, not a claim about final
  provider billing categories.
* The watcher discovers new JSONL session files and polls them every two
  seconds by default (`--poll-seconds`). It can act only after Codex writes a
  `token_count` event, so a running turn can overshoot a threshold. It counts
  a newly spawned child once its parent linkage is written. It cannot safely
  account for an old child session resumed outside this wrapper's new-session
  lineage; do not use native child resume as a way around a budget.
* The wrapper uses the regular Codex TUI, not a replacement client. It does not
  change `~/.codex/config.toml`.
* Run the no-cost checks with `bound-codex-tokens --self-test`.
