from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    # TestClient's context manager runs the lifespan, which builds a fresh
    # StateStore per test. That gives us isolation without extra plumbing.
    with TestClient(app) as c:
        yield c
