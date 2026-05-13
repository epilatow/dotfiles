# This is AI generated code
"""Consumer-local ``*.md`` real files match canonical mdformat output.

Walks real-file ``*.md`` under the repo root, skipping symlinks (the
canonical-path symlinks into ``_repo_shared/`` would double-count
vendored content otherwise) and the ``_repo_shared/`` prefix itself
(vendored content is gated by the drift test).

The subclass below picks up consumer-configured knobs from
``[tool.repo-shared.markdown]`` in the consumer's
``pyproject.toml`` -- recognised keys:

- ``wrap`` (int, default 79) -- ``mdformat --wrap`` value.
- ``extra-exclude-dirs`` (list[str], default ``[]``) -- appended
  to the base default set; never replaces, so the shared baseline
  (``_repo_shared/``, ``node_modules/`` etc.) keeps applying.
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
