#!/usr/bin/env bash
# Trend Desk watchdog (11 Nov 2026), run by systemd every minute as root (installed automatically by autoupdate.sh).
#  1. Health: GET http://127.0.0.1:8000/api/health with a 10 s limit. 3 failed checks in a row (about 3 minutes stuck or down),
#     or the server's background loop silent for over 10 minutes -> restart the app server. Your stops are GTTs on Angel, so a
#     restart never leaves a position unprotected; the Top Bottom bots run as their own services and are not touched.
#  2. Buttons in the app (Settings -> Server): the server writes var/cmd_update or var/cmd_restart; this script acts on it
#     within a minute (update = pull the latest code now, even in market hours, then restart).
APP=/opt/trenddesk; VAR=$APP/var; LOG=$VAR/watchdog.log; F=$VAR/wd_fail
log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; tail -n 400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; }
for alt in $APP/repo/tools/live_server/var; do for c in cmd_update cmd_restart; do [ -f "$alt/$c" ] && mv -f "$alt/$c" "$VAR/$c"; done; done   # if DATA_DIR isn't set
if [ -f "$VAR/cmd_update" ]; then rm -f "$VAR/cmd_update"; log "update requested from the app"; bash $APP/repo/tools/live_server/deploy/autoupdate.sh --now; echo 0 > "$F"; exit 0; fi
if [ -f "$VAR/cmd_restart" ]; then rm -f "$VAR/cmd_restart"; log "restart requested from the app"; systemctl restart trenddesk; echo 0 > "$F"; exit 0; fi
H=$(curl -s -m 10 http://127.0.0.1:8000/api/health || true)
n=$(cat "$F" 2>/dev/null || echo 0)
if echo "$H" | grep -q '"ok":true'; then
  age=$(echo "$H" | python3 -c 'import sys,json; print(int(json.load(sys.stdin).get("loop_age") or 0))' 2>/dev/null || echo 0)
  if [ "$age" -gt 600 ]; then log "background loop silent for ${age}s -> restart"; systemctl restart trenddesk; echo 0 > "$F"; exit 0; fi
  echo 0 > "$F"; exit 0
fi
n=$((n + 1)); echo $n > "$F"; log "health check failed ($n in a row)"
if [ "$n" -ge 3 ]; then log "server stuck or down -> restart"; systemctl restart trenddesk; echo 0 > "$F"; fi
