output "static_ip_address" {
  description = "Public static IP of the Monops Lightsail instance."
  value       = aws_lightsail_static_ip.app.ip_address
}

output "ssh_command" {
  description = "Ready-to-paste SSH command (note: unlike Terraform's file(), your shell DOES expand a leading ~ when you actually run this)."
  value       = "ssh -i ${trimsuffix(var.ssh_public_key_path, ".pub")} ubuntu@${aws_lightsail_static_ip.app.ip_address}"
}
