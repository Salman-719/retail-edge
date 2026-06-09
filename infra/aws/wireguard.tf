# Minimal private edge gateway. Store devices establish WireGuard tunnels to this
# instance and route only the VPC CIDR through it. The gateway SNATs tunnel traffic
# to its VPC address, so no VPC route-table changes are required.

data "aws_ami" "wireguard" {
  count       = var.wireguard_enabled ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-6.1-arm64"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_iam_role" "wireguard" {
  count = var.wireguard_enabled ? 1 : 0
  name  = "${local.cluster_name}-wireguard"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "wireguard_ssm" {
  count      = var.wireguard_enabled ? 1 : 0
  role       = aws_iam_role.wireguard[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "wireguard" {
  count = var.wireguard_enabled ? 1 : 0
  name  = "${local.cluster_name}-wireguard"
  role  = aws_iam_role.wireguard[0].name
}

resource "aws_security_group" "wireguard" {
  count       = var.wireguard_enabled ? 1 : 0
  name_prefix = "${local.cluster_name}-wireguard-"
  description = "WireGuard ingress and VPC data-plane forwarding"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "WireGuard peers"
    protocol    = "udp"
    from_port   = var.wireguard_port
    to_port     = var.wireguard_port
    cidr_blocks = var.wireguard_client_cidrs
  }

  egress {
    description = "Package updates, SSM, and VPC data services"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_instance" "wireguard" {
  count = var.wireguard_enabled ? 1 : 0

  ami                         = data.aws_ami.wireguard[0].id
  instance_type               = var.wireguard_instance_type
  subnet_id                   = module.vpc.public_subnets[0]
  associate_public_ip_address = true
  source_dest_check           = false
  vpc_security_group_ids      = [aws_security_group.wireguard[0].id]
  iam_instance_profile        = aws_iam_instance_profile.wireguard[0].name

  user_data = templatefile("${path.module}/templates/wireguard-user-data.sh.tpl", {
    server_address = var.wireguard_server_address
    listen_port    = var.wireguard_port
    tunnel_cidr    = var.wireguard_tunnel_cidr
    tunnel_prefix  = join(".", slice(split(".", cidrhost(var.wireguard_tunnel_cidr, 0)), 0, 3))
    vpc_cidr       = var.vpc_cidr
  })

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 8
  }

  lifecycle {
    # Peer keys live on the encrypted root volume. Do not replace the gateway
    # merely because Amazon published a newer AL2023 AMI.
    ignore_changes = [ami]

    precondition {
      condition     = split("/", var.wireguard_server_address)[0] == cidrhost(var.wireguard_tunnel_cidr, 1)
      error_message = "wireguard_server_address must be host 1 of wireguard_tunnel_cidr."
    }
  }

  tags = {
    Name = "${local.cluster_name}-wireguard"
  }

  depends_on = [aws_iam_role_policy_attachment.wireguard_ssm]
}

resource "aws_eip" "wireguard" {
  count    = var.wireguard_enabled ? 1 : 0
  domain   = "vpc"
  instance = aws_instance.wireguard[0].id

  tags = {
    Name = "${local.cluster_name}-wireguard"
  }
}
