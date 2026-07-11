"""Configuration errors carrying file and field context.

A bad config must fail fast with a human-readable error, never crash
mid-drive (docs/ARCHITECTURE.md §Configuration).
"""

from pathlib import Path


class ConfigError(Exception):
    """A config file is missing, unparseable, or failed schema validation.

    Carries the offending file and one problem string per fault
    (``"<dotted.field.path>: <message>"`` for validation faults) so the CLI
    can print a readable report instead of a pydantic traceback.
    """

    def __init__(self, file: str | Path, problems: str | list[str]) -> None:
        """Build the error from the offending file and its problem list."""
        self.file = str(file)
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        detail = "\n".join(f"  - {problem}" for problem in self.problems)
        super().__init__(f"Invalid config: {self.file}\n{detail}")
