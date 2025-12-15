from flask import Flask, jsonify, render_template_string
import json
import os
import time
import sqlite3
import re

try:
    import psutil
except ImportError:
    psutil = None  # Le dashboard fonctionne sans psutil

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
# Template (joli design)
# ─────────────────────────────────────────────────────────────
TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Monitor</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>

  <style>
    :root {
      --bg: #020617;
      --bg-card: #020617;
      --bg-card-soft: #0b1220;
      --accent: #22c55e;
      --accent-soft: rgba(34, 197, 94, 0.1);
    }
    body {
      background: radial-gradient(circle at top, #111827 0, #020617 45%);
      color: #e5e7eb;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .glass {
      background: linear-gradient(145deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.85));
      border-radius: 1.25rem;
      border: 1px solid rgba(148, 163, 184, 0.35);
      box-shadow:
        0 18px 45px rgba(15, 23, 42, 0.9),
        0 0 0 1px rgba(15, 23, 42, 0.9);
      backdrop-filter: blur(20px);
    }
    .metric-card {
      border-radius: 1rem;
      background: radial-gradient(circle at top left, rgba(15, 23, 42, 0.95), rgba(15, 23, 42, 0.9));
      border: 1px solid rgba(55, 65, 81, 0.8);
    }
    .metric-label {
      font-size: 0.65rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: #9ca3af;
    }
    .metric-main {
      font-size: 1.6rem;
      font-weight: 600;
    }
    .mono-box {
      background: #020617;
      border-radius: 0.75rem;
      border: 1px solid rgba(30, 64, 175, 0.6);
      font-size: 0.7rem;
      white-space: pre-wrap;
    }
    .sys-label {
      font-size: 0.7rem;
      color: #9ca3af;
      text-transform: uppercase;
      letter-spacing: 0.16em;
    }
  </style>

  <script>
    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();

        const gen = data.generator || {};
        const sys = data.system || {};
        const db  = data.database || {};
        const imp = data.importer || {};

        const speed = Number(gen.speed_keys_per_sec || 0);
        const kpm = Number(gen.keys_per_minute || 0);
        const kpd = Number(gen.keys_per_day || 0);

        document.getElementById('keys_session').textContent =
          (gen.keys_tested || 0).toLocaleString('fr-CH');

        document.getElementById('keys_total').textContent =
          (gen.total_keys_tested || 0).toLocaleString('fr-CH');

        document.getElementById('speed_sec').textContent =
          speed.toFixed(2);

        document.getElementById('speed_min').textContent =
          kpm.toLocaleString('fr-CH', { maximumFractionDigits: 0 });

        document.getElementById('speed_day').textContent =
          kpd.toLocaleString('fr-CH', { maximumFractionDigits: 0 });

        document.getElementById('btc_hits').textContent =
          gen.btc_hits || 0;

        document.getElementById('btc_matches').textContent =
          gen.btc_address_matches || 0;

        document.getElementById('elapsed').textContent =
          gen.elapsed_human || '-';

        document.getElementById('last_addr').textContent =
          gen.last_btc_address || '-';

        // Tested vs total keyspace
        const tested = gen.total_keys_tested || 0;
        const totalKeyspace = gen.total_keyspace_str || '-';
        const testedSci = gen.total_tested_str || String(tested);
        document.getElementById('tested_vs_total').textContent =
          `${tested.toLocaleString('fr-CH')} / ${totalKeyspace} (${testedSci})`;

        document.getElementById('percent_tested').textContent =
          gen.percent_tested_str || '-';

        // Database info
        document.getElementById('db_rows').textContent =
          (db.rows != null) ? db.rows.toLocaleString('fr-CH') : '-';
        document.getElementById('db_mtime').textContent =
          db.last_modified || '-';

        // Importer info
        document.getElementById('import_duration').textContent =
          imp.import_duration || '-';
        document.getElementById('import_last_line').textContent =
          imp.last_line || '-';

        // System
        document.getElementById('cpu').textContent =
          sys.cpu_text || '-';
        document.getElementById('ram').textContent =
          sys.ram_text || '-';

      } catch (e) {
        console.error('Erreur fetch status:', e);
      }
    }

    document.addEventListener('DOMContentLoaded', () => {
      fetchStatus();
      setInterval(fetchStatus, 2000);
    });
  </script>
</head>

<body class="min-h-screen">
  <div class="max-w-6xl mx-auto px-4 py-8">

    <h1 class="text-2xl md:text-3xl font-semibold tracking-tight mb-6">
      <span class="text-slate-200">Scanner</span>
      <span class="text-slate-500"> · Monitor</span>
    </h1>

    <div class="glass p-5 md:p-6 space-y-6">

      <!-- Ligne 1 -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés testées · session</div>
          <div class="metric-main text-emerald-400" id="keys_session">-</div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés testées · total</div>
          <div class="metric-main text-sky-400" id="keys_total">-</div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Uptime · session</div>
          <div class="metric-main text-slate-100" id="elapsed">-</div>
        </div>
      </div>

      <!-- Percentage of keyspace tested -->
      <div class="grid grid-cols-1 md:grid-cols-1 gap-4 pt-4">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Pourcentage clefs testées · total keyspace</div>
          <div class="metric-main text-indigo-300" id="percent_tested">-</div>
        </div>
      </div>

      <!-- Tested vs Total keyspace -->
      <div class="grid grid-cols-1 md:grid-cols-1 gap-4 pt-2">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés testées · / · Total keyspace</div>
          <div class="mt-2 mono-box p-3 text-[10px] tracking-tight text-sky-200 break-all" id="tested_vs_total">-</div>
        </div>
      </div>

      <!-- Ligne 2 : Vitesse -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés / seconde</div>
          <div class="metric-main text-indigo-400">
            <span id="speed_sec">-</span>
            <span class="text-sm text-slate-500 ml-1">keys/s</span>
          </div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés / minute</div>
          <div class="metric-main text-indigo-300">
            <span id="speed_min">-</span>
            <span class="text-sm text-slate-500 ml-1">keys/min</span>
          </div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés / jour</div>
          <div class="metric-main text-indigo-200">
            <span id="speed_day">-</span>
            <span class="text-sm text-slate-500 ml-1">keys/jour</span>
          </div>
        </div>
      </div>

      <!-- Résultats BTC -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Adresse DB</div>
          <div class="metric-main text-amber-300" id="btc_matches">-</div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Adresse sold</div>
          <div class="metric-main text-emerald-300" id="btc_hits">-</div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Dernière adresse générée</div>
          <div class="mt-2 mono-box p-3 text-[10px] tracking-tight text-sky-200 break-all" id="last_addr">-</div>
        </div>
      </div>

      <!-- DB status -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">DB · lignes (btc_addresses)</div>
          <div class="metric-main text-amber-300" id="db_rows">-</div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">DB · dernière mise à jour</div>
          <div class="mt-2 mono-box p-3 text-[10px] tracking-tight text-sky-200 break-all" id="db_mtime">-</div>
        </div>
      </div>

      <!-- Importer status -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Import · durée</div>
          <div class="metric-main text-emerald-300" id="import_duration">-</div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Import · dernier log</div>
          <div class="mt-2 mono-box p-3 text-[10px] tracking-tight text-sky-200 break-all" id="import_last_line">-</div>
        </div>
      </div>

      <!-- Ligne système -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2 border-t border-slate-800/70">
        <div>
          <div class="sys-label mb-1">CPU</div>
          <div class="text-sm font-medium text-slate-100" id="cpu">-</div>
        </div>

        <div>
          <div class="sys-label mb-1">RAM</div>
          <div class="text-sm font-medium text-slate-100" id="ram">-</div>
        </div>
      </div>

    </div>
  </div>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────
# Helpers / Status
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
    if m > 0:
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
        "last_update": "-",
        "keys_per_minute": 0.0,
        "keys_per_day": 0.0,
        "percent_tested_str": "-",
        "total_keyspace_str": "-",
        "total_tested_str": "-",
    }


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

    # multi-format addresses display support
    last_addrs = data.get("last_btc_addresses")
    if isinstance(last_addrs, dict):
        display = []
        if last_addrs.get("p2pkh"):
            display.append(f"P2PKH: {last_addrs.get('p2pkh')}")
        if last_addrs.get("p2sh"):
            display.append(f"P2SH: {last_addrs.get('p2sh')}")
        if last_addrs.get("bech32"):
            display.append(f"Bech32: {last_addrs.get('bech32')}")
        last_addr_display = "\n".join(display) if display else data.get("last_btc_address", "")
    else:
        last_addr_display = data.get("last_btc_address", "")

    # keyspace %
    from decimal import Decimal, getcontext
    SECP256K1_N = int("0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16)
    total_tested = int(data.get("total_keys_tested", 0))

    getcontext().prec = 50
    try:
        percent = (Decimal(total_tested) / Decimal(SECP256K1_N)) * Decimal(100)
        percent_str = format(percent, "0.2E") + " %"
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
        "last_update": data.get("last_update", "-"),
        "keys_per_minute": speed * 60,
        "keys_per_day": speed * 86400,
        "percent_tested_str": percent_str,
        "total_keyspace_str": format(SECP256K1_N, "0.2E"),
        "total_tested_str": format(total_tested, "0.2E"),
    }


def get_db_status():
    if not os.path.exists(GEN_DB):
        return {"exists": False, "rows": None, "last_modified": None}

    try:
        mtime = os.path.getmtime(GEN_DB)
        last_modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
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


def get_importer_status():
    if not os.path.exists(IMPORTER_LOG):
        return {"last_line": None, "import_duration": None}

    # read last ~200 lines (simple but OK for small logs)
    try:
        with open(IMPORTER_LOG, "r", encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
    except Exception:
        return {"last_line": None, "import_duration": None}

    last_line = lines[-1] if lines else None
    duration = None

    # "Import terminé: ... en X min"
    for l in reversed(lines[-200:]):
        m = re.search(r"Import terminé: .* en ([0-9]+(?:\.[0-9]+)?) min", l)
        if m:
            duration = f"{m.group(1)} min"
            break

    # fallback: "Download OK: ... en Xs"
    if duration is None:
        for l in reversed(lines[-200:]):
            m = re.search(r"Download OK: .* en ([0-9]+(?:\.[0-9]+)?)s", l)
            if m:
                duration = f"download {m.group(1)}s"
                break

    return {"last_line": last_line, "import_duration": duration}


def get_system_status():
    if psutil is None:
        return {"cpu_text": "psutil non installé", "ram_text": "-"}

    try:
        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        ram_text = f"{mem.used / 1e9:.2f} / {mem.total / 1e9:.2f} GB"
        return {"cpu_text": f"{cpu:.1f} %", "ram_text": ram_text}
    except Exception:
        return {"cpu_text": "-", "ram_text": "-"}


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
        "system": get_system_status(),
        "database": get_db_status(),
        "importer": get_importer_status(),
        "timestamp": time.time(),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)