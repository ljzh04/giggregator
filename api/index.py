"""Vercel serverless entry for the Giggregator web app.

Seeded read-only snapshot: on cold start the bundled seed/seed.db is copied to
/tmp (the only writable dir on serverless) and served from there. No ingest
runs here — the live DB stays local until Turso env vars are configured.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

_SEED = os.path.join(_ROOT, "seed", "seed.db")
_RUNTIME_DB = os.path.join(tempfile.gettempdir(), "giggregator.db")

if os.environ.get("GIGGREGATOR_TURSO_DATABASE_URL") or os.environ.get("TURSO_DATABASE_URL"):
    pass  # ADR-0011 remote backend takes precedence inside db.connect(); no seed needed.
else:
    if not os.path.exists(_RUNTIME_DB):
        shutil.copyfile(_SEED, _RUNTIME_DB)
    os.environ.setdefault("GIGGREGATOR_DB", _RUNTIME_DB)

from giggregator.web import app as fastapi_app  # noqa: E402


async def app(scope, receive, send):
    """ASGI entry: strip the /api/index function prefix Vercel invokes us under."""
    if scope.get("type") == "http":
        path = scope.get("path", "")
        if path == "/api/index" or path.startswith("/api/index/"):
            rest = path[len("/api/index") :] or "/"
            scope = {**scope, "path": rest, "raw_path": rest.encode()}
    await fastapi_app(scope, receive, send)
