# Milestone 10: Cloud Deployment & Kubernetes

**Duration:** 1.5 weeks
**Dependencies:** M8
**Goal:** Full deployment on AWS EKS with all services running, publicly accessible, and end-to-end functional.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| Docker Compose (local) | DONE | 13 containers working |
| Dockerfiles per service | DONE | All 6 services + frontend |
| AWS infrastructure | NOT STARTED | |
| EKS cluster | NOT STARTED | |
| K8s manifests | NOT STARTED | /infra/ empty |
| ECR image registry | NOT STARTED | |
| CI/CD deployment pipeline | NOT STARTED | |
| SSL/domain | NOT STARTED | |

**Overall: 0% complete**

---

## Implementation Tasks

### 1. AWS Infrastructure Setup

**File:** `infra/terraform/main.tf` (NEW) or manual setup

```
Resources to create:
- VPC with 2 public + 2 private subnets
- Security groups:
  - EKS nodes: allow internal traffic
  - Load balancer: allow 80/443 from internet
  - RDS: allow 5432 from EKS nodes only
  - ElastiCache: allow 6379 from EKS nodes only
- RDS PostgreSQL (db.t3.medium): retailvision database
- ElastiCache Redis (cache.t3.small): single node
- S3 bucket: retailvision-{env}
- ECR repositories: one per service (6 total + frontend)
```

### 2. Build & Push Docker Images

**File:** `infra/scripts/build_push.sh` (NEW)

```bash
#!/bin/bash
# Build and push all service images to ECR
REGION=us-east-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_BASE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR_BASE

SERVICES=(eep iep1-ingestion iep2-vision iep3-alerts iep4-analytics iep5-agent frontend)
for svc in "${SERVICES[@]}"; do
    docker build -t "$ECR_BASE/retailvision-$svc:latest" ./services/$svc 2>/dev/null \
      || docker build -t "$ECR_BASE/retailvision-$svc:latest" ./$svc
    docker push "$ECR_BASE/retailvision-$svc:latest"
done
```

### 3. EKS Cluster Creation

```bash
# Two node groups:
# CPU: t3.large (2 vCPU, 8GB) x 3 nodes — runs EEP, IEP1, IEP3-5, frontend
# GPU: g4dn.xlarge (4 vCPU, 16GB, T4 GPU) x 1 node — runs IEP2 vision

eksctl create cluster \
  --name retailvision \
  --region us-east-1 \
  --nodegroup-name cpu-nodes \
  --node-type t3.large \
  --nodes 3 \
  --managed

eksctl create nodegroup \
  --cluster retailvision \
  --name gpu-nodes \
  --node-type g4dn.xlarge \
  --nodes 1 \
  --managed \
  --install-nvidia-plugin
```

### 4. Kubernetes Manifests

**Directory:** `infra/k8s/`

```
infra/k8s/
  namespace.yaml
  secrets.yaml              # DB creds, S3 keys, API keys (sealed-secrets)
  configmap.yaml            # service URLs, feature flags

  # Per-service (6 services + frontend):
  eep/
    deployment.yaml         # replicas: 2, resources: 256Mi/500m
    service.yaml            # ClusterIP, port 8000
    hpa.yaml                # min 2, max 5, cpu target 70%
  iep1-ingestion/
    deployment.yaml         # replicas: 1, resources: 256Mi/500m
    service.yaml
  iep2-vision/
    deployment.yaml         # replicas: 1, GPU tolerations, resources: 2Gi/1000m + nvidia.com/gpu: 1
    service.yaml
  iep3-alerts/
    deployment.yaml
    service.yaml
  iep4-analytics/
    deployment.yaml
    service.yaml
  iep5-agent/
    deployment.yaml
    service.yaml
  frontend/
    deployment.yaml         # replicas: 2
    service.yaml

  # Ingress
  ingress.yaml              # ALB ingress controller
                            # / -> frontend
                            # /api -> eep
                            # /grafana -> grafana

  # Monitoring
  monitoring/
    prometheus-values.yaml  # Helm values for kube-prometheus-stack
    grafana-values.yaml
```

#### Example: EEP Deployment

```yaml
# infra/k8s/eep/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: eep
  namespace: retailvision
spec:
  replicas: 2
  selector:
    matchLabels:
      app: eep
  template:
    metadata:
      labels:
        app: eep
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
    spec:
      containers:
        - name: eep
          image: <ECR_BASE>/retailvision-eep:latest
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: retailvision-config
            - secretRef:
                name: retailvision-secrets
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 30
```

#### Example: IEP2 with GPU

```yaml
# infra/k8s/iep2-vision/deployment.yaml
spec:
  template:
    spec:
      tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
      containers:
        - name: iep2-vision
          image: <ECR_BASE>/retailvision-iep2-vision:latest
          resources:
            requests:
              memory: "2Gi"
              cpu: "1000m"
              nvidia.com/gpu: 1
            limits:
              memory: "4Gi"
              cpu: "2000m"
              nvidia.com/gpu: 1
```

### 5. Ingress & Load Balancer

**File:** `infra/k8s/ingress.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: retailvision-ingress
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/certificate-arn: <ACM_CERT_ARN>
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
spec:
  rules:
    - host: retailvision.yourdomain.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: eep
                port:
                  number: 8000
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend
                port:
                  number: 3000
```

Install AWS ALB Ingress Controller:
```bash
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --set clusterName=retailvision \
  -n kube-system
```

### 6. Deploy Monitoring to EKS

```bash
# Prometheus + Grafana via Helm
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  -f infra/k8s/monitoring/prometheus-values.yaml
```

Import existing Grafana dashboards from `monitoring/grafana/dashboards/`.

### 7. SSL & Domain (Optional)

```
1. Register domain or use existing
2. Create ACM certificate in AWS
3. Point domain DNS to ALB
4. Update ingress with certificate ARN
```

### 8. CI/CD Deployment Pipeline

**File:** `.github/workflows/deploy.yml` (NEW)

```yaml
name: Deploy to EKS
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
      - uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push images
        run: ./infra/scripts/build_push.sh

      - name: Deploy to EKS
        run: |
          aws eks update-kubeconfig --name retailvision
          kubectl apply -f infra/k8s/ --recursive
          kubectl rollout status deployment -n retailvision --timeout=300s

      - name: E2E smoke test
        run: |
          EEP_URL=$(kubectl get ingress -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}')
          curl -f "$EEP_URL/health" || exit 1

      - name: Rollback on failure
        if: failure()
        run: kubectl rollout undo deployment -n retailvision
```

---

## Evaluation Criteria (must pass before M11)

- [ ] All pods Running and passing health checks
- [ ] EEP publicly accessible via load balancer
- [ ] E2E test passes on deployed system
- [ ] Grafana dashboards accessible with live metrics
- [ ] CI/CD deploys code change automatically
- [ ] DB and Redis accessible only from within VPC
- [ ] GPU pod schedules and IEP2 can run YOLO inference

## Re-iteration Triggers

- If GPU pods fail to schedule: check NVIDIA device plugin, node labels, resource requests
- If services can't communicate: check K8s service discovery, DNS, security groups
- If too expensive: use spot instances for CPU nodes, scale down for demo
