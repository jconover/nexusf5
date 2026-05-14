"""LTM + system-DO walker.

Drives an `IControlRestClient` across the iControl REST endpoint families
the brownfield extractor needs and returns a structured raw-data
dictionary. Emission to AS3/DO declarations is a *separate* layer (next
checkpoint) — the walker's job stops at "give me everything I'll need to
emit, normalized only as much as HTTP transport noise demands."

Normalization choices (Checkpoint 2 surface — call out at review):

  - Collection envelopes (kind/selfLink/items) are stripped; callers get
    just the items array. The envelope is HTTP transport, not data.
  - selfLinks WITHIN items are preserved as-is (debugging + provenance).
  - `?ver=` query suffixes are preserved on selfLinks.
  - Pool's `membersReference.link` is FOLLOWED and members are embedded
    under a `_members` key on the pool object. The follow is HTTP-layer
    plumbing; treating it as a normalization keeps the pool object
    self-contained for the emitter.
  - The /inspect response's task envelope (id/selfLink/result) and the
    outer `class: "DO"` wrapper are STRIPPED. Callers receive the inner
    `class: "Device"` declaration directly. The double-wrapping is
    documented F5 transport (ADR 007 §Prior art table), not semantic
    data the emitter should know about.

Deferred to emission (intentionally NOT done here):

  - Parsing `destination` "/Common/IP:port" into structured fields.
  - Splitting pool `monitor` strings ("min 1 of { ... }").
  - Mapping virtual `profiles` object to AS3 service classes.
  - Filtering built-in system objects (/Common/http, /Common/tcp).
  - Tenant decomposition (partition → tenant mapping).
  - iRule TCL semantic analysis or version-checking.

Anything in the deferred list is a semantic choice the emitter makes
with knowledge of the AS3/DO target shape. The walker stays purely
extractive so the same output can drive multiple emitters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from brownfield.client import IControlRestClient


@dataclass
class WalkerOutput:
    """Structured raw-data result of a single-device walk.

    Each field holds the items collection (envelope stripped) from one
    endpoint family, except `inspect` which is the unwrapped inner
    Device declaration from /mgmt/shared/declarative-onboarding/inspect.

    The shapes here are intentionally raw F5 dicts — no semantic
    normalization. The emitter consumes this and produces declarations.
    """

    virtuals: list[dict[str, Any]] = field(default_factory=list)
    pools: list[dict[str, Any]] = field(default_factory=list)
    monitors_http: list[dict[str, Any]] = field(default_factory=list)
    profiles_clientssl: list[dict[str, Any]] = field(default_factory=list)
    persistence_cookie: list[dict[str, Any]] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)
    inspect: dict[str, Any] = field(default_factory=dict)


class Walker:
    """Orchestrates GETs across the brownfield-relevant endpoint families.

    No retry, no parallelism, no caching — single-threaded sequential
    walk per ADR 007 §Out of scope. Each step is independent and
    re-runnable; an extractor crash mid-walk leaves no partial mutation
    on the device (the surface is read-only by design).
    """

    def __init__(self, client: IControlRestClient) -> None:
        self._client = client

    def walk_virtuals(self) -> list[dict[str, Any]]:
        body = self._client.get("/mgmt/tm/ltm/virtual")
        return _items(body)

    def walk_pools(self, *, include_members: bool = True) -> list[dict[str, Any]]:
        """Walk pools. With `include_members=True` (default), follow each
        pool's `membersReference.link` and embed members under `_members`.

        The `_` prefix on `_members` flags it as a walker-added key
        (not present in the wire response). Emitters that consume the
        walker's output recognize the convention.
        """
        body = self._client.get("/mgmt/tm/ltm/pool")
        pools = _items(body)
        if not include_members:
            return pools
        for pool in pools:
            members_ref = pool.get("membersReference", {})
            link = members_ref.get("link") if isinstance(members_ref, dict) else None
            if isinstance(link, str):
                members_body = self._client.follow_link(link)
                pool["_members"] = _items(members_body)
            else:
                pool["_members"] = []
        return pools

    def walk_monitors_http(self) -> list[dict[str, Any]]:
        body = self._client.get("/mgmt/tm/ltm/monitor/http")
        return _items(body)

    def walk_profiles_clientssl(self) -> list[dict[str, Any]]:
        body = self._client.get("/mgmt/tm/ltm/profile/client-ssl")
        return _items(body)

    def walk_persistence_cookie(self) -> list[dict[str, Any]]:
        body = self._client.get("/mgmt/tm/ltm/persistence/cookie")
        return _items(body)

    def walk_rules(self) -> list[dict[str, Any]]:
        body = self._client.get("/mgmt/tm/ltm/rule")
        return _items(body)

    def walk_inspect(self) -> dict[str, Any]:
        """Walk /mgmt/shared/declarative-onboarding/inspect and unwrap
        the documented task-envelope + class:"DO" wrapping.

        Returns the inner `class: "Device"` declaration directly. That
        block validates against the ADR 006 vendored DO schema as-is —
        the test gate `test_walker_inspect_passes_adr_006_schema`
        enforces this composition (ADR 006 schema ↔ ADR 007 extractor).

        Raises ValueError if the response shape doesn't match the F5
        documented contract. That's a mock-vs-spec mismatch (the mock
        regressed) or a real-F5-vs-doc divergence (file an F5 issue).
        Either way it surfaces loudly rather than silently producing a
        broken declaration.
        """
        body = self._client.get("/mgmt/shared/declarative-onboarding/inspect")
        if not isinstance(body, list) or len(body) != 1:
            raise ValueError(
                f"/inspect: expected JSON array of one element per F5 contract; "
                f"got {type(body).__name__} of length "
                f"{len(body) if isinstance(body, list) else 'n/a'}"
            )
        entry = body[0]
        if not isinstance(entry, dict):
            raise ValueError(f"/inspect: array element is {type(entry).__name__}, expected dict")
        outer = entry.get("declaration")
        if not isinstance(outer, dict) or outer.get("class") != "DO":
            raise ValueError(
                '/inspect: missing or wrong-shape outer `declaration.class: "DO"` wrapper'
            )
        inner = outer.get("declaration")
        if not isinstance(inner, dict) or inner.get("class") != "Device":
            raise ValueError(
                '/inspect: missing or wrong-shape inner `declaration.declaration.class: "Device"`'
            )
        return inner

    def walk_all(self) -> WalkerOutput:
        """Convenience: walk every endpoint family the extractor needs
        and bundle into a single WalkerOutput.

        Each step is independent. Order matches the dataclass field
        order so a partial-walk debug log reads top-to-bottom in step
        sequence.
        """
        return WalkerOutput(
            virtuals=self.walk_virtuals(),
            pools=self.walk_pools(),
            monitors_http=self.walk_monitors_http(),
            profiles_clientssl=self.walk_profiles_clientssl(),
            persistence_cookie=self.walk_persistence_cookie(),
            rules=self.walk_rules(),
            inspect=self.walk_inspect(),
        )


def _items(body: Any) -> list[dict[str, Any]]:
    """Strip the F5 collection envelope, return the items array.

    A response shape that lacks `items` is treated as an empty
    collection — real F5 always returns an items key (possibly empty)
    on collection endpoints; if a response is missing it, that's a
    mock-vs-spec gap and the empty-list fallback keeps the walk
    moving forward.
    """
    if not isinstance(body, dict):
        return []
    items = body.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]
