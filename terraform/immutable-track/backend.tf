# Local backend by design — same rationale as terraform/environments/integration:
# everything in this root is AutoDestroy=true and ≤ 45 min long-lived. State
# is recreated by the wrapper on every `make integration-immutable` run; a
# remote backend would only add a leak vector (interrupted run leaves state
# in S3 nobody owns).
terraform {
  backend "local" {}
}
