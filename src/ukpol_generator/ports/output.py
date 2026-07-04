"""Port for persisting the rendered AutoModerator rules document."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path


@runtime_checkable
class RuleOutput(Protocol):
    """A destination for the rendered rules document."""

    def write(self, document: str) -> Path:
        """Persist the rendered document and return the path written.

        Args:
            document: The full rendered YAML document.

        Returns:
            The filesystem path the document was written to.
        """
        ...
