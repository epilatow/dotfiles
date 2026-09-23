---
description: Run repo-shared's independent code review gate
---

# Independent Code Review

Read and follow the first available skill entrypoint in this order:

1. `.agents/skills/repo-shared-independent-code-review/SKILL.md` in the current
   repository.
2. `~/.agents/skills/repo-shared-independent-code-review/SKILL.md` in the home
   directory.

Prefer the repository-local entrypoint when both exist. If neither exists,
report the gate as blocked. Do not use a copy found at any other path. If
repository policy requires the repository-local entrypoint, do not use the
home-directory fallback when that entrypoint is absent; report the gate as
blocked instead.
