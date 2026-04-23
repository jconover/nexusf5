"""Integration-test fixtures.

Auto-skips every test in this directory when the mock stack isn't reachable,
so `pytest` without `make mock-up` still produces a green unit run. `make
test` brings the stack up first, so these tests do run as part of the
default workflow.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator

import httpx
import pytest

from tests.integration.helpers import mock_reachable, reset_device


@pytest.fixture(scope="session")
def mock_stack_up() -> bool:
    return mock_reachable()


@pytest.fixture(autouse=True)
def _require_mock_stack(mock_stack_up: bool) -> None:
    if not mock_stack_up:
        pytest.skip("mock stack not running — run `make mock-up`")


@pytest.fixture
def reset_device_fixture() -> Generator[Callable[[str], None], None, None]:
    """Reset a device to fresh state and clean up on teardown.

    Tests may fail mid-flight and leave chaos set; the teardown reset makes
    the next test robust to that.
    """
    touched: list[str] = []

    def _reset(hostname: str) -> None:
        reset_device(hostname)
        touched.append(hostname)

    yield _reset
    for hostname in touched:
        with contextlib.suppress(httpx.HTTPError):
            reset_device(hostname)
