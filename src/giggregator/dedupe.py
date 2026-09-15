"""Dedupe stage 1 (cheap): canonical key on normalized company+title tokens.

Stage 2 (embedding similarity) arrives with phase-1 models; the DB unique index on
dedupe_key makes merges collision-free in the meantime.
"""

from __future__ import annotations

import re


def dedupe_key(company: str, title: str) -> str:
    text = f"{company or ''} {title or ''}".lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    # sorted set -> order-insensitive; cap length -> robust to boilerplate suffixes
    return " ".join(sorted(set(tokens))[:24])
