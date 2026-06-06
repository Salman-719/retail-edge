resource "random_password" "k3s_token" {
  length  = 48
  special = false
}

# Latest Canonical Ubuntu 22.04 arm64 (Graviton) AMI.
data "aws_ami" "ubuntu_arm64" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  k3s_version = "v1.29.4+k3s1"
  # No-domain mode: derive public hostnames from the Elastic IP via nip.io
  # (wildcard DNS that resolves <anything>.<ip>.nip.io -> <ip>). Override by
  # setting app_host / eep_host explicitly.
  app_host = var.app_host != "" ? var.app_host : "app.${aws_eip.server.public_ip}.nip.io"
  eep_host = var.eep_host != "" ? var.eep_host : "eep.${aws_eip.server.public_ip}.nip.io"
}

# Allocated standalone (not tied to the instance at creation) so the instance
# user-data can reference its IP without a dependency cycle.
resource "aws_eip" "server" {
  domain = "vpc"
  tags   = { Name = "retailvision-${var.environment}-server" }
}

resource "aws_instance" "server" {
  ami                    = data.aws_ami.ubuntu_arm64.id
  instance_type          = var.server_instance_type
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.node.id]
  iam_instance_profile   = aws_iam_instance_profile.node.name
  key_name               = var.ssh_key_name != "" ? var.ssh_key_name : null

  root_block_device {
    volume_size = var.server_root_volume_gb
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/templates/server-user-data.sh.tpl", {
    aws_region        = var.aws_region
    app_host          = local.app_host
    eep_host          = local.eep_host
    letsencrypt_email = var.letsencrypt_email
    k3s_token         = random_password.k3s_token.result
    k3s_version       = local.k3s_version
    git_repo_url      = var.git_repo_url
    git_branch        = var.git_branch
  })

  tags = { Name = "retailvision-${var.environment}-server" }
}

# Bind the pre-allocated Elastic IP to the server.
resource "aws_eip_association" "server" {
  allocation_id = aws_eip.server.id
  instance_id   = aws_instance.server.id
}

resource "aws_instance" "agent" {
  count                  = var.agent_count
  ami                    = data.aws_ami.ubuntu_arm64.id
  instance_type          = var.agent_instance_type
  subnet_id              = aws_subnet.public[count.index % length(aws_subnet.public)].id
  vpc_security_group_ids = [aws_security_group.node.id]
  iam_instance_profile   = aws_iam_instance_profile.node.name
  key_name               = var.ssh_key_name != "" ? var.ssh_key_name : null

  root_block_device {
    volume_size = var.server_root_volume_gb
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/templates/agent-user-data.sh.tpl", {
    server_ip   = aws_instance.server.private_ip
    k3s_token   = random_password.k3s_token.result
    k3s_version = local.k3s_version
    index       = count.index
  })

  tags = { Name = "retailvision-${var.environment}-agent-${count.index}" }
}
