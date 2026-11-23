#!/usr/bin/env bash
# 24 Nov 2026: moomoo OpenD (moomoo's API gateway) on the Trend Desk server, as a service that restarts by itself.
# You type your moomoo ID and LOGIN password here on the server (stored only as an MD5 hash in OpenD's own config, readable by
# root). Nothing is sent anywhere else. Trading stays on moomoo's PAPER account until you change MOOMOO_ENV yourself.
#   1. download the Ubuntu command-line OpenD .tar.gz link from moomoo's OpenAPI download page
#   2. sudo bash /opt/trenddesk/repo/tools/live_server/deploy/opend_setup.sh "<that download link>"
#   3. if OpenD asks for an SMS code:  sudo bash .../opend_setup.sh code 123456
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
D=/opt/opend; ENVF=/opt/trenddesk/.env
if [ "${1:-}" = "code" ]; then
  [ -n "${2:-}" ] || { echo "usage: opend_setup.sh code 123456"; exit 1; }
  { echo "input_phone_verify_code -code=$2"; sleep 2; } | timeout 8 nc 127.0.0.1 22222 || true
  sleep 3; journalctl -u opend -n 15 --no-pager; exit 0
fi
URL="${1:-}"; [ -n "$URL" ] || { echo 'usage: opend_setup.sh "<OpenD Ubuntu .tar.gz link>"'; exit 1; }
apt-get install -y -q netcat-openbsd >/dev/null 2>&1 || true
# memory: OpenD + the app on a 1 GB box needs swap (the server froze once on low memory)
if [ "$(free -m | awk '/Mem:/{print $2}')" -lt 1900 ] && ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "added 2 GB swap"
fi
mkdir -p $D && cd $D && rm -rf dl && mkdir dl && cd dl
curl -fsSL "$URL" -o opend.tgz && tar xzf opend.tgz
BIN=$(find . -type f \( -name OpenD -o -name FutuOpenD -o -name MoomooOpenD \) -perm -u+x | head -1)
[ -n "$BIN" ] || { echo "OpenD binary not found in the download - is it the Ubuntu command-line version?"; exit 1; }
DIR=$(dirname "$BIN"); rm -rf $D/app && mv "$DIR" $D/app; cd $D/app
XML=$(ls OpenD.xml FutuOpenD.xml 2>/dev/null | head -1); [ -n "$XML" ] || { echo "OpenD.xml not found"; exit 1; }
read -r -p "moomoo ID (login account number, email or phone as you log in): " ACC
read -r -s -p "moomoo LOGIN password (not shown): " PW; echo
MD5=$(printf '%s' "$PW" | md5sum | cut -d' ' -f1); unset PW
setx() { if grep -q "<$1>" "$XML"; then sed -i "s|<$1>[^<]*</$1>|<$1>$2</$1>|" "$XML"; else sed -i "s|</config>|  <$1>$2</$1>\n</config>|" "$XML"; fi; }
setx login_account "$ACC"; setx login_pwd_md5 "$MD5"; sed -i 's|<login_pwd>[^<]*</login_pwd>|<login_pwd></login_pwd>|' "$XML"
setx ip 127.0.0.1; setx api_port 11111; setx telnet_ip 127.0.0.1; setx telnet_port 22222; setx lang en; setx log_level info
chmod 600 "$XML"
cat > /etc/systemd/system/opend.service <<UNIT
[Unit]
Description=moomoo OpenD (API gateway for Trend Desk; listens on 127.0.0.1:11111 only)
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=$D/app
ExecStart=$D/app/$(basename "$BIN") -cfg_file=$D/app/$XML
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload && systemctl enable --now opend >/dev/null
# app settings: read-only account view now; orders only on moomoo's PAPER account (SIMULATE) and only if MOOMOO_TRADE=1
for kv in MOOMOO_ENABLED=1 MOOMOO_MARKETS=AU,US MOOMOO_FIRM=FUTUAU MOOMOO_ENV=SIMULATE; do
  k=${kv%%=*}; grep -q "^$k=" $ENVF && sed -i "s|^$k=.*|$kv|" $ENVF || echo "$kv" >> $ENVF; done
sleep 12; journalctl -u opend -n 20 --no-pager
echo
echo "If the log asks for a phone verification code:  sudo bash $0 code <code from SMS>"
echo "If it says the API questionnaire/agreement is not done: complete it at https://www.moomoo.com/en-us/about/api-disclaimer (logged in), then: sudo systemctl restart opend"
echo "When the log shows login success:  sudo systemctl restart trenddesk"
echo "OPEND__SETUP__DONE"
