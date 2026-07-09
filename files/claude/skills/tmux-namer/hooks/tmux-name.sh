#!/bin/sh
# Make the surrounding tmux SESSION track the Claude Code conversation
# title (published live as the pane title). The name is "claudeNN-<title>":
# NN is a stable two-digit slot assigned once per session (lowest free
# 00-99, recycled as sessions end), the title has its leading spinner glyph
# stripped and spaces turned to dashes, and the whole is capped at 30 chars.
# Also tidies this session's status bar so the name is not clipped and not
# duplicated in the right-hand segment. Stdin carries the hook JSON payload;
# unused here.

[ -n "$TMUX" ] || exit 0

# Assign a slot number once, remembered in a session user-option so it stays
# fixed across title changes and a re-fired SessionStart on resume. Slots
# are read back from every session's option, so a number frees the moment
# its session ends and is reused by the next new session.
num=$(tmux show-options -qv @claude_num 2>/dev/null)
if [ -z "$num" ]; then
    used=$(tmux list-sessions -F '#{@claude_num}' 2>/dev/null | grep -E '^[0-9]+$')
    n=0
    while [ "$n" -le 99 ]; do
        num=$(printf '%02d' "$n")
        printf '%s\n' "$used" | grep -qx "$num" && n=$((n + 1)) || break
    done
    tmux set-option @claude_num "$num"
fi

# "claudeNN-" + title (spinner stripped, spaces dashed), capped at 30 chars.
name='#{=30:claude#{@claude_num}-#{s| |-|:#{s|^. ||:pane_title}}}'

# Rename this session on each pane-title change, guarded against an empty
# result, scoped to this session so other tmux sessions are untouched.
tmux set-hook pane-title-changed "if -F \"$name\" \"rename-session \\\"$name\\\"\""

# Fit "[claudeNN-...]" without clipping, and drop the default status-right
# copy of pane_title (the session name already shows it). Session-scoped.
tmux set-option status-left-length 34
tmux set-option status-right '#{?window_bigger,[#{window_offset_x}#,#{window_offset_y}] ,}%H:%M %d-%b-%y'

exit 0
