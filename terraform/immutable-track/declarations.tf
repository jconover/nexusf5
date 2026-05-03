# DO + AS3 declarations applied to the new VE.
#
# This is the load-bearing claim of the immutable track: the do-declaration
# and as3-declaration modules from PR 1 apply unchanged against a
# freshly-provisioned VE. If a declaration works against a hybrid-upgraded
# VE (lab env) and against this fresh VE, that's the proof of declaration
# portability.
#
# The bigip provider talks to the VE's iControl REST endpoint. The VE only
# answers iControl REST after f5-bigip-runtime-init's `bigip_ready_enabled`
# phase posts the bootstrap DO declaration (admin user + hostname) — which
# means a single `terraform apply` from cold cannot drive these resources
# directly: the provider tries to authenticate at apply time, before
# user_data has finished running. The integration wrapper splits this into
# two phases with `-target`:
#
#   Phase 1: terraform apply -target=module.bigip_aws_new -target=local_sensitive_file.inventory \
#            -target=local_sensitive_file.ssh_private_key
#            (creates the VE; user_data runs runtime-init; admin password set)
#   Phase 2: (after the wrapper waits for /mgmt/tm/sys/version → 200)
#            terraform apply  -- full graph; bigip_do + bigip_as3 succeed
#
# Direct `terraform apply` from a laptop must follow the same two-phase
# shape — see README.md "Two-phase apply" for the manual recipe.

provider "bigip" {
  alias    = "bigip_aws_new"
  address  = module.bigip_aws_new.mgmt_public_ip
  port     = tostring(module.bigip_aws_new.mgmt_https_port)
  username = "admin"
  password = random_password.admin.result
  # token_auth=false matches the lab env. Basic auth is sufficient for the
  # short-lived integration credential and avoids the token-refresh edge
  # cases the F5 provider handles inconsistently.
  token_auth = false
  # Note on TLS verification: the F5Networks/bigip provider does not expose
  # a per-provider validate_certs/ssl_verify argument — the underlying HTTP
  # client is built with InsecureSkipVerify=true unconditionally for the
  # iControl REST channel. The freshly-bootstrapped VE serves a self-signed
  # cert from a per-instance CA, which would never validate; the provider's
  # default is the right default for this lifecycle. If TLS pinning is
  # needed in the future, do it via a sidecar (e.g. trusted_cert_path on a
  # newer provider release) rather than expecting an argument here.
}

module "do_new" {
  source    = "../modules/do-declaration"
  providers = { bigip = bigip.bigip_aws_new }

  # FQDN matches the runtime-init bootstrap hostname so the DO declaration
  # is idempotent — re-applying does not change /Common/system.hostname.
  device_hostname = "bigip-aws-new.nexusf5.local"
}

module "as3_new" {
  source    = "../modules/as3-declaration"
  providers = { bigip = bigip.bigip_aws_new }

  device_hostname = "bigip-aws-new.nexusf5.local"
  tenant_name     = "nexusf5_immutable"
  vip_address     = "10.98.10.10"
}
