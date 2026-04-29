# Local backend for the lab. State for the mock fleet has no value beyond
# the local apply -> plan loop, and a remote backend would force every
# contributor to provision an S3 bucket + DynamoDB lock just to run
# `make lab-up` against a laptop. Real environments (PR 2's stage/prod)
# use the S3 + DynamoDB pattern documented in CLAUDE.md.
terraform {
  backend "local" {}
}
