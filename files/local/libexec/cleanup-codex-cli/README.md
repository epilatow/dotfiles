# Codex CLI cleanup

Prune superseded standalone Codex CLI installations without touching
conversation history, databases, plugins, or credentials.

Run a preview:

```sh
~/.local/libexec/cleanup-codex-cli/cleanup-codex-cli
```

Pass `--apply` to delete the listed eligible releases. `--codex-home PATH`
selects a different Codex data directory; otherwise `CODEX_HOME` or `~/.codex`
is used. Requires `lsof` and a Unix platform with file locking.

The latest installed stable version for each platform target, the `current`
symlink target, and every release reported in use are preserved. Unknown or
incomplete release directories are left alone. An installation lock in use
defers cleanup; a failed activity check or invalid installation layout fails
the command. Activity is checked again immediately before each deletion. A
process starting an old release after that check is still a race; avoid
launching explicit superseded release paths during cleanup.
