terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "5.100.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "2.14.1"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "2.31.0"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = "1.19.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "4.0.5"
    }
    cloudinit = {
      source  = "hashicorp/cloudinit"
      version = "2.3.5"
    }
    null = {
      source  = "hashicorp/null"
      version = "3.2.2"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.11.2"
    }
  }

  # Remote state — uncomment and set a real bucket/table to share state across a team.
  # backend "s3" {
  #   bucket         = "retailvision-tfstate"
  #   key            = "cloud/terraform.tfstate"
  #   region         = "eu-west-1"
  #   dynamodb_table = "retailvision-tflock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project   = "retailvision"
      ManagedBy = "terraform"
      Env       = var.environment
    }
  }
}

# ── Kubernetes / Helm / kubectl providers authenticated against the EKS cluster ──
# The aws CLI exec plugin issues short-lived tokens so they don't expire mid-apply.
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
    }
  }
}

provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  load_config_file       = false
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
  }
}
