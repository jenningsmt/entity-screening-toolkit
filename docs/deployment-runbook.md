# Deployment Runbook: Monops on AWS Lightsail

Living operational doc -- unlike `docs/plans/`, this gets updated in place as
the real process changes. See `docs/plans/2026-09-02-lightsail-deployment.md`
for why these choices were made (originally CDKTF, corrected to plain
Terraform/HCL after discovering CDKTF was archived by HashiCorp in December
2025 -- see that doc's correction note).

**Run all of this yourself, in a normal terminal on your own machine** (not
through any AI session's shell) -- it's the only place your AWS credentials
should ever be typed.

## 0. Prerequisites

- [Terraform CLI](https://developer.hashicorp.com/terraform/install) (>= 1.5).
  No Node.js or any other toolchain is needed for `infra/` -- it's plain HCL.
- AWS CLI v2, then `aws configure` with an IAM user/role that has Lightsail
  permissions (and Budgets, for step 8's cost alert). Verify with
  `aws sts get-caller-identity`.
- Docker is **not** needed on your machine for this -- it only needs to be on
  the Lightsail instance itself, which `infra/user_data.sh` installs
  automatically at first boot.

## 1. Confirm live bundle and blueprint IDs

`infra/variables.tf`'s `bundle_id` default (`small_3_0`) and `blueprint_id`
default (`ubuntu_24_04`) are researched-current-as-of-Sept-2026 defaults, not
guarantees -- AWS has changed Lightsail's bundle-ID generation before
(`_1_0` -> `_2_0` -> `_3_0`). Confirm before you deploy:

```
aws lightsail get-bundles --query "bundles[?ramSizeInGb==\`2\`].{id:bundleId,price:price}"
aws lightsail get-blueprints --query "blueprints[?contains(blueprintId,'ubuntu')].blueprintId"
```

If the live values differ, either edit the defaults in `infra/variables.tf`
directly, or override them at apply time without touching the file:

```
terraform apply -var="bundle_id=<confirmed-id>" -var="blueprint_id=<confirmed-id>"
```

## 2. Generate a dedicated SSH key

```
ssh-keygen -t ed25519 -f ~/.ssh/monops_lightsail -C monops-lightsail
```

No passphrase needed for a hobby box, your call. This key pair is never
committed to the repo -- `infra/main.tf` reads the `.pub` file from this path
at apply time and only the public half ever reaches AWS/Terraform state.

## 3. Deploy the infrastructure

```
cd infra
terraform init
terraform plan
terraform apply
```

Review the plan Terraform prints before typing `yes` to confirm. On success,
note the `static_ip_address` output -- you'll need it for steps 4 and 6.
`terraform init` creates `infra/.terraform.lock.hcl` the first time it runs;
commit that file (it pins the exact AWS provider version that was verified to
work) -- everything else `init`/`apply` create under `infra/.terraform/` and
`infra/terraform.tfstate*` is already gitignored.

## 4. Point DNS at the instance

`mikejennings.dev`'s DNS is at your registrar, not Route 53, so this is a
manual step: create an **A record** for the apex domain (`@` /
`mikejennings.dev`) pointing at the static IP from step 3. Propagation is
usually minutes, occasionally longer -- check with:

```
dig +short mikejennings.dev
```

## 5. Verify HTTP works

Before worrying about DNS or TLS at all:

```
curl -I http://<static-ip>/          # placeholder page, expect 200
curl -I http://<static-ip>/monops    # Streamlit, expect 200
```

If either fails, SSH in and check `/var/log/monops-bootstrap.log` first (the
full cloud-init bootstrap log), then `sudo systemctl status monops docker
nginx`.

## 6. Enable TLS

Once `dig` in step 4 resolves to your static IP:

```
ssh -i ~/.ssh/monops_lightsail ubuntu@<static-ip>
sudo certbot --nginx -d mikejennings.dev
```

Follow the prompts (it'll offer to redirect HTTP to HTTPS -- take it).
Certbot's own systemd timer (`certbot.timer`, installed with the package)
handles renewal automatically; no cron entry needed on current Ubuntu.

Confirm in a browser: `https://mikejennings.dev/monops` should load with a
valid padlock and the actual Streamlit UI -- not a "Please wait..." spinner
that never resolves, which is the classic symptom of a websocket or
baseUrlPath mismatch (see the plan doc's research notes if this happens).

## 7. Day-2 redeploys (after the first one)

The bootstrap script isn't a repeatable deploy mechanism by itself. To ship a
new commit to the running instance:

```
ssh -i ~/.ssh/monops_lightsail ubuntu@<static-ip>
cd /opt/monops && git pull
sudo systemctl restart monops
```

## 8. Housekeeping (Section 9's remaining asks)

- **AWS Budget alert:** set one at $72 (the 6-month initial commitment) in
  AWS Budgets. Reset it to $144 if you decide to renew at the 6-month mark.
- **Calendar reminder:** ~2 weeks before the 6-month mark from whenever
  `terraform apply` actually ran (not exactly on it) -- time to actually
  decide renew-or-retire and act on it before the next month's charge.
- **Demo recording:** a short GIF or 60-90s video of the running app for the
  top of `README.md` -- cheap insurance if the instance is ever paused,
  mid-patch, or retired after the hosting window while the GitHub repo lives
  on.

## Tearing down

```
cd infra
terraform destroy
```

Leaves the GitHub repo (no hosting cost or end date) as the permanent record,
per Section 9's own framing of the repo as the primary artifact and the
hosted demo as a convenience layer on top of it.
