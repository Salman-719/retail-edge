# Node IAM role. In-cluster controllers (EBS CSI, External Secrets) and EEP's S3
# client all use the instance-profile credential chain — no static keys, no IRSA
# (which would require EKS).
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "retailvision-${var.environment}-node"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Managed policy for the EBS CSI driver (create/attach/detach volumes & snapshots).
resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

# Allow SSM Session Manager access (SSH-less administration).
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "node_inline" {
  # Object storage: full access to the project bucket only.
  statement {
    sid       = "S3Bucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.objects.arn]
  }
  statement {
    sid       = "S3Objects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.objects.arn}/*"]
  }
  # Secrets Manager: read only the project's secrets.
  statement {
    sid       = "SecretsRead"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:retailvision/*"]
  }
}

resource "aws_iam_role_policy" "node_inline" {
  name   = "retailvision-${var.environment}-node-inline"
  role   = aws_iam_role.node.id
  policy = data.aws_iam_policy_document.node_inline.json
}

resource "aws_iam_instance_profile" "node" {
  name = "retailvision-${var.environment}-node"
  role = aws_iam_role.node.name
}
