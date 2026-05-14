"""Brownfield extractor CLI.

Subcommands enforce ADR 007's safety property — extract and validate
are separate invocations; there is no combined extract-and-apply mega-
command. The operator workflow is:

  1. python -m brownfield extract --base-url ... --output ./extracted/<host>
  2. python -m brownfield validate ./extracted/<host>
  3. terraform plan        (review the import + plan)
  4. human review of as3.json, do.json
  5. terraform apply

Step 1 writes files. Step 2 schema-validates against ADR 006 vendored
schemas. Steps 3-5 are operator-driven; the tool does NOT invoke
terraform.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from brownfield.client import IControlRestClient
from brownfield.emit import emit_as3, emit_do, emit_readme, emit_terraform
from brownfield.walker import Walker

_EXIT_OK = 0
_EXIT_USAGE = 2
_EXIT_VALIDATION_FAILED = 3


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "extract":
        return _cmd_extract(args)
    if args.command == "validate":
        return _cmd_validate(args)
    parser.print_help()
    return _EXIT_USAGE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brownfield",
        description=(
            "Walk a live F5 BIG-IP and emit AS3 + DO declarations + Terraform "
            "import blocks for adoption. See docs/decisions/007-brownfield-config-discovery.md."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=False)

    extract = sub.add_parser(
        "extract",
        help="Walk a device and write extraction artifacts to a directory.",
    )
    extract.add_argument(
        "--base-url",
        required=True,
        help=(
            "iControl REST base URL. Real F5: https://<device-fqdn>. Mock-f5: "
            "http://localhost:8100/<device-hostname>."
        ),
    )
    extract.add_argument(
        "--hostname",
        required=True,
        help="Device hostname (used for Terraform resource naming and README).",
    )
    extract.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory. Created if absent; will overwrite existing files.",
    )
    extract.add_argument(
        "--partition",
        default="Common",
        help="F5 partition to extract (default: Common). 1:1 with AS3 tenant.",
    )
    extract.add_argument(
        "--auth",
        default=None,
        help="HTTP Basic auth credentials as user:password (omit for mock-f5).",
    )
    extract.add_argument(
        "--no-verify-tls",
        action="store_true",
        help="Skip TLS verification (real F5 default-cert use case).",
    )
    extract.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print declarations to stdout, do NOT write files. Per ADR 007 "
            "§Tradeoffs — preview the would-be artifacts before committing to "
            "the output directory."
        ),
    )

    validate = sub.add_parser(
        "validate",
        help=(
            "Validate emitted as3.json and do.json against the vendored ADR 006 "
            "schemas. Run before `terraform apply`."
        ),
    )
    validate.add_argument(
        "directory",
        type=Path,
        help="Output directory from a prior `extract` run.",
    )
    return parser


def _cmd_extract(args: argparse.Namespace) -> int:
    auth = _parse_auth(args.auth)
    walker_output: Any
    with IControlRestClient(
        args.base_url,
        auth=auth,
        verify=not args.no_verify_tls,
    ) as client:
        walker_output = Walker(client).walk_all()

    as3 = emit_as3(walker_output, hostname=args.hostname, partition=args.partition)
    do = emit_do(walker_output, hostname=args.hostname)
    tf_files = emit_terraform(hostname=args.hostname, partition=args.partition)
    readme = emit_readme(walker_output, hostname=args.hostname, partition=args.partition)

    if args.dry_run:
        # Per ADR 007 §Tradeoffs — preview without writing.
        print("=== as3.json ===")
        print(_dumps(as3))
        print("=== do.json ===")
        print(_dumps(do))
        print("=== main.tf ===")
        print(tf_files["main.tf"])
        print("=== imports.tf ===")
        print(tf_files["imports.tf"])
        print("=== README.md ===")
        print(readme)
        return _EXIT_OK

    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)
    (out / "as3.json").write_text(_dumps(as3) + "\n")
    (out / "do.json").write_text(_dumps(do) + "\n")
    (out / "main.tf").write_text(tf_files["main.tf"])
    (out / "imports.tf").write_text(tf_files["imports.tf"])
    (out / "README.md").write_text(readme)
    print(f"Extracted to {out}/", file=sys.stderr)
    return _EXIT_OK


def _cmd_validate(args: argparse.Namespace) -> int:
    # Import the ADR 006 validators lazily so the CLI can run without
    # mock-f5 on sys.path for users who only need `extract`.
    from app.schemas import validate_as3_declaration, validate_do_declaration

    directory: Path = args.directory
    as3_path = directory / "as3.json"
    do_path = directory / "do.json"
    failures = []
    if as3_path.exists():
        as3 = json.loads(as3_path.read_text())
        err = validate_as3_declaration(as3)
        if err is not None:
            failures.append(("as3.json", err))
    else:
        failures.append(("as3.json", {"message": f"file not found: {as3_path}"}))
    if do_path.exists():
        do = json.loads(do_path.read_text())
        err = validate_do_declaration(do)
        if err is not None:
            failures.append(("do.json", err))
    else:
        failures.append(("do.json", {"message": f"file not found: {do_path}"}))

    if failures:
        for name, err in failures:
            print(f"FAIL {name}: {err}", file=sys.stderr)
        return _EXIT_VALIDATION_FAILED
    print(f"OK {as3_path}", file=sys.stderr)
    print(f"OK {do_path}", file=sys.stderr)
    return _EXIT_OK


def _parse_auth(auth_arg: str | None) -> tuple[str, str] | None:
    """Parse a `user:password` CLI value into the httpx auth tuple."""
    if auth_arg is None:
        return None
    user, sep, password = auth_arg.partition(":")
    if not sep:
        raise SystemExit("--auth must be in user:password form")
    return user, password


def _dumps(payload: Any) -> str:
    """Deterministic JSON serialization: sorted keys, 2-space indent.

    Same shape used in mock-f5 for response serialization; matches the
    "byte-stable up to documented normalization" property in ADR 007.
    """
    return json.dumps(payload, sort_keys=True, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
