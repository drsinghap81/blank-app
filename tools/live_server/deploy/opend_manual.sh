#!/usr/bin/env bash
# 24 Nov 2026: one-time manual first login for moomoo OpenD (its login prompt only takes a real keyboard).
#   sudo bash /opt/trenddesk/repo/tools/live_server/deploy/opend_manual.sh        -> answer: moomoo ID, login password, Y (+ SMS code)
#   when it says the login succeeded press Ctrl+C, then:
#   sudo bash /opt/trenddesk/repo/tools/live_server/deploy/opend_manual.sh done   -> starts the service with the remembered login
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
U=/etc/systemd/system/opend.service; A=/opt/opend/app
if [ "${1:-}" = "done" ]; then
  systemctl start opend; sleep 20; systemctl --no-pager -l status opend | head -n 5
  (echo > /dev/tcp/127.0.0.1/11111) 2>/dev/null && echo "OpenD API port is open" || echo "OpenD API port not open yet"
  systemctl restart trenddesk; echo "Trend Desk restarted - check Connect moomoo in the app"; exit 0
fi
systemctl stop opend 2>/dev/null
grep -q '^Environment=HOME=/root' $U || sed -i '/^\[Service\]/a Environment=HOME=/root' $U
sed -i 's|^ExecStart=\(.*\) -login_pwd_md5=[^ ]*|ExecStart=\1|' $U; grep -q 'login_by_remember' $U || sed -i 's|^ExecStart=.*|& -login_by_remember=1|' $U
rm -f /opt/opend/login.env; sed -i '/^EnvironmentFile=/d' $U; systemctl daemon-reload
grep ExecStart $U
XML=$(ls $A/*.xml 2>/dev/null | head -n 1)
echo "=== OpenD login: type your moomoo ID, then your moomoo LOGIN password, then Y. Ctrl+C once it says the login succeeded. ==="
cd $A && HOME=/root ./$(ls $A | grep -iE '^(OpenD|FutuOpenD|MoomooOpenD)$' | head -n 1) -cfg_file=$XML -lang=en
