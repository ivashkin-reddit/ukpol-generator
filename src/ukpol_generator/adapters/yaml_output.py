"""Filesystem adapter that writes the rendered rules document into a directory.

Implements :class:`RuleOutput`. The output directory (``output/`` by default) is
created on demand so a clean checkout can generate rules without manual setup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_FILENAME = "generated-social-rules.yaml"


@dataclass(frozen=True)
class YamlRuleOutput:
    """Write the rendered rules document to ``directory / filename``.

    Attributes:
        directory: The directory the document is written into.
        filename: The document filename.
    """

    directory: Path = DEFAULT_OUTPUT_DIR
    filename: str = DEFAULT_FILENAME

    def write(self, document: str) -> Path:
        """Write the document, creating the output directory if needed."""
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / self.filename
        _ = destination.write_text(document, encoding="utf-8")
        return destination
