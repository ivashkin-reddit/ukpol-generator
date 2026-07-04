"""Use case: generate AutoModerator rules from a contact source into an output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ukpol_generator.domain.rules import collect, render_document

if TYPE_CHECKING:
    from pathlib import Path

    from ukpol_generator.ports.contacts import MemberContactSource
    from ukpol_generator.ports.output import RuleOutput


@dataclass(frozen=True)
class GenerateResult:
    """Outcome of a rule-generation run.

    Attributes:
        output_path: Where the rendered rules document was written.
        accounts_per_platform: Whitelisted account count per platform.
    """

    output_path: Path
    accounts_per_platform: dict[str, int]


@dataclass(frozen=True)
class GenerateRulesService:
    """Generate the rules document from a contact source and write it out.

    Attributes:
        source: The contact source (e.g. the cached JSON store).
        output: The destination for the rendered rules document.
    """

    source: MemberContactSource
    output: RuleOutput

    def run(self) -> GenerateResult:
        """Load members, render the rules, write them, and report the counts."""
        members = self.source.load_members()
        whitelist = collect(members)
        document = render_document(whitelist)
        output_path = self.output.write(document)
        accounts_per_platform = {platform: len(entries) for platform, entries in whitelist.items()}
        return GenerateResult(
            output_path=output_path,
            accounts_per_platform=accounts_per_platform,
        )
