# GitHub Actions OIDC trust — workflows assume this role via OIDC instead of
# storing long-lived AWS access keys.
#
# Trust policy scope (intentional and load-bearing):
#   - Specific repository (no wildcards on the GitHub side)
#   - Named branches OR named GitHub environments — both, never any of either
#   - sts.amazonaws.com audience
#
# A wildcard sub-claim like `repo:OWNER/REPO:*` would let any branch (and
# any pull-request fork ref) assume the role. That's the failure mode AWS
# Security Hub and `aws-actions/configure-aws-credentials` documentation
# explicitly call out — fork PRs can otherwise mint AWS credentials. This
# trust policy is built up from explicit lists in variables.tf.
#
# To debug trust-policy mismatches: GitHub's OIDC token includes the actual
# `sub` claim that AWS sees. The aws-actions/configure-aws-credentials
# action prints the assume-role failure with the exact subject string the
# trust policy rejected, which is what to compare against the StringLike
# patterns below.

# Thumbprint is largely cosmetic — AWS validates the OIDC issuer against
# its internal IDP allowlist for github.com rather than the supplied
# fingerprint, but the IAM provider resource still requires the field. The
# value is GitHub's documented sha1 fingerprint and is verifiable via:
#   echo | openssl s_client -showcerts -servername token.actions.githubusercontent.com \
#     -connect token.actions.githubusercontent.com:443 2>/dev/null | \
#     openssl x509 -fingerprint -noout -sha1
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  # Explicit AutoDestroy=false even though default_tags sets the same
  # value account-wide. This resource has only one in the account (an
  # OIDC provider URL is unique), and any nuclear-option teardown that
  # filtered on AutoDestroy=true must never reach it. Defense in depth
  # against a typo'd inversion of the filter.
  tags = {
    AutoDestroy = "false"
  }
}

data "aws_iam_policy_document" "gha_trust" {
  statement {
    sid     = "AssumeRoleFromGitHubActions"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = concat(
        [for r in var.trusted_branch_refs : "repo:${var.github_repo}:ref:${r}"],
        [for e in var.trusted_environments : "repo:${var.github_repo}:environment:${e}"],
      )
    }
  }
}

resource "aws_iam_role" "gha" {
  name        = var.github_oidc_role_name
  description = "GitHub Actions OIDC role for nexusf5 workflows. Trust policy is repo-scoped and limited to specific branches + environments - see oidc.tf."

  assume_role_policy = data.aws_iam_policy_document.gha_trust.json

  # 1-hour session is plenty for the integration test (45-min outer timeout
  # plus margin) and keeps blast radius small if a credential is exfiltrated
  # mid-flight.
  max_session_duration = 3600
}

# Read-only baseline so the auth-test workflow can do something meaningful
# beyond `aws sts get-caller-identity`. Provisioning permissions land in a
# follow-up commit alongside the ve-instance module — keeping the policy
# narrow during OIDC trust-policy iteration limits blast radius if the
# trust policy turns out to be broader than intended.
data "aws_iam_policy_document" "gha_readonly" {
  statement {
    sid    = "RegionScopedDescribeAndIdentity"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "iam:GetRole",
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }
}

resource "aws_iam_role_policy" "gha_readonly" {
  name   = "${var.github_oidc_role_name}-readonly"
  role   = aws_iam_role.gha.id
  policy = data.aws_iam_policy_document.gha_readonly.json
}
