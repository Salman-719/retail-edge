#!/usr/bin/env bash
set -euo pipefail

report_error() {
  local status="$?"
  local line="$1"
  local command="$2"
  trap - ERR
  echo "ERROR: ${BASH_SOURCE[0]}:${line}: command failed with exit ${status}: ${command}" >&2
  exit "$status"
}
trap 'report_error "$LINENO" "$BASH_COMMAND"' ERR

AWS_REGION="${AWS_REGION:-${REGION:-eu-west-1}}"
ENVIRONMENT="${ENVIRONMENT:-production}"
CLUSTER_NAME="retailvision-${ENVIRONMENT}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${BUCKET:-retailvision-prod-objects-${ACCOUNT_ID}}"

if [[ ! -d infra/aws ]]; then
  echo "ERROR: run this script from the retail-edge repository root." >&2
  exit 1
fi

STATE="$(terraform -chdir=infra/aws state list 2>/dev/null || true)"
CONFLICTS=()

state_has() {
  grep -Fq "$1" <<<"$STATE"
}

conflict() {
  CONFLICTS+=("$1")
}

if aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" >/dev/null 2>&1 &&
  ! state_has "module.eks.aws_eks_cluster.this[0]"; then
  conflict "EKS cluster $CLUSTER_NAME exists outside the active Terraform state."
fi

if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1 &&
  ! state_has "aws_s3_bucket.objects"; then
  conflict "S3 bucket $BUCKET exists outside the active Terraform state."
fi

if aws iam get-user --user-name "retailvision-${ENVIRONMENT}-s3" >/dev/null 2>&1 &&
  ! state_has "aws_iam_user.s3"; then
  conflict "IAM user retailvision-${ENVIRONMENT}-s3 exists outside the active Terraform state."
fi

if aws iam get-role --role-name "${CLUSTER_NAME}-wireguard" >/dev/null 2>&1 &&
  ! state_has "aws_iam_role.wireguard[0]"; then
  conflict "IAM role ${CLUSTER_NAME}-wireguard exists outside the active Terraform state."
fi

for role_spec in \
  "${CLUSTER_NAME}-ebs-csi|module.irsa_ebs_csi" \
  "${CLUSTER_NAME}-lb-controller|module.irsa_lb_controller" \
  "${CLUSTER_NAME}-external-secrets|module.irsa_external_secrets"
do
  role_name="${role_spec%%|*}"
  state_prefix="${role_spec##*|}"
  if aws iam get-role --role-name "$role_name" >/dev/null 2>&1 &&
    ! grep -Fq "$state_prefix" <<<"$STATE"; then
    conflict "IAM role $role_name exists outside the active Terraform state."
  fi
done

declare -A SECRET_KEYS=(
  ["retailvision/postgres-password"]="postgres_password"
  ["retailvision/redis-password"]="redis_password"
  ["retailvision/jwt-secret"]="jwt_secret"
  ["retailvision/agent-secret"]="agent_secret"
  ["retailvision/redis-url"]="redis_url"
  ["retailvision/s3-access-key"]="s3_access_key"
  ["retailvision/s3-secret-key"]="s3_secret_key"
  ["retailvision/openai-api-key"]="openai_api_key"
  ["retailvision/grafana-admin-password"]="grafana_admin_password"
)

for secret_name in "${!SECRET_KEYS[@]}"; do
  key="${SECRET_KEYS[$secret_name]}"
  if aws secretsmanager describe-secret --secret-id "$secret_name" --region "$AWS_REGION" >/dev/null 2>&1 &&
    ! grep -Fq "aws_secretsmanager_secret.this[\"${key}\"]" <<<"$STATE"; then
    conflict "Secrets Manager secret $secret_name exists outside the active Terraform state."
  fi
done

LOG_GROUP_COUNT="$(aws logs describe-log-groups \
  --region "$AWS_REGION" \
  --log-group-name-prefix "/aws/eks/${CLUSTER_NAME}/cluster" \
  --query "logGroups[?logGroupName=='/aws/eks/${CLUSTER_NAME}/cluster'] | length(@)" \
  --output text)"
if [[ "$LOG_GROUP_COUNT" == "1" ]]; then
  if ! state_has "module.eks.aws_cloudwatch_log_group.this[0]"; then
    conflict "CloudWatch log group /aws/eks/${CLUSTER_NAME}/cluster exists outside the active Terraform state."
  fi
fi

KMS_ALIAS_COUNT="$(aws kms list-aliases \
  --region "$AWS_REGION" \
  --query "Aliases[?AliasName=='alias/eks/${CLUSTER_NAME}'] | length(@)" \
  --output text)"
if [[ "$KMS_ALIAS_COUNT" == "1" ]]; then
  if ! grep -Fq "module.eks.module.kms.aws_kms_alias.this" <<<"$STATE"; then
    conflict "KMS alias alias/eks/${CLUSTER_NAME} exists outside the active Terraform state."
  fi
fi

if aws sqs get-queue-url \
  --region "$AWS_REGION" \
  --queue-name "Karpenter-${CLUSTER_NAME}" \
  >/dev/null 2>&1 &&
  ! state_has "module.karpenter.aws_sqs_queue.this[0]"; then
  conflict "SQS queue Karpenter-${CLUSTER_NAME} exists outside the active Terraform state."
fi

EIP_STATE_LIVE_COUNT=0
while IFS= read -r eip_address; do
  [[ -z "$eip_address" ]] && continue
  eip_state="$(terraform -chdir=infra/aws state show -no-color "$eip_address" 2>/dev/null || true)"
  allocation_id="$(awk '$1 == "id" && $2 == "=" && !found {print $3; found=1}' <<<"$eip_state")"
  if [[ -n "$allocation_id" ]] &&
    aws ec2 describe-addresses \
      --region "$AWS_REGION" \
      --allocation-ids "$allocation_id" \
      >/dev/null 2>&1; then
    EIP_STATE_LIVE_COUNT=$((EIP_STATE_LIVE_COUNT + 1))
  fi
done < <(grep -E '^aws_eip\.(ingress|grpc|wireguard)' <<<"$STATE" || true)

EIP_REQUIRED=$((5 - EIP_STATE_LIVE_COUNT))
((EIP_REQUIRED < 0)) && EIP_REQUIRED=0
EIP_USED="$(aws ec2 describe-addresses --region "$AWS_REGION" --query 'length(Addresses)' --output text)"
EIP_QUOTA="$(aws service-quotas get-service-quota \
  --service-code ec2 \
  --quota-code L-0263D0A3 \
  --region "$AWS_REGION" \
  --query 'Quota.Value' \
  --output text 2>/dev/null || echo 5)"
if [[ ! "$EIP_QUOTA" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  EIP_QUOTA=5
fi
EIP_QUOTA="${EIP_QUOTA%.*}"
EIP_AVAILABLE=$((EIP_QUOTA - EIP_USED))
EIP_CAPACITY_ERROR=0

if ((EIP_REQUIRED > EIP_AVAILABLE)); then
  EIP_CAPACITY_ERROR=1
  conflict "Elastic IP capacity is insufficient: quota=$EIP_QUOTA used=$EIP_USED available=$EIP_AVAILABLE required=$EIP_REQUIRED."
fi

if ((${#CONFLICTS[@]} > 0)); then
  echo
  echo "ERROR: this is not a clean AWS account/state for a scratch deployment."
  echo "Terraform state and AWS contain different RetailVision resources:"
  for item in "${CONFLICTS[@]}"; do
    echo "  - $item"
  done
  if ((EIP_CAPACITY_ERROR == 1)); then
    echo
    echo "Current regional Elastic IP allocations:"
    # shellcheck disable=SC2016
    aws ec2 describe-addresses \
      --region "$AWS_REGION" \
      --query 'Addresses[].{IP:PublicIp,AllocationId:AllocationId,AssociationId:AssociationId,Name:Tags[?Key==`Name`]|[0].Value}' \
      --output table || true
  fi
  echo
  echo "Do not rerun terraform apply yet."
  echo "For the approved wipe-and-redeploy path, run from the repo root:"
  echo "  export CONFIRM_RESET=${CLUSTER_NAME}"
  echo "  make cloud-eks-reset"
  echo
  echo "Then rerun:"
  echo "  make cloud-eks-deploy"
  exit 1
fi

echo "AWS/Terraform preflight passed."
echo "Elastic IP capacity: quota=$EIP_QUOTA used=$EIP_USED available=$EIP_AVAILABLE required=$EIP_REQUIRED"
