#!/bin/bash
# 26 Nov 2026: save the moomoo TRADING password (trade PIN) for the real account into the server's .env.
# Typed by the account owner at the hidden prompt - never shown, never logged, never sent anywhere.
# Run:  sudo bash /opt/trenddesk/repo/tools/live_server/deploy/mm_pin.sh
set -e
F=/opt/trenddesk/.env
[ -f "$F" ] || { echo "no $F"; exit 1; }
read -rsp "moomoo trading password (hidden): " P; echo
read -rsp "again: " P2; echo
[ -n "$P" ] && [ "$P" = "$P2" ] || { echo "did not match - nothing changed"; exit 1; }
sed -i '/^MOOMOO_TRADE_PWD=/d' "$F"
printf 'MOOMOO_TRADE_PWD=%s\n' "$P" >> "$F"
chown trenddesk "$F" 2>/dev/null || true; chmod 600 "$F"; unset P P2
systemctl restart trenddesk
echo "Saved. Server restarted. Now in the app: Automation -> moomoo -> Switch to real money."
