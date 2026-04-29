variable "aws_profile" {
  type        = string
  description = "Named AWS profile to assume locally. Pinned to 'outlook' so a stray $AWS_PROFILE in the operator's shell can't drop apply traffic into the wrong account. Override only if you know what you're doing."
  default     = "outlook"
}

variable "aws_region" {
  type        = string
  description = "Region for all NexusF5 resources. PR 2 is single-region by design — multi-region disaster recovery is out of scope."
  default     = "us-east-2"
}

variable "aws_account_id" {
  type        = string
  description = "Expected AWS account ID. The provider asserts caller identity against this value so a misconfigured profile can't accidentally apply against the wrong account. Required (no default) — must be set in terraform.tfvars (gitignored) so the account ID never lands in source control."
}

variable "github_repo" {
  type        = string
  description = "GitHub repository (owner/name) the OIDC trust policy scopes to. Trust-policy subject claims hard-code this — broadening it requires a deliberate edit, not a tfvars override."
  default     = "jconover/nexusf5"
}

variable "github_oidc_role_name" {
  type        = string
  description = "IAM role name GitHub Actions assumes via OIDC. Lives in the role ARN baked into workflow files, so renames require a workflow update too."
  default     = "nexusf5-gha-aws"
}

variable "trusted_branch_refs" {
  type        = list(string)
  description = "Branch refs that may assume the GHA role without an environment context. main always; the active feature branch during PR-2 iteration so the auth-test workflow can run pre-merge. Trim back to ['main'] before merging PR 2."
  # TODO(pr-2-merge): drop "refs/heads/phase-4-aws-ve" before merge. A
  # feature branch in the trust policy is permanent attack surface — the
  # branch can be re-created with the same name post-merge by anyone with
  # repo write access, and the trust policy would still accept it. See
  # TODO.md Phase 4 PR 2 wrap-up.
  default = [
    "refs/heads/main",
    "refs/heads/phase-4-aws-ve",
  ]
}

variable "trusted_environments" {
  type        = list(string)
  description = "GitHub environment names that may assume the GHA role. Each entry produces a `repo:OWNER/REPO:environment:NAME` subject claim in the trust policy. Environments must exist in GitHub repository settings; protected environments add a second gate (required reviewers, deployment branches)."
  default = [
    "nexusf5-aws-test",
    "nexusf5-aws-integration",
  ]
}

variable "budget_alert_email" {
  type        = string
  description = "Email address for monthly budget alerts (50%, 80%, 100% of cap). Use a real human inbox — the alarm only matters if someone reads it."
}

variable "monthly_budget_usd" {
  type        = number
  description = "Monthly spend cap for the nexusf5 project, in USD. Belt against the per-run hard timeout (suspenders) — leftover resources from a wedged make integration would still show up here within the month."
  default     = 50
}
