"""FastAPI dependencies: resolve the StateStore and the active DeviceState.

The iControl REST router is prefixed with `/{hostname}/mgmt/tm`, so every
request carries the target device's hostname in `request.path_params`.
`get_device` reads it and looks up the state; unknown hostnames 404.

See docs/decisions/001-mock-topology.md.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.state import DeviceState, StateStore


def get_store(request: Request) -> StateStore:
    return request.app.state.store  # type: ignore[no-any-return]


def get_device(request: Request) -> DeviceState:
    store: StateStore = request.app.state.store
    hostname = request.path_params.get("hostname")
    if hostname is None:
        raise RuntimeError(
            "get_device requires {hostname} in the route prefix; "
            "the iControl REST router mounts at /{hostname}/mgmt/tm."
        )
    if not store.has(hostname):
        raise HTTPException(status_code=404, detail=f"unknown device: {hostname}")
    return store.get(hostname)


StoreDep = Annotated[StateStore, Depends(get_store)]
DeviceDep = Annotated[DeviceState, Depends(get_device)]
