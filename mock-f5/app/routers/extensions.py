"""DO and AS3 endpoints — F5 BIG-IP iApps "extensions" surface.

These endpoints emulate the async task contract that the Terraform
`f5networks/bigip` provider expects when it manages a `bigip_do` or
`bigip_as3` resource. The provider parses task IDs out of the POST response
body and polls a task endpoint until completion. The HTTP status codes,
JSON shapes, and field names below are the parts the provider keys on —
deviating breaks the provider in subtle ways that only surface against a
real BIG-IP, so the contract here is deliberately strict.

References:
- DO: https://clouddocs.f5.com/products/extensions/f5-declarative-onboarding/latest/
- AS3: https://clouddocs.f5.com/products/extensions/f5-appsvcs-extension/latest/
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.deps import DeviceDep
from app.state import DeviceState

router = APIRouter(prefix="/{hostname}/mgmt/shared")


def _reboot_guard(device: DeviceState) -> Response | None:
    """Return a 503 if the device is mid-reboot.

    Same shape as `app.routers.icontrol._reboot_guard`. Duplicated rather
    than imported because both routers are siblings under app.routers and a
    cross-import would be the only reason for either to know about the other.
    """
    device.advance()
    if device.is_rebooting():
        return Response(
            content='{"code":503,"message":"Device is rebooting"}',
            media_type="application/json",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "5"},
        )
    return None


async def _parse_declaration(request: Request) -> dict[str, Any]:
    """Parse a DO/AS3 request body, tolerating the F5 provider's
    double-encoded wire format.

    Real BIG-IP accepts a JSON-object body. The F5 Terraform provider
    (verified against v1.26.0) sends `as3_json` / `do_json` as a JSON-encoded
    *string* — i.e. the wire body is `"\\"{\\\\\\"action\\\\\\":...}\\""`
    rather than `{"action":...}`. FastAPI's `request.json()` parses that
    correctly, but returns a `str` instead of a `dict`. Storing the str and
    reading it back via `_json_dumps` produces a JSON string literal on the
    response, which the provider's Read func then fails to unmarshal into
    `map[string]interface{}`. Detecting and re-parsing the inner JSON gives
    us a dict either way and matches what real BIG-IP would store.
    """
    try:
        parsed = await request.json()
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid JSON body") from e
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail="JSON-encoded string body did not contain valid JSON",
            ) from e
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=400,
            detail=f"declaration body must be a JSON object, got {type(parsed).__name__}",
        )
    return parsed


def _drift_mutate(payload: dict[str, Any]) -> dict[str, Any]:
    """Inject a marker so the next terraform plan exits with code 2.

    Mutating the *read* response (not the stored declaration) keeps the
    drift effect chaos-driven and one-shot-capable: clearing the chaos flag
    immediately makes plan green again without re-applying anything.
    """
    mutated = deepcopy(payload)
    mutated["__drift_marker"] = "chaos.drift_postcheck"
    return mutated


# GET /mgmt/shared/declarative-onboarding/info
# Provider probes this before any DO operation to confirm DO is installed
# and to read its version. Real BIG-IP returns a list of one element.
# https://clouddocs.f5.com/products/extensions/f5-declarative-onboarding/latest/apidocs.html
@router.get("/declarative-onboarding/info")
def do_info(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return [
        {
            "id": 0,
            "selfLink": f"https://{device.hostname}/mgmt/shared/declarative-onboarding/info",
            "result": {"class": "Result", "code": 200, "status": "OK", "message": ""},
            "version": "1.40.0",
            "release": "0",
            "schemaCurrent": "1.40.0",
            "schemaMinimum": "1.0.0",
        }
    ]


# GET /mgmt/shared/appsvcs/info
# Provider probes this before any AS3 op. Without it, the provider's pre-check
# (`Getting AS3 Version failed`) panics.
# https://clouddocs.f5.com/products/extensions/f5-appsvcs-extension/latest/refguide/apidocs.html
@router.get("/appsvcs/info")
def as3_info(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return {
        "version": "3.50.0",
        "release": "5",
        "schemaCurrent": "3.50.0",
        "schemaMinimum": "3.0.0",
    }


# GET /mgmt/shared/appsvcs/settings
# Provider reads this for `per_app_mode` and other tuning knobs. Real BIG-IP
# returns the active AS3 settings; the mock returns the documented defaults.
@router.get("/appsvcs/settings")
def as3_settings(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return {
        "betaOptions": {"perAppDeploymentAllowed": True},
        "asyncTaskStorage": "data-group",
        "burstHandlingEnabled": False,
        "performanceTracingEnabled": False,
        "performanceTracingEndpoint": "",
        "serializeFileUploads": False,
        "encodeDeclarationMetadata": False,
        "webhook": "",
    }


# POST /mgmt/shared/declarative-onboarding
# Provider parses task ID from JSON `id` field. Returns 202 + RUNNING result.
# Body is read as raw JSON: real DO declarations are deeply nested and the
# F5 provider wraps the user's `do_json` in extra envelope fields the mock
# would have to enumerate to validate strictly. Permissive ingress is fine
# because the mock's job is to round-trip the body, not to validate F5
# schema (`/info` already advertises the supported schema range).
# Both `/declarative-onboarding` and `/declarative-onboarding/` are registered
# because the F5 provider POSTs the trailing-slash form and does not follow
# 307 redirects on POST.
# https://clouddocs.f5.com/products/extensions/f5-declarative-onboarding/latest/apidocs.html
@router.post("/declarative-onboarding")
@router.post("/declarative-onboarding/")
async def do_post(device: DeviceDep, request: Request) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    declaration = await _parse_declaration(request)
    task = device.start_do_task(declaration)
    self_link = f"https://{device.hostname}/mgmt/shared/declarative-onboarding/task/{task.id}"
    return Response(
        content=(
            '{"id":"' + task.id + '",'
            '"selfLink":"' + self_link + '",'
            '"result":{"status":"RUNNING","message":"processing"}}'
        ),
        media_type="application/json",
        status_code=status.HTTP_202_ACCEPTED,
    )


# GET /mgmt/shared/declarative-onboarding/task/{task_id}
# Provider polls 1s/1200s. RUNNING -> HTTP 202. OK -> HTTP 200. ERROR -> HTTP 202
# (the provider treats any non-RUNNING status carried on a 202 as an error).
@router.get("/declarative-onboarding/task/{task_id}")
def do_task_get(device: DeviceDep, task_id: str) -> Response:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    task = device.do_tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"DO task {task_id} not found")
    self_link = f"https://{device.hostname}/mgmt/shared/declarative-onboarding/task/{task.id}"
    if task.status == "RUNNING":
        body: dict[str, Any] = {
            "id": task.id,
            "selfLink": self_link,
            "result": {"status": "RUNNING", "message": "processing"},
        }
        return Response(
            content=_json_dumps(body),
            media_type="application/json",
            status_code=status.HTTP_202_ACCEPTED,
        )
    if task.status == "OK":
        body = {
            "id": task.id,
            "selfLink": self_link,
            "result": {"status": "OK", "message": task.message},
            "declaration": task.declaration,
        }
        return Response(
            content=_json_dumps(body),
            media_type="application/json",
            status_code=status.HTTP_200_OK,
        )
    body = {
        "id": task.id,
        "selfLink": self_link,
        "result": {"status": "ERROR", "message": task.message},
    }
    return Response(
        content=_json_dumps(body),
        media_type="application/json",
        status_code=status.HTTP_202_ACCEPTED,
    )


# GET /mgmt/shared/declarative-onboarding
# Read endpoint used by the provider's Read func — returns the last applied
# declaration. 204 if nothing has been applied yet. Drift chaos mutates the
# response so terraform plan reports drift.
@router.get("/declarative-onboarding")
@router.get("/declarative-onboarding/")
def do_get(device: DeviceDep) -> Response:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    if device.do_state is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    payload = device.do_state
    if device.chaos.drift_postcheck:
        payload = _drift_mutate(payload)
    return Response(
        content=_json_dumps(payload),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )


# POST /mgmt/shared/appsvcs/declare/{tenant}
# Provider does respRef["id"].(string) with no nil check — `id` MUST be present
# or the provider crashes. `?async=true` is accepted but informational; the
# mock is always async.
# Body parsed as raw JSON for the same reason as the DO endpoint: real AS3
# declarations are large and the provider wraps them in an envelope (action
# + persist + declaration) that doesn't match a single Pydantic shape.
# https://clouddocs.f5.com/products/extensions/f5-appsvcs-extension/latest/refguide/apidocs.html
@router.post("/appsvcs/declare/{tenant}")
@router.post("/appsvcs/declare/{tenant}/")
async def as3_post(device: DeviceDep, tenant: str, request: Request) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    declaration = await _parse_declaration(request)
    task = device.start_as3_task(tenant, declaration)
    self_link = f"https://{device.hostname}/mgmt/shared/appsvcs/task/{task.id}"
    payload = {
        "id": task.id,
        "selfLink": self_link,
        "results": [
            {
                "code": 0,
                "message": "Declaration successfully submitted",
                "tenant": tenant,
            }
        ],
    }
    return Response(
        content=_json_dumps(payload),
        media_type="application/json",
        status_code=status.HTTP_202_ACCEPTED,
    )


# GET /mgmt/shared/appsvcs/task/{task_id}
# Always HTTP 200. Provider keys on results[0].code: 0 = pending, 200 = done.
# Provider sleeps 3s between polls. On success the response also includes
# the inner ADC `declaration` block — the provider reads it back to populate
# computed attributes on the resource.
@router.get("/appsvcs/task/{task_id}")
def as3_task_get(device: DeviceDep, task_id: str) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    task = device.as3_tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"AS3 task {task_id} not found")
    result: dict[str, Any] = {
        "code": task.code,
        "message": task.message,
        "tenant": task.tenant,
    }
    if task.code == 422:
        result["errors"] = [task.message]
    self_link = f"https://{device.hostname}/mgmt/shared/appsvcs/task/{task.id}"
    body: dict[str, Any] = {
        "id": task.id,
        "selfLink": self_link,
        "results": [result],
    }
    if task.code == 200:
        inner = task.declaration.get("declaration") if isinstance(task.declaration, dict) else None
        if isinstance(inner, dict):
            body["declaration"] = inner
    return body


# GET /mgmt/shared/appsvcs/declare/{tenant}
# Read endpoint per tenant. 404 if no declaration has been applied for this
# tenant yet — keeps multi-tenant state independent.
#
# Returns the full ADC inner block (the value of `declaration` from the
# applied AS3 envelope): `{class, schemaVersion, id, label, controls,
# <tenant>}`. This matches what real BIG-IP returns. The F5 provider's Read
# func iterates the top-level keys and special-cases the non-tenant string
# values (`class`, `id`, `label`, `schemaVersion`) to skip them, processing
# only map values as tenants. Returning just `{tenant: tenant_block}` strips
# fields the provider writes back into `as3_json` state, so every subsequent
# `terraform plan` reports drift. See the `test_as3_apply_then_plan_clean`
# integration assertion for why this matters.
@router.get("/appsvcs/declare/{tenant}")
@router.get("/appsvcs/declare/{tenant}/")
def as3_get(device: DeviceDep, tenant: str) -> Response:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    stored = device.as3_state.get(tenant)
    if stored is None:
        raise HTTPException(
            status_code=404,
            detail=f"no AS3 declaration applied for tenant {tenant}",
        )
    inner = stored.get("declaration") if isinstance(stored, dict) else None
    if not isinstance(inner, dict) or tenant not in inner:
        raise HTTPException(
            status_code=404,
            detail=f"tenant {tenant} not present in stored declaration",
        )
    payload: dict[str, Any] = inner
    if device.chaos.drift_postcheck:
        payload = _drift_mutate(payload)
    return Response(
        content=_json_dumps(payload),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )


def _json_dumps(payload: dict[str, Any]) -> str:
    """JSON serialisation with stable key order so test assertions are
    diffable across runs without resorting to dict comparisons.
    """
    return json.dumps(payload, sort_keys=True)
