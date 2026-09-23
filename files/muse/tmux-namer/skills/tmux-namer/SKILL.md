---
name: tmux-namer
description: Name the surrounding tmux session after this Muse session. Always call read_skill for tmux-namer at session start and after every session rename when running inside tmux.
---

# Tmux Namer

Name the surrounding tmux session after this Muse session.

## When

Call this skill at session start and again every time this session is
renamed. Do nothing when not running inside tmux (`TMUX` or `TMUX_PANE`
is unset): there is no session to name.

## How

Run the helper with this session's current name as the single argument:

```bash
UV_CACHE_DIR="${TMPDIR:-/tmp}/tmux-agent-session-namer-uv" "$HOME/.local/libexec/tmux-agent-session-namer/tmux-agent-session-namer" muse "<this session's name>"
```

The helper reaches tmux through the session's server socket, so the
tool call must declare that socket in `unix_socket_paths` (find it
under `/tmp/tmux-$(id -u)/`, resolving `/tmp` to its real path), and
the first run prompts for approval. `UV_CACHE_DIR` must point
somewhere the sandbox can write: the helper runs through
`uv run --script`, whose default cache is not writable there.

The helper decides whether naming happens: it names nothing when tmux
did not start this pane with the `muse` command (for example a shell
where `muse` was typed at the prompt), and it leaves the session alone
when another agent (`claude` or `codex`) already names it. Each run
lands on this agent's own `muse<NN>-<name>` slot, so re-running after a
rename moves the same slot to the new name. To hand a session to a
different agent, unset the owner with
`tmux set-option -u @agent_namer` and start that agent as a pane's own
command.
