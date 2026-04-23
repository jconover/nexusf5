"""FastAPI mock iControl REST server for NexusF5.

Phase 1 topology: one container per device, selected via MOCK_F5_HOSTNAME.
Phase 3 will multiplex — see docs/decisions/001-mock-topology.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import chaos, icontrol
from app.state import build_store_from_env


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.store = build_store_from_env()
    yield


app = FastAPI(
    title="NexusF5 Mock iControl REST",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(icontrol.router)
app.include_router(chaos.router)
