output "server_public_ip" {
  description = "Elastic IP of the k3s server — point app_host/eep_host DNS here."
  value       = aws_eip.server.public_ip
}

output "server_instance_id" {
  description = "EC2 instance ID of the k3s server (use for SSM: aws ssm start-session)."
  value       = aws_instance.server.id
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

output "app_host" {
  description = "Public hostname for the SPA/API (nip.io off the EIP unless overridden)."
  value       = local.app_host
}

output "eep_host" {
  description = "Public hostname edge devices dial for gRPC."
  value       = local.eep_host
}

output "helm_install_hint" {
  description = "Ready-to-run helm install for this cluster."
  value       = "helm upgrade --install retailvision ./charts/retailvision -f charts/retailvision/values.production.yaml --set global.imageRegistry=ghcr.io/salman-719/retailvision --set ingress.appHost=${local.app_host} --set eep.grpcHost=${local.eep_host} --set s3.bucket=${var.s3_bucket_name} --set s3.region=${var.aws_region} -n retailvision --create-namespace"
}
