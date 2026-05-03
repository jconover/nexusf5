# f5_postcheck

DO/AS3 validation. Two callers, two shapes:

* **Upgrade flow (default).** Both gates run:
  1. **Version check.** Running version on the device must equal
     `f5_target_version`. Pulled via `GET /mgmt/tm/sys/version`.
  2. **DO/AS3 drift check.** Runs `terraform plan -detailed-exitcode`
     against the env's declarations (default
     `terraform/environments/lab`). Exit 0 is the only pass. Exit 1 (error)
     and exit 2 (drift) both fail with a pointer to
     `runbooks/06-postcheck-drift.md`.
* **Immutable track first-apply.** Set
  `f5_postcheck_version_check_enabled=false`. Only the drift gate runs.
  There is no "target version" for a freshly-provisioned VE; "did the
  apply succeed?" is answered by `plan -detailed-exitcode` returning 0
  immediately after `apply`. Same exit-code semantics as drift detection,
  same role.

The drift step runs `delegate_to: localhost` and `run_once: true` because
`terraform plan` is global to the environment, not per-host. Running it
once per device would be O(N) plans for the same answer.

## Variables

| Variable                                | Default                                               | Notes                                                                  |
|-----------------------------------------|-------------------------------------------------------|------------------------------------------------------------------------|
| `f5_target_version`                     | required when version check is enabled                | The version the upgrade was driving toward                             |
| `f5_postcheck_terraform_env_path`       | `{{ playbook_dir }}/../../terraform/environments/lab` | Env to plan against                                                    |
| `f5_postcheck_terraform_binary`         | `terraform`                                           | Override for `tofu` etc.                                               |
| `f5_postcheck_drift_enabled`            | `true`                                                | Set false on lanes without a terraform bin                             |
| `f5_postcheck_version_check_enabled`    | `true`                                                | Set false for the immutable-track first-apply case (drift gate only)   |

## Tags

- `postcheck` — every task
- `terraform` — only the drift gate (skip with `--skip-tags terraform` when
  no terraform binary is available)
