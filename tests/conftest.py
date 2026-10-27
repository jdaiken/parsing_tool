"""Shared setup: tests import the app's modules from the repository root and read the demo case."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEMO = ROOT / "demo"


@pytest.fixture(scope="session")
def parse():
    """parse('1_checking_2025-03.pdf') -> ParseResult, cached for the test run."""
    from statement_parser import parse_statement

    cache = {}

    def _parse(name: str):
        """Parse a demo file (or a file in the repository root) once per test run."""
        if name not in cache:
            path = DEMO / name if (DEMO / name).exists() else ROOT / name
            cache[name] = parse_statement(path.stem, path.read_bytes())
        return cache[name]

    return _parse
