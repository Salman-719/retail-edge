#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-${REGION:-eu-west-1}}"
ENVIRONMENT="${ENVIRONMENT:-production}"
CLUSTER_NAME="retailvision-${ENVIRONMENT}"
export AWS_PAGER=""

if ! aws eks describe-cluster \
  --name "$CLUSTER_NAME" \
  --region "$AWS_REGION" \
  >/dev/null 2>&1; then
  exit 0
fi

kubeconfig="$(mktemp)"
trap 'rm -f "$kubeconfig"' EXIT

aws eks update-kubeconfig \
  --name "$CLUSTER_NAME" \
  --region "$AWS_REGION" \
  --kubeconfig "$kubeconfig" \
  >/dev/null

release_specs=(
  "aws-load-balancer-controller|kube-system"
  "ingress-nginx|ingress-nginx"
  "cert-manager|cert-manager"
  "external-secrets|external-secrets"
  "keda|keda"
  "metrics-server|kube-system"
  "karpenter|kube-system"
)

for release_spec in "${release_specs[@]}"; do
  release="${release_spec%%|*}"
  namespace="${release_spec##*|}"
  status="$(helm --kubeconfig "$kubeconfig" \
    status "$release" \
    --namespace "$namespace" \
    --output json \
    2>/dev/null |
    jq -r '.info.status // empty' || true)"

  case "$status" in
    failed|pending-install|pending-upgrade|pending-rollback)
      echo "Removing unhealthy Helm release ${namespace}/${release} (${status}) before Terraform retry..."
      helm --kubeconfig "$kubeconfig" \
        uninstall "$release" \
        --namespace "$namespace" \
        --wait \
        --timeout 10m
      ;;
  esac
done
