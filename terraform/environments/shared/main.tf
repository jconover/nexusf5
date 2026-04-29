provider "aws" {
  profile = var.aws_profile
  region  = var.aws_region

  # Belt-and-suspenders against a stray AWS_PROFILE in the operator's shell:
  # the provider refuses to apply if the resolved caller identity isn't the
  # expected account. Without this guard, `terraform apply` against the wrong
  # profile would silently create a $50 budget and an OIDC provider in
  # someone else's account.
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project     = "nexusf5"
      ManagedBy   = "terraform"
      Environment = "shared"
      # Resources in `shared/` are intentionally long-lived (budget alarm,
      # OIDC trust). The AutoDestroy=true tag is reserved for ephemeral
      # integration resources in terraform/environments/integration/ — see
      # tools/integration-wrapper.py for the nuclear-option teardown filter.
      AutoDestroy = "false"
    }
  }
}

# Caller identity is captured as a data source so it surfaces in `terraform
# output` after apply. Useful when iterating the OIDC trust policy from a
# laptop — confirms which principal the role gets created against.
data "aws_caller_identity" "current" {}
