# RetailVision EKS Architecture

The cloud deployment runs on Amazon EKS. Edge devices still run k3s.

## Cloud Shape

- **EKS managed control plane**: HA Kubernetes API managed by AWS.
- **Public subnets only**: no NAT gateway. Nodes receive public IPs and use IGW
  egress, with security groups limiting inbound access.
- **S3 gateway endpoint**: S3 traffic stays on AWS networking without NAT cost.
- **Two NLBs with fixed EIPs**:
  - ingress NLB for HTTPS app/API traffic through ingress-nginx.
  - gRPC NLB for edge-to-EEP mTLS on `:50051`.

## Node Pools

- **Stable managed node group**:
  - on-demand Graviton nodes.
  - labeled `workload=stable`.
  - tainted `stable=true:NoSchedule`.
  - hosts TimescaleDB/Postgres, Redis, Prometheus, Grafana, MLflow, ingress-nginx,
    AWS Load Balancer Controller, cert-manager, External Secrets, metrics-server,
    Karpenter, CoreDNS, and EBS CSI controller.

- **Karpenter worker pool**:
  - arm64 Graviton capacity.
  - Spot with on-demand fallback.
  - launches nodes for EEP, frontend, IEP6, per-store IEP3/IEP4, and IEP5 jobs.
  - consolidates empty or underutilized nodes.

## Scheduling Rules

Stable workloads use:

```yaml
nodeSelector:
  workload: stable
tolerations:
  - key: stable
    operator: Equal
    value: "true"
    effect: NoSchedule
```

Stateless and per-store workers do not use that toleration by default, so they
trigger Karpenter instead of consuming stable DB/controller capacity.

## Deployment Flow

1. Terraform creates VPC, EKS, stable nodes, Karpenter, cluster add-ons, S3, IAM,
   Secrets Manager entries, and fixed EIPs.
2. `aws eks update-kubeconfig` points `kubectl` at the cluster.
3. Helm installs `charts/retailvision` with production values and Terraform output
   hostnames/EIP allocation IDs.
4. EEP starts, runs migrations, and later provisions per-store IEP3/IEP4/IEP5
   workloads through the Kubernetes API.

## Verification

- `kubectl get nodes -L workload`
- `kubectl get pods -A`
- `kubectl -n retailvision get hpa`
- `kubectl -n retailvision get svc eep-grpc`
- trigger a pod burst and verify Karpenter creates then consolidates worker nodes.
