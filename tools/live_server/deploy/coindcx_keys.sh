#!/bin/bash
# 29 Nov 2026: save the CoinDCX API key and secret into the server's .env, for the BTC / ETH Top Bottom bot (crypto_tb.py).
# Typed by the account owner at hidden prompts - never shown, never logged, never sent anywhere else.
# Make the key on CoinDCX with TRADE permission only (no withdrawals) and bind it to this server's IP 13.126.118.48.
# Run:  sudo bash /opt/trenddesk/repo/tools/live_server/deploy/coindcx_keys.sh
# The bot reads the file each time it needs the key, so no restart is needed. Live stays OFF until you switch it on in the app.
set -e
F=/opt/trenddesk/.env
[ -f "$F" ] || { echo "no $F"; exit 1; }
read -rsp "CoinDCX API key (hidden): " K; echo
read -rsp "CoinDCX API secret (hidden): " S; echo
[ -n "$K" ] && [ -n "$S" ] || { echo "empty - nothing changed"; exit 1; }
case "$K$S" in *"'"*|*" "*) echo "unexpected character in the key - copy it again from CoinDCX"; exit 1;; esac
sed -i '/^COINDCX_API_KEY=/d;/^COINDCX_API_SECRET=/d' "$F"
printf "COINDCX_API_KEY='%s'\nCOINDCX_API_SECRET='%s'\n" "$K" "$S" >> "$F"
chown trenddesk "$F" 2>/dev/null || true; chmod 600 "$F"
NK=${#K}; NS=${#S}; unset K S
echo "Saved (key $NK characters, secret $NS characters). Checking the key with CoinDCX (read-only: lists positions)..."
cd /opt/trenddesk/repo/tools/live_server
sudo -u trenddesk /opt/trenddesk/venv/bin/python - <<'EOF' || true
import crypto_tb
d = crypto_tb.DCX()
try:
    p = d.positions(); print("CoinDCX accepted the key. Open futures positions:", sum(1 for x in p if float(x.get("active_pos") or 0) != 0))
except Exception as e:
    print("CoinDCX did not accept the key:", str(e)[:200])
EOF
echo "Next, in the app: Bots -> Top Bottom BTC / ETH -> Live (app password + LIVE)."
