"""FastAPI mock iControl REST server for NexusF5.

Phase 3 topology: a single container multiplexes many devices keyed by the
first URL path segment (`/{hostname}/mgmt/tm/...`). Startup either loads a
JSON manifest (`MOCK_F5_MANIFEST`) or falls back to a single device from
`MOCK_F5_HOSTNAME` / `MOCK_F5_VERSION` — the latter keeps the in-process
test fixture fast and self-contained. See docs/decisions/001-mock-topology.md.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import chaos, icontrol
from app.state import build_store_from_env, build_store_from_manifest


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    manifest = os.environ.get("MOCK_F5_MANIFEST")
    if manifest:
        app.state.store = build_store_from_manifest(manifest)
    else:
        app.state.store = build_store_from_env()
    yield


app = FastAPI(
    title="NexusF5 Mock iControl REST",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(icontrol.router)
app.include_router(chaos.router)
