output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = module.eks.cluster_endpoint
}

output "update_kubeconfig" {
  description = "Command to configure kubectl for this cluster."
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region}"
}

output "ingress_eip" {
  description = "Primary ingress NLB Elastic IP — app_host resolves here (nip.io)."
  value       = aws_eip.ingress[0].public_ip
}

output "ingress_eip_allocation_ids" {
  description = "EIP allocation IDs bound to the ingress NLB."
  value       = aws_eip.ingress[*].id
}

output "grpc_eip" {
  description = "Primary EEP gRPC NLB Elastic IP — eep_host resolves here (nip.io)."
  value       = aws_eip.grpc[0].public_ip
}

output "grpc_eip_allocation_ids" {
  description = "EIP allocation IDs bound to the EEP gRPC NLB."
  value       = aws_eip.grpc[*].id
}

output "public_subnet_ids" {
  description = "Public subnet IDs used by EKS nodes and internet-facing NLBs."
  value       = module.vpc.public_subnets
}

output "vpc_cidr" {
  description = "VPC CIDR routed through WireGuard from enrolled edge devices."
  value       = var.vpc_cidr
}

output "wireguard_instance_id" {
  description = "SSM-managed WireGuard gateway instance ID."
  value       = var.wireguard_enabled ? aws_instance.wireguard[0].id : null
}

output "wireguard_public_ip" {
  description = "Public WireGuard endpoint address."
  value       = var.wireguard_enabled ? aws_eip.wireguard[0].public_ip : null
}

output "wireguard_endpoint" {
  description = "WireGuard endpoint in host:port form."
  value       = var.wireguard_enabled ? "${aws_eip.wireguard[0].public_ip}:${var.wireguard_port}" : null
}

output "wireguard_tunnel_cidr" {
  description = "Overlay CIDR assigned to enrolled edge devices."
  value       = var.wireguard_enabled ? var.wireguard_tunnel_cidr : null
}

output "app_host" {
  description = "Public hostname for the SPA/API."
  value       = local.app_host
}

output "eep_host" {
  description = "Public hostname edge devices dial for gRPC."
  value       = local.eep_host
}

output "s3_bucket" {
  description = "Object-storage bucket name."
  value       = aws_s3_bucket.objects.id
}

output "agent_secret" {
  description = "Shared secret for edge agents — pass to bootstrap-edge-k3s.sh."
  value       = random_password.agent.result
  sensitive   = true
}

output "helm_install_hint" {
  description = "Ready-to-run helm install for this cluster (run after update-kubeconfig)."
  value       = <<-EOT
    helm upgrade --install retailvision ./charts/retailvision \
      -f charts/retailvision/values.production.yaml \
      --set global.imageRegistry=ghcr.io/salman-719/retailvision \
      --set ingress.appHost=${local.app_host} \
      --set eep.grpcHost=${local.eep_host} \
      --set eep.grpc.serviceType=LoadBalancer \
      --set-string 'eep.grpc.serviceAnnotations.service\.beta\.kubernetes\.io/aws-load-balancer-type=external' \
      --set-string 'eep.grpc.serviceAnnotations.service\.beta\.kubernetes\.io/aws-load-balancer-nlb-target-type=ip' \
      --set-string 'eep.grpc.serviceAnnotations.service\.beta\.kubernetes\.io/aws-load-balancer-scheme=internet-facing' \
      --set-string 'eep.grpc.serviceAnnotations.service\.beta\.kubernetes\.io/aws-load-balancer-eip-allocations=${join("\\,", aws_eip.grpc[*].id)}' \
      --set-string 'eep.grpc.serviceAnnotations.service\.beta\.kubernetes\.io/aws-load-balancer-subnets=${join("\\,", module.vpc.public_subnets)}' \
      --set-string 'postgres.service.annotations.service\.beta\.kubernetes\.io/aws-load-balancer-subnets=${join("\\,", module.vpc.public_subnets)}' \
      --set-string 'redis.service.annotations.service\.beta\.kubernetes\.io/aws-load-balancer-subnets=${join("\\,", module.vpc.public_subnets)}' \
      --set-string 'postgres.service.loadBalancerSourceRanges[0]=${var.vpc_cidr}' \
      --set-string 'redis.service.loadBalancerSourceRanges[0]=${var.vpc_cidr}' \
      --set s3.bucket=${var.s3_bucket_name} --set s3.region=${var.aws_region} \
      --set monitoring.grafana.host=grafana.${local.ingress_ip}.nip.io \
      --set mlflow.host=mlflow.${local.ingress_ip}.nip.io \
      -n retailvision --create-namespace
  EOT
}
