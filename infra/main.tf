# Provisions the AWS Lightsail instance behind Monops' public demo at
# mikejennings.dev/monops.
#
# See docs/deployment-runbook.md for how to actually run this, and
# docs/plans/2026-09-02-lightsail-deployment.md for why these choices were
# made. That plan was originally written for CDKTF (Python bindings) per
# docs/requirements.md Section 9a -- corrected to plain Terraform/HCL after
# discovering HashiCorp archived CDKTF on December 10, 2025. See the plan
# doc's correction note for the full story.
#
# IMPORTANT -- confirm var.bundle_id / var.blueprint_id are still current
# before your first `terraform apply` (see variables.tf).

resource "aws_lightsail_key_pair" "ssh_key" {
  name       = "${var.project_name}-key"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_lightsail_instance" "app" {
  name              = "${var.project_name}-instance"
  availability_zone = var.availability_zone
  blueprint_id      = var.blueprint_id
  bundle_id         = var.bundle_id
  key_pair_name     = aws_lightsail_key_pair.ssh_key.name
  user_data         = file("${path.module}/user_data.sh")

  tags = {
    Project = var.project_name
  }
}

resource "aws_lightsail_static_ip" "app" {
  name = "${var.project_name}-ip"
}

resource "aws_lightsail_static_ip_attachment" "app" {
  static_ip_name = aws_lightsail_static_ip.app.name
  instance_name  = aws_lightsail_instance.app.name
}

# Hobby box: 22 is open by default (key-only auth); 80/443 are the actual
# public surface, fronted by nginx on the instance itself (infra/user_data.sh,
# infra/nginx/monops.conf). The FastAPI service never appears here at all --
# it's reachable only over the instance's internal Docker network.
resource "aws_lightsail_instance_public_ports" "app" {
  instance_name = aws_lightsail_instance.app.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = [var.allowed_ssh_cidr]
  }

  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80
    cidrs     = ["0.0.0.0/0"]
  }

  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
    cidrs     = ["0.0.0.0/0"]
  }
}
