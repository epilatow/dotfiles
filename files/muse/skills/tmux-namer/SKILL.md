---
name: tmux-namer
description: Keep the surrounding tmux session named after this Muse session when tmux started this pane with Muse and no other agent already names it.
---

# Tmux Namer

Name the surrounding tmux session after this Muse session.

## When

Run the naming helper once at session start and again every time this
session is renamed. Do nothing when not running inside tmux (`TMUX` or
`TMUX_PANE` is unset): there is no session to name.

## How

Run the helper with this session's current name as the single argument:

```bash
"$HOME/.local/libexec/tmux-agent-session-namer/tmux-agent-session-namer" muse "<this session's name>"
```

The helper decides whether naming happens: it names nothing when tmux
did not start this pane with the `muse` command (for example a shell
where `muse` was typed at the prompt), and it leaves the session alone
when another agent (`claude` or `codex`) already names it. Each run
lands on this agent's own `muse<NN>-<name>` slot, so re-running after a
rename moves the same slot to the new name. To hand a session to a
different agent, unset the owner with
`tmux set-option -u @agent_namer` and start that agent as a pane's own
command.
