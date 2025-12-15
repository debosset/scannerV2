from flask import Flask, jsonify, render_template_string
import json
import os
import time
import sqlite3
import re

try:
    import psutil
except ImportError:
    psutil = None

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

GEN_STATUS = os.path.join(PARENT_DIR, "generator", "status.json")
GEN_DB = os.path.join(PARENT_DIR, "generator", "bitcoin_addresses.db")
IMPORTER_LOG = os.path.join(PARENT_DIR, "generator", "btc_db_importer.log")

# ─────────────────────────────────────────────────────────────
# HTML TEMPLATE
# ─────────────────────────────────────────────────────────────
TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>BTC Scanner Monitor</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-200 min-h-screen p-6">
  <h1 class="text-2xl font-semibold mb-6">BTC Scanner · Monitor</h1>

  <pre id="data" class="bg-black p-4 rounded text-sm overflow-x-auto">Chargement…</pre>

  <script>
    async function refresh() {
      try {
        const r = await fetch("/api/status");
        const j = await r.json();
        document.getElementById("data").textContent =
          JSON.stringify(j, null, 2);
      } catch (e) {
        document.getElementById("data").textContent = "Erreur API";
      }
    }
    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def human_readable_time(seconds: float) -> str:
    try:
        seconds = int(seconds)
    except Exception:
        return "-"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    elif m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def default_status():
    return {
        "keys_tested": 0,
        "total_keys_tested": 0,
        "btc_hits": 0,
        "btc_address_matches": 0,
        "last_btc_address": "",
        "speed_keys_per_sec": 0.0,
        "elapsed_seconds": 0.0,
        "elapsed_human": "-",
        "keys_per_minute": 0.0,
        "keys_per_day": 0.0,
    }


# ─────────────────────────────────────────────────────────────
# Generator status
# ─────────────────────────────────────────────────────────────
def load_generator_status():
    if not os.path.exists(GEN_STATUS):
        return default_status()

    try:
        with open(GEN_STATUS, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default_status()

    speed = float(data.get("speed_keys_per_sec", 0.0))
    elapsed = float(data.get("elapsed_seconds", 0.0))

    # multi-format addresses support
    last_addrs = data.get("last_btc_addresses")
    if isinstance(last_addrs, dict):
        parts = []
        if last_addrs.get("p2pkh"):
            parts.append(f"P2PKH: {last_addrs['p2pkh']}")
        if last_addrs.get("p2sh"):
            parts.append(f"P2SH: {last_addrs['p2sh']}")
        if last_addrs.get("bech32"):
            parts.append(f"Bech32: {last_addrs['bech32']}")
        last_addr_display = "\n".join(parts)
    else:
        last_addr_display = data.get("last_btc_address", "")

    # keyspace %
    from decimal import Decimal, getcontext
    SECP256K1_N = int(
        "0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16
    )

    total_tested = int(data.get("total_keys_tested", 0))
    getcontext().prec = 50
    try:
        percent = (Decimal(total_tested) / Decimal(SECP256K1_N)) * Decimal(100)
        percent_str = f"{percent:.2E} %"
    except Exception:
        percent_str = "0 %"

    return {
        "keys_tested": int(data.get("keys_tested", 0)),
        "total_keys_tested": total_tested,
        "btc_hits": int(data.get("btc_hits", 0)),
        "btc_address_matches": int(data.get("btc_address_matches", 0)),
        "last_btc_address": last_addr_display,
        "speed_keys_per_sec": speed,
        "elapsed_seconds": elapsed,
        "elapsed_human": human_readable_time(elapsed),
        "keys_per_minute": speed * 60,
        "keys_per_day": speed * 86400,
        "percent_tested_str": percent_str,
        "total_keyspace_str": format(SECP256K1_N, "0.2E"),
        "total_tested_str": format(total_tested, "0.2E"),
    }


# ─────────────────────────────────────────────────────────────
# DB status
# ─────────────────────────────────────────────────────────────
def get_db_status():
    if not os.path.exists(GEN_DB):
        return {"exists": False, "rows": None, "last_modified": None}

    try:
        mtime = os.path.getmtime(GEN_DB)
        last_modified = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(mtime)
        )
    except Exception:
        last_modified = None

    rows = None
    try:
        conn = sqlite3.connect(GEN_DB)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM btc_addresses")
        rows = cur.fetchone()[0]
        conn.close()
    except Exception:
        rows = None

    return {"exists": True, "rows": rows, "last_modified": last_modified}


# ─────────────────────────────────────────────────────────────
# Importer status
# ─────────────────────────────────────────────────────────────
def get_importer_status():
    if not os.path.exists(IMPORTER_LOG):
        return {"last_line": None, "import_duration": None}

    try:
        with open(IMPORTER_LOG, "r", encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
    except Exception:
        return {"last_line": None, "import_duration": None}

    last_line = lines[-1] if lines else None
    duration = None

    for l in reversed(lines):
        m = re.search(r"Import terminé: .* en ([0-9]+(?:\.[0-9]+)?) min", l)
        if m:
            duration = f"{m.group(1)} min"
            break

    if duration is None:
        for l in reversed(lines):
            m = re.search(r"Download OK: .* en ([0-9]+(?:\.[0-9]+)?)s", l)
            if m:
                duration = f"download {m.group(1)}s"
                break

    return {"last_line": last_line, "import_duration": duration}


# ─────────────────────────────────────────────────────────────
# System status
# ─────────────────────────────────────────────────────────────
def get_system_status():
    if psutil is None:
        return {"cpu_text": "psutil non installé", "ram_text": "-"}

    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()

    ram_text = f"{mem.used / 1e9:.2f} / {mem.total / 1e9:.2f} GB"

    return {
        "cpu_text": f"{cpu:.1f} %",
        "ram_text": ram_text,
    }


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(TEMPLATE)


@app.route("/api/status")
def api_status():
    return jsonify({
        "generator": load_generator_status(),
        "database": get_db_status(),
        "importer": get_importer_status(),
        "system": get_system_status(),
        "timestamp": time.time(),
    })


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
