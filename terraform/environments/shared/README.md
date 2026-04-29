# shared environment

Account-wide infrastructure that has to exist before any nexusf5 workload
can spin up. Three resources, one purpose: make `make integration` safe to
run.

| Resource | Why |
|---|---|
| AWS Budget (`nexusf5-monthly`, $50 cap) | Belt against the per-run timeout's suspenders. Email alerts at 50%, 80%, 100% of monthly cap, plus a forecast alert when projected spend exceeds 100%. |
| GitHub OIDC Provider | Let workflows assume a role without long-lived AWS access keys. |
| GHA Assume-Role IAM Role | Repo + branch + environment-scoped trust. Read-only baseline policy. Provisioning permissions land in a follow-up commit alongside `terraform/modules/ve-instance/`. |

## Prerequisites (manual, one-time per AWS account)

Four things Terraform cannot do for you. Items (1) and (3) block this env's
apply being useful; item (2) only blocks Stage D (`make integration`); item
(4) lands automatically on first-apply but requires a human action.

1. **Activate `Project` as a user-defined cost-allocation tag.**
   Billing → Cost Allocation Tags → search for `Project` → activate.
   Without this, the budget filter `user:Project$nexusf5` matches zero
   resources and alerts never fire. AWS does not expose this through any
   provider.

   **Activate this *before* the first integration run.** Activation only
   catches future costs, not retroactive — anything launched and torn down
   before activation never enters the budget. Doing it on a mostly-empty
   account is fine and recommended; doing it after a wave of leakage means
   the leak doesn't surface in the budget.

2. **Subscribe to the F5 BIG-IP VE PAYG marketplace AMI.**
   AWS Marketplace → search "F5 BIG-IP Virtual Edition" → "Continue to
   Subscribe" → accept terms. Required before EC2 can launch the AMI in
   `make integration`. Per-account, one-time.

3. **Create the GitHub environments referenced by the trust policy.**
   On `github.com/jconover/nexusf5/settings/environments` create:
   - `nexusf5-aws-test`
   - `nexusf5-aws-integration` (add required reviewers if you want a
     human gate before the integration workflow assumes the role)

4. **Confirm the AWS Budgets email subscription on first delivery.**
   AWS Budgets sends a one-time confirmation email to the subscriber
   address before any alert is delivered. After `terraform apply`, watch
   the configured inbox (and spam folder) for an "AWS Budgets" sender and
   click the confirmation link. **Do not skip.** An unconfirmed subscriber
   silently drops every subsequent alert — discovering the alarm was never
   live during a real overspend defeats the budget.

## Apply

```bash
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars   # set budget_alert_email

cd terraform/environments/shared
terraform init
terraform apply
```

Apply this once per account. State is local — see `backend.tf` for the
chicken-and-egg rationale.

After apply, set the role ARN as a GitHub Actions repository variable so
workflows reference it by name rather than hard-coded:

```bash
gh variable set AWS_OIDC_ROLE_ARN \
  --body "$(cd terraform/environments/shared && terraform output -raw github_oidc_role_arn)"
```

## Iterating the OIDC trust policy

Trust-policy bugs only surface when a workflow actually tries to assume the
role. Use `.github/workflows/test-aws-auth.yml` as the cheapest possible
iteration target — it does nothing but `aws sts get-caller-identity` and
exits, so each iteration is one runner spin-up (~30s, fractions of a cent)
rather than a full integration test.

When `aws-actions/configure-aws-credentials` rejects the assume-role, the
error message includes the exact `sub` claim AWS saw. Compare against the
`trusted_subjects` output:

```bash
terraform output trusted_subjects
```

If the failing claim isn't in that list, edit `trusted_branch_refs` or
`trusted_environments` in `variables.tf`, re-apply, re-run the workflow.

## Out of scope

- Stage and prod environments (S3 + DynamoDB remote state pattern). Those
  ride on top of `shared/` once they exist.
- `tflint` of this env. Lands in the same commit as the lint workflow's
  terraform-validate job covers `shared/`.
