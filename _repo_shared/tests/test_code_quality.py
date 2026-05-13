# This is AI generated code
"""Lint + type-check every Python file in the repo.

Auto-discovers every ``.py`` under the consumer repo root (skipping
``_repo_shared/``, ``.venv/``, ``__pycache__/``, ...). Each
discovered file becomes one parametrize case per tool, with the
file path as the pytest ID so failures point straight at the
offending file.

Three consumer-side customisation knobs, all optional, all under
``[tool.repo-shared.code-quality]`` in pyproject:

- ``python-targets`` is *additive* to discovery -- list explicit
  file paths for extension-less shebang scripts (``bin/foo``) that
  ``rglob("*.py")`` cannot find. Discovery does not need pyproject
  configuration to cover regular ``.py`` files.
- ``extra-exclude-dirs`` appends to the discovery exclude list
  (which already covers ``_repo_shared/``, ``.venv/``,
  ``__pycache__/``, etc.). Use to skip per-repo dirs like vendored
  third-party Python or generated code.
- ``mypy-extra-deps`` + ``mypy-python-version`` supply project-wide
  fallback mypy ``--with`` deps / ``--python-version`` for files
  *without* a PEP 723 ``# /// script`` block. A file with PEP 723
  uses its own ``dependencies`` and ``requires-python``.

Adding a new module / script that needs project-wide-default mypy
behavior just lands the file -- no pyproject edit needed. Files
needing extra mypy deps put a PEP 723 block at the top instead of
editing a centralised list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from epilatow_repo_shared.config import code_quality_overrides
from epilatow_repo_shared.python_quality import (
    DEFAULT_IGNORED_DIRS,
    ResolvedFile,
    discover_python_files,
    resolve_files,
    run_mypy_strict,
    run_ruff_format_check,
    run_ruff_lint,
    validate_additional_targets,
)


def _consumer_repo_root() -> Path:
    """Walk up from ``cwd`` to the consumer repo root.

    ``Path(__file__).resolve()`` would follow into the vendored
    tree; the consumer pyproject lives at the workspace root, so
    walking up from cwd finds the right spot.
    """
    here = Path.cwd()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return here


REPO_ROOT = _consumer_repo_root()
_OVERRIDES = code_quality_overrides(REPO_ROOT)
_IGNORED_DIRS = (
    *DEFAULT_IGNORED_DIRS,
    *_OVERRIDES.extra_exclude_dirs,
)


def _build_targets() -> list[ResolvedFile]:
    discovered = discover_python_files(REPO_ROOT, exclude_dirs=_IGNORED_DIRS)
    targets = sorted(set(discovered) | set(_OVERRIDES.additional_targets))
    return resolve_files(
        REPO_ROOT,
        discovered=targets,
        default_deps=_OVERRIDES.mypy_extra_deps,
        default_python_version=_OVERRIDES.mypy_python_version,
    )


_TARGETS: list[ResolvedFile] = _build_targets()


def _id(rf: ResolvedFile) -> str:
    return rf.path


def test_python_targets_well_formed() -> None:
    """``[tool.repo-shared.code-quality] python-targets`` entries are sane.

    Catches typos / renamed / removed files and entries that name
    ``.py`` files (which are already auto-discovered, so listing them
    here is dead weight). Surfacing this as a real test makes the
    misconfiguration loud rather than letting ruff / mypy emit
    "file not found" mid-suite.
    """
    errors = validate_additional_targets(
        REPO_ROOT,
        additional_targets=_OVERRIDES.additional_targets,
    )
    if errors:
        raise AssertionError(
            "[tool.repo-shared.code-quality] python-targets has "
            "errors:\n\n" + "\n".join(f"- {e}" for e in errors)
        )


@pytest.mark.parametrize("rf", _TARGETS, ids=_id)
def test_ruff_lint(rf: ResolvedFile) -> None:
    run_ruff_lint([rf.path], cwd=REPO_ROOT)


@pytest.mark.parametrize("rf", _TARGETS, ids=_id)
def test_ruff_format(rf: ResolvedFile) -> None:
    run_ruff_format_check([rf.path], cwd=REPO_ROOT)


@pytest.mark.parametrize("rf", _TARGETS, ids=_id)
def test_mypy_strict(rf: ResolvedFile) -> None:
    run_mypy_strict(
        [rf.path],
        cwd=REPO_ROOT,
        extra_deps=rf.deps,
        python_version=rf.python_version,
    )
