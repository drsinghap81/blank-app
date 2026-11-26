#!/usr/bin/env bash
# 26 Nov 2026 (Amritpal: "Yes start" - Top Bottom on MCX mini commodities, claude/top-bottom-mcx-minis-test.md): one bot per
# commodity on the REAL MCX contract from Angel, index rules 1 / 2 / 2, 0.05% buffer, 1 lot each, DRY RUN:
#   crude  CRUDEOILM   both sides
#   silver SILVERMIC   buy only, only while above its 200-day average
#   natgas NATGASMINI  buy only, only while above its 200-day average
#   gold   GOLDPETAL   buy only
# MCX session 09:00 - 23:30 / 23:55 IST; the contract rolls 5 days before expiry (tender period). They share the Bank Nifty bot's
# Angel session. Re-running keeps existing configs. Installed by the app's "Install MCX bots" button (watchdog) or:
#   sudo bash /opt/trenddesk/repo/tools/live_server/deploy/tb_mcx_setup.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
R=/opt/trenddesk/repo; V=/opt/trenddesk/venv; M=/opt/trenddesk/var/tb
[ -f /etc/systemd/system/trenddesk-tb.service ] || { echo "install the Bank Nifty bot first (tb_setup.sh)"; exit 1; }
grep -q TB_SESSION_OUT /etc/systemd/system/trenddesk-tb.service || \
  sed -i 's|^Environment=TB_STATE_DIR=/opt/trenddesk/var/tb |Environment=TB_SESSION_OUT=/opt/trenddesk/var/tb/session.json TB_STATE_DIR=/opt/trenddesk/var/tb |' /etc/systemd/system/trenddesk-tb.service
cat > /etc/systemd/system/trenddesk-tbm@.service <<'UNIT'
[Unit]
Description=Top Bottom MCX bot %i (one MCX day, to 23:55 IST; shares the Bank Nifty bot's Angel session)
After=network-online.target trenddesk.service trenddesk-tb.service
Wants=network-online.target

[Service]
Type=simple
User=trenddesk
WorkingDirectory=/opt/trenddesk/var/tb_%i
EnvironmentFile=/opt/trenddesk/.env
Environment=TB_STATE_DIR=/opt/trenddesk/var/tb_%i TB_CHANNEL=app TB_CONFIG=/opt/trenddesk/var/tb_%i/config.json TB_SESSION_FROM=/opt/trenddesk/var/tb/session.json
ExecStart=/opt/trenddesk/venv/bin/python /opt/trenddesk/repo/tools/angel/run_bot.py --no-pull
Restart=on-failure
RestartSec=60
TimeoutStopSec=90
UNIT
cat > /etc/systemd/system/trenddesk-tbm@.timer <<'UNIT'
[Unit]
Description=Start the Top Bottom MCX bot %i on weekday mornings (08:31 IST, after the Bank Nifty bot logs in)

[Timer]
OnCalendar=Mon..Fri 08:31 Asia/Kolkata
RandomizedDelaySec=60
Persistent=false
Unit=trenddesk-tbm@%i.service

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
for row in crude:CRUDEOILM:false:false silver:SILVERMIC:true:true natgas:NATGASMINI:true:true gold:GOLDPETAL:true:false; do
  IFS=: read -r k S LO TR <<<"$row"; D=/opt/trenddesk/var/tb_$k
  mkdir -p $D/app
  [ -f $D/config.json ] || cat > $D/config.json <<CFG
{
  "symbol": "$S",
  "exchange": "MCX",
  "session_open": "09:00",
  "session_close": "auto",
  "roll_days": 5,
  "next_month_on_expiry_day": false,
  "long_only": $LO,
  "trend_200d": $TR,
  "buffer_pts": 0,
  "buffer_pct": 0.05,
  "day_sl_pct": 1.0,
  "max_sl_pct": 2.0,
  "be_pct": 2.0,
  "gap_pct": 1.0,
  "event_exit": false,
  "lots": 1,
  "max_lots": 1,
  "channel": "app",
  "confirm_entries": true,
  "confirm_reversals": true,
  "no_reply": "skip",
  "login_mode": "onetap",
  "morning_button": false,
  "max_daily_loss_rs": 5000,
  "max_entries_per_day": 2,
  "heartbeat_minutes": 0
}
CFG
  [ -f $D/mode.json ] || echo '{"live": false}' > $D/mode.json
  chown -R trenddesk $D
  systemctl enable --now trenddesk-tbm@$k.timer >/dev/null
  # start FLAT from now (levels already broken are spent) and post the next buy level for approval in the app
  (cd $D && sudo -u trenddesk env $(grep -v '^#' /opt/trenddesk/.env | grep '=' | sed 's/[[:space:]]#.*$//' | xargs -d '\n') \
    TB_STATE_DIR=$D TB_CHANNEL=app TB_CONFIG=$D/config.json TB_SESSION_FROM=$M/session.json $V/bin/python $R/tools/angel/run_bot.py --init --check --no-pull 2>&1 | tail -n 4) \
    || echo "$k: init check failed (it retries at the next morning start)"
done
echo "TB_MCX__SETUP__DONE  timers: $(systemctl list-timers 'trenddesk-tbm@*' --no-legend | wc -l)"
