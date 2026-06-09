#!/usr/bin/env bash
set -uo pipefail

NAMESPACE="${NAMESPACE:-retailvision}"

echo
echo "=== RetailVision cloud application diagnostics ==="

echo
echo "--- Helm release ---"
helm status retailvision -n "$NAMESPACE" 2>&1 || true

echo
echo "--- Nodes ---"
kubectl get nodes -L workload,kubernetes.io/arch,karpenter.sh/capacity-type -o wide 2>&1 || true

echo
echo "--- Workloads and pods ---"
kubectl -n "$NAMESPACE" get deploy,statefulset,job,pod -o wide 2>&1 || true

echo
echo "--- Services, endpoints, ingress, and PVCs ---"
kubectl -n "$NAMESPACE" get svc,endpoints,ingress,pvc 2>&1 || true

echo
echo "--- External secrets and certificates ---"
kubectl get clustersecretstore aws-secrets-manager 2>&1 || true
kubectl -n "$NAMESPACE" get externalsecret,certificate,certificaterequest 2>&1 || true

echo
echo "--- Non-ready pod details and logs ---"
while IFS= read -r pod; do
  [[ -n "$pod" ]] || continue
  echo
  echo "### ${pod}"
  kubectl -n "$NAMESPACE" describe pod "$pod" 2>&1 || true

  while IFS= read -r container; do
    [[ -n "$container" ]] || continue
    echo "--- logs ${pod}/${container} ---"
    kubectl -n "$NAMESPACE" logs "$pod" -c "$container" --tail=120 2>&1 || true
    kubectl -n "$NAMESPACE" logs "$pod" -c "$container" --previous --tail=120 2>&1 || true
  done < <(
    kubectl -n "$NAMESPACE" get pod "$pod" \
      -o jsonpath='{range .spec.initContainers[*]}{.name}{"\n"}{end}{range .spec.containers[*]}{.name}{"\n"}{end}' \
      2>/dev/null
  )
done < <(
  kubectl -n "$NAMESPACE" get pods \
    -o jsonpath='{range .items[?(@.status.phase!="Succeeded")]}{.metadata.name}{" "}{range .status.conditions[?(@.type=="Ready")]}{.status}{end}{"\n"}{end}' \
    2>/dev/null |
    awk '$2 != "True" {print $1}'
)

echo
echo "--- Recent events ---"
kubectl -n "$NAMESPACE" get events --sort-by=.lastTimestamp 2>&1 | tail -100 || true

echo
echo "=== End diagnostics ==="
