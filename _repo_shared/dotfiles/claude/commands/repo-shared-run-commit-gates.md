---
description: Run all required gates on one exact commit
---

# Run Gates on One Commit

Read and follow the first available skill entrypoint in this order:

1. `.agents/skills/repo-shared-run-commit-gates/SKILL.md` in the current
   repository.
2. `~/.agents/skills/repo-shared-run-commit-gates/SKILL.md` in the home
   directory.

Prefer the repository-local entrypoint when both exist. If neither exists, stop
before running scoped development checks or the final landing suite. Do not use
a copy found at any other path.
