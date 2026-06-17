# This is AI generated code
"""Consumer-local ``*.md`` files satisfy markdownlint-cli2.

The gate discovers ``*.md`` via ``git ls-files`` (honoring
``.gitignore``, dropping symlinks and ``exclude_dirs``) and feeds the
explicit list to ``markdownlint-cli2 --no-globs``, so no tree walk
happens and ignored files are never linted. The repo's
``.markdownlint.json`` still supplies the lint rules and the custom
``no-squashed-file-references`` rule.

The subclass below picks up the consumer-configured
``extra-exclude-dirs`` knob from ``[tool.repo-shared.markdown]`` in
the consumer's ``pyproject.toml`` -- the same knob the mdformat gate
reads -- and appends it to the base ``exclude_dirs``, so a directory
excluded from the mdformat gate is excluded from this one too.

Lives under ``_repo_shared/tests/`` in a consumer; pytest finds it
via the ``testpaths`` entry that ``repo-shared init`` injects into
the consumer's ``pyproject.toml``. To adjust the lint rules, edit the
markdownlint config files at the consumer root (themselves symlinks
into ``_repo_shared/dotfiles/``, so the canonical content is
maintained centrally).
"""

from epilatow_repo_shared.config import markdown_overrides
from epilatow_repo_shared.markdown import MarkdownlintCheckBase

_overrides = markdown_overrides()


class TestMarkdownlint(MarkdownlintCheckBase):
    exclude_dirs = (
        *MarkdownlintCheckBase.exclude_dirs,
        *_overrides.extra_exclude_dirs,
    )
