#!/usr/bin/env bash
# Asks for the app password and the Angel keys and writes them into /opt/trenddesk/.env.
# Run on the server:  sudo bash /opt/trenddesk/repo/tools/live_server/deploy/setkeys.sh
# Nothing is printed back; leave an answer blank to keep the current value.
set -euo pipefail
ENV=/opt/trenddesk/.env
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
[ -f "$ENV" ] || { echo "no $ENV - run setup.sh first"; exit 1; }

setv() {  # setv KEY VALUE  (value escaped for sed)
  local k=$1 v=$2
  v=${v//\\/\\\\}; v=${v//|/\\|}; v=${v//&/\\&}
  if grep -q "^$k=" "$ENV"; then sed -i "s|^$k=.*|$k=$v|" "$ENV"; else echo "$k=$v" >> "$ENV"; fi
}
ask() {  # ask KEY "prompt" hidden(1/0)
  local k=$1 p=$2 hide=${3:-1} v
  if [ "$hide" = 1 ]; then read -rsp "$p: " v; echo; else read -rp "$p: " v; fi
  v=${v//[[:space:]]/}
  if [ -n "$v" ]; then setv "$k" "$v"; echo "   $k saved"; else echo "   $k unchanged"; fi
}

echo "Leave any answer blank to keep what is there. Hidden answers show nothing while you type."
read -rsp "New app password (you'll type it on the phone): " PW; echo
if [ -n "$PW" ]; then
  read -rsp "Same password again: " PW2; echo
  [ "$PW" = "$PW2" ] || { echo "The two passwords differ - run the command again."; exit 1; }
  H=$(PW="$PW" python3 -c 'import os,hashlib;s=os.urandom(16);print("scrypt$"+s.hex()+"$"+hashlib.scrypt(os.environ["PW"].encode(),salt=s,n=2**14,r=8,p=1).hex())')
  setv APP_PASSWORD_HASH "$H"; echo "   APP_PASSWORD_HASH saved"
fi
unset PW PW2 H
if ! grep -Eq '^TOKEN_SECRET=[0-9a-f]{64}' "$ENV"; then
  setv TOKEN_SECRET "$(python3 -c 'import os;print(os.urandom(32).hex())')"; echo "   TOKEN_SECRET created"
fi
ask ANGEL_API_KEY     "Angel SmartAPI API key" 0
ask ANGEL_CLIENT_CODE "Angel client code (login ID)" 0
ask ANGEL_PIN         "Angel PIN (hidden)" 1
ask ANGEL_TOTP_SECRET "Angel TOTP secret - the text behind the QR code (hidden)" 1
chmod 600 "$ENV"

systemctl restart trenddesk; sleep 6
echo "service: $(systemctl is-active trenddesk)   mode: $(grep '^LIVE_ORDERS=' "$ENV")"
echo "KEYS__DONE"
