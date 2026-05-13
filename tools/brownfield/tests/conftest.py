"""Pytest fixtures for the brownfield extractor.

The `mock_client` fixture wires FastAPI's TestClient into the mock-f5
ASGI app so the walker runs hermetically in-process — no uvicorn, no
docker, no real socket. TestClient is an `httpx.Client` subclass that
runs FastAPI lifespan events and dispatches requests directly to the
ASGI app, so the walker's sync httpx surface works against it without
any async refactor. mock-f5 is imported via the `pythonpath` shim in
pyproject.toml.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from brownfield.client import IControlRestClient


@pytest.fixture
def mock_client() -> Iterator[IControlRestClient]:
    """An IControlRestClient bound to the in-process mock-f5 app.

    base_url's `/bigip-lab-01` suffix is the multiplexing prefix for
    the bootstrap device that mock-f5's lifespan registers from env
    (see mock-f5/app/state.py::build_store_from_env). TestClient's
    own base_url defaults to http://testserver; we append the device
    hostname so the walker's path-relative GETs land on the right
    multiplexed device.
    """
    # Imported inside the fixture so collection doesn't fail if a future
    # refactor breaks the mock-f5 import path — the failure surfaces on
    # the specific tests that need the mock, not on every collection.
    from app.main import app

    with TestClient(app, base_url="http://testserver/bigip-lab-01") as tc:
        client = IControlRestClient("http://testserver/bigip-lab-01", http_client=tc)
        yield client
        client.close()
