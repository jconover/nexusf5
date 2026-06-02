#!/usr/bin/env bash
# Read-only sweep of us-east-2 for any leftover NexusF5 / BIG-IP resources.
# Requires valid AWS credentials (profile or OIDC) in the calling shell.
# Lists only — deletes nothing. Investigate anything it prints.
set -euo pipefail
export AWS_REGION=us-east-2
export AWS_DEFAULT_REGION=us-east-2

echo "Account: $(aws sts get-caller-identity --query Account --output text)"
echo "Region : us-east-2"
echo

echo "== EC2 instances (non-terminated) =="
aws ec2 describe-instances \
  --filters "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].{Id:InstanceId,State:State.Name,Type:InstanceType,Name:Tags[?Key==`Name`]|[0].Value}' \
  --output table

echo "== Elastic IPs (each unattached one bills) =="
aws ec2 describe-addresses \
  --query 'Addresses[].{Ip:PublicIp,AllocId:AllocationId,Assoc:AssociationId}' --output table

echo "== EBS volumes =="
aws ec2 describe-volumes \
  --query 'Volumes[].{Id:VolumeId,State:State,Size:Size,Attached:Attachments[0].InstanceId}' --output table

echo "== EBS snapshots (owned by you) =="
aws ec2 describe-snapshots --owner-ids self \
  --query 'Snapshots[].{Id:SnapshotId,Size:VolumeSize,Desc:Description}' --output table

echo "== AMIs (owned by you) =="
aws ec2 describe-images --owners self \
  --query 'Images[].{Id:ImageId,Name:Name}' --output table

echo "== Key pairs =="
aws ec2 describe-key-pairs --query 'KeyPairs[].KeyName' --output table

echo "== VPCs (non-default) =="
aws ec2 describe-vpcs \
  --query 'Vpcs[?IsDefault==`false`].{Id:VpcId,Cidr:CidrBlock,Name:Tags[?Key==`Name`]|[0].Value}' \
  --output table

echo "== Security groups (non-default) =="
aws ec2 describe-security-groups \
  --query 'SecurityGroups[?GroupName!=`default`].{Id:GroupId,Name:GroupName}' --output table

echo "== NAT gateways (available) =="
aws ec2 describe-nat-gateways \
  --filter "Name=state,Values=available" \
  --query 'NatGateways[].{Id:NatGatewayId,Vpc:VpcId}' --output table

echo "== RDS instances (bill hourly) =="
aws rds describe-db-instances \
  --query 'DBInstances[].{Id:DBInstanceIdentifier,Class:DBInstanceClass,Engine:Engine,Status:DBInstanceStatus}' \
  --output table

echo "== RDS clusters (Aurora; bill hourly) =="
aws rds describe-db-clusters \
  --query 'DBClusters[].{Id:DBClusterIdentifier,Engine:Engine,Status:Status}' --output table

echo "== EFS file systems (bill on stored bytes) =="
aws efs describe-file-systems \
  --query 'FileSystems[].{Id:FileSystemId,Name:Name,Bytes:SizeInBytes.Value}' --output table

echo
echo "Sweep complete. Anything listed above is a candidate for cleanup."
echo "Cross-check VPC/SG/IGW removal — they block VPC deletion if orphaned."
