variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Environment name (staging|production), used in tags and resource names."
  type        = string
  default     = "production"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

# ── EKS cluster ──────────────────────────────────────────────────────────────
variable "cluster_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.30"
}

variable "eks_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint. Lock down for production."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# ── Stable on-demand node group (stateful + system tier) ─────────────────────
variable "stable_instance_type" {
  description = "Instance type for the stable on-demand node group (Graviton/arm64)."
  type        = string
  default     = "t4g.large"
}

variable "stable_node_count" {
  description = "Fixed size of the stable node group (hosts TimescaleDB/Redis/monitoring/MLflow/controllers). 2 = HA across 2 AZs."
  type        = number
  default     = 2
}

variable "stable_node_max_count" {
  description = "Maximum stable on-demand nodes for controlled manual expansion of the stateful/system tier."
  type        = number
  default     = 4
}

variable "node_root_volume_gb" {
  description = "Root EBS volume size (GB) for nodes (stable group + Karpenter)."
  type        = number
  default     = 60
}

# ── Private edge data-plane access ──────────────────────────────────────────
variable "wireguard_enabled" {
  description = "Create the SSM-managed WireGuard gateway used by edge devices to reach private EKS data services."
  type        = bool
  default     = true
}

variable "wireguard_instance_type" {
  description = "Graviton instance type for the WireGuard gateway."
  type        = string
  default     = "t4g.nano"
}

variable "wireguard_port" {
  description = "Public UDP port used by WireGuard."
  type        = number
  default     = 51820

  validation {
    condition     = var.wireguard_port >= 1 && var.wireguard_port <= 65535
    error_message = "wireguard_port must be between 1 and 65535."
  }
}

variable "wireguard_client_cidrs" {
  description = "Internet CIDRs allowed to send WireGuard UDP traffic. 0.0.0.0/0 supports roaming store uplinks; WireGuard still requires an enrolled key."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "wireguard_tunnel_cidr" {
  description = "WireGuard overlay subnet. Must not overlap the VPC or store LANs."
  type        = string
  default     = "10.99.0.0/24"

  validation {
    condition     = can(cidrhost(var.wireguard_tunnel_cidr, 1)) && endswith(var.wireguard_tunnel_cidr, "/24")
    error_message = "wireguard_tunnel_cidr must be a valid IPv4 /24 CIDR."
  }
}

variable "wireguard_server_address" {
  description = "WireGuard gateway address inside the overlay subnet, including prefix."
  type        = string
  default     = "10.99.0.1/24"

  validation {
    condition     = can(cidrhost(var.wireguard_server_address, 0)) && endswith(var.wireguard_server_address, "/24")
    error_message = "wireguard_server_address must be a valid IPv4 address with a /24 prefix."
  }
}

# ── Karpenter (elastic worker capacity) ──────────────────────────────────────
variable "karpenter_version" {
  description = "Karpenter Helm chart version (OCI public.ecr.aws/karpenter)."
  type        = string
  default     = "1.0.6"
}

variable "karpenter_cpu_limit" {
  description = "Max total vCPUs Karpenter may provision across the elastic NodePool."
  type        = string
  default     = "200"
}

# ── Add-on chart versions ────────────────────────────────────────────────────
variable "lb_controller_version" {
  description = "aws-load-balancer-controller Helm chart version."
  type        = string
  default     = "1.8.2"
}

variable "ingress_nginx_version" {
  description = "ingress-nginx Helm chart version."
  type        = string
  default     = "4.11.2"
}

variable "cert_manager_version" {
  description = "cert-manager Helm chart version."
  type        = string
  default     = "v1.15.3"
}

variable "external_secrets_version" {
  description = "external-secrets Helm chart version."
  type        = string
  default     = "0.10.4"
}

variable "keda_version" {
  description = "KEDA Helm chart version (event/metric-driven autoscaling for IEP6 agent)."
  type        = string
  default     = "2.14.0"
}

variable "metrics_server_version" {
  description = "metrics-server Helm chart version."
  type        = string
  default     = "3.12.1"
}

# ── DNS / hostnames ──────────────────────────────────────────────────────────
variable "app_host" {
  description = "Public hostname for the SPA/API. Leave empty to derive app.<ingress-eip>.nip.io."
  type        = string
  default     = ""
}

variable "eep_host" {
  description = "Public hostname edge devices dial for gRPC. Leave empty to derive eep.<grpc-eip>.nip.io."
  type        = string
  default     = ""
}

variable "create_dns_records" {
  description = "Create Route53 A records for app_host -> ingress EIP and eep_host -> gRPC EIP."
  type        = bool
  default     = false
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID (required when create_dns_records = true)."
  type        = string
  default     = ""
}

variable "letsencrypt_email" {
  description = "Contact email for Let's Encrypt certificate issuance."
  type        = string
}

variable "s3_bucket_name" {
  description = "Globally-unique S3 bucket name for object storage (frames/uploads/mlflow)."
  type        = string
}

variable "secret_names" {
  description = "AWS Secrets Manager secret names (must match chart values.secrets.*)."
  type        = map(string)
  default = {
    postgres_password      = "retailvision/postgres-password"
    redis_password         = "retailvision/redis-password"
    jwt_secret             = "retailvision/jwt-secret"
    agent_secret           = "retailvision/agent-secret"
    redis_url              = "retailvision/redis-url"
    s3_access_key          = "retailvision/s3-access-key"
    s3_secret_key          = "retailvision/s3-secret-key"
    openai_api_key         = "retailvision/openai-api-key"
    grafana_admin_password = "retailvision/grafana-admin-password"
  }
}
