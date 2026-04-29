# Local backend by design.
#
# `shared/` creates the S3 bucket pattern would itself store its state in,
# so a remote backend here is a chicken-and-egg setup that adds bootstrap
# complexity without buying anything until stage and prod environments
# exist (PR 2.x or later). Until then this state file lives on the
# operator's laptop, gitignored. The state contains:
#   - AWS Budget definition (idempotent — recreatable from HCL)
#   - GitHub OIDC provider (one per account; recreatable from HCL)
#   - GHA assume-role IAM role + policy (recreatable from HCL)
#
# Nothing in this state is operationally hot; losing it costs one
# `terraform import` round-trip, not a service outage.
terraform {
  backend "local" {}
}
