# This is AI generated code
"""Consumer-local ``*.md`` files satisfy markdownlint-cli2.

markdownlint-cli2 follows the repo's ``.markdownlint.json`` config
plus ``.markdownlint-cli2.jsonc`` to scope which files are linted; the
typical scope excludes ``_repo_shared/`` so vendored content isn't
double-checked here.

Lives under ``_repo_shared/tests/`` in a consumer; pytest finds it
via the ``testpaths`` entry that ``repo-shared init`` injects into
the consumer's ``pyproject.toml``. To customise scope, edit the
markdownlint config files at the consumer root (themselves symlinks
into ``_repo_shared/dotfiles/``, so the canonical content is
maintained centrally).
"""

from epilatow_repo_shared.markdown import MarkdownlintCheckBase


class TestMarkdownlint(MarkdownlintCheckBase):
    pass
