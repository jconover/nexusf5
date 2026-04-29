# Local backend by design.
#
# Every resource in this env carries AutoDestroy=true and is meant to live
# for ~45 minutes max. State is recreated on every `make integration` run
# (the wrapper's first step is `terraform init`); a remote backend would
# add latency and a leak vector (an interrupted run leaving state in S3
# that nobody knows about) without buying anything.
#
# State file is gitignored. Wrapper handles cleanup on its own — see
# tools/integration-wrapper.py.
terraform {
  backend "local" {}
}
