provider "aws" {
  profile             = var.aws_profile
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project     = "nexusf5"
      ManagedBy   = "terraform"
      Environment = "immutable-track"
      AutoDestroy = "true"
      # CreatedAt is set per-resource via merge() so the value is locked at
      # apply time. A default-tag value would update on every apply and lose
      # its "when did this run start" meaning.
    }
  }
}

# Per-run identifier: prefer the wrapper-supplied run_id; fall back to a
# random suffix so direct `terraform apply` from a laptop still tags
# everything with a unique CreatedAt-equivalent.
resource "random_id" "run" {
  byte_length = 4
}

locals {
  run_id = coalesce(var.run_id, random_id.run.hex)

  per_run_tags = {
    CreatedAt = local.run_id
  }
}

# Detect the runner's public IP at plan time so the VE security group only
# accepts mgmt traffic from where the apply is actually running. Same shape
# as the integration env — avoids the failure mode where a forgotten
# 0.0.0.0/0 in tfvars exposes a default-credential VE during the
# cloud-init bootstrap window.
data "http" "runner_ip" {
  count = length(var.explicit_mgmt_cidrs) == 0 ? 1 : 0
  url   = "https://api.ipify.org"

  request_headers = {
    Accept = "text/plain"
  }
}

locals {
  detected_runner_cidr = length(data.http.runner_ip) > 0 ? "${trimspace(data.http.runner_ip[0].response_body)}/32" : null

  effective_mgmt_cidrs = length(var.explicit_mgmt_cidrs) > 0 ? var.explicit_mgmt_cidrs : [local.detected_runner_cidr]
}

# Fresh VPC per run. Single public subnet, IGW, no NAT — same minimal
# topology as the integration env. A real production immutable track would
# attach to an existing VPC; this root config is a demonstration shape that
# round-trips cleanly without depending on prior infra.
resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(local.per_run_tags, { Name = "nexusf5-immutable-${local.run_id}" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.per_run_tags, { Name = "nexusf5-immutable-${local.run_id}-igw" })
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = false # EIPs only

  tags = merge(local.per_run_tags, { Name = "nexusf5-immutable-${local.run_id}-public" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = merge(local.per_run_tags, { Name = "nexusf5-immutable-${local.run_id}-rt" })
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Per-run SSH key + admin password. Same shape as the integration env. Both
# are sensitive terraform outputs; the wrapper writes them to chmod-600
# files under build/integration-immutable/.
resource "tls_private_key" "ssh" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "this" {
  key_name_prefix = "nexusf5-immutable-${local.run_id}-"
  public_key      = tls_private_key.ssh.public_key_openssh

  tags = merge(local.per_run_tags, { Name = "nexusf5-immutable-${local.run_id}-key" })
}

resource "random_password" "admin" {
  length  = 24
  special = false
}

# Single new VE provisioned at the target version. The immutable track is a
# *modernization demonstration*, not a production cutover — one VE is
# enough to prove the load-bearing claim that the DO/AS3 modules apply
# unchanged against a freshly-provisioned VE. Real production would
# provision an HA pair on the new side, but that's wave-orchestration
# scope, not declaration-portability scope.
module "bigip_aws_new" {
  source = "../modules/ve-instance"

  name      = "bigip-aws-new"
  vpc_id    = aws_vpc.this.id
  subnet_id = aws_subnet.public.id

  ssh_key_name = aws_key_pair.this.key_name

  instance_type      = var.ve_instance_type
  f5_version_pattern = var.f5_version_pattern
  f5_license_tier    = var.f5_license_tier
  f5_throughput_tier = var.f5_throughput_tier

  admin_password = random_password.admin.result

  allowed_mgmt_cidrs = local.effective_mgmt_cidrs

  tags = local.per_run_tags
}
