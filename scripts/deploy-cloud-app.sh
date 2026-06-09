#!/usr/bin/env bash
set -euo pipefail

report_error() {
  local status="$?"
  local line="$1"
  local command="$2"
  trap - ERR
  echo "ERROR: ${BASH_SOURCE[0]}:${line}: command failed with exit ${status}: ${command}" >&2
  echo "The failed Helm resources were preserved for diagnosis." >&2
  bash scripts/diagnose-cloud-app.sh >&2 || true
  exit "$status"
}
trap 'report_error "$LINENO" "$BASH_COMMAND"' ERR

if [[ ! -d charts/retailvision || ! -d infra/aws ]]; then
  echo "ERROR: run this script from the retail-edge repository root." >&2
  exit 1
fi

for cmd in aws terraform kubectl helm jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: missing command: $cmd" >&2
    echo "Run: make cloud-eks-prereqs" >&2
    exit 1
  fi
done

: "${VERSION:?Set VERSION to the deployed image tag, for example 1.3.1}"

export AWS_REGION="${AWS_REGION:-${REGION:-eu-west-1}}"
export OWNER="${OWNER:-salman-719}"
export AWS_PAGER=""
export AWS_SDK_LOAD_CONFIG="${AWS_SDK_LOAD_CONFIG:-1}"
export AWS_EC2_METADATA_DISABLED="${AWS_EC2_METADATA_DISABLED:-true}"
HELM_TIMEOUT="${HELM_TIMEOUT:-30m}"

CLUSTER_NAME="$(terraform -chdir=infra/aws output -raw cluster_name)"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"

INGRESS_EIP="$(terraform -chdir=infra/aws output -raw ingress_eip)"
APP_HOST="$(terraform -chdir=infra/aws output -raw app_host)"
EEP_HOST="$(terraform -chdir=infra/aws output -raw eep_host)"
S3_BUCKET="$(terraform -chdir=infra/aws output -raw s3_bucket)"
GRPC_EIP_ALLOCATIONS="$(
  terraform -chdir=infra/aws output -json grpc_eip_allocation_ids |
    jq -r 'join("\\,")'
)"
PUBLIC_SUBNET_IDS="$(
  terraform -chdir=infra/aws output -json public_subnet_ids |
    jq -r 'join("\\,")'
)"
VPC_CIDR="$(terraform -chdir=infra/aws output -raw vpc_cidr)"

echo "Waiting for cluster prerequisites..."
kubectl -n kube-system rollout status deploy/aws-load-balancer-controller --timeout=10m
kubectl -n external-secrets rollout status deploy/external-secrets --timeout=10m
kubectl -n cert-manager rollout status deploy/cert-manager --timeout=10m
kubectl wait --for=condition=Ready clustersecretstore/aws-secrets-manager --timeout=5m
kubectl wait --for=condition=Ready clusterissuer/retailvision-ca-issuer --timeout=5m
kubectl get nodes

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
helm template retailvision ./charts/retailvision \
  "${HELM_VALUES[@]}" >/tmp/retailvision-rendered.yaml

echo "Installing RetailVision application. Failed resources will be preserved."
helm upgrade --install retailvision ./charts/retailvision \
  "${HELM_VALUES[@]}" \
  --create-namespace \
  --wait \
  --wait-for-jobs \
  --timeout "$HELM_TIMEOUT" \
  --history-max 10

kubectl -n retailvision rollout status deploy/eep --timeout=10m
kubectl -n retailvision rollout status deploy/frontend --timeout=10m
kubectl -n retailvision rollout status deploy/iep6-agent --timeout=10m
kubectl -n retailvision rollout status deploy/iep6-scheduler --timeout=10m

PG_HOST=""
REDIS_HOST=""
for _ in {1..120}; do
  PG_HOST="$(
    kubectl -n retailvision get svc postgres \
      -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true
  )"
  REDIS_HOST="$(
    kubectl -n retailvision get svc redis-server \
      -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true
  )"
  [[ -n "$PG_HOST" && -n "$REDIS_HOST" ]] && break
  sleep 5
done

if [[ -z "$PG_HOST" || -z "$REDIS_HOST" ]]; then
  echo "ERROR: private Postgres/Redis load balancers did not receive hostnames." >&2
  exit 1
fi

kubectl -n cert-manager get secret retailvision-ca \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/retailvision-ca.crt

AGENT_SECRET="$(terraform -chdir=infra/aws output -raw agent_secret)"
WG_INSTANCE_ID="$(terraform -chdir=infra/aws output -raw wireguard_instance_id)"
WG_ENDPOINT="$(terraform -chdir=infra/aws output -raw wireguard_endpoint)"

cat > /tmp/retailvision-cloud.env <<EOF
export AWS_REGION="${AWS_REGION}"
export OWNER="${OWNER}"
export VERSION="${VERSION}"
export BUCKET="${S3_BUCKET}"
export INGRESS_EIP="${INGRESS_EIP}"
export APP_HOST="${APP_HOST}"
export EEP_HOST="${EEP_HOST}"
export AGENT_SECRET='${AGENT_SECRET}'
export WG_INSTANCE_ID="${WG_INSTANCE_ID}"
export WG_ENDPOINT="${WG_ENDPOINT}"
export PG_HOST="${PG_HOST}"
export REDIS_HOST="${REDIS_HOST}"
EOF
chmod 600 /tmp/retailvision-cloud.env

echo
echo "RetailVision application deployment completed."
echo "App:     https://${APP_HOST}"
echo "Grafana: https://grafana.${INGRESS_EIP}.nip.io"
echo "MLflow:  https://mlflow.${INGRESS_EIP}.nip.io"
echo "Saved edge commissioning values to /tmp/retailvision-cloud.env"
echo "Saved cloud CA certificate to /tmp/retailvision-ca.crt"
