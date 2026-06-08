# Public hostnames. No-domain mode derives app.<ingress-eip>.nip.io and
# eep.<grpc-eip>.nip.io. Override by setting app_host / eep_host (and optionally
# create_dns_records for Route53).
locals {
  ingress_ip = aws_eip.ingress[0].public_ip
  grpc_ip    = aws_eip.grpc[0].public_ip
  app_host   = var.app_host != "" ? var.app_host : "app.${local.ingress_ip}.nip.io"
  eep_host   = var.eep_host != "" ? var.eep_host : "eep.${local.grpc_ip}.nip.io"
}

resource "aws_route53_record" "app" {
  count   = var.create_dns_records ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.app_host
  type    = "A"
  ttl     = 300
  records = [local.ingress_ip]
}

resource "aws_route53_record" "eep" {
  count   = var.create_dns_records ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.eep_host
  type    = "A"
  ttl     = 300
  records = [local.grpc_ip]
}
