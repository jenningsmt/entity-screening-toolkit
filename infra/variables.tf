variable "aws_region" {
  description = "AWS region to provision the Lightsail instance in."
  type        = string
  default     = "us-east-1"
}

variable "availability_zone" {
  description = "Availability zone within aws_region for the Lightsail instance."
  type        = string
  default     = "us-east-1a"
}

variable "project_name" {
  description = "Short name used to prefix Lightsail resource names."
  type        = string
  default     = "monops"
}

# CONFIRM LIVE before `terraform apply` -- see the note at the top of
# main.tf. Bundle/blueprint IDs are versioned by AWS and change over time
# (they've moved from generation "_1_0" to "_2_0" to "_3_0" over the
# product's life) -- the defaults below are a starting point to verify,
# not a guarantee.
variable "bundle_id" {
  description = "Lightsail bundle ID. Confirm with: aws lightsail get-bundles"
  type        = string
  default     = "small_3_0" # ~2GB RAM / 2 vCPU / 60GB SSD / 3TB xfer, ~$12/mo
}

variable "blueprint_id" {
  description = "Lightsail blueprint ID. Confirm with: aws lightsail get-blueprints"
  type        = string
  default     = "ubuntu_24_04"
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key to install on the instance. Generate it first -- see docs/deployment-runbook.md, step 2."
  type        = string
  default     = "~/.ssh/monops_lightsail.pub"
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to SSH in on port 22. Default is wide open (key-only auth -- password auth is disabled by default on Lightsail's Ubuntu images); narrow to your own IP/32 for a quick, easy hardening step if you'd rather not leave 22 open to the world."
  type        = string
  default     = "0.0.0.0/0"
}
