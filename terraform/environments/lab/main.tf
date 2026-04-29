# Lab environment — wires the do-declaration and as3-declaration modules to
# the 5 canary mock devices.
#
# WHY THIS FILE IS REPETITIVE:
# Terraform's provider model is static. `for_each` cannot be applied to
# `provider` blocks (HCL grammar rejects it; aliases must be known at parse
# time so the dependency graph can be built before any expression evaluates).
# That means one `provider "bigip"` block per device and one explicit
# `module ... { providers = { bigip = bigip.<alias> } }` per device. Five
# devices yields ~50 lines of structural duplication. This is correct and
# load-bearing — collapsing it requires a pre-render step (e.g. cookiecutter)
# that obscures the per-device wiring without saving meaningful work.
#
# Source-of-truth port allocation lives in mock-f5/manifests/canary.json and
# is mirrored in terraform.tfvars; if those drift, the proxy adapter routes
# the wrong device.

provider "bigip" {
  alias      = "bigip_lab_01"
  address    = "127.0.0.1"
  port       = "8101"
  username   = var.f5_username
  password   = var.f5_password
  token_auth = false
}

provider "bigip" {
  alias      = "bigip_lab_02"
  address    = "127.0.0.1"
  port       = "8102"
  username   = var.f5_username
  password   = var.f5_password
  token_auth = false
}

provider "bigip" {
  alias      = "bigip_lab_03"
  address    = "127.0.0.1"
  port       = "8103"
  username   = var.f5_username
  password   = var.f5_password
  token_auth = false
}

provider "bigip" {
  alias      = "bigip_lab_04"
  address    = "127.0.0.1"
  port       = "8104"
  username   = var.f5_username
  password   = var.f5_password
  token_auth = false
}

provider "bigip" {
  alias      = "bigip_lab_05"
  address    = "127.0.0.1"
  port       = "8105"
  username   = var.f5_username
  password   = var.f5_password
  token_auth = false
}

locals {
  device_by_name = { for d in var.canary_devices : d.hostname => d }
}

module "do_bigip_lab_01" {
  source          = "../../modules/do-declaration"
  providers       = { bigip = bigip.bigip_lab_01 }
  device_hostname = local.device_by_name["bigip-lab-01"].hostname
}

module "do_bigip_lab_02" {
  source          = "../../modules/do-declaration"
  providers       = { bigip = bigip.bigip_lab_02 }
  device_hostname = local.device_by_name["bigip-lab-02"].hostname
}

module "do_bigip_lab_03" {
  source          = "../../modules/do-declaration"
  providers       = { bigip = bigip.bigip_lab_03 }
  device_hostname = local.device_by_name["bigip-lab-03"].hostname
}

module "do_bigip_lab_04" {
  source          = "../../modules/do-declaration"
  providers       = { bigip = bigip.bigip_lab_04 }
  device_hostname = local.device_by_name["bigip-lab-04"].hostname
}

module "do_bigip_lab_05" {
  source          = "../../modules/do-declaration"
  providers       = { bigip = bigip.bigip_lab_05 }
  device_hostname = local.device_by_name["bigip-lab-05"].hostname
}

module "as3_bigip_lab_01" {
  source          = "../../modules/as3-declaration"
  providers       = { bigip = bigip.bigip_lab_01 }
  device_hostname = local.device_by_name["bigip-lab-01"].hostname
  tenant_name     = "nexusf5_lab_01"
  vip_address     = "10.10.0.11"
}

module "as3_bigip_lab_02" {
  source          = "../../modules/as3-declaration"
  providers       = { bigip = bigip.bigip_lab_02 }
  device_hostname = local.device_by_name["bigip-lab-02"].hostname
  tenant_name     = "nexusf5_lab_02"
  vip_address     = "10.10.0.12"
}

module "as3_bigip_lab_03" {
  source          = "../../modules/as3-declaration"
  providers       = { bigip = bigip.bigip_lab_03 }
  device_hostname = local.device_by_name["bigip-lab-03"].hostname
  tenant_name     = "nexusf5_lab_03"
  vip_address     = "10.10.0.13"
}

module "as3_bigip_lab_04" {
  source          = "../../modules/as3-declaration"
  providers       = { bigip = bigip.bigip_lab_04 }
  device_hostname = local.device_by_name["bigip-lab-04"].hostname
  tenant_name     = "nexusf5_lab_04"
  vip_address     = "10.10.0.14"
}

module "as3_bigip_lab_05" {
  source          = "../../modules/as3-declaration"
  providers       = { bigip = bigip.bigip_lab_05 }
  device_hostname = local.device_by_name["bigip-lab-05"].hostname
  tenant_name     = "nexusf5_lab_05"
  vip_address     = "10.10.0.15"
}
