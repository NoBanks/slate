#!/usr/bin/env bash
# One-shot setup for a fresh Vultr VX1 Ubuntu 24.04 instance. Run as root.
#   bash setup_vm.sh <domain> <vendor-domain-suffix>
#   e.g. bash setup_vm.sh slate.nohumannearby.com nohumannearby.com
set -euo pipefail
DOMAIN=${1:-slate.nohumannearby.com}
SUFFIX=${2:-nohumannearby.com}
APPUSER=slate

apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip git curl ufw debian-keyring debian-archive-keyring apt-transport-https

# Firewall: SSH + web only. The egress proxy port is never exposed.
ufw allow 22/tcp; ufw allow 80/tcp; ufw allow 443/tcp; ufw --force enable

# Caddy (automatic HTTPS)
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y && apt-get install -y caddy
cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN, slate-brightline.$SUFFIX, slate-lumen.$SUFFIX, slate-northfield.$SUFFIX {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
EOF
systemctl restart caddy

# App user with KVM access for microVMs
id $APPUSER >/dev/null 2>&1 || useradd -m -s /bin/bash $APPUSER
usermod -aG kvm $APPUSER || true
ls -l /dev/kvm || echo "WARNING: /dev/kvm missing"

# Code
sudo -u $APPUSER bash -lc '
  cd ~ && (test -d slate || git clone https://github.com/NoBanks/slate.git) && cd slate && git pull --ff-only
  python3 -m venv .venv && . .venv/bin/activate
  pip install -q -r requirements.txt playwright==1.58.0
  python -m playwright install chromium
  curl -fsSL https://install.microsandbox.dev | sh || true
'
sudo python3 -m venv /tmp/pwdeps && /tmp/pwdeps/bin/pip install -q playwright==1.58.0 && /tmp/pwdeps/bin/python -m playwright install-deps chromium

cat > /etc/systemd/system/slate.service <<EOF
[Unit]
Description=SLATE control plane
After=network-online.target

[Service]
User=$APPUSER
WorkingDirectory=/home/$APPUSER/slate
EnvironmentFile=/home/$APPUSER/slate/.env
Environment=PATH=/home/$APPUSER/.local/bin:/home/$APPUSER/slate/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/home/$APPUSER/slate/.venv/bin/uvicorn slate.app:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
echo "Setup done. Put .env in /home/$APPUSER/slate/.env, then: systemctl enable --now slate"
