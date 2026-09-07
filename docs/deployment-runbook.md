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

From this point the deployed nginx vhost is **certbot-managed** and has
diverged from `infra/nginx/monops.conf` (which stays HTTP-only). Never copy
the template over it -- see §7a for why and for how nginx changes are
actually applied. If TLS is ever clobbered anyway, recover with
`sudo certbot install --nginx --cert-name mikejennings.dev`.

Confirm in a browser: `https://mikejennings.dev/monops` should load with a
valid padlock and the actual Streamlit UI -- not a "Please wait..." spinner
that never resolves, which is the classic symptom of a websocket or
baseUrlPath mismatch (see the plan doc's research notes if this happens).

## 7. Day-2 redeploys (after the first one)

The bootstrap script isn't a repeatable deploy mechanism by itself. To ship a
new commit to the running instance:

```
ssh -i ~/.ssh/monops_lightsail ubuntu@<static-ip>
sudo git config --global --add safe.directory /opt/monops
sudo git -C /opt/monops pull
sudo git -C /opt/monops rev-parse HEAD          # check this against the commit you expect
sudo systemctl restart monops
```

**Confirmed via a real redeploy, not assumed:** a plain `cd /opt/monops &&
git pull` (no `sudo`) fails with `fatal: detected dubious ownership in
repository at '/opt/monops'`. `infra/user_data.sh` clones the repo as root
during first boot, but a redeploy over SSH runs as `ubuntu` -- git's own
safe-directory check (added as a security guard in git >= 2.35) refuses to
operate on a repo it doesn't own unless told otherwise, and `ubuntu` likely
also doesn't have plain write permission on root-owned files regardless. The
`sudo git config --global --add safe.directory` line is a one-time fix (it
edits *root's* global gitconfig, since every command here already runs via
`sudo`) -- every redeploy after the first one only needs the `git pull`,
`rev-parse` check and `systemctl restart` lines. **A silent trap worth
knowing about:** if this step is skipped, `git pull` fails but `sudo
systemctl restart monops` still succeeds -- it just restarts the *old* code,
with no error surfaced anywhere that would tell you the deploy didn't
actually ship anything new. That is why the `rev-parse HEAD` check is in the
sequence: it is the only thing that actually confirms new code landed.

### 7a. What a `git pull` deploy does NOT touch

- **nginx config does not ship via `git pull`.** `infra/user_data.sh` copies
  `infra/nginx/monops.conf` into place exactly once, at first boot. After
  certbot runs (step 6) the deployed vhost is certbot-managed and has
  diverged from the repo template -- see that file's own header. To apply an
  nginx change (e.g. the 2026-09-07 rate-limit fix): hand-edit the deployed
  `/etc/nginx/sites-available/monops` on the instance to match the two
  changes the template now carries (the `/monops/static/` location, and
  `burst=100` on `/monops`), then `sudo nginx -t && sudo systemctl reload
  nginx`. Copying the template over the deployed file destroys TLS -- this
  happened 2026-09-06, took the site down with `ERR_CONNECTION_REFUSED`, and
  was recovered with `sudo certbot install --nginx --cert-name
  mikejennings.dev`.
- **The action-gate secret does not ship either.** It is minted once by the
  bootstrap into `/etc/monops.env` (root-only) and loaded by the
  `monops.service` unit via `EnvironmentFile=`. Read it with `sudo cat
  /etc/monops.env`; the value is what you paste into the UI sidebar's
  "Action secret" field to run any gated action. A `terraform apply` rebuild
  on a box that already has this file leaves it alone (the bootstrap never
  overwrites it).

### 7b. After a deploy that changes the case path

Warm the self-healing demo case so the first real visitor doesn't pay the
build cost (and so a stale `DEMO_FIXTURE_VERSION` rebuild happens now, not
under load):

```
curl -s http://127.0.0.1:8000/cases/demo/worksheet > /dev/null
```

## 8. Public-demo security posture (Workstream 2)

The public instance runs with two env vars set in `docker-compose.prod.yml`
(see that file's own comments for the exact values) -- both default to
"unlocked" when unset, which is also local dev's trust boundary, so neither
is a hard requirement to get the stack running:

- **`MONOPS_ACTION_SECRET`** -- gates starting a *new* run and all three
  enrichment steps (ownership, bibliometric, topic-similarity) behind a
  shared secret sent as the `X-Monops-Action-Secret` header. Viewing the
  pre-computed public-demo run, its scored table, evidence trail, rubric
  sliders, and exports all stay open regardless -- this gates *actions*, not
  read access (see `docs/plans/2026-09-02-remediation-pass.md`'s Workstream
  2 for the full reasoning on why site-wide auth was deliberately rejected).
  On a fresh instance the bootstrap now mints this into `/etc/monops.env` and
  the systemd unit loads it (see §7a) -- so a bootstrapped instance is gated
  by default. To rotate it, edit `/etc/monops.env` on the instance and
  `sudo systemctl restart monops`. **Never commit the real secret value to
  the repo.**
- **`MONOPS_DATA_FILE_ALLOWLIST`** -- restricts `nsf_file`/`opensanctions_file`/
  GLEIF file paths `POST /runs` and `POST /runs/{id}/ownership` will accept
  to the four bundled demo/sample fixtures (`docker-compose.prod.yml` sets
  this to their exact container paths). GLEIF/Section 117 files are
  deliberately not in the allowlist -- those routes always reject on the
  public deployment, matching the sidebar's own "leave blank to skip"
  framing for files that were never bundled in the first place.

Two additional hygiene measures, not access control (nothing stops a
scraper that simply ignores them):

- `infra/nginx/monops.conf` returns `X-Robots-Tag: noindex, nofollow` on the
  `/monops` location (verify with `curl -sI https://mikejennings.dev/monops/`).
- `infra/user_data.sh` lays down `/var/www/monops-placeholder/robots.txt`
  disallowing `/monops/` (`curl https://mikejennings.dev/robots.txt`).

The actual defence against request volume is `infra/nginx/monops.conf`'s
rate limit (`limit_req_zone`, 5 req/s per client IP, burst 100), which
exempts Streamlit's websocket upgrade requests so the live UI doesn't
stutter under its own budget, and does not rate-limit `/monops/static/` at
all -- a fresh Streamlit page pulls ~150 lazily-imported frontend chunks in
one burst, and the original burst of 20 rejected the excess with 503,
breaking the site for every cold-cache visitor (found 2026-09-07, after
days unnoticed because a warm cache never hits the limit). Every expensive
operation is behind the action secret regardless.

## 9. Housekeeping (Section 9's remaining asks)

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
