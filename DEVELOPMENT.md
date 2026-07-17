# Development Guide

Repo-specific development conventions for working in this repo. The companion
shared / cross-repo files cover what every epilatow repo inherits from
`epilatow/repo-shared`:

- [DEVELOPMENT_SHARED.md](DEVELOPMENT_SHARED.md) -- shared conventions for
  humans + agents (file shebangs, ASCII-only rule, comment style, Python
  conventions, markdown style, doc-sync rule, commit-message hygiene).
- [DEVELOPMENT_AGENT.md](DEVELOPMENT_AGENT.md) -- repo-specific agent
  conventions (this file's agent-side companion).
- [DEVELOPMENT_SHARED_AGENT.md](DEVELOPMENT_SHARED_AGENT.md) -- shared agent
  conventions (plan-first protocol, SCM rules, code-review protocol).

**Repo-level conventions in this file take precedence over the shared files on
conflict.** The shared files are vendored from `epilatow/repo-shared` under
`_repo_shared/` and updated via `_repo_shared/repo-shared upgrade`.

## Testing

Run the complete shared and repository-local test suite with:

```sh
uv run pytest
```

Repository-local tests live under `tests/`.
