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

# iControl REST + mgmt GUI port. BIG-IP 17.1.x defaults `sys httpd ssl-port`
# to 8443 (was 443 in earlier releases) to avoid colliding with data-plane
# VIPs that bind 443 in real deployments. We follow F5's documented
# direction-of-travel rather than overriding it back to 443 — overriding
# would compound maintenance debt as TMOS defaults shift across versions.
# Centralized in var.mgmt_https_port so a future TMOS bump that flips the
# default is one edit. The Ansible F5 collections and Terraform F5 provider
# accept arbitrary ports; both inventory's f5_api_base_url and the
# integration wrapper's probe URL read from the module's matching output.
# Limited to allowed_mgmt_cidrs so a typo'd 0.0.0.0/0 can't expose a
# bootstrap-window VE to the internet.
# Refs:
#   - BIG-IP 17.1 manual `tmsh list sys httpd` (default ssl-port = 8443)
#   - F5 K-article "Default ports for BIG-IP management traffic"
resource "aws_vpc_security_group_ingress_rule" "mgmt_https" {
  for_each = toset(var.allowed_mgmt_cidrs)

  security_group_id = aws_security_group.ve.id
  cidr_ipv4         = each.value
  from_port         = var.mgmt_https_port
  to_port           = var.mgmt_https_port
  ip_protocol       = "tcp"
  description       = "iControl REST + mgmt GUI (tcp/${var.mgmt_https_port}) from ${each.value}"

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

# First-boot bootstrap via f5-bigip-runtime-init v2.0.3
# (https://github.com/F5Networks/f5-bigip-runtime-init).
#
# Runtime-init's `bigip_ready_enabled` phase blocks until mcpd is up
# before any iControl REST work runs — that ordering is what this
# bootstrap requires. The DO declaration in `extension_services` then
# sets the admin user's password and the hostname.
#
# Don't replace this with raw tmsh user_data (races mcpd) or with no
# user_data (leaves httpd crashed after the first-boot reboot, with no
# supervisor restart). Both have been tried; runtime-init is the
# documented path. Installer URL, SHAs, schema citations, and DO User
# class shape live alongside their literal values in
# runtime-init-userdata.sh.tftpl.

resource "aws_instance" "ve" {
  ami           = data.aws_ami.f5_ve.id
  instance_type = var.instance_type
  subnet_id     = var.subnet_id
  key_name      = var.ssh_key_name

  vpc_security_group_ids = [aws_security_group.ve.id]

  # user_data is processed by BIG-IP's first-boot cloud-init. Templatefile
  # renders the bash wrapper + embedded runtime-init YAML; the password is
  # baked in at apply time as a static runtime_parameter (ADMIN_PASSWORD).
  # A change to admin_password forces replacement (user_data_replace_on_change)
  # because changing the password on a running VE via in-place user_data
  # update would leave the live admin user out of sync with terraform state
  # — replacement is the correct semantics for an ephemeral integration VE.
  user_data = templatefile("${path.module}/runtime-init-userdata.sh.tftpl", {
    admin_password = var.admin_password
    # FQDN required by F5 DO's /Common/system.hostname constraint. A bare
    # short name like 'bigip-aws-01' returns 422 / 01070903:3 "hostname
    # must be a fully qualified DNS name" and rolls back the entire
    # declaration (no admin password, no shell change). var.name stays as
    # the short form for EC2 tags and ansible inventory; only the BIG-IP
    # system hostname is FQDN-shaped.
    hostname = "${var.name}.${var.hostname_dns_suffix}"
  })
  user_data_replace_on_change = true

  # Public IP via EIP, not auto-assigned, so the address survives stop/start.
  associate_public_ip_address = false

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
