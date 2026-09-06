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

### Reaching an extension-less script

The tools under `files/local/libexec/` are shebang scripts with no `.py`
extension, so the code-quality gate's `*.py` discovery cannot find them by
name. Two ways to expose one:

- `src/<module>.py`, a symlink to the script. The gate lints and type-checks it
  through that path.
- Its real path in `[tool.repo-shared.code-quality] python-targets`.

Only the symlink also gives the script a module name, which is what lets a test
import it rather than load it through `importlib`. `tests/` is not on the
import path for `src/`, so such a test puts it there first:

```python
REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import gas_prices_breakdown as gpb  # noqa: E402
```

Two settings follow from that import. `[tool.mypy] mypy_path` covers the gate,
which type-checks the test without running its `sys.path` line, and whatever
the script imports at module scope has to be in the project `dependencies`,
since the test environment is not the PEP 723 one the script builds for itself.
