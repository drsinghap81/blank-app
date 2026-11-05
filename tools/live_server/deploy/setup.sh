#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 AWS Lightsail / EC2 box in ap-south-1 (Mumbai) with a STATIC IP attached.
#   curl -fsSL https://raw.githubusercontent.com/drsinghap81/blank-app/main/tools/live_server/deploy/setup.sh | sudo bash
# Then: sudo nano /opt/trenddesk/.env  (fill in), sudo systemctl restart trenddesk
set -euo pipefail
APP=/opt/trenddesk
apt-get update -q && apt-get install -yq python3-venv python3-pip git debian-keyring debian-archive-keyring apt-transport-https curl ufw
# code (public repo; no secrets in it)
if [ ! -d $APP/repo ]; then git clone -q --depth 1 https://github.com/drsinghap81/blank-app.git $APP/repo; else git -C $APP/repo pull -q; fi
python3 -m venv $APP/venv
$APP/venv/bin/pip install -q -r $APP/repo/tools/live_server/requirements.txt
mkdir -p $APP/var
[ -f $APP/.env ] || cp $APP/repo/tools/live_server/.env.example $APP/.env
chmod 600 $APP/.env
id trenddesk >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin trenddesk
chown -R trenddesk $APP/var; chown trenddesk $APP/.env
cp $APP/repo/tools/live_server/deploy/trenddesk.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now trenddesk
# HTTPS with Caddy: hostname = <your-ip-with-dashes>.sslip.io unless you have a domain
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -yq caddy
fi
IP=$(curl -s https://api.ipify.org); HOST=${HOST:-$(echo $IP | tr . -).sslip.io}
cat > /etc/caddy/Caddyfile <<EOF
$HOST {
  reverse_proxy 127.0.0.1:8000
}
EOF
systemctl reload caddy || systemctl restart caddy
ufw allow 22/tcp; ufw allow 80/tcp; ufw allow 443/tcp; ufw --force enable
# daily code update at 08:00 IST (02:30 UTC)
echo "30 2 * * 1-5 root git -C $APP/repo pull -q && systemctl restart trenddesk" > /etc/cron.d/trenddesk-update
echo
echo "Server address for the phone app:  https://$HOST"
echo "Static IP to register in SmartAPI:  $IP"
echo "Next: sudo nano $APP/.env  then  sudo systemctl restart trenddesk"
