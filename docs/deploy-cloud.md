# Cloud Deployment Guide

Deploy the RetailVision cloud infrastructure (EEP, IEP3, Redis, RDS) to AWS eu-west-1 (Ireland) using CDK + k3s on EC2.

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
export AWS_PROFILE=adsal
export AWS_REGION=eu-west-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_IAM_USER=$(aws iam get-user --query 'User.UserName' --output text)
export ECR_REGISTRY=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# These are filled in after Step 2 (CDK outputs)
export MASTER_IP=""          # fill after Step 2
export DB_URL=""             # fill after Step 5
export INTERNAL_TOKEN=""     # fill after Step 5
export STORE_ID=""           # fill per store in Step 8
```

Verify AWS identity resolved:

```bash
echo "Account: $AWS_ACCOUNT_ID   Region: $AWS_REGION   Profile: $AWS_PROFILE   User: $AWS_IAM_USER"
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

Set `MASTER_IP` — read it straight from CloudFormation (robust; `outputs.json`
gets overwritten if you later deploy a single stack with `--outputs-file`):

```bash
export MASTER_IP=$(aws cloudformation describe-stacks --region $AWS_REGION \
  --stack-name RetailEdgeCluster \
  --query "Stacks[0].Outputs[?OutputKey=='MasterPublicIp'].OutputValue" --output text)
echo "Master IP: $MASTER_IP"
```

---

## Step 3 — Build and push images (local)

Cloud services (EEP, IEP3) run on x86 EC2. Since you're on Apple Silicon,
use `docker buildx` to cross-compile for `linux/amd64`.

**Create ECR repos** (must exist before push — a missing repo causes a
`403 Forbidden` on the push, not a clear "not found"):

```bash
# Idempotent: ignores "already exists", surfaces real errors
for repo in eep iep3-reconciliation frontend; do
  aws ecr create-repository --repository-name $repo --region $AWS_REGION \
    2>&1 | grep -v RepositoryAlreadyExistsException || true
done

# Verify all three exist before continuing
aws ecr describe-repositories --region $AWS_REGION \
  --query 'repositories[].repositoryName' --output text
# Expect: eep  iep3-reconciliation  frontend
```

**Login to ECR** (token is valid 12h; re-run if a push later returns 403):

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR_REGISTRY
```

**Set up buildx (once):**

```bash
docker buildx create --use --name cross --platform linux/amd64
docker buildx inspect --bootstrap
```

**Build and push both images:**

```bash
# EEP — uses its own directory as build context
docker buildx build \
  --platform linux/amd64 \
  -f services/eep/Dockerfile \
  -t $ECR_REGISTRY/eep:latest \
  --push \
  services/eep/

# IEP3 — uses repo root as build context (imports from common/)
docker buildx build \
  --platform linux/amd64 \
  -f services/iep3_reconciliation/Dockerfile \
  -t $ECR_REGISTRY/iep3-reconciliation:latest \
  --push \
  .

# Frontend — React SPA + nginx (context = frontend/)
docker buildx build \
  --platform linux/amd64 \
  -f frontend/Dockerfile \
  -t $ECR_REGISTRY/frontend:latest \
  --push \
  frontend/
```

Each build takes ~5–10 minutes. All three must complete without error before proceeding.

> **If the push fails with `403 Forbidden`** the IAM user lacks ECR layer-push
> permissions (it can create/describe repos but not upload layers). Attach the
> policy once, then re-login and retry:
> ```bash
> aws iam attach-user-policy \
>   --user-name $AWS_IAM_USER \
>   --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser
> aws ecr get-login-password --region $AWS_REGION \
>   | docker login --username AWS --password-stdin $ECR_REGISTRY
> ```
> If `attach-user-policy` is itself denied, do it in the Console:
> IAM → Users → $AWS_IAM_USER → Add permissions → attach
> `AmazonEC2ContainerRegistryPowerUser`.

---

## Step 4 — Wait for k3s master to initialise

k3s installs via EC2 user data on first boot (~3–5 minutes). The instances have
no SSH key pair and port 22 is closed by design — access is via **AWS SSM**
(the node IAM role grants SSM access). Nothing to install for `send-command`.

```bash
# Resolve the master instance ID from its Elastic IP
export MASTER_ID=$(aws ec2 describe-instances --region $AWS_REGION \
  --filters "Name=ip-address,Values=$MASTER_IP" \
            "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].InstanceId' --output text)
echo "Master instance: $MASTER_ID"

# Check k3s is up via SSM
CMD_ID=$(aws ssm send-command --region $AWS_REGION \
  --instance-ids $MASTER_ID \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["kubectl get nodes"]' \
  --query 'Command.CommandId' --output text)
sleep 5
aws ssm get-command-invocation --region $AWS_REGION \
  --command-id $CMD_ID --instance-id $MASTER_ID \
  --query 'StandardOutputContent' --output text
```

Re-run the last two commands until the node shows `Ready`.

---

## Step 5 — Set secrets

Generate secrets and pull the RDS endpoint:

```bash
# Strong shared token (copy to edge secrets too)
export INTERNAL_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Discover the RDS secret ARN and S3 bucket from the CloudFormation stack
# (names are auto-generated by CDK, so look them up by resource type)
export DB_SECRET_ARN=$(aws cloudformation describe-stack-resources \
  --region $AWS_REGION --stack-name RetailEdgeData \
  --query "StackResources[?ResourceType=='AWS::SecretsManager::Secret'].PhysicalResourceId" \
  --output text)

export RDS_HOST=$(aws secretsmanager get-secret-value \
  --secret-id "$DB_SECRET_ARN" --region $AWS_REGION \
  --query SecretString --output text \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['host'])")

export RDS_PASS=$(aws secretsmanager get-secret-value \
  --secret-id "$DB_SECRET_ARN" --region $AWS_REGION \
  --query SecretString --output text \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['password'])")

export DB_URL="postgresql+asyncpg://retailvision:${RDS_PASS}@${RDS_HOST}:5432/retailvision"

export S3_BUCKET=$(aws cloudformation describe-stack-resources \
  --region $AWS_REGION --stack-name RetailEdgeData \
  --query "StackResources[?ResourceType=='AWS::S3::Bucket'].PhysicalResourceId" \
  --output text)

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
# macOS (BSD sed) requires the empty '' after -i; on Linux use: sed -i "s|...|...|g"
sed -i '' "s|REPLACE_WITH_ECR_OR_REGISTRY|$ECR_REGISTRY|g" \
  infra/cloud/eep.yaml \
  infra/cloud/frontend.yaml \
  infra/cloud/stores/template/iep3.yaml
```

---

## Step 7 — Connect kubectl to the cluster

The k3s API (port 6443) is open to the VPC only. Allow your laptop's IP first,
then fetch the kubeconfig over SSM.

```bash
# Allow your current public IP to reach the k3s API
export CLUSTER_SG=$(aws ec2 describe-instances --region $AWS_REGION \
  --instance-ids $MASTER_ID \
  --query 'Reservations[].Instances[].SecurityGroups[].GroupId' --output text)
export MY_IP=$(curl -s https://checkip.amazonaws.com)

aws ec2 authorize-security-group-ingress --region $AWS_REGION \
  --group-id $CLUSTER_SG \
  --protocol tcp --port 6443 --cidr ${MY_IP}/32 \
  2>&1 | grep -v Duplicate || true

# Fetch kubeconfig over SSM, rewrite server address to the public IP
mkdir -p ~/.kube
CMD_ID=$(aws ssm send-command --region $AWS_REGION \
  --instance-ids $MASTER_ID \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["cat /etc/rancher/k3s/k3s.yaml"]' \
  --query 'Command.CommandId' --output text)
sleep 5
aws ssm get-command-invocation --region $AWS_REGION \
  --command-id $CMD_ID --instance-id $MASTER_ID \
  --query 'StandardOutputContent' --output text \
  | sed "s/127.0.0.1/$MASTER_IP/" > ~/.kube/retail-edge.yaml

export KUBECONFIG=~/.kube/retail-edge.yaml

# The k3s serving cert only covers the private IP. Since we connect via the
# public Elastic IP, drop the CA pin and skip TLS verify (safe: port 6443 is
# restricted to your IP above).
sed -i '' '/certificate-authority-data/d' ~/.kube/retail-edge.yaml
kubectl config set-cluster default --insecure-skip-tls-verify=true

kubectl get nodes   # confirm connection
```

> On Linux use `sed -i '/certificate-authority-data/d' ...` (no `''`).

> Your home/office IP may change. If `kubectl` later times out, re-run the
> `MY_IP` + `authorize-security-group-ingress` commands to whitelist the new one.

---

## Step 8 — ECR pull auth, deploy workloads, migrate

k3s does **not** authenticate to ECR using the node IAM role, and ECR tokens
expire after 12h. Create the initial pull secret manually, then the bundled
`ecr-refresh` CronJob keeps it fresh every 6h.

```bash
# Initial pull secret in both namespaces (default = one-shot migrate pod,
# retail-edge = the app workloads). Attach it to each default service account.
for NS in default retail-edge; do
  kubectl create namespace $NS 2>/dev/null || true
  kubectl create secret docker-registry ecr-creds \
    --docker-server=$ECR_REGISTRY \
    --docker-username=AWS \
    --docker-password="$(aws ecr get-login-password --region $AWS_REGION)" \
    --namespace=$NS \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl patch serviceaccount default -n $NS \
    -p '{"imagePullSecrets":[{"name":"ecr-creds"}]}'
done
```

```bash
# Install the nginx ingress controller (the CDK user-data also does this, but
# install here too in case it didn't land — idempotent). Pinned version.
kubectl apply -f \
  https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/cloud/deploy.yaml
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=180s

# Deploy all cloud workloads (EEP creates its own tables on startup;
# the ecr-refresh CronJob is included here too)
kubectl apply -k infra/cloud/

# Wait for app pods to pull and start
kubectl -n retail-edge rollout status deployment/eep --timeout=300s
kubectl -n retail-edge rollout status deployment/frontend --timeout=300s

# Create the IEP2/IEP3 subsystem tables (tracking_history, embeddings, etc.).
# These live in common/ — use the IEP3 image, which bundles that package.
# Run detached + wait so a slow first image pull doesn't time out.
kubectl run migrate \
  --image=$ECR_REGISTRY/iep3-reconciliation:latest \
  --restart=Never \
  --env="DATABASE_URL=$DB_URL" \
  --command -- python -m common.db.migrate

kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/migrate --timeout=300s
kubectl logs migrate          # expect "schema up to date"
kubectl delete pod migrate
```

---

## Step 9 — Onboard a store (backend pod)

This creates the **per-store IEP3 reconciliation pod**. Configuring the store's
cameras, zones, and calibration is done afterward in the **GUI** (see Step 10) —
this step only provisions the backend worker for the store.

```bash
export STORE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
echo "Store ID: $STORE_ID"   # save this — needed for edge configmap + GUI

mkdir -p infra/cloud/stores/$STORE_ID

sed "s/__STORE_ID__/$STORE_ID/g" infra/cloud/stores/template/iep3.yaml \
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

The IEP3 pod reads the store's cameras from the database and **auto-refreshes
every 30s**. When you add or remove cameras in the GUI (Step 10), reconciliation
picks them up automatically — no env var, no restart needed. The pod stays
`Running` from the moment it's deployed (it idles harmlessly until cameras exist).

---

## Step 10 — Verify + open the GUI

```bash
# All pods healthy — expect eep, frontend, redis, and iep3-<store> Running
kubectl -n retail-edge get pods

# EEP health check (via ingress)
curl http://$MASTER_IP/health

# Internal endpoint accepts tracking batches
curl -s -X POST http://$MASTER_IP/internal/stores/$STORE_ID/tracking-batch \
  -H "X-Internal-Token: $INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"camera_id":"test","batch_number":1,"window_start_ms":0,"window_end_ms":2000,"positions":[]}' \
  | python3 -m json.tool
# Expect: {"accepted": true, "batch_number": 1}
```

**Open the GUI** in your browser:

```bash
echo "http://$MASTER_IP/"
```

The frontend serves the SPA and proxies `/api` to EEP through the ingress.
Use the GUI to:
- Log in / create the store account
- Configure cameras, zones, and calibration for the store
- View live monitoring, analytics, and alerts

> The GUI is reachable from anywhere (ingress port 80 is open to `0.0.0.0`).
> Only the k3s API (6443) is IP-restricted. For production, put the frontend
> behind HTTPS — add a TLS cert to the ingress or front it with CloudFront/ALB.

---

## Scaling

**EEP autoscaling (automatic):** an HorizontalPodAutoscaler (`hpa.yaml`) scales
EEP between **2 and 6 replicas** at 70% CPU / 80% memory. Nothing to do — it's
applied with the rest of `infra/cloud/`. Check it:
```bash
kubectl -n retail-edge get hpa
# NAME  REFERENCE        TARGETS           MINPODS  MAXPODS  REPLICAS
# eep   Deployment/eep   12%/70%, 40%/80%  2        6        2
```
> Needs `metrics-server` (k3s installs it by default). If `TARGETS` shows
> `<unknown>`, metrics-server isn't running:
> `kubectl -n kube-system get deploy metrics-server`.

IEP3 is **not** autoscaled — it's a per-store singleton (a 2nd replica would
double-consume the store's Redis stream). Scale IEP3 by adding stores, not pods.

**Add a store:** repeat Step 9 with a new `STORE_ID`.

**Worker node full:** add more EC2 capacity, then redeploy:
```bash
cdk deploy RetailEdgeCluster
```

**Upgrade images** (example for EEP; same pattern for `frontend` / `iep3`):
```bash
docker buildx build \
  --platform linux/amd64 \
  -f services/eep/Dockerfile \
  -t $ECR_REGISTRY/eep:latest \
  --push \
  services/eep/

kubectl -n retail-edge rollout restart deployment/eep
kubectl -n retail-edge rollout status deployment/eep
```

**Upgrade the frontend GUI:**
```bash
docker buildx build --platform linux/amd64 \
  -f frontend/Dockerfile -t $ECR_REGISTRY/frontend:latest --push frontend/
kubectl -n retail-edge rollout restart deployment/frontend
```

**Recreate the data stack (e.g. resize RDS storage).** RDS storage can only
grow, never shrink — to reduce it you destroy and redeploy the Data stack. The
DB carries a final snapshot (`removal_policy=SNAPSHOT`), and the frames bucket is
retained. Only do this when the data is disposable or you've snapshotted.

```bash
# 1. Disable deletion protection, then destroy + redeploy
aws rds modify-db-instance --region $AWS_REGION \
  --db-instance-identifier <rds-id> --no-deletion-protection --apply-immediately
cd infra/cdk && cdk destroy RetailEdgeData
cdk deploy RetailEdgeData --outputs-file ../../outputs.json && cd ../..

# 2. Re-point services to the NEW endpoint. Preserve the existing token + JWT
#    (regenerating them breaks edge auth + logs users out):
export INTERNAL_TOKEN=$(kubectl -n retail-edge get secret retail-edge-secrets \
  -o jsonpath='{.data.VISION_INTERNAL_TOKEN}' | base64 -d)
export JWT_SECRET=$(kubectl -n retail-edge get secret retail-edge-secrets \
  -o jsonpath='{.data.JWT_SECRET}' | base64 -d)
#    Then re-run Step 5's discovery block to get the new DB_URL + S3_BUCKET,
#    rewrite infra/cloud/secrets.yaml, and:
kubectl apply -k infra/cloud/

# 3. The new DB is empty — recreate tracking tables, then restart services
kubectl run migrate --image=$ECR_REGISTRY/iep3-reconciliation:latest \
  --restart=Never --env="DATABASE_URL=$DB_URL" --command -- python -m common.db.migrate
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/migrate --timeout=300s
kubectl logs migrate && kubectl delete pod migrate
kubectl -n retail-edge rollout restart deployment/eep deployment/iep3-$STORE_ID
```

> RDS now provisions at **20 GB gp3** (autoscaling to 100 GB). Stacks created
> before this fix have 100 GB — recreate as above to reclaim it.

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
