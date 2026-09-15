"""Shared test helpers. Iron rule 5: no network in tests — fixtures only."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = ROOT / "tests" / "fixtures" / "sources"

# adapter id -> (fixture relative path, parse payload type)
FIXTURE_FILES = {
    "remotive": ("remotive", "remotive_20260915_01.json"),
    "jobicy": ("jobicy", "jobicy_20260915_01.json"),
    "arbeitnow": ("arbeitnow", "arbeitnow_20260915_01.json"),
    "onlinejobs_ph": ("onlinejobs_ph", "onlinejobs_ph_20260915_01.html"),
    "jooble_ph": ("jooble_ph", "jooble_ph_20260916_01.json"),
}


def fixture_bytes(relative: str) -> bytes:
    return (FIXTURES / relative).read_bytes()


def fixture_text(relative: str) -> str:
    return (FIXTURES / relative).read_text(encoding="utf-8", errors="replace")
