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

variable "server_instance_type" {
  description = "EC2 type for the k3s server. Graviton (t4g) is cheapest; images are arm64."
  type        = string
  default     = "t4g.large"
}

variable "agent_instance_type" {
  description = "EC2 type for k3s agent nodes (scale-out for more stores)."
  type        = string
  default     = "t4g.large"
}

variable "agent_count" {
  description = "Number of k3s agent nodes to join the server. 0 = single-node cluster."
  type        = number
  default     = 0
}

variable "server_root_volume_gb" {
  description = "Root EBS volume size (GB) for each node."
  type        = number
  default     = 40
}

variable "ssh_key_name" {
  description = "Existing EC2 key pair name for SSH. Empty = SSM-only access."
  type        = string
  default     = ""
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed to SSH (22). Lock this down; default is none."
  type        = string
  default     = "127.0.0.1/32"
}

variable "git_repo_url" {
  description = "Git URL of this repo, cloned by user-data to run the bootstrap script."
  type        = string
  default     = "https://github.com/your-org/retail-edge.git"
}

variable "git_branch" {
  description = "Branch to check out on the node."
  type        = string
  default     = "deploy/aws-k3s"
}

variable "app_host" {
  description = "Public hostname for the SPA/API. Leave empty to derive app.<eip>.nip.io."
  type        = string
  default     = ""
}

variable "eep_host" {
  description = "Public hostname edge devices dial for gRPC. Leave empty to derive eep.<eip>.nip.io."
  type        = string
  default     = ""
}

variable "letsencrypt_email" {
  description = "Contact email for Let's Encrypt certificate issuance."
  type        = string
}

variable "s3_bucket_name" {
  description = "Globally-unique S3 bucket name for object storage (frames/uploads)."
  type        = string
}

variable "create_dns_records" {
  description = "Create Route53 A records for app_host/eep_host -> the server EIP."
  type        = bool
  default     = false
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID (required when create_dns_records = true)."
  type        = string
  default     = ""
}

variable "secret_names" {
  description = "AWS Secrets Manager secret names (must match chart values.secrets.*)."
  type        = map(string)
  default = {
    postgres_password = "retailvision/postgres-password"
    redis_password    = "retailvision/redis-password"
    jwt_secret        = "retailvision/jwt-secret"
    agent_secret      = "retailvision/agent-secret"
    redis_url         = "retailvision/redis-url"
    s3_access_key     = "retailvision/s3-access-key"
    s3_secret_key     = "retailvision/s3-secret-key"
  }
}
