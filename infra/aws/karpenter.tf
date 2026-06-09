# ── Karpenter: elastic node autoscaling ──────────────────────────────────────
# The submodule provisions Karpenter's controller IAM (via EKS Pod Identity), the
# node IAM role + instance profile, and the SQS interruption queue. The Helm
# release runs the controller on the stable pool; the EC2NodeClass + NodePool
# define the elastic Graviton (Spot+on-demand) capacity that backs workers and
# per-store IEP3/IEP4/IEP5 pods.
module "karpenter" {
  source = "./modules/eks/modules/karpenter"

  cluster_name = module.eks.cluster_name

  enable_pod_identity             = true
  create_pod_identity_association = true

  # Let Karpenter-launched nodes be reached via SSM.
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }

  tags = { "karpenter.sh/discovery" = local.cluster_name }
}

resource "helm_release" "karpenter" {
  namespace       = "kube-system"
  name            = "karpenter"
  repository      = "oci://public.ecr.aws/karpenter"
  chart           = "karpenter"
  version         = var.karpenter_version
  wait            = true
  wait_for_jobs   = true
  atomic          = true
  cleanup_on_fail = true
  timeout         = 900

  values = [yamlencode({
    settings = {
      clusterName       = module.eks.cluster_name
      interruptionQueue = module.karpenter.queue_name
    }
    # Run the controller on the stable managed node group.
    nodeSelector = { workload = "stable" }
    tolerations  = local.stable_addon_tolerations
    controller = {
      resources = {
        requests = { cpu = "0.5", memory = "512Mi" }
        limits   = { memory = "512Mi" }
      }
    }
  })]

  depends_on = [null_resource.aws_lb_webhook_ready]
}

# EC2NodeClass — how Karpenter builds nodes (AL2023 arm64, discovered subnets/SG,
# the Karpenter node IAM role, IMDSv2, gp3 root).
resource "kubectl_manifest" "karpenter_node_class" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.k8s.aws/v1"
    kind       = "EC2NodeClass"
    metadata   = { name = "default" }
    spec = {
      amiFamily                  = "AL2023"
      amiSelectorTerms           = [{ alias = "al2023@latest" }]
      role                       = module.karpenter.node_iam_role_name
      subnetSelectorTerms        = [{ tags = { "karpenter.sh/discovery" = local.cluster_name } }]
      securityGroupSelectorTerms = [{ tags = { "karpenter.sh/discovery" = local.cluster_name } }]
      metadataOptions            = { httpTokens = "required", httpPutResponseHopLimit = 1 }
      blockDeviceMappings = [{
        deviceName = "/dev/xvda"
        ebs        = { volumeSize = "${var.node_root_volume_gb}Gi", volumeType = "gp3", encrypted = true }
      }]
      tags = { "karpenter.sh/discovery" = local.cluster_name }
    }
  })
  depends_on = [helm_release.karpenter]
}

# NodePool — the elastic capacity: Graviton (arm64), Spot with on-demand fallback,
# consolidates when empty/underutilized.
resource "kubectl_manifest" "karpenter_node_pool" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = "default" }
    spec = {
      template = {
        spec = {
          nodeClassRef = { group = "karpenter.k8s.aws", kind = "EC2NodeClass", name = "default" }
          requirements = [
            { key = "kubernetes.io/arch", operator = "In", values = ["arm64"] },
            { key = "karpenter.sh/capacity-type", operator = "In", values = ["spot", "on-demand"] },
            { key = "karpenter.k8s.aws/instance-category", operator = "In", values = ["t", "m", "c"] },
            { key = "karpenter.k8s.aws/instance-generation", operator = "Gt", values = ["6"] },
          ]
          expireAfter = "720h"
        }
      }
      limits = { cpu = var.karpenter_cpu_limit }
      disruption = {
        consolidationPolicy = "WhenEmptyOrUnderutilized"
        consolidateAfter    = "1m"
      }
    }
  })
  depends_on = [kubectl_manifest.karpenter_node_class]
}
