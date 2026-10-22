#!/usr/bin/env bash
# Top Bottom bot — one-time setup on a fresh Ubuntu 24.04 server (AWS Lightsail Mumbai).
# Run:  curl -fsSL https://raw.githubusercontent.com/drsinghap81/blank-app/main/tools/angel/deploy/setup.sh | sudo bash
# Your keys are typed in here, saved only on this server (readable by the 'bot' user alone), never sent anywhere else.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Please run with sudo"; exit 1; }
TTY=/dev/tty
ask()  { local v; read -r -p "$1" v < $TTY; echo "$v"; }
asks() { local v; read -r -s -p "$1" v < $TTY; echo >&2; echo "$v"; }

echo "=== 1/5  Updating the server and installing tools (2-4 minutes) ==="
export DEBIAN_FRONTEND=noninteractive
timedatectl set-timezone Asia/Kolkata
apt-get update -y -q && apt-get upgrade -y -q
apt-get install -y -q python3-venv python3-pip git unattended-upgrades fail2ban ufw curl
dpkg-reconfigure -f noninteractive unattended-upgrades
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
# Angel whitelists your static IPv4 -> always prefer IPv4 for outgoing connections
grep -q '^precedence ::ffff:0:0/96 100' /etc/gai.conf || echo 'precedence ::ffff:0:0/96 100' >> /etc/gai.conf

echo "=== 2/5  Locking down the server ==="
ufw default deny incoming >/dev/null; ufw default allow outgoing >/dev/null; ufw allow OpenSSH >/dev/null; ufw --force enable >/dev/null
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/; s/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
systemctl enable --now fail2ban >/dev/null 2>&1 || true

echo "=== 3/5  Installing the bot ==="
id bot >/dev/null 2>&1 || useradd -m -s /bin/bash bot
sudo -u bot bash -s <<'BOT'
set -e
cd ~
if [ -d blank-app ]; then git -C blank-app pull -q --ff-only; else git clone -q https://github.com/drsinghap81/blank-app.git; fi
[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r blank-app/tools/angel/requirements.txt
BOT
A=/home/bot/blank-app/tools/angel

echo "=== 4/5  Your keys (typing is hidden for secrets) ==="
echo "Login style:  1 = one tap (server keeps your Angel TOTP secret)   2 = tap + type the 6-digit code each morning"
MODE=$(ask "Choose 1 or 2: "); [ "$MODE" = "2" ] && LM=code || LM=onetap
API=$(ask "Angel SmartAPI API key: ")
CC=$(ask "Angel client ID: ")
PIN=$(asks "Angel PIN (hidden): ")
TOTP=""
[ "$LM" = "onetap" ] && TOTP=$(asks "Angel TOTP secret — the text behind the QR when you enabled TOTP (hidden): ")
TGT=$(asks "Telegram bot token from @BotFather (hidden): ")
echo "Now open Telegram, find your new bot, press START (or send 'hi'). Then press Enter here."
read -r _ < $TTY
CHAT=$(curl -fsS "https://api.telegram.org/bot${TGT}/getUpdates" | python3 -c 'import sys,json; r=json.load(sys.stdin).get("result",[]); print(next((str(u["message"]["chat"]["id"]) for u in reversed(r) if "message" in u), ""))')
[ -n "$CHAT" ] || { echo "Couldn't find your chat — send 'hi' to the bot and run this script again."; exit 1; }
umask 077
cat > $A/.env <<ENV
ANGEL_API_KEY=$API
ANGEL_CLIENT_CODE=$CC
ANGEL_PIN=$PIN
ANGEL_TOTP_SECRET=$TOTP
TELEGRAM_BOT_TOKEN=$TGT
TELEGRAM_CHAT_ID=$CHAT
ENV
chown bot:bot $A/.env && chmod 600 $A/.env
if [ ! -f $A/config.json ]; then
  python3 - "$A" "$LM" <<'PY'
import json, sys
a, lm = sys.argv[1], sys.argv[2]
c = json.load(open(f"{a}/config.example.json"))
c.update(dry_run=True, login_mode=lm)
json.dump(c, open(f"{a}/config.json", "w"), indent=2)
PY
  chown bot:bot $A/config.json
else
  python3 - "$A" "$LM" <<'PY'
import json, sys
a, lm = sys.argv[1], sys.argv[2]
c = json.load(open(f"{a}/config.json")); c["login_mode"] = lm
json.dump(c, open(f"{a}/config.json", "w"), indent=2)
PY
fi
curl -fsS -o /dev/null "https://api.telegram.org/bot${TGT}/sendMessage" --data-urlencode "chat_id=${CHAT}" \
  --data-urlencode "text=✅ Top Bottom bot connected to this chat. Mode: DRY RUN (no real orders) until you switch it live."

echo "=== 5/5  Daily timer + helper command ==="
cp $A/deploy/topbottom.service $A/deploy/topbottom.timer /etc/systemd/system/
install -m 755 $A/deploy/tb /usr/local/bin/tb
systemctl daemon-reload
systemctl enable --now topbottom.timer >/dev/null
echo
echo "Outgoing IPv4 of this server (must match the IP registered in Angel SmartAPI): $(curl -4 -fsS https://api.ipify.org || echo unknown)"
echo
echo "Done. Every weekday at 08:25 IST the bot messages you on Telegram with ▶️ Start / ⏸️ Skip."
echo "Test the Angel login now with:   sudo tb check"
echo "Other commands: sudo tb status | sudo tb logs | sudo tb live | sudo tb dry | sudo tb update"
