# This is AI generated code
"""Consumer-local ``*.md`` real files match canonical mdformat output.

Walks tracked real-file ``*.md`` under the repo root, plus a
tracked-but-skip post-filter that defaults to ``_repo_shared/``
(vendored content gated by the drift test) and skips symlinks
(canonical-path symlinks into ``_repo_shared/`` would otherwise
double-count vendored content).

The subclass below picks up consumer-configured knobs from
``[tool.repo-shared.markdown]`` in the consumer's
``pyproject.toml`` -- recognised keys:

- ``wrap`` (int, default 79) -- ``mdformat --wrap`` value.
- ``extra-exclude-dirs`` (list[str], default ``[]``) -- appended
  to the base default set.
"""

from epilatow_repo_shared.config import markdown_overrides
from epilatow_repo_shared.markdown import MdformatCheckBase

_overrides = markdown_overrides()


class TestMarkdownFormat(MdformatCheckBase):
    wrap = _overrides.wrap
    exclude_dirs = (
        *MdformatCheckBase.exclude_dirs,
        *_overrides.extra_exclude_dirs,
    )
