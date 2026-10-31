# This is AI generated code
"""The consumer leaves the packages repo-shared pins free to move.

Lives under ``_repo_shared/tests/`` in a consumer; pytest finds it
via the ``testpaths`` entry that ``repo-shared init`` injects into
the consumer's ``pyproject.toml``. The body subclasses the shared
base, which fails any entry in the consumer's ``pyproject.toml`` that
could block a future bump of a package repo-shared pins, or replace
that pin. The base ``pytest.skip``s when running from the repo-shared
source clone itself, where those pins are the source.
"""

from epilatow_repo_shared.tool_pins import ToolPinsBase


class TestToolPins(ToolPinsBase):
    pass
