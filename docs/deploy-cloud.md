# Cloud Deployment Guide

Deploy the RetailVision cloud infrastructure (EEP, IEP3, Redis, RDS) to AWS me-south-1 (Bahrain) using CDK + k3s on EC2.

---

## Prerequisites

- AWS CLI configured (`aws configure`) with an IAM user that has admin access
- Node.js ≥ 18 (for CDK CLI)
- Python ≥ 3.10
- Docker
- `kubectl`

```bash
npm install -g aws-cdk
pip install -r infra/cdk/requirements.txt
```

---

## Set variables — run this first in every new terminal session

All commands below use these variables. Set them once before starting.

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=me-south-1
export ECR_REGISTRY=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# These are filled in after Step 2 (CDK outputs)
export MASTER_IP=""          # fill after Step 2
export DB_URL=""             # fill after Step 5
export INTERNAL_TOKEN=""     # fill after Step 5
export STORE_ID=""           # fill per store in Step 8
```

Verify AWS identity resolved:

```bash
echo "Account: $AWS_ACCOUNT_ID   Region: $AWS_REGION"
```

---

## Step 1 — Bootstrap CDK

Only needed once per account/region.

```bash
cdk bootstrap aws://$AWS_ACCOUNT_ID/$AWS_REGION
```

---

## Step 2 — Deploy infrastructure

```bash
cd infra/cdk
cdk deploy --all \
  --context account=$AWS_ACCOUNT_ID \
  --context region=$AWS_REGION \
  --outputs-file ../../outputs.json
cd ../..
```

This provisions: VPC, RDS PostgreSQL t3.micro, k3s master t3.medium + worker t3.small.

Set `MASTER_IP` from the CDK output:

```bash
export MASTER_IP=$(python3 -c "
import json
with open('outputs.json') as f:
    print(json.load(f)['RetailEdgeCluster']['MasterPublicIp'])
")
echo "Master IP: $MASTER_IP"
```

---

## Step 3 — Build and push images (on AWS CodeBuild)

Images are built in AWS — no Docker required on your machine, no large uploads over slow connections.

**Create ECR repos:**

```bash
aws ecr create-repository --repository-name eep --region $AWS_REGION 2>/dev/null || true
aws ecr create-repository --repository-name iep3-reconciliation --region $AWS_REGION 2>/dev/null || true
```

**Trigger CodeBuild jobs** (one per service — runs in parallel):

```bash
# EEP
aws codebuild start-build \
  --project-name retail-edge-build \
  --region $AWS_REGION \
  --environment-variables-override \
    name=SERVICE,value=eep,type=PLAINTEXT \
    name=DOCKERFILE,value=services/eep/Dockerfile,type=PLAINTEXT \
    name=ECR_REPO,value=$ECR_REGISTRY/eep,type=PLAINTEXT \
  --query 'build.id' --output text

# IEP3
aws codebuild start-build \
  --project-name retail-edge-build \
  --region $AWS_REGION \
  --environment-variables-override \
    name=SERVICE,value=iep3-reconciliation,type=PLAINTEXT \
    name=DOCKERFILE,value=services/iep3_reconciliation/Dockerfile,type=PLAINTEXT \
    name=ECR_REPO,value=$ECR_REGISTRY/iep3-reconciliation,type=PLAINTEXT \
  --query 'build.id' --output text
```

**Watch build status:**

```bash
# Replace <build-id> with the ID returned above
aws codebuild batch-get-builds \
  --ids <build-id> --region $AWS_REGION \
  --query 'builds[0].{status:buildStatus,phase:currentPhase}' \
  --output table
```

Builds take ~4–6 minutes. Both must reach `SUCCEEDED` before proceeding.

> The CodeBuild project (`retail-edge-build`) is provisioned by the CDK cluster stack.
> It pulls source from the GitHub repo, builds with the specified Dockerfile,
> and pushes the image to ECR — all inside AWS, no local Docker needed.

---

## Step 4 — Wait for k3s master to initialise

k3s installs via EC2 user data on first boot (~3–5 minutes).

```bash
# SSH to master (replace key.pem with your EC2 key pair path)
ssh -i key.pem ec2-user@$MASTER_IP "kubectl get nodes && kubectl get pods -A"
```

Both commands should return without error and show nodes in `Ready` state before proceeding.

---

## Step 5 — Set secrets

Generate secrets and pull the RDS endpoint:

```bash
# Strong shared token (copy to edge secrets too)
export INTERNAL_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# RDS endpoint from Secrets Manager
export RDS_HOST=$(aws secretsmanager get-secret-value \
  --secret-id retailvision --region $AWS_REGION \
  --query SecretString --output text \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['host'])")

export RDS_PASS=$(aws secretsmanager get-secret-value \
  --secret-id retailvision --region $AWS_REGION \
  --query SecretString --output text \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['password'])")

export DB_URL="postgresql+asyncpg://retailvision:${RDS_PASS}@${RDS_HOST}:5432/retailvision"

export S3_BUCKET=$(python3 -c "
import json
with open('outputs.json') as f:
    print(json.load(f)['RetailEdgeData']['FramesBucket'])
")

echo "RDS host : $RDS_HOST"
echo "S3 bucket: $S3_BUCKET"
echo "Token    : $INTERNAL_TOKEN"
```

Write secrets into the manifest (never commit this file with real values):

```bash
cat > infra/cloud/secrets.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: retail-edge-secrets
  namespace: retail-edge
type: Opaque
stringData:
  DATABASE_URL: "$DB_URL"
  S3_BUCKET: "$S3_BUCKET"
  VISION_INTERNAL_TOKEN: "$INTERNAL_TOKEN"
  JWT_SECRET: "$JWT_SECRET"
EOF
```

---

## Step 6 — Inject image registry into manifests

```bash
sed -i "s|REPLACE_WITH_ECR_OR_REGISTRY|$ECR_REGISTRY|g" \
  infra/cloud/eep.yaml \
  infra/cloud/stores/template/iep3.yaml
```

---

## Step 7 — Connect kubectl to the cluster

```bash
mkdir -p ~/.kube
ssh -i key.pem ec2-user@$MASTER_IP 'sudo cat /etc/rancher/k3s/k3s.yaml' \
  | sed "s/127.0.0.1/$MASTER_IP/" > ~/.kube/retail-edge.yaml
export KUBECONFIG=~/.kube/retail-edge.yaml

kubectl get nodes   # confirm connection
```

---

## Step 8 — Run DB migrations and deploy workloads

```bash
# Migrations
kubectl run migrate --rm -it --restart=Never \
  --image=$ECR_REGISTRY/eep:latest \
  --overrides="{\"spec\":{\"containers\":[{\"name\":\"migrate\",\"image\":\"$ECR_REGISTRY/eep:latest\",\"command\":[\"python\",\"-m\",\"alembic\",\"upgrade\",\"head\"],\"env\":[{\"name\":\"DATABASE_URL\",\"value\":\"$DB_URL\"}]}]}}" \
  -- echo done

# Deploy all cloud workloads
kubectl apply -k infra/cloud/
```

---

## Step 9 — Onboard a store

```bash
export STORE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
echo "Store ID: $STORE_ID"   # save this — needed for edge configmap

mkdir -p infra/cloud/stores/$STORE_ID

sed "s/STORE_ID/$STORE_ID/g" infra/cloud/stores/template/iep3.yaml \
  > infra/cloud/stores/$STORE_ID/iep3.yaml

cat > infra/cloud/stores/$STORE_ID/kustomization.yaml <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: retail-edge
resources:
  - iep3.yaml
EOF

kubectl apply -k infra/cloud/stores/$STORE_ID/
```

---

## Step 10 — Verify

```bash
# All pods healthy
kubectl -n retail-edge get pods

# EEP health check
curl http://$MASTER_IP/health

# Internal endpoint accepts tracking batches
curl -s -X POST http://$MASTER_IP/internal/stores/$STORE_ID/tracking-batch \
  -H "X-Internal-Token: $INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"camera_id":"test","batch_number":1,"window_start_ms":0,"window_end_ms":2000,"positions":[]}' \
  | python3 -m json.tool
# Expect: {"accepted": true, "batch_number": 1}
```

---

## Scaling

**Add a store:** repeat Step 9 with a new `STORE_ID`.

**Worker node full:** add more EC2 capacity, then redeploy:
```bash
cdk deploy RetailEdgeCluster
```

**Scale EEP replicas:**
```bash
kubectl -n retail-edge scale deployment eep --replicas=4
```

**Upgrade images:**
```bash
# Trigger a new build on AWS (no local Docker needed)
aws codebuild start-build \
  --project-name retail-edge-build --region $AWS_REGION \
  --environment-variables-override \
    name=SERVICE,value=eep,type=PLAINTEXT \
    name=DOCKERFILE,value=services/eep/Dockerfile,type=PLAINTEXT \
    name=ECR_REPO,value=$ECR_REGISTRY/eep,type=PLAINTEXT \
  --query 'build.id' --output text

# After build succeeds, restart the deployment
kubectl -n retail-edge rollout restart deployment/eep
kubectl -n retail-edge rollout status deployment/eep
```

---

## Useful commands

```bash
# Service logs
kubectl -n retail-edge logs -f deployment/eep
kubectl -n retail-edge logs -f deployment/iep3-$STORE_ID

# Redis CLI — check per-store stream
kubectl -n retail-edge exec -it statefulset/redis -- \
  redis-cli XLEN stream:store:$STORE_ID:batch_complete

# DB connection test
kubectl run psql --rm -it --restart=Never --image=postgres:15 \
  -- psql "$DB_URL" -c '\dt'

# Tail IEP3 reconciliation for a store
kubectl -n retail-edge logs -f deployment/iep3-$STORE_ID
```
