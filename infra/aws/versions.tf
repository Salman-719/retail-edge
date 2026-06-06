terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state — uncomment and set a real bucket/table to share state across a team.
  # backend "s3" {
  #   bucket         = "retailvision-tfstate"
  #   key            = "cloud/terraform.tfstate"
  #   region         = "us-east-1"
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
