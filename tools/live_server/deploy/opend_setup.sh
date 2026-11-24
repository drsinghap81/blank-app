#!/usr/bin/env bash
# 24 Nov 2026: moomoo OpenD (moomoo's API gateway) on the Trend Desk server, as a service that restarts by itself.
# You type your moomoo ID and LOGIN password (here, or in the app's Connect moomoo form). OpenD >= 10.10 logs in once interactively
# and remembers it; the password is passed once and its temporary file deleted. Nothing is sent anywhere but moomoo. Trading stays on moomoo's PAPER account until you change MOOMOO_ENV yourself.
#   1. download the Ubuntu command-line OpenD .tar.gz link from moomoo's OpenAPI download page
#   2. sudo bash /opt/trenddesk/repo/tools/live_server/deploy/opend_setup.sh "<that download link>"
#   3. if OpenD asks for an SMS code:  sudo bash .../opend_setup.sh code 123456
# From the app (Settings -> Server -> Connect moomoo) the watchdog runs it with OPEND_ACC + OPEND_PWFILE set (no prompts).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
D=/opt/opend; ENVF=/opt/trenddesk/.env
if [ "${1:-}" = "code" ]; then
  [ -n "${2:-}" ] || { echo "usage: opend_setup.sh code 123456"; exit 1; }
  { echo "input_phone_verify_code -code=$2"; sleep 2; } | timeout 8 nc 127.0.0.1 22222 || true
  sleep 3; journalctl -u opend -n 15 --no-pager; exit 0
fi
URL="${1:-}"; [ -n "$URL" ] || { echo 'usage: opend_setup.sh "<OpenD Ubuntu .tar.gz link>"'; exit 1; }
echo "step 1/5: helper package"; timeout 120 apt-get install -y -q -o DPkg::Lock::Timeout=60 netcat-openbsd >/dev/null 2>&1 || echo "  (netcat not installed - only needed for a code entered later)"
echo "step 2/5: memory (swap)"
# OpenD + the app need memory: the server has ~400 MB RAM. Add a second 1 GB swap file (never switch the existing one off).
SW=$(swapon --show=SIZE --bytes --noheadings 2>/dev/null | awk '{s+=$1} END{print s+0}')
if [ "${SW:-0}" -lt 1900000000 ] && [ ! -f /swapfile2 ]; then
  { fallocate -l 1G /swapfile2 || dd if=/dev/zero of=/swapfile2 bs=1M count=1024; } >/dev/null 2>&1 && chmod 600 /swapfile2 && mkswap /swapfile2 >/dev/null \
    && swapon /swapfile2 && { grep -q '^/swapfile2 ' /etc/fstab || echo '/swapfile2 none swap sw 0 0' >> /etc/fstab; } && echo "  swap now $(free -m | awk '/Swap:/{print $2}') MB" || echo "  (could not add swap - continuing)"
fi
mkdir -p $D && cd $D && rm -rf dl && mkdir dl && cd dl
echo "step 3/5: downloading OpenD"; curl -fsSL --max-time 600 "$URL" -o opend.tgz; echo "  downloaded $(du -h opend.tgz | cut -f1)"
echo "step 4/5: unpacking"; tar xzf opend.tgz
find . -maxdepth 3 > files.txt || true; head -n 15 files.txt
BIN=$(find . -type f -perm -u+x \( -name OpenD -o -name FutuOpenD -o -name MoomooOpenD -o -iname '*opend' \) 2>/dev/null > bins.txt || true; head -n 1 bins.txt)
[ -n "$BIN" ] || { echo "OpenD program not found in the download - is it the Ubuntu command-line version?"; exit 1; }
DIR=$(dirname "$BIN"); rm -rf $D/app && mv "$DIR" $D/app; cd $D/app; echo "  OpenD: $(basename "$BIN")"
XML=""; for x in OpenD.xml FutuOpenD.xml MoomooOpenD.xml; do [ -f "$x" ] && { XML=$x; break; }; done
[ -n "$XML" ] || { XML=$(find . -maxdepth 1 -name '*.xml' > xml.txt || true; head -n 1 xml.txt); XML=${XML#./}; }
[ -n "$XML" ] || { echo "OpenD's .xml config file not found"; ls; exit 1; }
echo "  config: $XML"
if [ -n "${OPEND_ACC:-}" ] && [ -n "${OPEND_PWFILE:-}" ]; then ACC=$OPEND_ACC; PWF=$OPEND_PWFILE
else
  read -r -p "moomoo ID (login account number, email or +countrycode phone): " ACC
  PWF=$(mktemp); chmod 600 "$PWF"; read -r -s -p "moomoo LOGIN password (not shown): " PW; echo; printf '%s' "$PW" > "$PWF"; unset PW
fi
setx() { if grep -q "<$1>" "$XML"; then sed -i "s|<$1>[^<]*</$1>|<$1>$2</$1>|" "$XML"; else sed -i "s|</config>|  <$1>$2</$1>\n</config>|" "$XML"; fi; }
setx ip 127.0.0.1; setx api_port 11111; setx telnet_ip 127.0.0.1; setx telnet_port 22222; setx lang en; setx log_level info
chmod 600 "$XML"
cat > /etc/systemd/system/opend.service <<UNIT
[Unit]
Description=moomoo OpenD (API gateway for Trend Desk; listens on 127.0.0.1:11111 only)
After=network-online.target
Wants=network-online.target
[Service]
Environment=HOME=/root
WorkingDirectory=$D/app
ExecStart=$D/app/$(basename "$BIN") -cfg_file=$D/app/$XML -login_account=$ACC -login_by_remember=1
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload; systemctl stop opend 2>/dev/null || true
echo "step 5/5: first login"
# OpenD >= 10.10: first login is interactive (remember password); opend_login.py answers it and waits for the SMS code
ST=/opt/trenddesk/var/opend_setup.txt; : > $ST; chown trenddesk $ST 2>/dev/null || true
MODEF=$D/login.mode; rm -f $MODEF
python3 /opt/trenddesk/repo/tools/live_server/deploy/opend_login.py "$D/app/$(basename "$BIN")" "$D/app/$XML" "$ACC" "$PWF" $ST /opt/trenddesk/var/cmd_opendcode $MODEF \
  && echo "first login OK" || echo "first login not confirmed - check $ST"
rm -f "$PWF"
# start the service the way the first login worked: remembered password, or the password hash in a root-only env file
if [ -f $MODEF ] && grep -q '^md5 ' $MODEF; then
  ( umask 077; echo "OPEND_PWD_MD5=$(cut -d' ' -f2 $MODEF)" > $D/login.env )
  sed -i "s|^ExecStart=.*|ExecStart=$D/app/$(basename "$BIN") -cfg_file=$D/app/$XML -login_account=$ACC -login_pwd_md5=\${OPEND_PWD_MD5}|" /etc/systemd/system/opend.service
  grep -q '^EnvironmentFile=' /etc/systemd/system/opend.service || sed -i "s|^WorkingDirectory=.*|&\nEnvironmentFile=$D/login.env|" /etc/systemd/system/opend.service
  systemctl daemon-reload
fi
rm -f $MODEF
id trenddesk >/dev/null 2>&1 && { mkdir -p /home/trenddesk; chown trenddesk: /home/trenddesk; }   # the moomoo SDK logs under the app user's home
systemctl enable --now opend >/dev/null
# app settings: read-only account view now; orders only on moomoo's PAPER account (SIMULATE) and only if MOOMOO_TRADE=1
for kv in MOOMOO_ENABLED=1 MOOMOO_TRADE=1 MOOMOO_MARKETS=AU,US MOOMOO_FIRM=FUTUAU MOOMOO_ENV=SIMULATE; do
  k=${kv%%=*}; grep -q "^$k=" $ENVF && sed -i "s|^$k=.*|$kv|" $ENVF || echo "$kv" >> $ENVF; done
sleep 12; journalctl -u opend -n 20 --no-pager
echo
echo "If the log asks for a phone verification code:  sudo bash $0 code <code from SMS>"
echo "If it says the API questionnaire/agreement is not done: complete it at https://www.moomoo.com/en-us/about/api-disclaimer (logged in), then: sudo systemctl restart opend"
echo "When the log shows login success:  sudo systemctl restart trenddesk"
echo "OPEND__SETUP__DONE"
