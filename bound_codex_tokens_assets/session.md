The root TUI has {root_compact_every_tokens} reported tokens before this TUI
segment is automatically summarized into a handoff. The supervised workflow has
a global reported-token limit of {total_tokens}; this configuration permits at
most {effective_cap_tokens} before its compact-count limit. Approximately
{remaining_tokens} remain under the global limit. Subagents in this segment trigger a handoff after
{subagent_compact_every_tokens} aggregate reported tokens. There are
{compacts_remaining} automatic compacts remaining after this segment.

Work normally, but keep decisions, tests, changes, blockers, and the next exact
step clear enough for a short handoff. When the boundary is reached, preserve
the work in the conversation; the wrapper will create the handoff and reopen a
fresh TUI.
