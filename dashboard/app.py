from flask import Flask, jsonify, render_template_string
import json
import os
import time
import sqlite3
import random
from datetime import datetime
from decimal import Decimal, getcontext

try:
    import psutil
except ImportError:
    psutil = None

app = Flask(__name__)

# ============================================================
# PATHS
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

GEN_STATUS = os.path.join(PARENT_DIR, "generator", "status.json")

# DB utilisée UNIQUEMENT par la page /db (one-shot)
GEN_DB = os.path.join(PARENT_DIR, "generator", "bitcoin_addresses.db")
DB_TABLE = "btc_addresses"

# secp256k1 keyspace
SECP256K1_N = int(
    "0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16
)

# nombre de décimales pour le %
PERCENT_DECIMALS = 70

# ============================================================
# HTML – MONITOR
# ============================================================
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
  font-size: .75rem;
  word-break: break-all;
}
</style>

<script>
async function fetchStatus(){
  const r = await fetch('/api/status');
  const d = await r.json();
  const g = d.generator || {};
  const s = d.system || {};

  document.getElementById('keys_session').textContent =
    (g.keys_tested || 0).toLocaleString('fr-CH');

  document.getElementById('keys_total').textContent =
    (g.total_keys_tested || 0).toLocaleString('fr-CH');

  document.getElementById('elapsed').textContent = g.elapsed_human || '-';
  document.getElementById('speed').textContent =
    (g.speed_keys_per_sec || 0).toFixed(2);

  document.getElementById('btc_hits').textContent = g.btc_hits || 0;
  document.getElementById('btc_matches').textContent = g.btc_address_matches || 0;

  document.getElementById('percent').textContent =
    g.percent_tested_str || '-';

  const a = g.last_btc_addresses || {};
  document.getElementById('p2pkh').textContent = a.p2pkh || '-';
  document.getElementById('p2sh').textContent = a.p2sh || '-';
  document.getElementById('bech32').textContent = a.bech32 || '-';

  document.getElementById('cpu').textContent = s.cpu_text || '-';
  document.getElementById('ram').textContent = s.ram_text || '-';
}

document.addEventListener('DOMContentLoaded', () => {
  fetchStatus();
  setInterval(fetchStatus, 2000);
});
</script>
</head>

<body class="min-h-screen">
<div class="max-w-6xl mx-auto px-4 py-8">

<div class="flex justify-between mb-6">
<h1 class="text-3xl font-semibold">Scanner · Monitor</h1>
<a href="/db" class="text-sky-300">DB info →</a>
</div>

<div class="glass p-6 space-y-6">

<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
<div class="metric-card p-4">
<div class="metric-label">Clés testées · session</div>
<div class="metric-main text-emerald-400" id="keys_session">-</div>
</div>

<div class="metric-card p-4">
<div class="metric-label">Clés testées · total</div>
<div class="metric-main text-sky-400" id="keys_total">-</div>
</div>

<div class="metric-card p-4">
<div class="metric-label">Uptime</div>
<div class="metric-main" id="elapsed">-</div>
</div>
</div>

<div class="metric-card p-4">
<div class="metric-label">Pourcentage du keyspace testé</div>
<div class="mono-box p-3 text-indigo-200" id="percent">-</div>
</div>

<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
<div class="metric-card p-4">
<div class="metric-label">BTC matchs DB</div>
<div class="metric-main text-amber-300" id="btc_matches">-</div>
</div>

<div class="metric-card p-4">
<div class="metric-label">BTC hits</div>
<div class="metric-main text-emerald-300" id="btc_hits">-</div>
</div>
</div>

<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
<div class="metric-card p-4">
<div class="metric-label">Dernière · P2PKH</div>
<div class="mono-box p-3" id="p2pkh">-</div>
</div>
<div class="metric-card p-4">
<div class="metric-label">Dernière · P2SH</div>
<div class="mono-box p-3" id="p2sh">-</div>
</div>
<div class="metric-card p-4">
<div class="metric-label">Dernière · Bech32</div>
<div class="mono-box p-3" id="bech32">-</div>
</div>
</div>

<div class="grid grid-cols-1 md:grid-cols-2 gap-4 border-t border-slate-800 pt-4">
<div>
<div class="metric-label">CPU</div>
<div id="cpu">-</div>
</div>
<div>
<div class="metric-label">RAM</div>
<div id="ram">-</div>
</div>
</div>

</div>
</div>
</body>
</html>
"""

# ============================================================
# HTML – DB ONE SHOT
# ============================================================
DB_TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>DB info</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.tailwindcss.com"></script>
<style>
body{background:#020617;color:#e5e7eb;font-family:system-ui}
.card{background:#0b1220;border:1px solid #334155;border-radius:1rem}
.mono{background:#020617;border:1px solid #1e3a8a;border-radius:.75rem;font-size:.8rem}
</style>

<script>
async function loadDB(){
  const r = await fetch('/api/dbinfo');
  const d = await r.json();

  document.getElementById('path').textContent = d.meta.path || '-';
  document.getElementById('size').textContent = d.meta.size_mb + ' MB';
  document.getElementById('mtime').textContent = d.meta.mtime || '-';
  document.getElementById('tables').textContent =
    JSON.stringify(d.meta.table_counts, null, 2);

  document.getElementById('random').textContent =
    (d.random.items || []).join('\\n');
}
document.addEventListener('DOMContentLoaded', loadDB);
</script>
</head>

<body class="min-h-screen p-6">
<a href="/" class="text-sky-300">← retour monitor</a>

<div class="card p-4 mt-4">
<div>DB path</div>
<div class="mono p-3" id="path">-</div>
</div>

<div class="grid grid-cols-2 gap-4 mt-4">
<div class="card p-4">Taille<div id="size"></div></div>
<div class="card p-4">Modifié<div id="mtime"></div></div>
</div>

<div class="card p-4 mt-4">
<div>Tables</div>
<pre class="mono p-3" id="tables">-</pre>
</div>

<div class="card p-4 mt-4">
<div>10 adresses aléatoires</div>
<pre class="mono p-3" id="random">-</pre>
</div>
</body>
</html>
"""

# ============================================================
# HELPERS
# ============================================================
def human_time(sec):
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h: return f"{h}h {m:02d}m {s:02d}s"
    if m: return f"{m}m {s:02d}s"
    return f"{s}s"

def ultra_percent(total):
    getcontext().prec = 200
    if total <= 0:
        return "0." + ("0" * PERCENT_DECIMALS) + " %"
    p = (Decimal(total) / Decimal(SECP256K1_N)) * Decimal(100)
    return f"{p:.{PERCENT_DECIMALS}f} %"

def load_generator_status():
    if not os.path.exists(GEN_STATUS):
        return {}

    with open(GEN_STATUS, "r", encoding="utf-8") as f:
        d = json.load(f)

    speed = float(d.get("speed_keys_per_sec", 0))
    elapsed = float(d.get("elapsed_seconds", 0))
    total = int(d.get("total_keys_tested", 0))

    return {
        "keys_tested": d.get("keys_tested", 0),
        "total_keys_tested": total,
        "btc_hits": d.get("btc_hits", 0),
        "btc_address_matches": d.get("btc_address_matches", 0),
        "speed_keys_per_sec": speed,
        "elapsed_human": human_time(elapsed),
        "percent_tested_str": ultra_percent(total),
        "last_btc_addresses": d.get("last_btc_addresses", {}),
    }

def get_system_status():
    if not psutil:
        return {"cpu_text": "-", "ram_text": "-"}
    mem = psutil.virtual_memory()
    return {
        "cpu_text": f"{psutil.cpu_percent(0.1)} %",
        "ram_text": f"{mem.used/1e9:.2f}/{mem.total/1e9:.2f} GB",
    }

# ============================================================
# DB ONE SHOT
# ============================================================
def get_db_meta():
    if not os.path.exists(GEN_DB):
        return {"path": GEN_DB, "error": "DB absente"}

    st = os.stat(GEN_DB)
    conn = sqlite3.connect(GEN_DB)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cur.fetchall()]

    counts = {}
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            counts[t] = cur.fetchone()[0]
        except Exception:
            counts[t] = None

    conn.close()

    return {
        "path": GEN_DB,
        "size_mb": round(st.st_size / 1e6, 2),
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
        "table_counts": counts,
    }

def get_random_addresses(limit=10):
    conn = sqlite3.connect(GEN_DB)
    cur = conn.cursor()
    cur.execute(f"SELECT max(rowid) FROM {DB_TABLE}")
    max_id = cur.fetchone()[0] or 0

    items = set()
    while len(items) < limit and max_id:
        rid = random.randint(1, max_id)
        cur.execute(
            f"SELECT address FROM {DB_TABLE} WHERE rowid >= ? LIMIT 1", (rid,)
        )
        r = cur.fetchone()
        if r:
            items.add(r[0])

    conn.close()
    return {"items": list(items)}

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def index():
    return render_template_string(TEMPLATE)

@app.route("/api/status")
def api_status():
    return jsonify({
        "generator": load_generator_status(),
        "system": get_system_status(),
        "ts": time.time(),
    })

@app.route("/db")
def db_page():
    return render_template_string(DB_TEMPLATE)

@app.route("/api/dbinfo")
def api_dbinfo():
    return jsonify({
        "meta": get_db_meta(),
        "random": get_random_addresses(),
        "ts": time.time(),
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
