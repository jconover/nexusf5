# observability/ingest

Artifact schema, success-rate gate, and Pushgateway client for NexusF5
wave upgrades. The three entry points are thin CLIs, each invoked by
the reusable upgrade workflow in `.github/workflows/_reusable/`.

| Module | Role | Called by |
|---|---|---|
| `schema.py` | `UpgradeArtifact` — frozen 6-field Pydantic model. Locked interface to Phase 5's Grafana dashboard. | every module here |
| `writer.py` | Emits one validated artifact JSON per device. Validation here catches drift at write time rather than at the gate. | matrix job per device |
| `gate.py` | Reads prior-wave artifacts, computes success rate, compares to threshold. Load-bearing: the wave-to-wave promotion gate is whatever this file says it is. Fails closed on missing/empty/malformed inputs. | dedicated gate job between waves |
| `pusher.py` | Re-validates the artifact set and pushes `nexusf5_upgrade_total` + `nexusf5_upgrade_duration_seconds` to a Prometheus Pushgateway. | final step of the wave run |

## Test + lint

```bash
cd observability/ingest
uv sync
uv run pytest -q       # ~40 tests, run in < 1s
uv run ruff check .
uv run mypy
```

The test suite is the contract: `tests/test_gate.py` covers every
failure mode the gate documents (below-threshold, missing prior-wave
artifacts, malformed JSON, schema violations), plus boundary cases
(exactly-at-threshold passes, single failure blocks a strict gate).

## Schema contract

```python
class UpgradeArtifact(BaseModel, frozen=True, extra="forbid"):
    wave:   str             # canary / wave_1 / wave_2 / wave_3
    device: str             # bigip-{site}-NN per CLAUDE.md
    start:  datetime        # ISO 8601 UTC
    end:    datetime        # ISO 8601 UTC
    status: "success" | "failed"
    error:  str = ""        # failure summary; empty on success
```

Six fields exactly, per `ARCHITECTURE.md`. `extra="forbid"` makes
accidental schema drift fail at ingestion instead of silently producing
half-populated dashboard panels. Additions here require updating
`ARCHITECTURE.md` and the Phase 5 dashboard together — not one without
the other.
