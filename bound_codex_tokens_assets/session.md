The root TUI has {root_compact_every_tokens} reported tokens before this TUI
segment is automatically summarized into a handoff. The supervised workflow has
a total reported-token limit of {total_tokens}; approximately {remaining_tokens}
remain. Subagents have a separate aggregate limit of {subagent_total_tokens};
approximately {subagent_remaining_tokens} remain. There are
{compacts_remaining} automatic compacts remaining after this segment.

Work normally, but keep decisions, tests, changes, blockers, and the next exact
step clear enough for a short handoff. When the boundary is reached, preserve
the work in the conversation; the wrapper will create the handoff and reopen a
fresh TUI.
