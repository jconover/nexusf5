# F5 BIG-IP VE PAYG marketplace AMI lookup.
#
# Owner 679593333241 is F5 Networks Inc.'s AWS Marketplace publisher ID. The
# name filter combines the version pattern, license tier, and throughput tier
# variables — concrete examples:
#   F5 BIGIP-17.1.1.1-0.0.4 PAYG-Good 1Gbps Best ...
#   F5 BIGIP-17.1.0.3-0.0.5 PAYG-Best 1Gbps 2Boot...
# most_recent=true picks the latest match. Pin f5_version_pattern in the
# integration env's tfvars before merging if reproducibility matters more
# than tracking F5's point releases.
data "aws_ami" "f5_ve" {
  most_recent = true
  owners      = ["679593333241"]

  filter {
    name   = "name"
    values = ["${var.f5_version_pattern} PAYG-${var.f5_license_tier} ${var.f5_throughput_tier}*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# Single security group governing both ingress to the VE mgmt plane and
# egress from the VE to anywhere it needs to reach (NTP, DNS, F5 phone-home
# is disabled in DO but other outbound is fine). Three-NIC production
# topologies would split mgmt and data plane SGs; PR 2 uses one ENI by
# design and one SG matches.
resource "aws_security_group" "ve" {
  name_prefix = "${var.name}-"
  vpc_id      = var.vpc_id
  description = "F5 BIG-IP VE mgmt + iControl REST. PR 2 single-NIC."

  tags = merge(var.tags, { Name = "${var.name}-sg" })
}

# 443/tcp = iControl REST + GUI. The Ansible roles and Terraform F5 provider
# both target this port. Limited to allowed_mgmt_cidrs so a typo'd 0.0.0.0/0
# in the integration env can't expose a default-credential VE to the
# internet during the bootstrap window.
resource "aws_vpc_security_group_ingress_rule" "mgmt_https" {
  for_each = toset(var.allowed_mgmt_cidrs)

  security_group_id = aws_security_group.ve.id
  cidr_ipv4         = each.value
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "iControl REST + mgmt GUI from ${each.value}"

  tags = merge(var.tags, { Name = "${var.name}-mgmt-https-${each.value}" })
}

# 22/tcp = SSH for ad-hoc tmsh inspection during integration test failures.
# Not used by the upgrade flow itself (everything goes through iControl
# REST), but invaluable when debugging a wedged VE.
resource "aws_vpc_security_group_ingress_rule" "mgmt_ssh" {
  for_each = toset(var.allowed_mgmt_cidrs)

  security_group_id = aws_security_group.ve.id
  cidr_ipv4         = each.value
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
  description       = "SSH from ${each.value}"

  tags = merge(var.tags, { Name = "${var.name}-mgmt-ssh-${each.value}" })
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.ve.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Egress anywhere (DNS, NTP, package fetch)"

  tags = merge(var.tags, { Name = "${var.name}-egress" })
}

# Static EIP so ansible inventory and ansible host_vars don't have to
# regenerate after every reboot. The address is released on destroy via
# the EIP resource's lifecycle.
resource "aws_eip" "ve" {
  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.name}-eip" })
}

resource "aws_eip_association" "ve" {
  instance_id   = aws_instance.ve.id
  allocation_id = aws_eip.ve.id
}

# Cloud-init runs at first boot. F5 BIG-IP VE recognises a tmsh-style script
# and runs it once the management plane is ready. Sets the admin password to
# the variable value so the integration wrapper has a known credential before
# the DO declaration replaces it. gui-setup disabled skips the post-boot
# wizard that would otherwise block iControl REST until a human clicked
# through. Save persists the change across reboots.
#
# Caveat: user_data is visible to anyone with ec2:DescribeInstanceAttribute
# in this account. The integration wrapper randomises admin_password per run
# and the VE is destroyed within 45 minutes, so the exposure window is
# bounded — but the password is not a long-lived secret and must not be
# reused outside the run that generated it.
locals {
  user_data = <<-EOT
    #!/usr/bin/env bash
    set -euo pipefail
    tmsh modify auth user admin password '${var.admin_password}'
    tmsh modify sys global-settings gui-setup disabled
    tmsh save sys config
  EOT
}

resource "aws_instance" "ve" {
  ami           = data.aws_ami.f5_ve.id
  instance_type = var.instance_type
  subnet_id     = var.subnet_id
  key_name      = var.ssh_key_name

  vpc_security_group_ids = [aws_security_group.ve.id]

  # Public IP via EIP, not auto-assigned, so the address survives stop/start.
  associate_public_ip_address = false

  user_data                   = local.user_data
  user_data_replace_on_change = true

  # F5 BIG-IP VE images ship with an 80GB root volume requirement. Going
  # smaller fails first-boot disk checks; going larger is wasted spend. gp3
  # is cheaper than gp2 with equivalent perf for this workload.
  root_block_device {
    volume_size           = 80
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true

    tags = merge(var.tags, { Name = "${var.name}-root" })
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  tags = merge(var.tags, { Name = var.name })

  lifecycle {
    # AMI updates would force replacement, which is exactly what we want for
    # an ephemeral integration VE — but mark it explicit so plan output is
    # readable when F5 publishes a point release between runs.
    ignore_changes = []
  }
}
