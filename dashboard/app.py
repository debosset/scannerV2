from flask import Flask, jsonify, render_template_string
import json
import os
import time
from decimal import Decimal, getcontext

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

# secp256k1 curve order (keyspace size)
SECP256K1_N_INT = int("0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16)

# How many decimals to show for percent. (Big -> long 0.0000... output)
PERCENT_DECIMALS = 70

# ─────────────────────────────────────────────────────────────
# Template (design)
# ─────────────────────────────────────────────────────────────
TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Scanner Monitor</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>

  <style>
    body {
      background: radial-gradient(circle at top, #111827 0, #020617 45%);
      color: #e5e7eb;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .glass {
      background: linear-gradient(145deg, rgba(15,23,42,.96), rgba(15,23,42,.85));
      border-radius: 1.25rem;
      border: 1px solid rgba(148,163,184,.35);
      box-shadow: 0 18px 45px rgba(15,23,42,.9);
      backdrop-filter: blur(20px);
    }
    .metric-card {
      border-radius: 1rem;
      background: radial-gradient(circle at top left, rgba(15,23,42,.95), rgba(15,23,42,.9));
      border: 1px solid rgba(55,65,81,.8);
    }
    .metric-label {
      font-size: .65rem;
      letter-spacing: .16em;
      text-transform: uppercase;
      color: #9ca3af;
    }
    .metric-main {
      font-size: 1.6rem;
      font-weight: 600;
    }
    .mono-box {
      background: #020617;
      border-radius: .75rem;
      border: 1px solid rgba(30,64,175,.6);
      font-size: .72rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .sys-label {
      font-size: .7rem;
      color: #9ca3af;
      text-transform: uppercase;
      letter-spacing: .16em;
    }
  </style>

  <script>
    async function fetchStatus() {
      try {
        const r = await fetch('/api/status');
        const d = await r.json();
        const g = d.generator || {};
        const s = d.system || {};

        // Counters
        document.getElementById('keys_session').textContent =
          (g.keys_tested || 0).toLocaleString('fr-CH');
        document.getElementById('keys_total').textContent =
          (g.total_keys_tested || 0).toLocaleString('fr-CH');

        // Speed
        document.getElementById('speed_sec').textContent =
          (Number(g.speed_keys_per_sec || 0)).toFixed(2);
        document.getElementById('speed_min').textContent =
          Math.round(Number(g.keys_per_minute || 0)).toLocaleString('fr-CH');
        document.getElementById('speed_day').textContent =
          Math.round(Number(g.keys_per_day || 0)).toLocaleString('fr-CH');

        // Hits / matches
        document.getElementById('btc_hits').textContent = g.btc_hits || 0;
        document.getElementById('btc_matches').textContent = g.btc_address_matches || 0;

        // Uptime
        document.getElementById('elapsed').textContent = g.elapsed_human || '-';

        // Percent (very long decimal string)
        document.getElementById('percent_tested').textContent = g.percent_tested_str || '-';

        // Last addresses (3 separate fields)
        const addrs = g.last_btc_addresses || {};
        document.getElementById('last_p2pkh').textContent = addrs.p2pkh || '-';
        document.getElementById('last_p2sh').textContent  = addrs.p2sh  || '-';
        document.getElementById('last_bech32').textContent = addrs.bech32 || '-';

        // System
        document.getElementById('cpu').textContent = s.cpu_text || '-';
        document.getElementById('ram').textContent = s.ram_text || '-';

      } catch (e) {
        console.error(e);
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

      <!-- Pourcentage keyspace -->
      <div class="grid grid-cols-1 gap-4 pt-2">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Pourcentage du keyspace testé</div>
          <div class="mt-2 mono-box p-3 text-[12px] tracking-tight text-indigo-200 break-all" id="percent_tested">-</div>
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

      <!-- Résultats -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Adresse DB</div>
          <div class="metric-main text-amber-300" id="btc_matches">-</div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Adresse sold</div>
          <div class="metric-main text-emerald-300" id="btc_hits">-</div>
        </div>
      </div>

      <!-- Dernières adresses (3 champs séparés) -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Dernière adresse · P2PKH</div>
          <div class="mono-box p-3 text-[11px] tracking-tight text-sky-200" id="last_p2pkh">-</div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Dernière adresse · P2SH</div>
          <div class="mono-box p-3 text-[11px] tracking-tight text-sky-200" id="last_p2sh">-</div>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Dernière adresse · Bech32</div>
          <div class="mono-box p-3 text-[11px] tracking-tight text-sky-200" id="last_bech32">-</div>
        </div>
      </div>

      <!-- Système -->
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
# Backend helpers
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
        "speed_keys_per_sec": 0.0,
        "elapsed_seconds": 0.0,
        "elapsed_human": "-",
        "keys_per_minute": 0.0,
        "keys_per_day": 0.0,
        "percent_tested_str": "0." + ("0" * PERCENT_DECIMALS) + " %",
        "last_btc_addresses": {"p2pkh": "", "p2sh": "", "bech32": ""},
    }


def format_percent_ultra_decimal(total_tested: int) -> str:
    """
    Return percent as very long fixed-decimal string like:
    0.000000000000...0035 %
    """
    # high precision so we can safely format many decimals
    getcontext().prec = 200

    if total_tested <= 0:
        return "0." + ("0" * PERCENT_DECIMALS) + " %"

    tested = Decimal(total_tested)
    n = Decimal(SECP256K1_N_INT)

    percent = (tested / n) * Decimal(100)
    # fixed decimal with many places (keeps the long 0s)
    return f"{percent:.{PERCENT_DECIMALS}f} %"


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
    total_tested = int(data.get("total_keys_tested", 0))

    # last addresses (3 formats)
    last_addrs = data.get("last_btc_addresses")
    if isinstance(last_addrs, dict):
        last_btc_addresses = {
            "p2pkh": last_addrs.get("p2pkh") or "",
            "p2sh": last_addrs.get("p2sh") or "",
            "bech32": last_addrs.get("bech32") or "",
        }
    else:
        # fallback: only one string exists
        last_btc_addresses = {"p2pkh": data.get("last_btc_address", "") or "", "p2sh": "", "bech32": ""}

    return {
        "keys_tested": int(data.get("keys_tested", 0)),
        "total_keys_tested": total_tested,
        "btc_hits": int(data.get("btc_hits", 0)),
        "btc_address_matches": int(data.get("btc_address_matches", 0)),
        "speed_keys_per_sec": speed,
        "elapsed_seconds": elapsed,
        "elapsed_human": human_readable_time(elapsed),
        "keys_per_minute": speed * 60,
        "keys_per_day": speed * 86400,
        "percent_tested_str": format_percent_ultra_decimal(total_tested),
        "last_btc_addresses": last_btc_addresses,
    }


def get_system_status():
    if psutil is None:
        return {"cpu_text": "-", "ram_text": "-"}

    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        return {
            "cpu_text": f"{cpu:.1f} %",
            "ram_text": f"{mem.used/1e9:.2f} / {mem.total/1e9:.2f} GB",
        }
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
        "timestamp": time.time(),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
