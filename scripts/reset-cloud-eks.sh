#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-${REGION:-eu-west-1}}"
ENVIRONMENT="${ENVIRONMENT:-production}"
CLUSTER_NAME="retailvision-${ENVIRONMENT}"

if [[ "${CONFIRM_RESET:-}" != "$CLUSTER_NAME" ]]; then
  echo "ERROR: this command permanently deletes the ${CLUSTER_NAME} cloud deployment." >&2
  echo "To confirm, run:" >&2
  echo "  export CONFIRM_RESET=${CLUSTER_NAME}" >&2
  echo "  make cloud-eks-reset" >&2
  exit 1
fi

if [[ ! -d infra/aws ]]; then
  echo "ERROR: run this script from the retail-edge repository root." >&2
  exit 1
fi

for cmd in aws terraform kubectl helm jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: missing command: $cmd. Run make cloud-eks-prereqs first." >&2
    exit 1
  fi
done

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${BUCKET:-retailvision-prod-objects-${ACCOUNT_ID}}"
TF_STATE_BUCKET="${TF_STATE_BUCKET:-retailvision-tfstate-${ACCOUNT_ID}-${AWS_REGION}}"
TF_LOCK_TABLE="${TF_LOCK_TABLE:-retailvision-tflock-${AWS_REGION}}"
RESET_VARS_FILE="infra/aws/reset.auto.tfvars"

cat >"$RESET_VARS_FILE" <<EOF
aws_region        = "${AWS_REGION}"
environment       = "${ENVIRONMENT}"
letsencrypt_email = "reset-only@example.invalid"
s3_bucket_name    = "${BUCKET}"
EOF
trap 'rm -f "$RESET_VARS_FILE"' EXIT

echo "Resetting ${CLUSTER_NAME} in account ${ACCOUNT_ID}, region ${AWS_REGION}."
echo "Terraform backend bucket ${TF_STATE_BUCKET} and lock table ${TF_LOCK_TABLE} are retained."

cat > infra/aws/backend.tf <<EOF
terraform {
  backend "s3" {}
}
EOF

if aws s3api head-bucket --bucket "$TF_STATE_BUCKET" >/dev/null 2>&1; then
  terraform -chdir=infra/aws init -reconfigure \
    -backend-config="bucket=${TF_STATE_BUCKET}" \
    -backend-config="key=retailvision/${AWS_REGION}/terraform.tfstate" \
    -backend-config="region=${AWS_REGION}" \
    -backend-config="dynamodb_table=${TF_LOCK_TABLE}" \
    -backend-config="encrypt=true"

  echo "Destroying resources tracked by the active remote Terraform state..."
  set +e
  terraform -chdir=infra/aws destroy -auto-approve
  TF_DESTROY_STATUS=$?
  set -e
  if ((TF_DESTROY_STATUS != 0)); then
    echo "Terraform destroy was partial; continuing with scoped orphan cleanup."
  fi
fi

if aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "Cleaning Kubernetes resources from ${CLUSTER_NAME}..."
  aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" >/dev/null

  kubectl delete nodepool default --ignore-not-found --wait=false 2>/dev/null || true
  kubectl delete ec2nodeclass default --ignore-not-found --wait=false 2>/dev/null || true
  helm uninstall retailvision -n retailvision 2>/dev/null || true
  kubectl delete namespace retailvision --ignore-not-found --wait=false 2>/dev/null || true

  for release_spec in \
    "ingress-nginx|ingress-nginx" \
    "aws-load-balancer-controller|kube-system" \
    "cert-manager|cert-manager" \
    "external-secrets|external-secrets" \
    "keda|keda" \
    "metrics-server|kube-system" \
    "karpenter|kube-system"
  do
    release="${release_spec%%|*}"
    namespace="${release_spec##*|}"
    helm uninstall "$release" -n "$namespace" 2>/dev/null || true
  done

  sleep 30

  NODEGROUPS="$(aws eks list-nodegroups \
    --cluster-name "$CLUSTER_NAME" \
    --region "$AWS_REGION" \
    --query 'nodegroups[]' \
    --output text 2>/dev/null || true)"
  for nodegroup in $NODEGROUPS; do
    echo "Requesting deletion of EKS node group ${nodegroup}..."
    aws eks delete-nodegroup \
      --cluster-name "$CLUSTER_NAME" \
      --nodegroup-name "$nodegroup" \
      --region "$AWS_REGION" \
      >/dev/null || true
  done
  for nodegroup in $NODEGROUPS; do
    echo "Waiting for EKS node group ${nodegroup} to be deleted..."
    aws eks wait nodegroup-deleted \
      --cluster-name "$CLUSTER_NAME" \
      --nodegroup-name "$nodegroup" \
      --region "$AWS_REGION" || true
    echo "EKS node group ${nodegroup} deletion wait finished."
  done

  FARGATE_PROFILES="$(aws eks list-fargate-profiles \
    --cluster-name "$CLUSTER_NAME" \
    --region "$AWS_REGION" \
    --query 'fargateProfileNames[]' \
    --output text 2>/dev/null || true)"
  for profile in $FARGATE_PROFILES; do
    echo "Deleting EKS Fargate profile ${profile}..."
    aws eks delete-fargate-profile \
      --cluster-name "$CLUSTER_NAME" \
      --fargate-profile-name "$profile" \
      --region "$AWS_REGION" \
      >/dev/null || true
    aws eks wait fargate-profile-deleted \
      --cluster-name "$CLUSTER_NAME" \
      --fargate-profile-name "$profile" \
      --region "$AWS_REGION" || true
    echo "EKS Fargate profile ${profile} deletion wait finished."
  done

  echo "Requesting deletion of EKS cluster ${CLUSTER_NAME}..."
  aws eks delete-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" >/dev/null || true
  echo "Waiting for EKS cluster ${CLUSTER_NAME} to be deleted..."
  aws eks wait cluster-deleted --name "$CLUSTER_NAME" --region "$AWS_REGION" || true
  echo "EKS cluster ${CLUSTER_NAME} deletion wait finished."
fi

echo "Terminating project EC2 instances..."
INSTANCE_IDS="$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters \
    "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    "Name=tag:karpenter.sh/discovery,Values=${CLUSTER_NAME}" \
  --query 'Reservations[].Instances[].InstanceId' \
  --output text)"
WG_INSTANCE_IDS="$(aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters \
    "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    "Name=tag:Name,Values=${CLUSTER_NAME}-wireguard" \
  --query 'Reservations[].Instances[].InstanceId' \
  --output text)"
ALL_INSTANCE_IDS="$(printf '%s\n%s\n' "$INSTANCE_IDS" "$WG_INSTANCE_IDS" | tr '\t ' '\n' | sed '/^$/d' | sort -u | tr '\n' ' ')"
if [[ -n "$ALL_INSTANCE_IDS" ]]; then
  read -r -a instance_id_array <<<"$ALL_INSTANCE_IDS"
  aws ec2 terminate-instances --region "$AWS_REGION" --instance-ids "${instance_id_array[@]}" >/dev/null
  aws ec2 wait instance-terminated --region "$AWS_REGION" --instance-ids "${instance_id_array[@]}" || true
fi

echo "Deleting project load balancers..."
LOAD_BALANCER_ARNS="$(aws elbv2 describe-load-balancers \
  --region "$AWS_REGION" \
  --query 'LoadBalancers[].LoadBalancerArn' \
  --output text)"
[[ "$LOAD_BALANCER_ARNS" == "None" ]] && LOAD_BALANCER_ARNS=""
for arn in $LOAD_BALANCER_ARNS; do
  tags="$(aws elbv2 describe-tags --region "$AWS_REGION" --resource-arns "$arn" --output json 2>/dev/null || echo '{}')"
  if jq -e --arg cluster "$CLUSTER_NAME" '
    [.TagDescriptions[0].Tags[]?] |
    any(
      (.Key == "elbv2.k8s.aws/cluster" and .Value == $cluster) or
      (.Key == ("kubernetes.io/cluster/" + $cluster)) or
      (.Key == "kubernetes.io/service-name" and (.Value | startswith("retailvision/")))
    )
  ' <<<"$tags" >/dev/null; then
    aws elbv2 delete-load-balancer --region "$AWS_REGION" --load-balancer-arn "$arn" || true
  fi
done
sleep 30

echo "Releasing RetailVision Elastic IPs..."
for _ in {1..12}; do
  EIP_ROWS="$(aws ec2 describe-addresses \
    --region "$AWS_REGION" \
    --filters "Name=tag:Name,Values=${CLUSTER_NAME}-*" \
    --query 'Addresses[].[AllocationId,AssociationId]' \
    --output text)"
  [[ "$EIP_ROWS" == "None" ]] && EIP_ROWS=""
  [[ -z "$EIP_ROWS" ]] && break
  while read -r allocation_id association_id; do
    [[ -z "${allocation_id:-}" || "$allocation_id" == "None" ]] && continue
    if [[ -n "${association_id:-}" && "$association_id" != "None" ]]; then
      aws ec2 disassociate-address --region "$AWS_REGION" --association-id "$association_id" 2>/dev/null || true
    fi
    aws ec2 release-address --region "$AWS_REGION" --allocation-id "$allocation_id" 2>/dev/null || true
  done <<<"$EIP_ROWS"
  sleep 10
done

echo "Deleting versioned object bucket ${BUCKET}..."
if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  aws s3 rm "s3://${BUCKET}" --recursive --region "$AWS_REGION" || true
  while true; do
    PAGE="$(aws s3api list-object-versions --bucket "$BUCKET" --region "$AWS_REGION" --max-keys 1000 --output json)"
    DELETE_PAYLOAD="$(jq -c '{
      Objects: (((.Versions // []) + (.DeleteMarkers // [])) | map({Key, VersionId})),
      Quiet: true
    }' <<<"$PAGE")"
    OBJECT_COUNT="$(jq '.Objects | length' <<<"$DELETE_PAYLOAD")"
    ((OBJECT_COUNT == 0)) && break
    aws s3api delete-objects \
      --bucket "$BUCKET" \
      --region "$AWS_REGION" \
      --delete "$DELETE_PAYLOAD" \
      >/dev/null
  done
  aws s3api delete-bucket --bucket "$BUCKET" --region "$AWS_REGION" || true
fi

echo "Deleting RetailVision secrets..."
SECRETS=(
  retailvision/postgres-password
  retailvision/redis-password
  retailvision/jwt-secret
  retailvision/agent-secret
  retailvision/redis-url
  retailvision/s3-access-key
  retailvision/s3-secret-key
  retailvision/openai-api-key
  retailvision/grafana-admin-password
)
for secret in "${SECRETS[@]}"; do
  aws secretsmanager delete-secret \
    --region "$AWS_REGION" \
    --secret-id "$secret" \
    --force-delete-without-recovery \
    >/dev/null 2>&1 || true
done
for _ in {1..60}; do
  remaining=0
  for secret in "${SECRETS[@]}"; do
    if aws secretsmanager describe-secret --region "$AWS_REGION" --secret-id "$secret" >/dev/null 2>&1; then
      remaining=$((remaining + 1))
    fi
  done
  ((remaining == 0)) && break
  sleep 2
done

delete_iam_user() {
  local user="$1"
  aws iam get-user --user-name "$user" >/dev/null 2>&1 || return 0
  for key in $(aws iam list-access-keys --user-name "$user" --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
    aws iam delete-access-key --user-name "$user" --access-key-id "$key" || true
  done
  for policy in $(aws iam list-user-policies --user-name "$user" --query 'PolicyNames[]' --output text); do
    aws iam delete-user-policy --user-name "$user" --policy-name "$policy" || true
  done
  for policy_arn in $(aws iam list-attached-user-policies --user-name "$user" --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-user-policy --user-name "$user" --policy-arn "$policy_arn" || true
  done
  aws iam delete-user --user-name "$user" || true
}

delete_iam_role() {
  local role="$1"
  aws iam get-role --role-name "$role" >/dev/null 2>&1 || return 0
  for profile in $(aws iam list-instance-profiles-for-role --role-name "$role" --query 'InstanceProfiles[].InstanceProfileName' --output text); do
    aws iam remove-role-from-instance-profile --instance-profile-name "$profile" --role-name "$role" || true
    aws iam delete-instance-profile --instance-profile-name "$profile" || true
  done
  for policy in $(aws iam list-role-policies --role-name "$role" --query 'PolicyNames[]' --output text); do
    aws iam delete-role-policy --role-name "$role" --policy-name "$policy" || true
  done
  for policy_arn in $(aws iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-role-policy --role-name "$role" --policy-arn "$policy_arn" || true
  done
  aws iam delete-role --role-name "$role" || true
}

echo "Deleting fixed-name IAM resources..."
delete_iam_user "retailvision-${ENVIRONMENT}-s3"
delete_iam_role "${CLUSTER_NAME}-wireguard"
delete_iam_role "${CLUSTER_NAME}-ebs-csi"
delete_iam_role "${CLUSTER_NAME}-lb-controller"
delete_iam_role "${CLUSTER_NAME}-external-secrets"

echo "Deleting project CloudWatch log group and KMS alias..."
aws logs delete-log-group \
  --region "$AWS_REGION" \
  --log-group-name "/aws/eks/${CLUSTER_NAME}/cluster" \
  2>/dev/null || true

KMS_KEY_ID="$(aws kms list-aliases \
  --region "$AWS_REGION" \
  --query "Aliases[?AliasName=='alias/eks/${CLUSTER_NAME}'].TargetKeyId | [0]" \
  --output text)"
if [[ -n "$KMS_KEY_ID" && "$KMS_KEY_ID" != "None" ]]; then
  aws kms delete-alias --region "$AWS_REGION" --alias-name "alias/eks/${CLUSTER_NAME}" || true
  aws kms schedule-key-deletion --region "$AWS_REGION" --key-id "$KMS_KEY_ID" --pending-window-in-days 7 >/dev/null || true
fi

KARPENTER_QUEUE_URL="$(aws sqs get-queue-url \
  --region "$AWS_REGION" \
  --queue-name "Karpenter-${CLUSTER_NAME}" \
  --query QueueUrl \
  --output text 2>/dev/null || true)"
if [[ -n "$KARPENTER_QUEUE_URL" && "$KARPENTER_QUEUE_URL" != "None" ]]; then
  aws sqs delete-queue --region "$AWS_REGION" --queue-url "$KARPENTER_QUEUE_URL" || true
fi

echo "Removing leftover project VPCs..."
VPC_IDS="$(aws ec2 describe-vpcs \
  --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=retailvision-${ENVIRONMENT}" \
  --query 'Vpcs[].VpcId' \
  --output text)"
for vpc_id in $VPC_IDS; do
  ENDPOINTS="$(aws ec2 describe-vpc-endpoints --region "$AWS_REGION" --filters "Name=vpc-id,Values=$vpc_id" --query 'VpcEndpoints[].VpcEndpointId' --output text)"
  if [[ -n "$ENDPOINTS" && "$ENDPOINTS" != "None" ]]; then
    read -r -a endpoint_id_array <<<"$ENDPOINTS"
    aws ec2 delete-vpc-endpoints --region "$AWS_REGION" --vpc-endpoint-ids "${endpoint_id_array[@]}" >/dev/null || true
  fi

  for igw in $(aws ec2 describe-internet-gateways --region "$AWS_REGION" --filters "Name=attachment.vpc-id,Values=$vpc_id" --query 'InternetGateways[].InternetGatewayId' --output text); do
    aws ec2 detach-internet-gateway --region "$AWS_REGION" --internet-gateway-id "$igw" --vpc-id "$vpc_id" || true
    aws ec2 delete-internet-gateway --region "$AWS_REGION" --internet-gateway-id "$igw" || true
  done

  for subnet in $(aws ec2 describe-subnets --region "$AWS_REGION" --filters "Name=vpc-id,Values=$vpc_id" --query 'Subnets[].SubnetId' --output text); do
    aws ec2 delete-subnet --region "$AWS_REGION" --subnet-id "$subnet" 2>/dev/null || true
  done

  for sg in $(aws ec2 describe-security-groups --region "$AWS_REGION" --filters "Name=vpc-id,Values=$vpc_id" --query "SecurityGroups[?GroupName!='default'].GroupId" --output text); do
    aws ec2 delete-security-group --region "$AWS_REGION" --group-id "$sg" 2>/dev/null || true
  done

  # shellcheck disable=SC2016
  for route_table in $(aws ec2 describe-route-tables --region "$AWS_REGION" --filters "Name=vpc-id,Values=$vpc_id" --query 'RouteTables[?Associations[?Main==`false`]].RouteTableId' --output text); do
    # shellcheck disable=SC2016
    for association in $(aws ec2 describe-route-tables --region "$AWS_REGION" --route-table-ids "$route_table" --query 'RouteTables[].Associations[?Main==`false`].RouteTableAssociationId' --output text); do
      aws ec2 disassociate-route-table --region "$AWS_REGION" --association-id "$association" 2>/dev/null || true
    done
    aws ec2 delete-route-table --region "$AWS_REGION" --route-table-id "$route_table" 2>/dev/null || true
  done

  aws ec2 delete-vpc --region "$AWS_REGION" --vpc-id "$vpc_id" 2>/dev/null || true
done

echo "Running a final Terraform destroy against the remote state..."
set +e
terraform -chdir=infra/aws destroy -auto-approve
FINAL_DESTROY_STATUS=$?
set -e
if ((FINAL_DESTROY_STATUS != 0)); then
  echo "WARNING: the final Terraform destroy reported remaining dependencies." >&2
  echo "The preflight below will identify any fixed-name or EIP blocker before redeployment." >&2
fi

REMAINING_STATE="$(terraform -chdir=infra/aws state list 2>/dev/null || true)"
if [[ -n "$REMAINING_STATE" ]]; then
  echo "ERROR: reset is incomplete; Terraform still tracks these resources:" >&2
  printf '%s\n' "$REMAINING_STATE" >&2
  echo "Do not redeploy until the reset completes with an empty state." >&2
  exit 1
fi

echo
echo "Terraform state is empty. Confirming AWS preflight before redeploying:"
bash scripts/check-cloud-deploy-preflight.sh
