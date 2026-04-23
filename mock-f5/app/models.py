"""Pydantic v2 models for the iControl REST request bodies the mock accepts.

Responses are built as plain dicts in the router handlers to keep the F5
"entries -> URL -> nestedStats -> entries" response shape explicit and
readable. Request bodies get models so we validate on ingress.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class IControlCommand(BaseModel):
    """Permissive base for iControl REST command payloads.

    Real F5 requests carry many optional fields; the mock accepts them all
    and uses only the subset the upgrade runbook exercises.
    """

    model_config = ConfigDict(extra="allow")
    command: str | None = None


class UcsSaveCommand(IControlCommand):
    name: str | None = None


class SoftwareImageInstallCommand(IControlCommand):
    name: str | None = None
    volume: str | None = None


class SoftwareVolumeCommand(IControlCommand):
    name: str | None = None
    version: str | None = None
    product: str = "BIG-IP"


class FailoverCommand(IControlCommand):
    pass
