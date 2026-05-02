provider "aws" {
  profile             = var.aws_profile
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project     = "nexusf5"
      ManagedBy   = "terraform"
      Environment = "integration"
      AutoDestroy = "true"
      # CreatedAt is set per-resource via merge() in ve-instances.tf so the
      # value is locked at apply time. A default-tag value would update on
      # every apply and lose its "when did this run start" meaning.
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

  # Threaded onto every resource the ve-instance module creates. The
  # nuclear-option teardown filters on AutoDestroy=true; CreatedAt lets a
  # human age-filter when investigating a leaked resource.
  per_run_tags = {
    CreatedAt = local.run_id
  }
}

# Detect the runner's public IP at plan time so the VE security group only
# accepts mgmt traffic from where the integration test is actually running.
# Avoids the failure mode where a forgotten 0.0.0.0/0 in tfvars exposes a
# default-credential VE during the cloud-init bootstrap window.
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

# Fresh VPC per run. No NAT gateway (the most expensive accidental leak),
# no peering, no transit gateway. Public subnet only — VEs reach the
# internet directly via IGW for AMI activation and DNS, and the operator
# reaches the VEs via EIP from the runner CIDR.
resource "aws_vpc" "integration" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(local.per_run_tags, { Name = "nexusf5-integration-${local.run_id}" })
}

resource "aws_internet_gateway" "integration" {
  vpc_id = aws_vpc.integration.id
  tags   = merge(local.per_run_tags, { Name = "nexusf5-integration-${local.run_id}-igw" })
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.integration.id
  cidr_block              = var.subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = false # EIPs only; no auto-assigned ephemeral IPs

  tags = merge(local.per_run_tags, { Name = "nexusf5-integration-${local.run_id}-public" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.integration.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.integration.id
  }

  tags = merge(local.per_run_tags, { Name = "nexusf5-integration-${local.run_id}-rt" })
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Generate an ephemeral SSH key pair per run. The private key surfaces in
# the local terraform state file (gitignored) and as a base64-encoded
# output the wrapper writes to a chmod-600 file on disk for ad-hoc tmsh
# debugging. The key never persists past the run's destroy.
resource "tls_private_key" "ssh" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "integration" {
  key_name_prefix = "nexusf5-integration-${local.run_id}-"
  public_key      = tls_private_key.ssh.public_key_openssh

  tags = merge(local.per_run_tags, { Name = "nexusf5-integration-${local.run_id}-key" })
}

# Per-run admin password, threaded through the ve-instance module's
# admin_password variable into the runtime-init YAML as a static
# runtime_parameter and rendered into the DO User declaration on first
# boot. Both VEs share one password (single resource, two module
# instances) — fine for an ephemeral integration env.
#
# Alphanumeric only (special = false → [A-Za-z0-9]) at 24 chars
# (~143 bits) sidesteps escape rules across all five layers between
# terraform and tmsh: templatefile, single-quoted YAML, runtime-init
# triple-mustache, DO JSON, iControl REST. Entropy is more than enough
# for a 30-45 minute integration credential.
resource "random_password" "admin" {
  length  = 24
  special = false
}
