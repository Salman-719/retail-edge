# VPC for the EKS cluster. Public subnets only across 2 AZs — nodes get public IPs
# and egress via the Internet Gateway (NO NAT gateway: reliable + cost-saving, the
# same egress model the prior k3s setup used). A free S3 gateway endpoint keeps S3
# traffic off the public path. LB + Karpenter discovery via subnet/VPC tags.
data "aws_availability_zones" "available" {
  state = "available"
}

module "vpc" {
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git?ref=v5.21.0"

  name = "retailvision-${var.environment}"
  cidr = var.vpc_cidr
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)

  # Public subnets only; nodes launch here with public IPs.
  public_subnets          = [for i in range(2) : cidrsubnet(var.vpc_cidr, 8, i)]
  map_public_ip_on_launch = true

  enable_nat_gateway   = false
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    "karpenter.sh/discovery" = local.cluster_name
  }
  # The AWS LB Controller places internet-facing LBs in subnets tagged role/elb;
  # Karpenter discovers subnets by the discovery tag; EKS needs the cluster tag.
  public_subnet_tags = {
    "kubernetes.io/role/elb"                      = "1"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    "karpenter.sh/discovery"                      = local.cluster_name
  }
}

# S3 gateway endpoint (free) — routes S3 traffic privately via the public route table.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.public_route_table_ids
  tags              = { Name = "retailvision-${var.environment}-s3" }
}
