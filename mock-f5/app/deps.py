"""FastAPI dependencies: resolve the StateStore and the active DeviceState.

Phase 3 refactor point: `get_device` switches from `store.primary()` to
Host-header-based lookup. The rest of the app does not care.
See docs/decisions/001-mock-topology.md.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.state import DeviceState, StateStore


def get_store(request: Request) -> StateStore:
    return request.app.state.store  # type: ignore[no-any-return]


def get_device(request: Request) -> DeviceState:
    store: StateStore = request.app.state.store
    return store.primary()


StoreDep = Annotated[StateStore, Depends(get_store)]
DeviceDep = Annotated[DeviceState, Depends(get_device)]
