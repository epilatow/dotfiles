# This is AI generated code
"""Vendored ``_repo_shared/`` matches the pinned package content.

Lives under ``_repo_shared/tests/`` in a consumer; pytest finds it
via the ``testpaths`` entry that ``repo-shared init`` injects into
the consumer's ``pyproject.toml``. The body subclasses the shared
base, which walks every ``shared/`` file in the installed
``epilatow_repo_shared`` package and asserts the consumer's
``_repo_shared/`` copy matches byte-for-byte. The base ``pytest.skip``s
when running from the repo-shared source clone itself (where the
``_repo_shared/`` copy doesn't exist by design).
"""

from epilatow_repo_shared.vendor import VendorDriftBase


class TestRepoSharedDrift(VendorDriftBase):
    pass
