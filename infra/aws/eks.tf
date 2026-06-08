locals {
  cluster_name = "retailvision-${var.environment}"
}

data "aws_caller_identity" "current" {}

# ── EKS cluster (managed control plane) ──────────────────────────────────────
# Public API endpoint (optionally CIDR-restricted) so kubectl/helm work from your
# workstation. Nodes + LBs live in the public subnets (no NAT). EKS-managed add-ons
# cover networking/DNS/storage; the EBS CSI driver gets an IRSA role.
module "eks" {
  source = "./modules/eks"

  cluster_name    = local.cluster_name
  cluster_version = var.cluster_version

  cluster_endpoint_public_access       = true
  cluster_endpoint_public_access_cidrs = var.eks_public_access_cidrs

  # Give the Terraform-applying principal cluster-admin (access entries API).
  enable_cluster_creator_admin_permissions = true

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.public_subnets
  control_plane_subnet_ids = module.vpc.public_subnets

  cluster_addons = {
    kube-proxy = {}
    vpc-cni    = { before_compute = true }
    eks-pod-identity-agent = {
      before_compute = true
    }
    coredns = {
      configuration_values = jsonencode({
        nodeSelector = { workload = "stable" }
        tolerations = [{
          key      = "stable"
          operator = "Equal"
          value    = "true"
          effect   = "NoSchedule"
        }]
      })
    }
    aws-ebs-csi-driver = {
      service_account_role_arn = module.irsa_ebs_csi.iam_role_arn
      configuration_values = jsonencode({
        controller = {
          nodeSelector = { workload = "stable" }
          tolerations = [{
            key      = "stable"
            operator = "Equal"
            value    = "true"
            effect   = "NoSchedule"
          }]
        }
      })
    }
  }

  # Stable on-demand pool (fixed size) — hosts the stateful + system tier. Workers
  # overflow onto Karpenter-provisioned nodes (see karpenter.tf).
  eks_managed_node_groups = {
    stable = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = [var.stable_instance_type]
      capacity_type  = "ON_DEMAND"
      min_size       = var.stable_node_count
      max_size       = var.stable_node_max_count
      desired_size   = var.stable_node_count
      subnet_ids     = module.vpc.public_subnets
      labels         = { workload = "stable" }
      taints = {
        stable = {
          key    = "stable"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      }
      disk_size = var.node_root_volume_gb
    }
  }

  # Karpenter discovers the node security group by this tag.
  node_security_group_tags = {
    "karpenter.sh/discovery" = local.cluster_name
  }

  tags = {
    "karpenter.sh/discovery" = local.cluster_name
  }
}

# ── IRSA roles for cluster controllers ───────────────────────────────────────
module "irsa_ebs_csi" {
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-iam.git//modules/iam-role-for-service-accounts-eks?ref=v5.60.0"

  role_name             = "${local.cluster_name}-ebs-csi"
  attach_ebs_csi_policy = true
  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }
}

module "irsa_lb_controller" {
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-iam.git//modules/iam-role-for-service-accounts-eks?ref=v5.60.0"

  role_name                              = "${local.cluster_name}-lb-controller"
  attach_load_balancer_controller_policy = true
  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:aws-load-balancer-controller"]
    }
  }
}

module "irsa_external_secrets" {
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-iam.git//modules/iam-role-for-service-accounts-eks?ref=v5.60.0"

  role_name = "${local.cluster_name}-external-secrets"
  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["external-secrets:external-secrets"]
    }
  }
}

# External Secrets needs read access to the project's Secrets Manager entries.
resource "aws_iam_role_policy" "external_secrets" {
  name = "${local.cluster_name}-external-secrets-read"
  role = module.irsa_external_secrets.iam_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:retailvision/*"
    }]
  })
}
