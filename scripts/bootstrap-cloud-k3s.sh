#!/bin/bash
# Bootstrap an AWS EC2 instance as the RetailVision CLOUD k3s server.
#
# AWS-native, NO EKS: a single k3s server (scale out later with agents) running
# the server-side stack (EEP, IEP3, Postgres, Redis, pgbouncer, frontend).
# Cost-efficient by default: k3s built-in ServiceLB (klipper) exposes the
# LoadBalancer Services directly on the node's public Elastic IP — no always-on
# AWS NLB required. Cluster add-ons (ingress-nginx, cert-manager, external-secrets,
# ebs-csi) are installed via Helm.
#
# Intended to run from EC2 user-data (see infra/aws/compute.tf) or manually as root.
# Required env (exported by user-data or the operator):
#   AWS_REGION            e.g. us-east-1
#   APP_HOST              public hostname for the SPA/API, e.g. app.retailvision.example.com
#   EEP_HOST              public hostname for edge<->EEP gRPC, e.g. eep.retailvision.example.com
#   LETSENCRYPT_EMAIL     contact email for Let's Encrypt
# Optional:
#   K3S_VERSION           default v1.29.4+k3s1
#   INGRESS_NGINX_VERSION default 4.11.3
#   CERT_MANAGER_VERSION  default v1.16.2
#   EXTERNAL_SECRETS_VERSION default 0.10.5
#   EBS_CSI_VERSION       default 2.36.0
set -euo pipefail

: "${AWS_REGION:?set AWS_REGION}"
: "${LETSENCRYPT_EMAIL:?set LETSENCRYPT_EMAIL}"
# Hostnames are informational at bootstrap time; the real ingress host / gRPC SAN
# are set at `helm install`. Safe to be empty (no-domain / nip.io mode).
APP_HOST="${APP_HOST:-}"
EEP_HOST="${EEP_HOST:-}"
K3S_VERSION="${K3S_VERSION:-v1.29.4+k3s1}"
INGRESS_NGINX_VERSION="${INGRESS_NGINX_VERSION:-4.11.3}"
CERT_MANAGER_VERSION="${CERT_MANAGER_VERSION:-v1.16.2}"
EXTERNAL_SECRETS_VERSION="${EXTERNAL_SECRETS_VERSION:-0.10.5}"
EBS_CSI_VERSION="${EBS_CSI_VERSION:-2.36.0}"

echo "=== RetailVision cloud k3s bootstrap (region=${AWS_REGION}) ==="

# 1. NTP — server timestamps must align with edge stream timestamps
apt-get update -y
apt-get install -y chrony curl
systemctl enable --now chrony
echo "[1/7] NTP (chrony) enabled"

# 2. Install k3s server. Keep ServiceLB (klipper) so type=LoadBalancer binds the
#    node's public IP; disable traefik (we use ingress-nginx). A fixed K3S_TOKEN
#    (set by Terraform) lets agent nodes join for scale-out.
# K3S_TOKEN (if set) is read from the environment by the installer automatically.
curl -sfL https://get.k3s.io | \
    INSTALL_K3S_VERSION="${K3S_VERSION}" \
    sh -s - \
    --disable=traefik \
    --write-kubeconfig-mode=644 \
    --node-name="cloud-server"
until k3s kubectl get node &>/dev/null; do echo "waiting for k3s API..."; sleep 3; done
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
echo "[2/7] k3s server installed"

# 3. Install Helm
if ! command -v helm &>/dev/null; then
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
helm repo add jetstack https://charts.jetstack.io
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add external-secrets https://charts.external-secrets.io
helm repo add aws-ebs-csi-driver https://kubernetes-sigs.github.io/aws-ebs-csi-driver
helm repo update
echo "[3/7] Helm repos ready"

# 4. aws-ebs-csi-driver + default gp3 StorageClass (durable PVCs survive node
#    replacement). Auth via the node IAM instance profile (see infra/aws/iam.tf).
helm upgrade --install aws-ebs-csi-driver aws-ebs-csi-driver/aws-ebs-csi-driver \
    --namespace kube-system --version "${EBS_CSI_VERSION}" \
    --set controller.region="${AWS_REGION}" --wait
kubectl apply -f - <<'YAML'
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
YAML
echo "[4/7] EBS CSI + gp3 default StorageClass installed"

# 5. ingress-nginx (type=LoadBalancer -> klipper binds node public IP:80/443)
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
    --namespace ingress-nginx --create-namespace --version "${INGRESS_NGINX_VERSION}" \
    --set controller.service.type=LoadBalancer \
    --set controller.publishService.enabled=true \
    --wait
echo "[5/7] ingress-nginx installed"

# 6. cert-manager + ClusterIssuers:
#    - letsencrypt-prod : public cert for the SPA/API ingress (APP_HOST)
#    - retailvision-ca-issuer : internal CA for edge<->EEP gRPC mTLS (eep-certificate.yaml)
helm upgrade --install cert-manager jetstack/cert-manager \
    --namespace cert-manager --create-namespace --version "${CERT_MANAGER_VERSION}" \
    --set crds.enabled=true --wait
kubectl apply -f - <<YAML
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ${LETSENCRYPT_EMAIL}
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
      - http01:
          ingress:
            ingressClassName: nginx
---
# Self-signed root -> CA cert -> CA ClusterIssuer used to sign the EEP gRPC server
# cert. Distribute the CA (cloud-ca secret) to edge devices as ca.crt.
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: retailvision-selfsigned
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: retailvision-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: retailvision-ca
  secretName: retailvision-ca
  duration: 87600h
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: retailvision-selfsigned
    kind: ClusterIssuer
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: retailvision-ca-issuer
spec:
  ca:
    secretName: retailvision-ca
YAML
echo "[6/7] cert-manager + ClusterIssuers installed"

# 7. External Secrets Operator + ClusterSecretStore backed by AWS Secrets Manager.
#    Auth uses the node IAM instance profile (no static keys / no IRSA needed).
helm upgrade --install external-secrets external-secrets/external-secrets \
    --namespace external-secrets --create-namespace --version "${EXTERNAL_SECRETS_VERSION}" \
    --set installCRDs=true --wait
kubectl apply -f - <<YAML
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: aws-secrets-manager
spec:
  provider:
    aws:
      service: SecretsManager
      region: ${AWS_REGION}
      auth: {}   # falls back to the node instance-profile credential chain
YAML
echo "[7/7] External Secrets + ClusterSecretStore installed"

echo ""
echo "=== cloud k3s bootstrap complete ==="
echo "  APP_HOST: ${APP_HOST}   EEP_HOST: ${EEP_HOST}"
echo ""
echo "Next steps:"
echo "  1. Point DNS A records APP_HOST and EEP_HOST at this node's Elastic IP."
echo "  2. Seed AWS Secrets Manager (see docs/operations/deploy-aws-cloud.md)."
echo "  3. helm install retailvision charts/retailvision -f values.production.yaml \\"
echo "       --set ingress.appHost=${APP_HOST} --set iep3.stores={<store-uuid>}"
echo "  4. Export edge CA:  kubectl -n cert-manager get secret retailvision-ca \\"
echo "       -o jsonpath='{.data.tls\\.crt}' | base64 -d > ca.crt   # copy to each edge"
