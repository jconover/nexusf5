"""Pydantic v2 models for iControl REST request bodies the mock accepts.

Responses are built as plain dicts in the router handlers to keep the F5
`entries -> URL -> nestedStats -> entries` shape explicit and readable.
Request bodies get models so we validate on ingress.
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


class VolumePatchCommand(BaseModel):
    """PATCH /mgmt/tm/sys/software/volume/{volume} body.

    Setting `active: true` flips this volume to active and every other
    volume to inactive (only one boots next). Setting `active: false` is
    rejected — F5's two-volume model requires exactly one active volume.
    """

    model_config = ConfigDict(extra="allow")
    active: bool | None = None


class FailoverCommand(IControlCommand):
    pass


class UtilBashCommand(IControlCommand):
    """POST /mgmt/tm/util/bash.

    The mock only recognises `utilCmdArgs` strings containing `reboot` —
    anything else is a no-op that echoes the request. Ansible roles that
    run non-reboot bash commands against real F5 will work in prod and be
    ignored by the mock, which is what we want for a Phase 2 runbook focused
    on the upgrade path.
    """

    utilCmdArgs: str | None = None  # noqa: N815 — F5 wire field name, keep as-is


class DODeclaration(BaseModel):
    """POST /mgmt/shared/declarative-onboarding body.

    Real DO declarations are deeply nested and large; the mock just stores
    them verbatim and replays them on the read endpoint, so any extra fields
    are accepted.
    """

    model_config = ConfigDict(extra="allow")


class AS3Declaration(BaseModel):
    """POST /mgmt/shared/appsvcs/declare/{tenant} body.

    Same permissive shape as DO. The tenant comes from the URL, not the body.
    """

    model_config = ConfigDict(extra="allow")
