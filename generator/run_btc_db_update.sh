#!/usr/bin/env bash
set -euo pipefail

cd /opt/generator

LOG="/opt/generator/btc_db_importer.log"
LOCK="/tmp/btc_db_update.lock"

# Bons noms de services
SERVICES=(
  "btc_generator.service"
  "btc_dashboard.service"
  "dashboard.service"
)

log() {
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"
}

stop_services() {
  log "Stopping services..."
  for s in "${SERVICES[@]}"; do
    if systemctl list-unit-files --type=service | awk '{print $1}' | grep -qx "$s"; then
      if systemctl is-active --quiet "$s"; then
        log " - stop $s"
        systemctl stop "$s" || true
      else
        log " - $s already stopped (or failed)"
      fi
    else
      log " - $s not found (skip)"
    fi
  done
}

start_services() {
  log "Starting services..."
  for s in "${SERVICES[@]}"; do
    if systemctl list-unit-files --type=service | awk '{print $1}' | grep -qx "$s"; then
      log " - start $s"
      systemctl start "$s" || log " ! failed to start $s"
    fi
  done
}

cleanup() {
  rc=$?
  log "Importer exit code=$rc"
  start_services
  log "=== BTC DB update END ==="
  exit $rc
}

# Lock anti double-run
exec 9>"$LOCK"
flock -n 9 || { log "Another update is running, exiting."; exit 0; }

trap cleanup EXIT

log "=== BTC DB update START ==="
stop_services

log "Running importer..."
/usr/bin/python3 /opt/generator/btc_db_importer.py --update-daily --batch-size 5000 --test >> "$LOG" 2>&1
