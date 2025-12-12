#!/usr/bin/env bash
set -euo pipefail
cd /opt/generator

exec 9>/tmp/btc_db_update.lock
flock -n 9 || exit 0

/usr/bin/python3 /opt/generator/btc_db_importer.py --update-daily --test >> /opt/generator/btc_db_importer.log 2>&1