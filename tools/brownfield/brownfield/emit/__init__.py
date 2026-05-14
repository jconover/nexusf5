"""Emission layer: walker output → AS3/DO declarations + Terraform.

Per ADR 007 §Decision, the emitter applies the semantic decisions the
walker intentionally deferred:

  - destination "/Common/IP:port" → (address, port) structured fields
  - Pool monitor strings → AS3 monitor reference shapes
  - Virtual profiles object → AS3 Service_* class selection
  - Built-in /Common/* filtering (via brownfield.builtins)
  - Partition → AS3 tenant 1:1 mapping (literal — see ADR 007 Addendum 2026-05-13)
  - iRule TCL body → embedded AS3 iRule

Each emit_* function is deterministic: same WalkerOutput input → byte-stable
output. JSON serialization uses sort_keys + indent=2 throughout.
"""

from brownfield.emit.as3 import emit_as3
from brownfield.emit.do import emit_do
from brownfield.emit.readme import emit_readme
from brownfield.emit.terraform import emit_terraform

__all__ = ["emit_as3", "emit_do", "emit_readme", "emit_terraform"]
