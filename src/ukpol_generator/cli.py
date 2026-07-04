"""Command-line driving adapter that wires adapters to application services.

Two subcommands make the network fetch and the offline generation independent:

- ``fetch``: pull current MPs/Lords and their contacts from the Parliament API
  and cache them as a raw JSON dump.
- ``generate``: read the cached dump and write the AutoModerator rules document
  into the output directory (``output/`` by default).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ukpol_generator.adapters.json_store import JsonContactStore
from ukpol_generator.adapters.parliament_api import ParliamentApiContactSource
from ukpol_generator.adapters.yaml_output import (
    DEFAULT_FILENAME,
    DEFAULT_OUTPUT_DIR,
    YamlRuleOutput,
)
from ukpol_generator.application.fetch_contacts import FetchContactsService
from ukpol_generator.application.generate_rules import GenerateRulesService
from ukpol_generator.ports.contacts import ContactSourceError

if TYPE_CHECKING:
    from collections.abc import Sequence

_logger = logging.getLogger(__name__)

DEFAULT_RAW_FILE = Path("mp_lords_contacts_raw.json")


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with the ``fetch`` and ``generate`` commands."""
    parser = argparse.ArgumentParser(prog="ukpol-generator", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser(
        "fetch",
        help="Fetch raw member contacts from the Parliament API into a JSON dump.",
    )
    _ = fetch.add_argument(
        "--output",
        default=str(DEFAULT_RAW_FILE),
        help=f"Raw contacts JSON path (default: {DEFAULT_RAW_FILE}).",
    )

    generate = subparsers.add_parser(
        "generate",
        help="Generate AutoModerator rules from a cached contacts JSON dump.",
    )
    _ = generate.add_argument(
        "--input",
        default=str(DEFAULT_RAW_FILE),
        help=f"Raw contacts JSON path (default: {DEFAULT_RAW_FILE}).",
    )
    _ = generate.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory for the generated rules (default: {DEFAULT_OUTPUT_DIR}).",
    )
    _ = generate.add_argument(
        "--filename",
        default=DEFAULT_FILENAME,
        help=f"Generated rules filename (default: {DEFAULT_FILENAME}).",
    )

    run = subparsers.add_parser(
        "run",
        help="Fetch contacts from the API and generate rules in one step.",
    )
    _ = run.add_argument(
        "--output",
        default=str(DEFAULT_RAW_FILE),
        help=f"Raw contacts JSON cache path (default: {DEFAULT_RAW_FILE}).",
    )
    _ = run.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory for the generated rules (default: {DEFAULT_OUTPUT_DIR}).",
    )
    _ = run.add_argument(
        "--filename",
        default=DEFAULT_FILENAME,
        help=f"Generated rules filename (default: {DEFAULT_FILENAME}).",
    )
    return parser


def _run_fetch(raw_path: Path) -> int:
    """Fetch contacts from the Parliament API and cache them to ``raw_path``."""
    service = FetchContactsService(
        source=ParliamentApiContactSource(),
        sink=JsonContactStore(path=raw_path),
    )
    try:
        result = service.run()
    except ContactSourceError:
        _logger.exception("Fetch incomplete - aborting; existing cache left untouched")
        return 1
    _logger.info(
        "Wrote %d members (%d contact records) to %s",
        result.member_count,
        result.contact_count,
        result.output_path,
    )
    return 0


def _run_generate(raw_path: Path, output_dir: Path, filename: str) -> int:
    """Generate the rules document from the cached dump into ``output_dir``."""
    service = GenerateRulesService(
        source=JsonContactStore(path=raw_path),
        output=YamlRuleOutput(directory=output_dir, filename=filename),
    )
    result = service.run()
    _logger.info("Wrote %s", result.output_path)
    for platform, count in result.accounts_per_platform.items():
        _logger.info("  %s: %d", platform, count)
    return 0


def _run_all(raw_path: Path, output_dir: Path, filename: str) -> int:
    """Fetch and cache contacts, then generate rules \u2014 the full pipeline."""
    try:
        fetch_result = FetchContactsService(
            source=ParliamentApiContactSource(),
            sink=JsonContactStore(path=raw_path),
        ).run()
    except ContactSourceError:
        _logger.exception("Fetch incomplete - aborting; no rules generated")
        return 1
    _logger.info(
        "Fetched %d members (%d contact records) to %s",
        fetch_result.member_count,
        fetch_result.contact_count,
        fetch_result.output_path,
    )
    return _run_generate(raw_path, output_dir, filename)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        The process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _build_parser().parse_args(argv)
    if args.command == "fetch":
        return _run_fetch(Path(args.output))
    if args.command == "run":
        return _run_all(Path(args.output), Path(args.output_dir), str(args.filename))
    return _run_generate(Path(args.input), Path(args.output_dir), str(args.filename))


if __name__ == "__main__":
    raise SystemExit(main())
