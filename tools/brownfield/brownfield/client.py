"""Thin iControl REST HTTP client.

Wraps httpx with the small amount of F5-specific knowledge the walker
needs:

- A device-scoped base_url (for real F5: `https://bigip-dc1-042.example.net`;
  for the multiplexed mock: `http://localhost:8100/bigip-lab-01`).
- A `get(path)` that returns parsed JSON or raises on non-2xx.
- A `follow_link(href)` that re-anchors an F5 selfLink/reference URL onto
  the configured base_url. Real F5 returns selfLinks with the device's
  own hostname (`https://bigip-lab-01/mgmt/...`); we treat those as
  path+query carriers, not absolute navigation targets, so the same
  client works against any base_url shape.

Single-process, single-threaded by design per ADR 007 §Out of scope
("No fleet-scale concurrency"). One device at a time. No async, no
worker pool.

Auth is HTTP Basic by default — real F5 supports HTTP Basic and token
auth, mock-f5 currently authenticates nothing. The client accepts an
auth tuple and forwards it to httpx; callers pass None against the mock.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any
from urllib.parse import urlparse

import httpx


class IControlRestClient:
    """Device-scoped iControl REST client.

    Use as a context manager so the underlying httpx.Client gets cleanly
    closed:

        with IControlRestClient("http://localhost:8100/bigip-lab-01") as c:
            virtuals = c.get("/mgmt/tm/ltm/virtual")
    """

    def __init__(
        self,
        base_url: str,
        *,
        auth: tuple[str, str] | None = None,
        verify: bool | str = True,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # If a caller injects a pre-built httpx.Client (or a subclass like
        # FastAPI's TestClient), use it as-is and don't own its lifecycle.
        # Production callers pass None and we build a real HTTP client
        # bound to base_url; tests pass a TestClient(app, base_url=...)
        # so the walker runs against the in-process ASGI app without
        # spinning up uvicorn. This is the same DI pattern observability/
        # ingest uses for its Pushgateway client.
        if http_client is not None:
            self._client = http_client
            self._owns_client = False
        else:
            self._client = httpx.Client(
                base_url=self._base_url,
                auth=auth,
                verify=verify,
                timeout=timeout,
            )
            self._owns_client = True

    def __enter__(self) -> IControlRestClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying httpx.Client only if we own it.
        Injected clients are the caller's responsibility — closing them
        here would invalidate other consumers (e.g. the test fixture).
        """
        if self._owns_client:
            self._client.close()

    def get(self, path: str) -> Any:
        """GET <base_url><path> and return parsed JSON.

        Raises httpx.HTTPStatusError on non-2xx — the walker treats any
        non-2xx as a discovery failure rather than papering over with
        defaults. The exception carries the response so callers can
        introspect F5's error envelope if they need to.
        """
        r = self._client.get(path)
        r.raise_for_status()
        return r.json()

    def follow_link(self, link: str) -> Any:
        """Re-anchor an F5 selfLink/reference URL onto base_url and GET it.

        F5 returns links like
        `https://<device-hostname>/mgmt/tm/.../<name>?ver=17.1.0`. The
        host portion is informational — we keep only the path+query and
        let httpx prepend our configured base_url. This way the walker
        doesn't care whether base_url is a mock prefix or a real device
        DNS name.
        """
        return self.get(_path_from_link(link))


def _path_from_link(link: str) -> str:
    """Extract the path+query portion of an F5 link URL.

    Examples:
      https://bigip-lab-01/mgmt/tm/ltm/pool/~Common~p/members?ver=17.1.0
        -> /mgmt/tm/ltm/pool/~Common~p/members?ver=17.1.0
      /mgmt/tm/already-relative -> /mgmt/tm/already-relative
    """
    parsed = urlparse(link)
    path = parsed.path
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path
