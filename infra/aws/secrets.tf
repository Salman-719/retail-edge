# AWS Secrets Manager entries consumed by the chart via External Secrets.
# Passwords are generated here (special=false keeps them safe inside DB/Redis URLs).
# Values are set once; lifecycle ignore_changes lets you rotate them out-of-band.

resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "random_password" "jwt" {
  length  = 48
  special = false
}

resource "random_password" "agent" {
  length  = 48
  special = false
}

resource "random_password" "redis" {
  length  = 32
  special = false
}

locals {
  secret_values = {
    postgres_password = random_password.postgres.result
    redis_password    = random_password.redis.result
    jwt_secret        = random_password.jwt.result
    agent_secret      = random_password.agent.result
    # In-cluster Redis (TLS) — no auth configured in redis.conf.
    redis_url     = "rediss://redis-server:6380"
    s3_access_key = aws_iam_access_key.s3.id
    s3_secret_key = aws_iam_access_key.s3.secret
  }
}

resource "aws_secretsmanager_secret" "this" {
  for_each = var.secret_names
  name     = each.value
}

resource "aws_secretsmanager_secret_version" "this" {
  for_each      = var.secret_names
  secret_id     = aws_secretsmanager_secret.this[each.key].id
  secret_string = local.secret_values[each.key]

  lifecycle {
    ignore_changes = [secret_string] # allow out-of-band rotation
  }
}

# Dedicated IAM user for EEP's S3 client. EEP requires explicit S3 keys
# (see services/eep/app/core/config.py), so we cannot rely on the node role here.
resource "aws_iam_user" "s3" {
  name = "retailvision-${var.environment}-s3"
}

data "aws_iam_policy_document" "s3_user" {
  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.objects.arn]
  }
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.objects.arn}/*"]
  }
}

resource "aws_iam_user_policy" "s3" {
  name   = "s3-access"
  user   = aws_iam_user.s3.name
  policy = data.aws_iam_policy_document.s3_user.json
}

resource "aws_iam_access_key" "s3" {
  user = aws_iam_user.s3.name
}
