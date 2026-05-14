"""CLI tests.

Covers:
  - `extract --output DIR` writes 5 expected files with deterministic content.
  - `extract --dry-run` prints to stdout, writes no files.
  - `validate DIR` schema-validates emitted files; succeeds on the
    extract output and fails clearly on malformed inputs.
  - `--auth user:password` is parsed correctly.
  - The CLI does NOT bundle extract+apply.

CLI uses the same IControlRestClient that walker tests cover, so we
focus on CLI-shape behavior here and trust the underlying layers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from brownfield import cli

# Reuse the mock_client fixture's TestClient pattern by injecting our
# own httpx.Client into the IControlRestClient. The CLI normally builds
# its own client from base_url; for tests we monkeypatch the constructor
# so it accepts a pre-built http_client and skip the real network path.


@pytest.fixture
def patched_cli(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Replace cli.IControlRestClient with a factory that returns one
    bound to the in-process mock-f5 app via TestClient. Lets the CLI
    `extract` subcommand run end-to-end without real network.
    """
    from app.main import app

    from brownfield.client import IControlRestClient as RealClient

    tc = TestClient(app, base_url="http://testserver/bigip-lab-01")
    tc.__enter__()

    def factory(base_url: str, **kwargs: object) -> RealClient:
        _ = base_url  # ignored — we always point at the mock
        kwargs.pop("auth", None)
        kwargs.pop("verify", None)
        return RealClient("http://testserver/bigip-lab-01", http_client=tc)

    monkeypatch.setattr(cli, "IControlRestClient", factory)
    yield tc
    tc.__exit__(None, None, None)


def test_cli_extract_writes_five_files(patched_cli: TestClient, tmp_path: Path) -> None:
    out = tmp_path / "bigip-lab-01"
    rc = cli.main(
        [
            "extract",
            "--base-url",
            "http://testserver/bigip-lab-01",
            "--hostname",
            "bigip-lab-01",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    expected = {"as3.json", "do.json", "main.tf", "imports.tf", "README.md"}
    actual = {p.name for p in out.iterdir()}
    assert actual == expected


def test_cli_extract_output_is_deterministic_across_runs(
    patched_cli: TestClient, tmp_path: Path
) -> None:
    """Two extract invocations against the same mock state produce
    byte-identical files. This is the file-level form of ADR 007's
    re-extraction byte-stability property.
    """
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    for out in (out_a, out_b):
        rc = cli.main(
            [
                "extract",
                "--base-url",
                "http://testserver/bigip-lab-01",
                "--hostname",
                "bigip-lab-01",
                "--output",
                str(out),
            ]
        )
        assert rc == 0

    for name in ("as3.json", "do.json", "main.tf", "imports.tf", "README.md"):
        a_bytes = (out_a / name).read_bytes()
        b_bytes = (out_b / name).read_bytes()
        assert a_bytes == b_bytes, f"{name} differs between identical runs"


def test_cli_extract_dry_run_writes_nothing(
    patched_cli: TestClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "would-be"
    rc = cli.main(
        [
            "extract",
            "--base-url",
            "http://testserver/bigip-lab-01",
            "--hostname",
            "bigip-lab-01",
            "--output",
            str(out),
            "--dry-run",
        ]
    )
    assert rc == 0
    assert not out.exists()  # nothing written
    captured = capsys.readouterr()
    assert "as3.json" in captured.out
    assert "do.json" in captured.out
    assert "main.tf" in captured.out
    assert "imports.tf" in captured.out
    assert "README.md" in captured.out


def test_cli_validate_succeeds_on_extract_output(patched_cli: TestClient, tmp_path: Path) -> None:
    out = tmp_path / "bigip-lab-01"
    assert (
        cli.main(
            [
                "extract",
                "--base-url",
                "http://testserver/bigip-lab-01",
                "--hostname",
                "bigip-lab-01",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    rc = cli.main(["validate", str(out)])
    assert rc == 0


def test_cli_validate_fails_on_malformed_as3(tmp_path: Path) -> None:
    """A broken as3.json (missing class field) fails validation with a
    non-zero exit, surfacing the F5-shape error envelope.
    """
    out = tmp_path / "broken"
    out.mkdir()
    (out / "as3.json").write_text(json.dumps({"not_class": "wrong"}))
    (out / "do.json").write_text(
        json.dumps(
            {
                "class": "Device",
                "schemaVersion": "1.40.0",
                "Common": {"class": "Tenant"},
            }
        )
    )
    rc = cli.main(["validate", str(out)])
    assert rc != 0


def test_cli_auth_parsing_user_password() -> None:
    assert cli._parse_auth("admin:secret") == ("admin", "secret")
    assert cli._parse_auth(None) is None


def test_cli_auth_parsing_rejects_bare_string() -> None:
    with pytest.raises(SystemExit, match="user:password"):
        cli._parse_auth("just_a_username")


def test_cli_does_not_bundle_apply() -> None:
    """Discipline requirement: the CLI does NOT have a subcommand or
    flag that runs `terraform apply`. Each step is a separate operator
    invocation per ADR 007 §Tradeoffs ("never extract-and-apply in a
    single command"). This test asserts that property by listing the
    subcommand surface and confirming `apply` isn't there.
    """
    parser = cli._build_parser()
    # argparse's _subparsers structure is private but stable across versions.
    sub = next((a for a in parser._actions if hasattr(a, "choices") and a.choices), None)
    assert sub is not None, "CLI must have subcommands"
    assert set(sub.choices.keys()) == {"extract", "validate"}, (
        "CLI subcommands must be exactly {extract, validate}. An `apply` "
        "or `run` subcommand would violate ADR 007 §Tradeoffs."
    )
