# Optional Route53 records. Enable with create_dns_records = true and a zone id.
resource "aws_route53_record" "app" {
  count   = var.create_dns_records ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.app_host
  type    = "A"
  ttl     = 300
  records = [aws_eip.server.public_ip]
}

resource "aws_route53_record" "eep" {
  count   = var.create_dns_records ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.eep_host
  type    = "A"
  ttl     = 300
  records = [aws_eip.server.public_ip]
}
