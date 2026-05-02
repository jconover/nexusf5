output "aws_account_id" {
  value       = data.aws_caller_identity.current.account_id
  description = "Account ID terraform applied against. Cross-check against the expected value before consuming any other output."
}

output "github_oidc_role_arn" {
  value       = aws_iam_role.gha.arn
  description = "ARN GHA workflows assume via aws-actions/configure-aws-credentials. Mirror this into the repo's vars.AWS_OIDC_ROLE_ARN GitHub Actions variable; do not hard-code in workflow YAML."
}

output "github_oidc_provider_arn" {
  value       = aws_iam_openid_connect_provider.github.arn
  description = "OIDC provider ARN. Useful when granting additional roles a sts:AssumeRoleWithWebIdentity trust on the same provider — never re-create the provider in another env."
}

output "trusted_subjects" {
  value = concat(
    [for r in var.trusted_branch_refs : "repo:${var.github_repo}:ref:${r}"],
    [for e in var.trusted_environments : "repo:${var.github_repo}:environment:${e}"],
  )
  description = "Exact subject claims the trust policy accepts. Compare against the failing sub claim in any aws-actions/configure-aws-credentials assume-role error message — string mismatch is the most common bug."
}
