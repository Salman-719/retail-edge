# ── Cluster add-ons (Terraform-managed for the EKS cloud) ───────────────────────
# AWS LB Controller, ingress-nginx (app/API NLB), cert-manager + ClusterIssuers,
# External Secrets + ClusterSecretStore, metrics-server (HPA), and a default gp3
# StorageClass. The EEP gRPC service gets its own NLB via Helm values so edge
# traffic has a stable, dedicated endpoint.

locals {
  stable_addon_tolerations = [{
    key      = "stable"
    operator = "Equal"
    value    = "true"
    effect   = "NoSchedule"
  }]
}

# Two EIPs (one per public subnet/AZ) for the ingress NLB → stable IPs for nip.io.
resource "aws_eip" "ingress" {
  count  = 2
  domain = "vpc"
  tags   = { Name = "retailvision-${var.environment}-ingress-${count.index}" }
}

# Two EIPs for the dedicated edge→EEP gRPC NLB.
resource "aws_eip" "grpc" {
  count  = 2
  domain = "vpc"
  tags   = { Name = "retailvision-${var.environment}-grpc-${count.index}" }
}

# ── AWS Load Balancer Controller ────────────────────────────────────────────
resource "helm_release" "aws_lb_controller" {
  namespace       = "kube-system"
  name            = "aws-load-balancer-controller"
  repository      = "https://aws.github.io/eks-charts"
  chart           = "aws-load-balancer-controller"
  version         = var.lb_controller_version
  wait            = true
  wait_for_jobs   = true
  atomic          = true
  cleanup_on_fail = true
  timeout         = 900

  values = [yamlencode({
    clusterName = module.eks.cluster_name
    region      = var.aws_region
    vpcId       = module.vpc.vpc_id
    serviceAccount = {
      name        = "aws-load-balancer-controller"
      annotations = { "eks.amazonaws.com/role-arn" = module.irsa_lb_controller.iam_role_arn }
    }
    nodeSelector = { workload = "stable" }
    tolerations  = local.stable_addon_tolerations
  })]

  depends_on = [module.eks]
}

# The controller registers a mutating Service webhook before its pods are always
# reachable. Helm releases installed in parallel can otherwise fail with
# "no endpoints available for service aws-load-balancer-webhook-service".
resource "null_resource" "aws_lb_webhook_ready" {
  triggers = {
    always_run         = timestamp()
    cluster_name       = module.eks.cluster_name
    controller_release = helm_release.aws_lb_controller.id
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      kubeconfig="$(mktemp)"
      trap 'rm -f "$kubeconfig"' EXIT

      aws eks update-kubeconfig \
        --name '${module.eks.cluster_name}' \
        --region '${var.aws_region}' \
        --kubeconfig "$kubeconfig" \
        >/dev/null

      kubectl --kubeconfig "$kubeconfig" \
        -n kube-system rollout status \
        deploy/aws-load-balancer-controller \
        --timeout=10m

      for attempt in $(seq 1 60); do
        endpoints="$(kubectl --kubeconfig "$kubeconfig" \
          -n kube-system get endpoints aws-load-balancer-webhook-service \
          -o jsonpath='{range .subsets[*].addresses[*]}{.ip}{"\n"}{end}' \
          2>/dev/null || true)"
        if [[ -n "$endpoints" ]]; then
          echo "AWS Load Balancer Controller webhook is ready: $endpoints"
          exit 0
        fi
        echo "Waiting for AWS Load Balancer Controller webhook endpoints ($attempt/60)..."
        sleep 5
      done

      kubectl --kubeconfig "$kubeconfig" \
        -n kube-system get pods,endpoints \
        -l app.kubernetes.io/name=aws-load-balancer-controller \
        -o wide || true
      echo "AWS Load Balancer Controller webhook did not become ready." >&2
      exit 1
    EOT
  }

  depends_on = [helm_release.aws_lb_controller]
}

# ── ingress-nginx → internet-facing NLB for HTTPS app/API traffic ───────────
resource "helm_release" "ingress_nginx" {
  namespace        = "ingress-nginx"
  name             = "ingress-nginx"
  create_namespace = true
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  version          = var.ingress_nginx_version
  wait             = true
  wait_for_jobs    = true
  atomic           = true
  cleanup_on_fail  = true
  timeout          = 900

  values = [yamlencode({
    controller = {
      nodeSelector = { workload = "stable" }
      tolerations  = local.stable_addon_tolerations
      admissionWebhooks = {
        patch = {
          nodeSelector = { workload = "stable" }
          tolerations  = local.stable_addon_tolerations
        }
      }
      service = {
        annotations = {
          "service.beta.kubernetes.io/aws-load-balancer-type"            = "external"
          "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type" = "ip"
          "service.beta.kubernetes.io/aws-load-balancer-scheme"          = "internet-facing"
          "service.beta.kubernetes.io/aws-load-balancer-eip-allocations" = join(",", aws_eip.ingress[*].id)
          "service.beta.kubernetes.io/aws-load-balancer-subnets"         = join(",", module.vpc.public_subnets)
        }
      }
    }
  })]

  depends_on = [null_resource.aws_lb_webhook_ready]
}

# ── cert-manager + ClusterIssuers ───────────────────────────────────────────
resource "helm_release" "cert_manager" {
  namespace        = "cert-manager"
  name             = "cert-manager"
  create_namespace = true
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  version          = var.cert_manager_version
  wait             = true
  wait_for_jobs    = true
  atomic           = true
  cleanup_on_fail  = true
  timeout          = 900
  set {
    name  = "crds.enabled"
    value = "true"
  }
  values = [yamlencode({
    nodeSelector = { workload = "stable" }
    tolerations  = local.stable_addon_tolerations
    cainjector = {
      nodeSelector = { workload = "stable" }
      tolerations  = local.stable_addon_tolerations
    }
    webhook = {
      nodeSelector = { workload = "stable" }
      tolerations  = local.stable_addon_tolerations
    }
    startupapicheck = {
      nodeSelector = { workload = "stable" }
      tolerations  = local.stable_addon_tolerations
    }
  })]
  depends_on = [null_resource.aws_lb_webhook_ready]
}

resource "kubectl_manifest" "issuer_letsencrypt" {
  yaml_body  = <<-YAML
    apiVersion: cert-manager.io/v1
    kind: ClusterIssuer
    metadata:
      name: letsencrypt-prod
    spec:
      acme:
        server: https://acme-v02.api.letsencrypt.org/directory
        email: ${var.letsencrypt_email}
        privateKeySecretRef:
          name: letsencrypt-prod-account-key
        solvers:
          - http01:
              ingress:
                ingressClassName: nginx
  YAML
  depends_on = [helm_release.cert_manager]
}

resource "kubectl_manifest" "issuer_selfsigned" {
  yaml_body  = <<-YAML
    apiVersion: cert-manager.io/v1
    kind: ClusterIssuer
    metadata:
      name: retailvision-selfsigned
    spec:
      selfSigned: {}
  YAML
  depends_on = [helm_release.cert_manager]
}

resource "kubectl_manifest" "ca_certificate" {
  yaml_body  = <<-YAML
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
  YAML
  depends_on = [kubectl_manifest.issuer_selfsigned]
}

resource "kubectl_manifest" "ca_issuer" {
  yaml_body  = <<-YAML
    apiVersion: cert-manager.io/v1
    kind: ClusterIssuer
    metadata:
      name: retailvision-ca-issuer
    spec:
      ca:
        secretName: retailvision-ca
  YAML
  depends_on = [kubectl_manifest.ca_certificate]
}

# ── KEDA — metric-driven autoscaling ────────────────────────────────────────
# Drives request-based autoscaling of the IEP6 agent API. The operator itself
# runs on the stable pool; KEDA-created workload replicas still schedule normally
# and can overflow to Karpenter elastic nodes.
resource "helm_release" "keda" {
  namespace        = "keda"
  name             = "keda"
  create_namespace = true
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = var.keda_version
  wait             = true
  wait_for_jobs    = true
  atomic           = true
  cleanup_on_fail  = true
  timeout          = 900

  values = [yamlencode({
    nodeSelector = { workload = "stable" }
    tolerations  = local.stable_addon_tolerations
    metricsServer = {
      nodeSelector = { workload = "stable" }
      tolerations  = local.stable_addon_tolerations
    }
    webhooks = {
      nodeSelector = { workload = "stable" }
      tolerations  = local.stable_addon_tolerations
    }
  })]

  depends_on = [null_resource.aws_lb_webhook_ready]
}

# ── External Secrets Operator + ClusterSecretStore (IRSA → Secrets Manager) ──
resource "helm_release" "external_secrets" {
  namespace        = "external-secrets"
  name             = "external-secrets"
  create_namespace = true
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = var.external_secrets_version
  wait             = true
  wait_for_jobs    = true
  atomic           = true
  cleanup_on_fail  = true
  timeout          = 900

  values = [yamlencode({
    installCRDs = true
    serviceAccount = {
      name        = "external-secrets"
      annotations = { "eks.amazonaws.com/role-arn" = module.irsa_external_secrets.iam_role_arn }
    }
    nodeSelector = { workload = "stable" }
    tolerations  = local.stable_addon_tolerations
    webhook = {
      nodeSelector = { workload = "stable" }
      tolerations  = local.stable_addon_tolerations
    }
    certController = {
      nodeSelector = { workload = "stable" }
      tolerations  = local.stable_addon_tolerations
    }
  })]
  depends_on = [null_resource.aws_lb_webhook_ready]
}

resource "kubectl_manifest" "cluster_secret_store" {
  yaml_body  = <<-YAML
    apiVersion: external-secrets.io/v1beta1
    kind: ClusterSecretStore
    metadata:
      name: aws-secrets-manager
    spec:
      provider:
        aws:
          service: SecretsManager
          region: ${var.aws_region}
          auth: {}
  YAML
  depends_on = [helm_release.external_secrets]
}

# ── metrics-server (HPA) ────────────────────────────────────────────────────
resource "helm_release" "metrics_server" {
  namespace       = "kube-system"
  name            = "metrics-server"
  repository      = "https://kubernetes-sigs.github.io/metrics-server/"
  chart           = "metrics-server"
  version         = var.metrics_server_version
  wait            = true
  wait_for_jobs   = true
  atomic          = true
  cleanup_on_fail = true
  timeout         = 900
  values = [yamlencode({
    nodeSelector = { workload = "stable" }
    tolerations  = local.stable_addon_tolerations
  })]
  depends_on = [null_resource.aws_lb_webhook_ready]
}

# ── default gp3 StorageClass (EBS CSI) ──────────────────────────────────────
resource "kubectl_manifest" "gp3_storageclass" {
  yaml_body  = <<-YAML
    apiVersion: storage.k8s.io/v1
    kind: StorageClass
    metadata:
      name: gp3
      annotations:
        storageclass.kubernetes.io/is-default-class: "true"
    provisioner: ebs.csi.aws.com
    volumeBindingMode: WaitForFirstConsumer
    allowVolumeExpansion: true
    parameters:
      type: gp3
      encrypted: "true"
  YAML
  depends_on = [module.eks]
}
