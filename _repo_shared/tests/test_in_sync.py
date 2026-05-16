# This is AI generated code
"""Canonical-path entries are in sync with the shared upstreams.

Lives under ``_repo_shared/tests/`` in a consumer; pytest finds it
via the ``testpaths`` entry that ``repo-shared init`` injects into
the consumer's ``pyproject.toml``. The body subclasses the shared
base, which compares every canonical-path entry against its upstream:
``files`` / ``dotfiles`` (symlink kinds) must resolve to the
vendored copy; ``templates`` / ``dottemplates`` (template kinds)
must byte-match the upstream. ``.repo-shared-ignore`` skips an entry.
repo-shared dogfoods its own shared symlinks and template copies
(``CLAUDE.md`` / ``.gitignore``) through the same base.
"""

from epilatow_repo_shared.vendor import InSyncBase


class TestInSync(InSyncBase):
    pass
