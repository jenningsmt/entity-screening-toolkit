# Section 9 Deployment -- Lightsail via Terraform for Monops

## Context

`docs/requirements.md` Section 9/9a already made the real decisions here: AWS
Lightsail, the ~$12/mo 2GB bundle, a 6-month hosting term, nginx + systemd +
Certbot, provisioned as infrastructure-as-code rather than through the
console. Since that section was written, the domain `mikejennings.dev` has
been registered, the project has been named **Monops**, and -- the one real
deviation from the original doc -- the demo will live at
**`mikejennings.dev/monops`** (a path) rather than a subdomain. Nothing else
is hosted at the apex domain yet, which is what makes the path approach
workable: nginx on the one Lightsail box serves a placeholder at `/` and
proxies `/monops` to the app, leaving room to replace `/` with a real
portfolio site later without touching the app.

This plan turns that into infrastructure code and a runbook, following this
repo's own established practice of a reviewed plan doc before a non-trivial
piece gets built.

## Correction (same day): CDKTF was the wrong tool

Section 9a specified CDKTF (Python bindings) "so the whole project stays in
Python rather than introducing HCL as a second language," and the first pass
of this plan and its implementation followed that -- an `infra/main.py` CDKTF
stack was written, reviewed, and reported as done. It was wrong: **HashiCorp
archived CDKTF (Terraform CDK) on December 10, 2025** -- "did not find
product-market fit at scale," no further features or fixes, repository
archived, with their own guidance to migrate to plain Terraform/HCL. That's
three months of dead-tool status before this plan was even written, and it
was missed during the original research pass, which verified the *shape* of
the CDKTF Python API (module names, construct patterns) without separately
checking whether the project itself was still alive -- a real gap, caught by
Mike, not by re-reading my own prior work.

**Consequence:** `infra/main.py`, `infra/cdktf.json`, and
`infra/requirements.txt` were deleted and replaced with plain Terraform HCL
(`infra/versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`) -- same
resources, same design decisions (own-generated SSH key rather than
AWS-generated, config values as plain variables rather than buried in
constructs, bundle/blueprint IDs flagged as needing live confirmation), just
expressed directly in HCL instead of through a now-unmaintained translation
layer. `infra/user_data.sh`, `infra/nginx/monops.conf`, and
`infra/placeholder/index.html` are untouched -- none of that was
CDKTF-specific. The methodology lesson, for whatever this project's own
"how Claude's first pass needed correcting" write-up eventually says about
it: verifying that a library's *API* is current is not the same check as
verifying the library itself hasn't been sunset, and both are needed before
building on anything.

## Research findings (confirmed directly this session, not assumed)

- **CDKTF's December 10, 2025 archival**, confirmed via HashiCorp's own
  `hashicorp/terraform-cdk` GitHub repo and independent coverage -- see the
  Correction section above.
- Current `aws_lightsail_instance` Terraform schema and its companion
  resources (`aws_lightsail_static_ip`, `_static_ip_attachment`,
  `_instance_public_ports`, `_key_pair`) -- via the HashiCorp AWS provider
  docs and a February 2026 walkthrough. Bundle IDs are versioned by AWS and
  do change over time (currently generation `_3_0`, e.g. `small_3_0`), so
  `infra/variables.tf` flags `bundle_id`/`blueprint_id` as needing live
  confirmation via `aws lightsail get-bundles` / `get-blueprints` before
  every first deploy, rather than trusting a hardcoded guess -- the same
  "re-verify at implementation time" discipline already used for the VSS
  topic-similarity corpora. (This part of the research held up fine even
  after the CDKTF correction -- it's the same underlying Terraform provider
  schema either way.)
- Streamlit's `STREAMLIT_SERVER_BASE_URL_PATH` environment variable has an
  **open, unconfirmed upstream report** of not taking effect when set via
  `docker run -e` / compose `environment:` (streamlit/streamlit#11509) --
  checked the issue directly rather than assuming from the title alone:
  Streamlit's own maintainers have so far been unable to reproduce it, so
  this is a real but unresolved report, not a confirmed bug. The
  `--server.baseUrlPath` CLI flag is used instead regardless, applied via a
  `command:` override in `docker-compose.prod.yml` rather than baked into
  the shared `Dockerfile.streamlit` (which would break local dev at `/`) --
  it's the more direct, unambiguous mechanism either way, not a workaround
  for a bug this plan is certain exists.
- The correct nginx pattern for proxying Streamlit's websocket connection
  under a sub-path uses a `map $http_upgrade $connection_upgrade { ... }`
  block, so the `Connection` header is set correctly for both the websocket
  upgrade and plain HTTP requests. A naive copy of the first blog example
  found while researching this sets `Connection` to two different values in
  the same location block -- nginx keeps only the last one, which would
  silently and permanently break Streamlit's live-reactivity channel behind
  the proxy while normal page loads kept working, exactly the kind of bug
  that's easy to ship and only notice much later.

## Design

New files, all under the repo root (`entity-screening-toolkit-portfolio`):

- **`infra/versions.tf`, `infra/variables.tf`, `infra/main.tf`,
  `infra/outputs.tf`** -- plain Terraform HCL: the AWS provider block,
  `aws_lightsail_key_pair` (fed our own locally-generated public key via
  `file(pathexpand(...))`, so the private key never touches Terraform
  state), `aws_lightsail_instance` (its `user_data` is
  `infra/user_data.sh`'s contents via `file()`), `aws_lightsail_static_ip` +
  attachment, `aws_lightsail_instance_public_ports` (22/80/443), and
  `output`s for the static IP and a ready-to-paste SSH command. Config
  values (region, AZ, bundle/blueprint ID, SSH key path, allowed SSH CIDR)
  are `variable` blocks with defaults in `variables.tf`, overridable at
  `terraform apply` time with `-var=...` without editing the file --
  specifically so they're easy to review and change.
- **`infra/user_data.sh`** -- the cloud-init bootstrap that runs once, as
  root, on first boot: installs Docker + the compose plugin (from Docker's
  own apt repo, not the older/staler distro package), nginx, and certbot;
  clones the public GitHub repo to `/opt/monops`; installs the nginx site
  config and placeholder page; brings the app stack up via
  `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
  --build`; and installs a small `monops.service` systemd unit wrapping that
  command (`Restart=on-failure`), on top of compose's own
  `restart: unless-stopped` -- belt and suspenders, and a literal match for
  Section 9's "systemd unit, Restart=always" language. Certbot is installed
  here but deliberately **not run** here -- it needs DNS actually pointed at
  the box first, so that's a manual runbook step, not part of first boot.
- **`infra/nginx/monops.conf`** -- the HTTP-only vhost for
  `mikejennings.dev`: `location /` serves the static placeholder,
  `location /monops` reverse-proxies to `127.0.0.1:8501` using the
  `map`-based websocket handling described above. Certbot's `--nginx` run
  later edits this file in place to add the TLS server block and an
  80-to-443 redirect.
- **`infra/placeholder/index.html`** -- a minimal dark-themed "the rest of
  this domain is coming soon, here's the live demo" page, reusing the
  project's own logo (`Project Monops Logo.jpeg`, already in the repo).
- **`docker-compose.prod.yml`** -- an override file, not edits to the
  existing `docker-compose.yml`, so local dev (`docker compose up` at the
  repo root, serving Streamlit at `/`) is completely untouched. It binds
  both services' ports to `127.0.0.1` only (nginx is the sole public entry
  point), adds `restart: unless-stopped`, and overrides the streamlit
  container's `command` to add `--server.baseUrlPath=monops`.
  **Review fix:** `ports:` needs the `!override` merge-type tag on both
  services -- Compose's default merge behavior for list-valued keys like
  `ports` concatenates values across `-f` files rather than replacing them
  (confirmed against Docker's own compose-file merge docs, not assumed), and
  the base file's unqualified `"8000:8000"`/`"8501:8501"` (implicit
  `0.0.0.0`) don't match this override's `127.0.0.1`-qualified entries on
  `{ip, target, published, protocol}`, so without `!override` both bindings
  would coexist and the containers would stay bound to `0.0.0.0` despite
  this file's own stated intent -- today's actual exposure is still blocked
  by `infra/main.tf`'s Lightsail firewall never opening 8000/8501, but that
  compensating control shouldn't be the only thing making the claim true.
- **`.gitignore`** additions for `infra/.terraform/` and
  `infra/terraform.tfstate*` -- Terraform's local provider-plugin cache and
  state never belong in git. `infra/.terraform.lock.hcl` (the dependency
  lock file `terraform init` generates) is the deliberate exception and
  should be committed once it exists, so a future re-provision uses the
  exact provider version that was actually verified to work. The SSH key
  itself is never written into the repo at all; `infra/main.tf` reads it
  from `~/.ssh/monops_lightsail*`, outside the repo entirely.
- **`docs/deployment-runbook.md`** -- the actual step-by-step commands,
  kept as living ops documentation (not a historical plan record like this
  file): local prerequisites, confirming live bundle/blueprint IDs,
  generating the SSH key, `terraform init/plan/apply`, the manual DNS step
  (the registrar, not Route 53 -- see below), the manual certbot step, and
  the Section 9 housekeeping items (budget alert, calendar reminder, demo
  recording).
- A short factual addendum to `docs/requirements.md` Section 9, and a status
  update to `README.md` -- recording the finalized name/domain/path/tooling
  decisions without rewriting Section 9's original rationale.

**Deliberately not automated:** DNS. `mikejennings.dev`'s DNS is at the
registrar, not Route 53, so there's no `aws_route53_record` -- the runbook
just has a one-line manual step (create an A record for the apex, pointed at
the static IP Terraform outputs). Automating a provider we're not actually
using would be dead code.

**Deliberately not run from this session:** `terraform apply` itself. AWS
credentials should never pass through a chat session, so the runbook has
Mike run the deploy commands himself, in his own terminal, against his own
`aws configure`. Separately, the sandboxed bridge this session can reach on
his machine has no Terraform, AWS CLI, or Docker installed, and
unknown/likely-restricted internet egress -- not a reliable place to run
infrastructure-provisioning commands even setting the credentials question
aside.

## Status

**Live.** `terraform apply` succeeded and Monops is running in production at
`https://mikejennings.dev/monops` as of 2026-09-02, verified end-to-end in a
real browser (TLS padlock, real Streamlit UI, screening/bibliometric/topic-
similarity all rendering against a real run).

Getting there surfaced five real bugs, none of which were anticipated by the
plan above -- documenting the deviations here rather than quietly rewriting
the plan to look like it was right the first time:

1. **Lightsail always prepends its own `#!/bin/sh` bootstrap snippet ahead of
   any `user_data` you supply**, so a script's own `#!/bin/bash` shebang is
   inert -- the combined file runs under `dash`, which chokes on bash-only
   syntax (`pipefail`, process substitution). This is real, confirmed
   Lightsail behavior, not plain EC2 user-data handling. Fixed in
   `infra/user_data.sh` by re-execing under bash as the first thing the
   script's own content does, in POSIX-sh-safe syntax.
2. **Replacing an `aws_lightsail_instance` in one `terraform apply` does not
   automatically also recreate dependent resources that reference it by
   name** (`aws_lightsail_static_ip_attachment`,
   `aws_lightsail_instance_public_ports`) -- Terraform's refresh happens
   before the destroy within the same apply, so it doesn't see the AWS-side
   breakage until a *second* plan/apply. Confirmed by directly querying
   `aws lightsail get-static-ip`/`get-instance` after the first replace and
   seeing `isAttached: false`. Fix is just running plan/apply a second time,
   but it's a real gotcha for any future instance replacement.
3. **Docker Compose's `ports:` merge behavior concatenates across `-f`
   files by default, it doesn't replace** -- `docker-compose.prod.yml`
   needed the `!override` YAML tag to actually confine ports to
   `127.0.0.1`. Verified on the live instance (`docker compose ps` shows
   `127.0.0.1:8000->8000` / `127.0.0.1:8501->8501`, not `0.0.0.0`).
4. **Streamlit's own "add trailing slash" redirect uses the protocol it
   thinks it's running under (plain HTTP inside Docker), not the
   client-facing protocol** -- behind TLS this downgraded
   `https://.../monops` to an `http://` redirect target. Fixed with an
   nginx-level exact-match `location = /monops` block that issues the
   redirect itself using nginx's own (always-correct) `$scheme`, in
   `infra/nginx/monops.conf`.
5. **There is no AWS-managed IAM policy for full Lightsail access** (no
   `AmazonLightsailFullAccess` -- that was an assumption from memory, and it
   was wrong). Fixed with a small custom policy (`lightsail:*` on `*`),
   documented in `docs/deployment-runbook.md`.

Still outstanding, from Step 8 of `docs/deployment-runbook.md`: the AWS
Budget alert (~$72 ceiling), a calendar reminder for the 6-month
renew-or-retire decision (~mid-Feb 2027), and a demo recording for the top
of the README.
