# f5_postcheck

Post-upgrade validation.

Phase 2: running version must equal `f5_target_version`. Phase 4 replaces
the drift-stub with a real `terraform plan -detailed-exitcode` against the
DO/AS3 declarations (the mock `chaos.drift_postcheck` flag is already wired
so the drop-in test exists the moment Phase 4 lands).

Tags: `postcheck`.
