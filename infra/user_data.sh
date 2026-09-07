#!/bin/bash
# Cloud-init bootstrap for the Monops Lightsail instance. Runs once, as root,
# on first boot. Idempotent-ish (safe-ish to re-run manually via SSH if a
# step needs redoing), but not designed as a repeatable deploy mechanism --
# see docs/deployment-runbook.md for how day-2 redeploys actually happen
# (SSH in, git pull, `sudo systemctl restart monops`).
#
# Confirmed via a real deployment, not assumed: Lightsail always prepends its
# own SSH-CA bootstrap snippet (its own "#!/bin/sh" shebang) ahead of whatever
# user_data is supplied here, so this script actually starts execution under
# /bin/sh (dash) regardless of the shebang above -- that shebang only takes
# effect if this file is ever run standalone. Re-exec under bash immediately,
# in POSIX sh-compatible syntax (this line has to run correctly under dash
# first), so the bash-only syntax below (process substitution, `pipefail`)
# actually works. Side effect, accepted as harmless: Lightsail's own prepended
# preamble re-runs a second time under bash after this re-exec -- it only
# overwrites a public-key file with the same content, appends one already-
# duplicate-tolerant sshd_config line again, and restarts sshd again.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -euxo pipefail
exec > >(tee -a /var/log/monops-bootstrap.log) 2>&1
echo "Monops bootstrap starting: $(date -u)"

REPO_URL="https://github.com/jenningsmt/entity-screening-toolkit.git"
APP_DIR="/opt/monops"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git nginx certbot python3-certbot-nginx openssl

# --- Docker Engine + Compose plugin, from Docker's own apt repo -----------
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker

# --- App code ---------------------------------------------------------------
git clone --depth 1 "$REPO_URL" "$APP_DIR"

# --- Placeholder page at the apex, Monops itself lives at /monops ----------
mkdir -p /var/www/monops-placeholder
cp "$APP_DIR/infra/placeholder/index.html" /var/www/monops-placeholder/index.html
if [ -f "$APP_DIR/assets/monops-logo.png" ]; then
    cp "$APP_DIR/assets/monops-logo.png" /var/www/monops-placeholder/monops-logo.png
fi
# Workstream 2e: keep the demo out of search indexes and casual scrapers.
# Host-wide by nature (one robots.txt per origin) -- revisit this, not add a
# second one, if a real site ever lands at the apex. Hygiene only, not
# access control; infra/nginx/monops.conf's rate limit is the actual defence
# against volume.
printf 'User-agent: *\nDisallow: /monops/\n' > /var/www/monops-placeholder/robots.txt

# --- nginx -------------------------------------------------------------------
# HTTP-only for now -- `sudo certbot --nginx -d mikejennings.dev` (a manual,
# later step, once DNS actually points here) edits this file in place to add
# TLS. Don't hand-add a 443 block before that.
cp "$APP_DIR/infra/nginx/monops.conf" /etc/nginx/sites-available/monops
ln -sf /etc/nginx/sites-available/monops /etc/nginx/sites-enabled/monops
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# --- Action-gate secret ----------------------------------------------------
# docker-compose.prod.yml reads MONOPS_ACTION_SECRET=${MONOPS_ACTION_SECRET:-}
# from the environment compose is invoked in. The monops.service unit below
# passes NO environment, so without this it resolves to empty -- and
# api/main.py:_require_action_secret documents that an unset secret means
# *every action is unlocked*. It fails open and it fails silently (only
# /health's action_gate_enabled would ever hint at it). So the bootstrap
# mints one and hands it to the unit via EnvironmentFile.
#
# Never overwritten: a manual re-run of this script on a box that already has
# /etc/monops.env must not rotate the operator's secret out from under them.
# `set +x` around the write so the secret never lands in the bootstrap log
# (which is tee'd to /var/log/monops-bootstrap.log); the path is echoed at
# the end, the value never is.
set +x
if [ ! -f /etc/monops.env ]; then
    monops_secret="$(openssl rand -hex 24)"
    [ -n "$monops_secret" ] || { echo "FATAL: could not generate MONOPS_ACTION_SECRET" >&2; exit 1; }
    ( umask 077; printf 'MONOPS_ACTION_SECRET=%s\n' "$monops_secret" > /etc/monops.env )
    unset monops_secret
    chown root:root /etc/monops.env
    chmod 600 /etc/monops.env
fi
set -x

# --- App stack, wrapped in a systemd unit so it survives a crash/reboot ----
# (on top of docker-compose.prod.yml's own `restart: unless-stopped` --
# belt and suspenders, and matches docs/requirements.md Section 9's explicit
# "systemd unit, Restart=always" ask.)
cat > /etc/systemd/system/monops.service <<'UNIT'
[Unit]
Description=Monops docker compose stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
WorkingDirectory=/opt/monops
# Supplies MONOPS_ACTION_SECRET (written above, root-only) into compose's
# environment, so docker-compose.prod.yml's ${MONOPS_ACTION_SECRET:-}
# resolves to the real value instead of empty. Without this the public
# instance boots with the action gate open.
EnvironmentFile=/etc/monops.env
ExecStart=/bin/bash -c 'cd /opt/monops && GIT_COMMIT=$(git rev-parse HEAD) docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build'
ExecStop=/usr/bin/docker compose -f /opt/monops/docker-compose.yml -f /opt/monops/docker-compose.prod.yml down

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now monops.service

echo "Monops bootstrap complete: $(date -u)"
echo "Action-gate secret written to /etc/monops.env (root-only). Read it with: sudo cat /etc/monops.env -- it is required in the UI sidebar to use any gated action."
