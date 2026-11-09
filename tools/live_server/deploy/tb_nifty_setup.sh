#!/usr/bin/env bash
# Top Bottom on NIFTY futures, BUY ONLY (tested 9 Nov 2026: 9.4%/yr at 1x, worst fall -9.4%, 2017-26), as a second bot next to
# Bank Nifty. It shares the Bank Nifty bot's Angel session (no second login), has its own levels, approvals, book and
# Dry run / Live switch in the Trend Desk app, and starts in DRY RUN.
#   sudo bash /opt/trenddesk/repo/tools/live_server/deploy/tb_nifty_setup.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
R=/opt/trenddesk/repo; V=/opt/trenddesk/venv; D=/opt/trenddesk/var/tb_nifty; M=/opt/trenddesk/var/tb
[ -f /etc/systemd/system/trenddesk-tb.service ] || { echo "install the Bank Nifty bot first (tb_setup.sh)"; exit 1; }
mkdir -p $D/app
if [ ! -f $D/config.json ]; then
cat > $D/config.json <<'CFG'
{
  "symbol": "NIFTY",
  "long_only": true,
  "buffer_pts": 12,
  "lots": 1,
  "max_lots": 1,
  "channel": "app",
  "confirm_entries": true,
  "confirm_reversals": true,
  "no_reply": "skip",
  "login_mode": "onetap",
  "morning_button": false,
  "max_daily_loss_rs": 15000,
  "max_entries_per_day": 2,
  "heartbeat_minutes": 0
}
CFG
fi
[ -f $D/mode.json ] || echo '{"live": false}' > $D/mode.json
chown -R trenddesk $D
# the Bank Nifty bot publishes its session for this bot (file readable only by the trenddesk user)
grep -q TB_SESSION_OUT /etc/systemd/system/trenddesk-tb.service || \
  sed -i 's|^Environment=TB_STATE_DIR=/opt/trenddesk/var/tb |Environment=TB_SESSION_OUT=/opt/trenddesk/var/tb/session.json TB_STATE_DIR=/opt/trenddesk/var/tb |' /etc/systemd/system/trenddesk-tb.service
cat > /etc/systemd/system/trenddesk-tb-nifty.service <<'UNIT'
[Unit]
Description=Top Bottom NIFTY futures bot, buy only (one trading day; shares the Bank Nifty bot's Angel session)
After=network-online.target trenddesk.service trenddesk-tb.service
Wants=network-online.target

[Service]
Type=simple
User=trenddesk
WorkingDirectory=/opt/trenddesk/var/tb_nifty
EnvironmentFile=/opt/trenddesk/.env
Environment=TB_STATE_DIR=/opt/trenddesk/var/tb_nifty TB_CHANNEL=app TB_CONFIG=/opt/trenddesk/var/tb_nifty/config.json TB_SESSION_FROM=/opt/trenddesk/var/tb/session.json
ExecStart=/opt/trenddesk/venv/bin/python /opt/trenddesk/repo/tools/angel/run_bot.py --no-pull
Restart=on-failure
RestartSec=60
TimeoutStopSec=90
UNIT
cat > /etc/systemd/system/trenddesk-tb-nifty.timer <<'UNIT'
[Unit]
Description=Start the Top Bottom NIFTY bot on weekday mornings (08:27 IST, after the Bank Nifty bot logs in)

[Timer]
OnCalendar=Mon..Fri 08:27 Asia/Kolkata
Persistent=false
Unit=trenddesk-tb-nifty.service

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now trenddesk-tb-nifty.timer >/dev/null
# start FLAT from now and post the next Nifty buy level for approval in the app
cd $D && sudo -u trenddesk env $(grep -v '^#' /opt/trenddesk/.env | grep '=' | sed 's/[[:space:]]#.*$//' | xargs -d '\n') \
  TB_STATE_DIR=$D TB_CHANNEL=app TB_CONFIG=$D/config.json TB_SESSION_FROM=$M/session.json $V/bin/python $R/tools/angel/run_bot.py --init --check --no-pull | tail -n 8
echo "TB_NIFTY__SETUP__DONE  timer: $(systemctl is-enabled trenddesk-tb-nifty.timer)  mode: $(cat $D/mode.json)"
