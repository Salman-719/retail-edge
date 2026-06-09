#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Deploy RetailVision cloud to a fresh Amazon EKS stack.

Run from the repository root after the image tag exists in GHCR.

Required environment:
  LETSENCRYPT_EMAIL  Contact email for cert-manager/Let's Encrypt.
  VERSION            Image tag built from the commit you are deploying.

Common environment:
  AWS_PROFILE        AWS CLI profile. Optional in CloudShell.
  AWS_REGION         AWS region. Default: eu-west-1.
  OWNER              GHCR owner/user/org. Default: salman-719.
  BUCKET             S3 bucket name. Default: retailvision-prod-objects-<account>.
  TF_STATE_BUCKET    Terraform state bucket. Default: retailvision-tfstate-<account>-<region>.
  TF_LOCK_TABLE      Terraform lock table. Default: retailvision-tflock-<region>.
  OPENAI_API_KEY     Optional. If set, writes retailvision/openai-api-key.

Optional switches:
  AUTO_APPROVE=1     Apply Terraform without an interactive approval prompt.
  SKIP_IMAGE_CHECK=1 Skip the GHCR tag/public visibility check.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ ! -d charts/retailvision || ! -d infra/aws ]]; then
  echo "ERROR: run this script from the retail-edge repository root." >&2
  exit 1
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: missing command: $1" >&2
    exit 1
  fi
}

for cmd in aws terraform kubectl helm jq curl; do
  require_command "$cmd"
done

export AWS_REGION="${AWS_REGION:-${REGION:-eu-west-1}}"
export REGION="$AWS_REGION"
export OWNER="${OWNER:-salman-719}"
export AWS_SDK_LOAD_CONFIG="${AWS_SDK_LOAD_CONFIG:-1}"
export AWS_EC2_METADATA_DISABLED="${AWS_EC2_METADATA_DISABLED:-true}"

if [[ -n "${AWS_PROFILE:-}" ]]; then
  export AWS_PROFILE
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export BUCKET="${BUCKET:-retailvision-prod-objects-${ACCOUNT_ID}}"
export TF_STATE_BUCKET="${TF_STATE_BUCKET:-retailvision-tfstate-${ACCOUNT_ID}-${AWS_REGION}}"
export TF_LOCK_TABLE="${TF_LOCK_TABLE:-retailvision-tflock-${AWS_REGION}}"

if [[ -z "${LETSENCRYPT_EMAIL:-}" ]]; then
  echo "ERROR: set LETSENCRYPT_EMAIL before running. Example:" >&2
  echo "  export LETSENCRYPT_EMAIL=you@example.com" >&2
  exit 1
fi

if [[ -z "${VERSION:-}" ]]; then
  echo "ERROR: set VERSION to the GHCR image tag built from this commit. Example:" >&2
  echo "  export VERSION=1.3.1" >&2
  exit 1
fi

if [[ "${SKIP_IMAGE_CHECK:-0}" != "1" ]]; then
  echo "Checking GHCR images for tag ${VERSION}..."
  for image in eep iep3 iep4 iep5 iep6 frontend mlflow; do
    token="$(curl -fsSL "https://ghcr.io/token?service=ghcr.io&scope=repository:${OWNER}/retailvision/${image}:pull" | jq -r .token)"
    curl -fsSL \
      -H "Authorization: Bearer ${token}" \
      -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
      "https://ghcr.io/v2/${OWNER}/retailvision/${image}/manifests/${VERSION}" \
      >/dev/null
    echo "  ${image}:${VERSION} OK"
  done
fi

cat > infra/aws/terraform.tfvars <<EOF
aws_region            = "${AWS_REGION}"
environment           = "production"
letsencrypt_email     = "${LETSENCRYPT_EMAIL}"
s3_bucket_name        = "${BUCKET}"
cluster_version       = "1.30"
stable_instance_type  = "t4g.large"
stable_node_count     = 2
stable_node_max_count = 4
node_root_volume_gb   = 60
karpenter_cpu_limit   = "200"
wireguard_enabled       = true
wireguard_instance_type = "t4g.nano"
wireguard_port          = 51820
wireguard_client_cidrs  = ["0.0.0.0/0"]
wireguard_tunnel_cidr   = "10.99.0.0/24"
wireguard_server_address = "10.99.0.1/24"
EOF

if ! aws s3api head-bucket --bucket "$TF_STATE_BUCKET" >/dev/null 2>&1; then
  if [[ "$AWS_REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION" >/dev/null
  else
    aws s3api create-bucket \
      --bucket "$TF_STATE_BUCKET" \
      --region "$AWS_REGION" \
      --create-bucket-configuration "LocationConstraint=${AWS_REGION}" \
      >/dev/null
  fi
fi

aws s3api put-bucket-versioning \
  --bucket "$TF_STATE_BUCKET" \
  --versioning-configuration Status=Enabled \
  --region "$AWS_REGION" \
  >/dev/null
aws s3api put-bucket-encryption \
  --bucket "$TF_STATE_BUCKET" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' \
  --region "$AWS_REGION" \
  >/dev/null
aws s3api put-public-access-block \
  --bucket "$TF_STATE_BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
  --region "$AWS_REGION" \
  >/dev/null

if ! aws dynamodb describe-table --table-name "$TF_LOCK_TABLE" --region "$AWS_REGION" >/dev/null 2>&1; then
  aws dynamodb create-table \
    --table-name "$TF_LOCK_TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$AWS_REGION" \
    >/dev/null
  aws dynamodb wait table-exists --table-name "$TF_LOCK_TABLE" --region "$AWS_REGION"
fi

cat > infra/aws/backend.tf <<EOF
terraform {
  backend "s3" {}
}
EOF

pushd infra/aws >/dev/null
terraform init -upgrade -reconfigure \
  -backend-config="bucket=${TF_STATE_BUCKET}" \
  -backend-config="key=retailvision/${AWS_REGION}/terraform.tfstate" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="dynamodb_table=${TF_LOCK_TABLE}" \
  -backend-config="encrypt=true"
terraform fmt -recursive
terraform validate
terraform plan -out eks.tfplan
if [[ "${AUTO_APPROVE:-0}" == "1" ]]; then
  terraform apply -auto-approve eks.tfplan
else
  terraform apply eks.tfplan
fi

aws eks update-kubeconfig \
  --name "$(terraform output -raw cluster_name)" \
  --region "$AWS_REGION"

export INGRESS_EIP="$(terraform output -raw ingress_eip)"
export GRPC_EIP="$(terraform output -raw grpc_eip)"
export APP_HOST="$(terraform output -raw app_host)"
export EEP_HOST="$(terraform output -raw eep_host)"
export AGENT_SECRET="$(terraform output -raw agent_secret)"
export GRPC_EIP_ALLOCATIONS="$(terraform output -json grpc_eip_allocation_ids | jq -r 'join("\\,")')"
export PUBLIC_SUBNET_IDS="$(terraform output -json public_subnet_ids | jq -r 'join("\\,")')"
export VPC_CIDR="$(terraform output -raw vpc_cidr)"
export WG_INSTANCE_ID="$(terraform output -raw wireguard_instance_id)"
export WG_ENDPOINT="$(terraform output -raw wireguard_endpoint)"
export S3_BUCKET="$(terraform output -raw s3_bucket)"
popd >/dev/null

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  aws secretsmanager put-secret-value \
    --region "$AWS_REGION" \
    --secret-id retailvision/openai-api-key \
    --secret-string "$OPENAI_API_KEY" \
    >/dev/null
fi

HELM_VALUES=(
  -f charts/retailvision/values.production.yaml
  --set "global.imageRegistry=ghcr.io/${OWNER}/retailvision"
  --set "ingress.appHost=${APP_HOST}"
  --set "eep.grpcHost=${EEP_HOST}"
  --set "eep.grpc.serviceType=LoadBalancer"
  --set-string "eep.grpc.serviceAnnotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-type=external"
  --set-string "eep.grpc.serviceAnnotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-nlb-target-type=ip"
  --set-string "eep.grpc.serviceAnnotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-scheme=internet-facing"
  --set-string "eep.grpc.serviceAnnotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-eip-allocations=${GRPC_EIP_ALLOCATIONS}"
  --set-string "eep.grpc.serviceAnnotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-subnets=${PUBLIC_SUBNET_IDS}"
  --set-string "postgres.service.annotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-subnets=${PUBLIC_SUBNET_IDS}"
  --set-string "redis.service.annotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-subnets=${PUBLIC_SUBNET_IDS}"
  --set-string "postgres.service.loadBalancerSourceRanges[0]=${VPC_CIDR}"
  --set-string "redis.service.loadBalancerSourceRanges[0]=${VPC_CIDR}"
  --set "s3.bucket=${S3_BUCKET}"
  --set "s3.region=${AWS_REGION}"
  --set "monitoring.grafana.host=grafana.${INGRESS_EIP}.nip.io"
  --set "mlflow.host=mlflow.${INGRESS_EIP}.nip.io"
  --set "eep.image.tag=${VERSION}"
  --set "iep3.image.tag=${VERSION}"
  --set "iep4.image.tag=${VERSION}"
  --set "iep5.image.tag=${VERSION}"
  --set "iep6.image.tag=${VERSION}"
  --set "frontend.image.tag=${VERSION}"
  --set "mlflow.image.tag=${VERSION}"
  -n retailvision
)

helm lint ./charts/retailvision "${HELM_VALUES[@]}"
helm template retailvision ./charts/retailvision "${HELM_VALUES[@]}" >/tmp/retailvision-rendered.yaml
helm upgrade --install retailvision ./charts/retailvision "${HELM_VALUES[@]}" --create-namespace --atomic --timeout 20m

kubectl -n retailvision rollout status deploy/eep --timeout=10m
kubectl -n retailvision rollout status deploy/frontend --timeout=10m
kubectl -n retailvision rollout status deploy/iep6-agent --timeout=10m
kubectl -n retailvision rollout status deploy/iep6-scheduler --timeout=10m

PG_HOST=""
REDIS_HOST=""
for _ in {1..60}; do
  PG_HOST="$(kubectl -n retailvision get svc postgres -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  REDIS_HOST="$(kubectl -n retailvision get svc redis-server -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  if [[ -n "$PG_HOST" && -n "$REDIS_HOST" ]]; then
    break
  fi
  sleep 5
done

kubectl -n cert-manager get secret retailvision-ca \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/retailvision-ca.crt

cat > /tmp/retailvision-cloud.env <<EOF
export AWS_REGION="${AWS_REGION}"
export OWNER="${OWNER}"
export VERSION="${VERSION}"
export BUCKET="${S3_BUCKET}"
export INGRESS_EIP="${INGRESS_EIP}"
export GRPC_EIP="${GRPC_EIP}"
export APP_HOST="${APP_HOST}"
export EEP_HOST="${EEP_HOST}"
export AGENT_SECRET='${AGENT_SECRET}'
export WG_INSTANCE_ID="${WG_INSTANCE_ID}"
export WG_ENDPOINT="${WG_ENDPOINT}"
export PG_HOST="${PG_HOST}"
export REDIS_HOST="${REDIS_HOST}"
EOF

echo
echo "Cloud deploy complete."
echo "App:     https://${APP_HOST}"
echo "Grafana: https://grafana.${INGRESS_EIP}.nip.io"
echo "MLflow:  https://mlflow.${INGRESS_EIP}.nip.io"
echo "gRPC:    ${EEP_HOST}:50051"
echo "Saved reusable exports to /tmp/retailvision-cloud.env"
echo "Saved cloud CA certificate to /tmp/retailvision-ca.crt"
