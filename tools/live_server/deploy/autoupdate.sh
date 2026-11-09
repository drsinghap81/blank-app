#!/usr/bin/env bash
# Trend Desk server: smarter auto-update (replaces the once-a-day 08:00 IST cron).
#   Every 15 minutes: fetch GitHub; if there is new code AND it is outside Indian market hours (weekdays 09:00-15:35 IST),
#   pull it, install any new Python packages, and restart the app server. During the session nothing restarts: the update
#   waits for the close. The Top Bottom bots are not restarted; they use the new code from their next morning start.
# Install once:   sudo bash /opt/trenddesk/repo/tools/live_server/deploy/autoupdate.sh --install
set -uo pipefail
APP=/opt/trenddesk; R=$APP/repo; V=$APP/venv; LOG=$APP/var/autoupdate.log
if [ "${1:-}" = "--install" ]; then
  [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
  rm -f /etc/cron.d/trenddesk-update
  cat > /etc/systemd/system/trenddesk-autoupdate.service <<UNIT
[Unit]
Description=Trend Desk auto-update (new code outside Indian market hours)
[Service]
Type=oneshot
ExecStart=/bin/bash $R/tools/live_server/deploy/autoupdate.sh
UNIT
  cat > /etc/systemd/system/trenddesk-autoupdate.timer <<UNIT
[Unit]
Description=Check for Trend Desk updates every 15 minutes
[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true
[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload && systemctl enable --now trenddesk-autoupdate.timer >/dev/null
  git -C "$R" fetch -q origin main && git -C "$R" merge -q --ff-only origin/main
  $V/bin/pip install -q -r "$R/tools/live_server/requirements.txt" >/dev/null 2>&1
  [ -f "$R/tools/angel/requirements.txt" ] && $V/bin/pip install -q -r "$R/tools/angel/requirements.txt" >/dev/null 2>&1
  systemctl restart trenddesk
  echo "AUTOUPDATE__INSTALLED  next checks: every 15 min ($(systemctl is-active trenddesk-autoupdate.timer))"; exit 0
fi
mkdir -p "$(dirname "$LOG")"
log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
git -C "$R" fetch -q origin main || { log "fetch failed"; exit 0; }
[ "$(git -C "$R" rev-parse HEAD)" = "$(git -C "$R" rev-parse origin/main)" ] && exit 0
if [ "${1:-}" != "--now" ]; then
  dow=$(TZ=Asia/Kolkata date +%u); hm=$(TZ=Asia/Kolkata date +%H%M)
  if [ "$dow" -le 5 ] && [ "$hm" -ge 0900 ] && [ "$hm" -lt 1535 ]; then log "new code waiting for the close"; exit 0; fi
fi
old=$(git -C "$R" rev-parse --short HEAD)
git -C "$R" merge -q --ff-only origin/main || { log "pull failed"; exit 0; }
$V/bin/pip install -q -r "$R/tools/live_server/requirements.txt" >/dev/null 2>&1 || log "pip (server) failed"
[ -f "$R/tools/angel/requirements.txt" ] && { $V/bin/pip install -q -r "$R/tools/angel/requirements.txt" >/dev/null 2>&1 || log "pip (bot) failed"; }
systemctl restart trenddesk && log "updated $old -> $(git -C "$R" rev-parse --short HEAD), server restarted" || log "restart failed"
