#!/usr/bin/env bash
# Top Bottom (Bank Nifty futures) on the Trend Desk server: approvals in the Trend Desk app, DRY RUN until you switch it.
#   sudo bash /opt/trenddesk/repo/tools/live_server/deploy/tb_setup.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
R=/opt/trenddesk/repo; V=/opt/trenddesk/venv; D=/opt/trenddesk/var/tb
$V/bin/pip install -q -r $R/tools/angel/requirements.txt
mkdir -p $D/app
if [ ! -f $D/config.json ]; then
cat > $D/config.json <<'CFG'
{
  "symbol": "BANKNIFTY",
  "lots": 1,
  "max_lots": 2,
  "channel": "app",
  "confirm_entries": true,
  "confirm_reversals": true,
  "no_reply": "skip",
  "login_mode": "onetap",
  "morning_button": false,
  "max_daily_loss_rs": 25000,
  "max_entries_per_day": 3,
  "heartbeat_minutes": 0
}
CFG
fi
[ -f $D/mode.json ] || echo '{"live": false}' > $D/mode.json
chown -R trenddesk $D
cat > /etc/systemd/system/trenddesk-tb.service <<'UNIT'
[Unit]
Description=Top Bottom Bank Nifty futures bot (one trading day; approvals in the Trend Desk app)
After=network-online.target trenddesk.service
Wants=network-online.target

[Service]
Type=simple
User=trenddesk
WorkingDirectory=/opt/trenddesk/var/tb
EnvironmentFile=/opt/trenddesk/.env
Environment=TB_STATE_DIR=/opt/trenddesk/var/tb TB_CHANNEL=app TB_CONFIG=/opt/trenddesk/var/tb/config.json
ExecStart=/opt/trenddesk/venv/bin/python /opt/trenddesk/repo/tools/angel/run_bot.py --no-pull
Restart=on-failure
RestartSec=60
TimeoutStopSec=90
UNIT
cat > /etc/systemd/system/trenddesk-tb.timer <<'UNIT'
[Unit]
Description=Start the Top Bottom bot on weekday mornings (08:25 IST)

[Timer]
OnCalendar=Mon..Fri 08:25 Asia/Kolkata
Persistent=false
Unit=trenddesk-tb.service

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now trenddesk-tb.timer >/dev/null
# start FLAT from now (levels already broken are spent) and post the next levels for approval in the app
cd $D && sudo -u trenddesk env $(grep -v '^#' /opt/trenddesk/.env | grep '=' | sed 's/[[:space:]]#.*$//' | xargs -d '\n') \
  TB_STATE_DIR=$D TB_CHANNEL=app TB_CONFIG=$D/config.json $V/bin/python $R/tools/angel/run_bot.py --init --check --no-pull | tail -n 8
echo "TB__SETUP__DONE  timer: $(systemctl is-enabled trenddesk-tb.timer)  mode: $(cat $D/mode.json)"
