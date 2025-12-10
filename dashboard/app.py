from flask import Flask, jsonify, render_template_string
import json
import os
import time

try:
    import psutil
except ImportError:
    psutil = None  # le dashboard fonctionnera quand même sans psutil

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
  <title>Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com"></script>

  <style>
    body {
      background: #0f172a;
      color: #e5e7eb;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
  </style>

  <script>
    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();

        const gen = data.generator || {};
        const sys = data.system || {};

        // Générateur
        document.getElementById('keys_session').textContent = gen.keys_tested.toLocaleString('fr-CH');
        document.getElementById('keys_total').textContent = gen.total_keys_tested.toLocaleString('fr-CH');
        document.getElementById('btc_hits').textContent = gen.btc_hits;
        document.getElementById('btc_matches').textContent = gen.btc_address_matches;
        document.getElementById('speed').textContent = gen.speed_keys_per_sec.toFixed(2) + ' keys/sec';
        document.getElementById('elapsed').textContent = gen.elapsed_human;
        document.getElementById('last_addr').textContent = gen.last_btc_address || '-';
        document.getElementById('last_update').textContent = gen.last_update || '-';

        // Système
        document.getElementById('cpu').textContent = sys.cpu_text || '-';
        document.getElementById('ram').textContent = sys.ram_text || '-';
        //document.getElementById('temp').textContent = sys.temp_text || '-';
      } catch (e) {
        console.error('Erreur fetch status:', e);
      }
    }

    document.addEventListener('DOMContentLoaded', () => {
      fetchStatus();
      setInterval(fetchStatus, 5000); // toutes les 5s
    });
  </script>
</head>
<body class="min-h-screen">
  <div class="max-w-6xl mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-2">Dashboard</h1>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div class="bg-slate-800/80 rounded-2xl p-4 shadow">
        <h2 class="text-sm text-slate-400 mb-1">Clés testées (session)</h2>
        <p class="text-2xl font-semibold" id="keys_session">-</p>
      </div>
      <div class="bg-slate-800/80 rounded-2xl p-4 shadow">
        <h2 class="text-sm text-slate-400 mb-1">Total de clés testées</h2>
        <p class="text-2xl font-semibold" id="keys_total">-</p>
      </div>
      <div class="bg-slate-800/80 rounded-2xl p-4 shadow">
        <h2 class="text-sm text-slate-400 mb-1">Vitesse</h2>
        <p class="text-2xl font-semibold" id="speed">-</p>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div class="bg-emerald-900/70 rounded-2xl p-4 shadow">
        <h2 class="text-sm text-emerald-200 mb-1">BTC hits (balance &gt; 0)</h2>
        <p class="text-2xl font-semibold text-emerald-300" id="btc_hits">-</p>
      </div>
      <div class="bg-indigo-900/70 rounded-2xl p-4 shadow">
        <h2 class="text-sm text-indigo-200 mb-1">BTC matchs (adresse connue)</h2>
        <p class="text-2xl font-semibold text-indigo-300" id="btc_matches">-</p>
      </div>
      <div class="bg-slate-800/80 rounded-2xl p-4 shadow">
        <h2 class="text-sm text-slate-400 mb-1">Temps écoulé (session)</h2>
        <p class="text-2xl font-semibold" id="elapsed">-</p>
      </div>
    </div>

    <div class="bg-slate-800/80 rounded-2xl p-4 shadow mb-6">
      <h2 class="text-sm text-slate-400 mb-1">Dernière adresse BTC générée</h2>
      <p class="font-mono text-sm break-all bg-slate-900/80 p-3 rounded-xl mt-1" id="last_addr">-</p>
      <p class="text-xs text-slate-500 mt-2">Dernière mise à jour: <span id="last_update">-</span></p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div class="bg-slate-800/80 rounded-2xl p-4 shadow">
        <h2 class="text-sm text-slate-400 mb-1">CPU</h2>
        <p class="text-lg font-semibold" id="cpu">-</p>
      </div>
      <div class="bg-slate-800/80 rounded-2xl p-4 shadow">
        <h2 class="text-sm text-slate-400 mb-1">RAM</h2>
        <p class="text-lg font-semibold" id="ram">-</p>
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


def load_generator_status():
    """Charge le status du fichier generator/status.json"""
    if not os.path.exists(GEN_STATUS):
        return {
            "keys_tested": 0,
            "total_keys_tested": 0,
            "btc_hits": 0,
            "btc_address_matches": 0,
            "last_btc_address": "",
            "speed_keys_per_sec": 0.0,
            "elapsed_seconds": 0.0,
            "elapsed_human": "-",
            "last_update": None,
        }

    try:
        with open(GEN_STATUS, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {
            "keys_tested": 0,
            "total_keys_tested": 0,
            "btc_hits": 0,
            "btc_address_matches": 0,
            "last_btc_address": "",
            "speed_keys_per_sec": 0.0,
            "elapsed_seconds": 0.0,
            "elapsed_human": "-",
            "last_update": None,
        }

    # On normalise les champs pour éviter les KeyError
    keys_tested = int(data.get("keys_tested", 0))
    total_keys_tested = int(data.get("total_keys_tested", 0))
    btc_hits = int(data.get("btc_hits", 0))
    btc_matches = int(data.get("btc_address_matches", 0))
    last_addr = data.get("last_btc_address", "")
    speed = float(data.get("speed_keys_per_sec", 0.0))
    elapsed = float(data.get("elapsed_seconds", 0.0))
    last_update = data.get("last_update")

    return {
        "keys_tested": keys_tested,
        "total_keys_tested": total_keys_tested,
        "btc_hits": btc_hits,
        "btc_address_matches": btc_matches,
        "last_btc_address": last_addr,
        "speed_keys_per_sec": speed,
        "elapsed_seconds": elapsed,
        "elapsed_human": human_readable_time(elapsed),
        "last_update": last_update,
    }


def get_system_status():
    """Retourne quelques infos système (CPU, RAM, température)"""
    if psutil is None:
        return {
            "cpu_text": "psutil non installé",
            "ram_text": "-",
            "temp_text": "-",
        }

    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        used_gb = mem.used / (1024**3)
        total_gb = mem.total / (1024**3)
        ram_text = f"{used_gb:.1f} / {total_gb:.1f} GB ({mem.percent:.0f}%)"

        temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
        temp_str = "-"
        if temps:
            # On prend le premier capteur dispo
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
    gen_status = load_generator_status()
    sys_status = get_system_status()
    return jsonify({
        "generator": gen_status,
        "system": sys_status,
        "timestamp": time.time(),
    })


if __name__ == "__main__":
    # Lancement en mode "prod simple"
    app.run(host="0.0.0.0", port=5000, debug=False)