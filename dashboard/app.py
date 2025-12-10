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
  <title>Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com"></script>

  <style>
    :root {
      --bg-main: #020617;
      --bg-gradient: radial-gradient(circle at top left, #0f172a, #020617 55%);
      --neon-cyan: #22d3ee;
      --neon-purple: #a855f7;
      --neon-pink: #ec4899;
      --card-bg: rgba(15, 23, 42, 0.85);
      --card-border: rgba(56, 189, 248, 0.4);
    }

    body {
      background: var(--bg-gradient);
      color: #e5e7eb;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    .neon-title {
      background: linear-gradient(120deg, var(--neon-cyan), var(--neon-purple), var(--neon-pink));
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
      text-shadow: 0 0 18px rgba(236, 72, 153, 0.25);
    }

    .neon-card {
      background: var(--card-bg);
      border-radius: 1.25rem;
      border: 1px solid rgba(148, 163, 184, 0.25);
      box-shadow:
        0 0 25px rgba(15, 23, 42, 0.9),
        0 0 18px rgba(56, 189, 248, 0.12);
      backdrop-filter: blur(16px);
    }

    .neon-card-accent {
      border-image: linear-gradient(135deg, var(--neon-cyan), var(--neon-purple)) 1;
      border-width: 1px;
      border-style: solid;
      box-shadow:
        0 0 25px rgba(15, 23, 42, 0.9),
        0 0 22px rgba(129, 140, 248, 0.38);
    }

    .neon-chip {
      font-size: 0.7rem;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      border-radius: 999px;
      padding: 0.2rem 0.6rem;
      background: radial-gradient(circle, rgba(56, 189, 248, 0.2), transparent 65%);
      border: 1px solid rgba(56, 189, 248, 0.6);
      color: #e0f2fe;
    }

    .glow-text {
      text-shadow:
        0 0 12px rgba(34, 211, 238, 0.6),
        0 0 28px rgba(129, 140, 248, 0.4);
    }

    .mono-box {
      background: radial-gradient(circle at top left, rgba(15, 23, 42, 0.9), rgba(15, 23, 42, 0.98));
      box-shadow: 0 0 18px rgba(15, 23, 42, 0.95);
    }

    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--neon-cyan);
      box-shadow: 0 0 10px rgba(34, 211, 238, 0.9);
      animation: pulse 1.6s infinite;
    }

    @keyframes pulse {
      0% {
        transform: scale(1);
        opacity: 1;
      }
      70% {
        transform: scale(1.8);
        opacity: 0;
      }
      100% {
        transform: scale(1);
        opacity: 0;
      }
    }

    .scan-grid {
      background-image: linear-gradient(rgba(30, 64, 175, 0.18) 1px, transparent 1px),
                        linear-gradient(90deg, rgba(30, 64, 175, 0.18) 1px, transparent 1px);
      background-size: 22px 22px;
      opacity: 0.25;
      pointer-events: none;
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
        document.getElementById('btc_hits').textContent = gen.btc_hits || 0;
        document.getElementById('btc_matches').textContent = gen.btc_address_matches || 0;
        document.getElementById('speed').textContent = speed.toFixed(2) + ' keys/sec';
        document.getElementById('elapsed').textContent = gen.elapsed_human || '-';
        document.getElementById('last_addr').textContent = gen.last_btc_address || '-';
        document.getElementById('last_update').textContent = gen.last_update || '-';

        document.getElementById('keys_per_min').textContent =
          kpm.toLocaleString('fr-CH', { maximumFractionDigits: 0 });

        document.getElementById('keys_per_day').textContent =
          kpd.toLocaleString('fr-CH', { maximumFractionDigits: 0 });

        document.getElementById('cpu').textContent = sys.cpu_text || '-';
        document.getElementById('ram').textContent = sys.ram_text || '-';
        document.getElementById('temp').textContent = sys.temp_text || '-';
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
<body class="min-h-screen relative overflow-hidden">
  <div class="scan-grid absolute inset-0 pointer-events-none"></div>

  <div class="max-w-6xl mx-auto px-4 py-8 relative z-10">

    <div class="flex items-center justify-between gap-4 mb-6">
      <div>
        <h1 class="text-3xl md:text-4xl font-bold neon-title mb-2">
          Dashboard
        </h1>
        <p class="text-xs md:text-sm text-slate-400">
          Source:&nbsp;
          <code class="bg-slate-900/80 px-2 py-1 rounded border border-slate-700/60 text-[10px] md:text-xs">
            generator/status.json
          </code>
        </p>
      </div>
      <div class="flex flex-col items-end gap-2">
        <div class="flex items-center gap-2">
          <span class="pulse-dot"></span>
          <span class="text-[11px] uppercase tracking-[0.18em] text-sky-300">
            Scanner actif
          </span>
        </div>
        <span class="neon-chip">
          BTC ONLY • MONITOR
        </span>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">

      <div class="neon-card p-4">
        <h2 class="text-xs text-slate-400 uppercase tracking-widest">Clés testées (session)</h2>
        <p class="text-3xl font-semibold glow-text" id="keys_session">-</p>
      </div>

      <div class="neon-card p-4">
        <h2 class="text-xs text-slate-400 uppercase tracking-widest">Total de clés testées</h2>
        <p class="text-3xl font-semibold text-sky-300" id="keys_total">-</p>
      </div>

      <div class="neon-card neon-card-accent p-4">
        <h2 class="text-xs text-slate-300 uppercase tracking-widest">Vitesse instantanée</h2>
        <p class="text-3xl font-semibold text-sky-200 glow-text" id="speed">-</p>
      </div>

    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">

      <div class="neon-card p-4">
        <h2 class="text-xs text-yellow-200 uppercase tracking-widest">Keys / minute</h2>
        <p class="text-3xl font-semibold text-yellow-300" id="keys_per_min">-</p>
      </div>

      <div class="neon-card p-4">
        <h2 class="text-xs text-orange-200 uppercase tracking-widest">Keys / jour</h2>
        <p class="text-3xl font-semibold text-orange-300" id="keys_per_day">-</p>
      </div>

      <div class="neon-card p-4">
        <h2 class="text-xs text-slate-300 uppercase tracking-widest">Uptime (session)</h2>
        <p class="text-3xl font-semibold text-slate-100" id="elapsed">-</p>
      </div>

    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">

      <div class="neon-card p-4">
        <h2 class="text-xs text-emerald-200 uppercase tracking-widest">BTC hits (balance > 0)</h2>
        <p class="text-3xl font-semibold text-emerald-300" id="btc_hits">-</p>
      </div>

      <div class="neon-card p-4">
        <h2 class="text-xs text-indigo-200 uppercase tracking-widest">BTC matchs (adresse connue)</h2>
        <p class="text-3xl font-semibold text-indigo-300" id="btc_matches">-</p>
      </div>

    </div>

    <div class="neon-card p-4 mb-6">
      <h2 class="text-xs text-slate-300 uppercase tracking-widest mb-1">Dernière adresse BTC générée</h2>
      <p class="font-mono text-xs break-all mono-box p-3 rounded-xl border border-slate-800" id="last_addr">-</p>
      <p class="text-xs text-slate-500 mt-2">Dernière mise à jour:&nbsp;<span id="last_update">-</span></p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">

      <div class="neon-card p-4">
        <h2 class="text-xs text-slate-400 uppercase tracking-widest">CPU</h2>
        <p class="text-xl font-semibold text-sky-200" id="cpu">-</p>
      </div>

      <div class="neon-card p-4">
        <h2 class="text-xs text-slate-400 uppercase tracking-widest">RAM</h2>
        <p class="text-xl font-semibold" id="ram">-</p>
      </div>

      <div class="neon-card p-4">
        <h2 class="text-xs text-slate-400 uppercase tracking-widest">Température</h2>
        <p class="text-xl font-semibold" id="temp">-</p>
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
