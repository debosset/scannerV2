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

# secp256k1 keyspace
SECP256K1_N = int(
    "0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16
)

# Nombre de décimales visibles dans le % (ex: 0.0000...0035 %)
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
    body{
      background: radial-gradient(circle at top, #111827 0, #020617 45%);
      color:#e5e7eb;
      font-family:system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .glass{
      background: linear-gradient(145deg, rgba(15,23,42,.96), rgba(15,23,42,.85));
      border-radius: 1.25rem;
      border: 1px solid rgba(148,163,184,.35);
      box-shadow: 0 18px 45px rgba(15,23,42,.9);
      backdrop-filter: blur(20px);
    }
    .metric-card{
      border-radius: 1rem;
      background: radial-gradient(circle at top left, rgba(15,23,42,.95), rgba(15,23,42,.9));
      border: 1px solid rgba(55,65,81,.8);
    }
    .metric-label{
      font-size: .65rem;
      letter-spacing: .16em;
      text-transform: uppercase;
      color: #9ca3af;
    }
    .metric-main{
      font-size: 1.6rem;
      font-weight: 600;
    }
    .mono-box{
      background: #020617;
      border-radius: .75rem;
      border: 1px solid rgba(30,64,175,.6);
      font-size: .75rem;
      word-break: break-all;
    }
  </style>

  <script>
    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    async function fetchStatus(){
      try {
        const r = await fetch('/api/status');
        const d = await r.json();
        const g = d.generator || {};
        const s = d.system || {};

        setText('keys_session', (g.keys_tested || 0).toLocaleString('fr-CH'));
        setText('keys_total', (g.total_keys_tested || 0).toLocaleString('fr-CH'));
        setText('elapsed', g.elapsed_human || '-');

        setText('speed', (Number(g.speed_keys_per_sec || 0)).toFixed(2));
        setText('speed_min', Math.round(Number(g.keys_per_minute || 0)).toLocaleString('fr-CH'));
        setText('speed_day', Math.round(Number(g.keys_per_day || 0)).toLocaleString('fr-CH'));

        setText('btc_hits', g.btc_hits || 0);
        setText('btc_matches', g.btc_address_matches || 0);

        setText('percent', g.percent_tested_str || '-');

        const a = g.last_btc_addresses || {};
        setText('p2pkh', a.p2pkh || '-');
        setText('p2sh', a.p2sh || '-');
        setText('bech32', a.bech32 || '-');

        setText('cpu', s.cpu_text || '-');
        setText('ram', s.ram_text || '-');

      } catch(e) {
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

    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl md:text-3xl font-semibold tracking-tight">
        <span class="text-slate-200">Scanner</span>
        <span class="text-slate-500"> · Monitor</span>
      </h1>
      <a href="/db" class="text-sky-300 hover:text-sky-200 text-sm">DB info →</a>
    </div>

    <div class="glass p-5 md:p-6 space-y-6">

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

      <div class="metric-card p-4">
        <div class="metric-label mb-1">Pourcentage du keyspace testé</div>
        <div class="mono-box p-3 text-indigo-200" id="percent">-</div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Clés / seconde</div>
          <div class="metric-main text-indigo-400">
            <span id="speed">-</span>
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

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Dernière adresse · P2PKH</div>
          <div class="mono-box p-3 text-sky-200" id="p2pkh">-</div>
        </div>
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Dernière adresse · P2SH</div>
          <div class="mono-box p-3 text-sky-200" id="p2sh">-</div>
        </div>
        <div class="metric-card p-4">
          <div class="metric-label mb-1">Dernière adresse · Bech32</div>
          <div class="mono-box p-3 text-sky-200" id="bech32">-</div>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 border-t border-slate-800 pt-4">
        <div>
          <div class="metric-label mb-1">CPU</div>
          <div class="text-sm font-medium text-slate-100" id="cpu">-</div>
        </div>
        <div>
          <div class="metric-label mb-1">RAM</div>
          <div class="text-sm font-medium text-slate-100" id="ram">-</div>
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
    body{
      background: radial-gradient(circle at top, #111827 0, #020617 45%);
      color:#e5e7eb;
      font-family:system-ui;
    }
    .card{background:#0b1220;border:1px solid #334155;border-radius:1rem}
    .mono{background:#020617;border:1px solid #1e3a8a;border-radius:.75rem;font-size:.8rem;white-space:pre-wrap}
    .label{font-size:.65rem;letter-spacing:.16em;text-transform:uppercase;color:#9ca3af}
  </style>

  <script>
    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    async function loadDB(){
      try{
        const r = await fetch('/api/dbinfo');
        const d = await r.json();

        const meta = d.meta || {};
        setText('path', meta.path || '-');
        setText('size', (meta.size_mb ?? '-') + ' MB');
        setText('mtime', meta.mtime || '-');

        const counts = meta.table_counts || {};
        const tables = meta.tables || [];
        setText('tables', tables.length ? tables.map(t => `${t}: ${counts[t] ?? '?'}`).join('\\n') : '-');

        const items = (d.random && d.random.items) ? d.random.items : [];
        setText('random', items.length ? items.join('\\n') : '-');

        setText('err', meta.error || d.error || '-');
      }catch(e){
        console.error(e);
        setText('err', String(e));
      }
    }
    document.addEventListener('DOMContentLoaded', loadDB);
  </script>
</head>

<body class="min-h-screen p-6">
  <a href="/" class="text-sky-300 hover:text-sky-200">← retour monitor</a>

  <div class="card p-4 mt-4">
    <div class="label">DB path</div>
    <div class="mono p-3 mt-2" id="path">-</div>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
    <div class="card p-4">
      <div class="label">Taille</div>
      <div class="text-lg mt-1" id="size">-</div>
    </div>
    <div class="card p-4">
      <div class="label">Modifié</div>
      <div class="text-lg mt-1" id="mtime">-</div>
    </div>
  </div>

  <div class="card p-4 mt-4">
    <div class="label">Tables + COUNT</div>
    <pre class="mono p-3 mt-2" id="tables">-</pre>
  </div>

  <div class="card p-4 mt-4">
    <div class="label">10 adresses aléatoires</div>
    <pre class="mono p-3 mt-2" id="random">-</pre>
  </div>

  <div class="card p-4 mt-4">
    <div class="label">Erreur</div>
    <pre class="mono p-3 mt-2" id="err">-</pre>
  </div>
</body>
</html>
"""

# ============================================================
# HELPERS (Monitor)
# ============================================================
def human_time(sec: float) -> str:
    try:
        sec = int(sec)
    except Exception:
        return "-"
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def ultra_percent(total: int) -> str:
    getcontext().prec = 260
    if total <= 0:
        return "0." + ("0" * PERCENT_DECIMALS) + " %"
    p = (Decimal(total) / Decimal(SECP256K1_N)) * Decimal(100)
    return f"{p:.{PERCENT_DECIMALS}f} %"


def _default_gen_status():
    return {
        "keys_tested": 0,
        "total_keys_tested": 0,
        "btc_hits": 0,
        "btc_address_matches": 0,
        "speed_keys_per_sec": 0.0,
        "keys_per_minute": 0.0,
        "keys_per_day": 0.0,
        "elapsed_human": "-",
        "percent_tested_str": "0." + ("0" * PERCENT_DECIMALS) + " %",
        "last_btc_addresses": {"p2pkh": "", "p2sh": "", "bech32": ""},
    }


def load_generator_status():
    if not os.path.exists(GEN_STATUS):
        return _default_gen_status()

    try:
        with open(GEN_STATUS, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return _default_gen_status()

    speed = float(d.get("speed_keys_per_sec", 0.0))
    elapsed_seconds = float(d.get("elapsed_seconds", 0.0))
    total = int(d.get("total_keys_tested", 0))

    last_addrs = d.get("last_btc_addresses")
    if not isinstance(last_addrs, dict):
        last_addrs = {"p2pkh": d.get("last_btc_address", ""), "p2sh": "", "bech32": ""}

    return {
        "keys_tested": int(d.get("keys_tested", 0)),
        "total_keys_tested": total,
        "btc_hits": int(d.get("btc_hits", 0)),
        "btc_address_matches": int(d.get("btc_address_matches", 0)),
        "speed_keys_per_sec": speed,
        "keys_per_minute": speed * 60.0,
        "keys_per_day": speed * 86400.0,
        "elapsed_human": human_time(elapsed_seconds),
        "percent_tested_str": ultra_percent(total),
        "last_btc_addresses": {
            "p2pkh": last_addrs.get("p2pkh", "") or "",
            "p2sh": last_addrs.get("p2sh", "") or "",
            "bech32": last_addrs.get("bech32", "") or "",
        },
    }


def get_system_status():
    if not psutil:
        return {"cpu_text": "-", "ram_text": "-"}
    try:
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)
        return {
            "cpu_text": f"{cpu:.1f} %",
            "ram_text": f"{mem.used/1e9:.2f}/{mem.total/1e9:.2f} GB",
        }
    except Exception:
        return {"cpu_text": "-", "ram_text": "-"}


# ============================================================
# DB helpers (used only by /db)
# ============================================================
def get_db_meta():
    if not os.path.exists(GEN_DB):
        return {
            "path": GEN_DB,
            "exists": False,
            "size_mb": None,
            "mtime": None,
            "tables": [],
            "table_counts": {},
            "error": "DB introuvable",
        }

    st = os.stat(GEN_DB)
    meta = {
        "path": GEN_DB,
        "exists": True,
        "size_mb": round(st.st_size / (1024 * 1024), 2),
        "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "tables": [],
        "table_counts": {},
        "error": None,
    }

    try:
        conn = sqlite3.connect(GEN_DB)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        tables = [r[0] for r in cur.fetchall()]
        meta["tables"] = tables

        for t in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t};")
                meta["table_counts"][t] = int(cur.fetchone()[0])
            except Exception:
                meta["table_counts"][t] = None

        conn.close()
    except Exception as e:
        meta["error"] = str(e)

    return meta


def _detect_address_table(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        try:
            cur.execute(f"PRAGMA table_info({t});")
            cols = [r[1] for r in cur.fetchall()]
            if "address" in cols:
                return t
        except Exception:
            continue
    return None


def get_random_addresses(limit=10):
    if not os.path.exists(GEN_DB):
        return {"items": [], "error": "DB introuvable"}

    try:
        conn = sqlite3.connect(GEN_DB)
        cur = conn.cursor()

        table = _detect_address_table(conn)
        if not table:
            conn.close()
            return {"items": [], "error": "Aucune table avec colonne 'address' détectée."}

        # Nombre total de lignes
        cur.execute(f"SELECT COUNT(*) FROM {table};")
        total = cur.fetchone()[0]

        if total <= 0:
            conn.close()
            return {"items": []}

        items = []
        seen_offsets = set()
        attempts = 0

        while len(items) < limit and attempts < limit * 10:
            attempts += 1
            offset = random.randint(0, total - 1)
            if offset in seen_offsets:
                continue
            seen_offsets.add(offset)

            cur.execute(
                f"SELECT address FROM {table} LIMIT 1 OFFSET ?;",
                (offset,)
            )
            row = cur.fetchone()
            if row and row[0]:
                items.append(row[0])

        conn.close()
        return {"items": items, "table": table}

    except Exception as e:
        return {"items": [], "error": str(e)}



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
    meta = get_db_meta()
    rnd = get_random_addresses(limit=10) if meta.get("exists") else {"items": [], "error": meta.get("error")}
    return jsonify({
        "meta": meta,
        "random": rnd,
        "ts": time.time(),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
