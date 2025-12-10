from flask import Flask, jsonify, render_template_string
import json
import os
import time

try:
    import psutil
except ImportError:
    psutil = None  # Le dashboard fonctionnera quand même sans psutil

app = Flask(__name__)

# Répertoires
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

# Fichier de status généré par btc_checker_db.py
GEN_STATUS = os.path.join(PARENT_DIR, "generator", "status.json")

TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Monitor</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <!-- Tailwind CSS -->
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

    .badge-live {
      font-size: 0.7rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      padding: 0.18rem 0.6rem;
      border-radius: 999px;
      border: 1px solid rgba(34, 197, 94, 0.7);
      background: radial-gradient(circle at top left, rgba(34, 197, 94, 0.18), transparent 70%);
      color: #bbf7d0;
    }

    .dot-live {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: #22c55e;
      box-shadow: 0 0 12px rgba(34, 197, 94, 0.9);
      animation: pulse 1.4s infinite;
    }

    @keyframes pulse {
      0%   { transform: scale(1);   opacity: 1; }
      60%  { transform: scale(1.8); opacity: 0; }
      100% { transform: scale(1);   opacity: 0; }
    }

    .mono-box {
      background: #020617;
      border-radius: 0.75rem;
      border: 1px solid rgba(30, 64, 175, 0.6);
      font-size: 0.7rem;
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

        const speed = gen.speed_keys_per_sec || 0;
        const kpm = gen.keys_per_minute || 0;
        const kpd = gen.keys_per_day || 0;

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

        document.getElementById('btc_hits').textContent = gen.btc_hits || 0;
        document.getElementById('btc_matches').textContent = gen.btc_address_matches || 0;
        document.getElementById('elapsed').textContent = gen.elapsed_human || '-';
        document.getElementById('last_addr').textContent = gen.last_btc_address || '-';
        document.getElementById('last_update').textContent = gen.last_update || '-';

        document.getElementById('cpu').textContent = sys.cpu_text || '-';
        document.getElementById('ram').textContent = sys.ram_text || '-';
        //document.getElementById('temp').textContent = sys.temp_text || '-';
      } catch (e) {
        console.error('Erreur fetch status:', e);
      }
    }

    document.addEventListener('DOMContentLoaded', () => {
      fetchStatus();
      setInterval(fetchStatus, 2000); // Refresh toutes les 2 secondes
    });
  </script>
</head>
<body class="min-h-screen">
  <div class="max-w-6xl mx-auto px-4 py-8">

    <!-- Header -->
    <div class="flex items-center justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl md:text-3xl font-semibold tracking-tight">
          <span class="text-slate-200">Scanner</span>
          <span class="text-slate-500"> · Monitor</span>
        </h1>
      </div>
    </div>

    <div class="glass p-5 md:p-6 space-y-6">

      <!-- Ligne 1 : Clés & vitesse -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés testées · session</div>
          <div class="metric-main text-emerald-400" id="keys_session">-</div>
          <p class="text-[11px] text-slate-500 mt-1">
            Depuis le dernier démarrage du générateur.
          </p>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés testées · total</div>
          <div class="metric-main text-sky-400" id="keys_total">-</div>
          <p class="text-[11px] text-slate-500 mt-1">
            Cumul historique (persisté dans total_keys_generator.json).
          </p>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Uptime · session</div>
          <div class="metric-main text-slate-100" id="elapsed">-</div>
          <p class="text-[11px] text-slate-500 mt-1">
            Temps écoulé depuis le lancement du générateur.
          </p>
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
          <p class="text-[11px] text-slate-500 mt-1">
            Vitesse instantanée calculée sur la session courante.
          </p>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés / minute</div>
          <div class="metric-main text-indigo-300">
            <span id="speed_min">-</span>
            <span class="text-sm text-slate-500 ml-1">keys/min</span>
          </div>
          <p class="text-[11px] text-slate-500 mt-1">
            Estimation basée sur la vitesse actuelle.
          </p>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés / jour</div>
          <div class="metric-main text-indigo-200">
            <span id="speed_day">-</span>
            <span class="text-sm text-slate-500 ml-1">keys/jour</span>
          </div>
          <p class="text-[11px] text-slate-500 mt-1">
            Estimation basée sur la vitesse actuelle.
          </p>
        </div>

      </div>

      <!-- Ligne 3 : Résultats BTC -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">

      <div class="metric-card p-4">
          <div class="metric-label mb-1">Adresse DB</div>
          <div class="metric-main text-amber-300" id="btc_matches">-</div>
          <p class="text-[11px] text-slate-500 mt-1">
            Nombre d'adresses générées qui matchent dans la base de donnée.
          </p>
        </div>

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Adresse sold</div>
          <div class="metric-main text-emerald-300" id="btc_hits">-</div>
          <p class="text-[11px] text-slate-500 mt-1">
            Solde vérifié avec API blockchain.
          </p>
        </div>

        

        <div class="metric-card p-4">
          <div class="metric-label mb-1">Dernière addresse générée</div>
          <div class="mt-2 mono-box p-3 text-[10px] tracking-tight text-sky-200 break-all" id="last_addr">-</div>
        </div>

      </div>

      <!-- Ligne 4 : Système -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 border-t border-slate-800/70">

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
    else:
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

    return {
        "keys_tested": int(data.get("keys_tested", 0)),
        "total_keys_tested": int(data.get("total_keys_tested", 0)),
        "btc_hits": int(data.get("btc_hits", 0)),
        "btc_address_matches": int(data.get("btc_address_matches", 0)),
        "last_btc_address": data.get("last_btc_address", ""),
        "speed_keys_per_sec": speed,
        "elapsed_seconds": elapsed,
        "elapsed_human": human_readable_time(elapsed),
        "last_update": data.get("last_update", "-"),
        "keys_per_minute": speed * 60,
        "keys_per_day": speed * 86400,
    }


def get_system_status():
    if psutil is None:
        return {
            "cpu_text": "psutil non installé",
            "ram_text": "-",
            "temp_text": "-",
        }

    try:
        cpu = psutil.cpu_percent(interval=0.0)
        mem = psutil.virtual_memory()
        used_gb = mem.used / (1024**3)
        total_gb = mem.total / (1024**3)
        ram_text = f"{used_gb:.1f} / {total_gb:.1f} GB ({mem.percent:.0f}%)"

        temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
        temp_str = "-"
        if temps:
            for name, entries in temps.items():
                if entries:
                    temp_str = f"{entries[0].current:.1f} °C ({name})"
                    break

        return {
            "cpu_text": f"{cpu:.1f} %",
            "ram_text": ram_text,
            "temp_text": temp_str,
        }

    except Exception:
        return {
            "cpu_text": "-",
            "ram_text": "-",
            "temp_text": "-",
        }


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
