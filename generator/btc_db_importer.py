#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bitcoin Address Database Importer (SQLite) - Low RAM / VPS safe

Télécharge et reconstruit une base SQLite contenant des adresses BTC.

Objectifs:
- Fonctionner sur petit VPS (1-2 GB RAM) sans se faire tuer par l'OOM killer
- Rebuild dans une DB temporaire puis swap atomique (DB jamais partielle)
- Import par lots, transactions, pragmas sqlite "low memory"
- Cron-safe (chemins absolus basés sur le dossier du script)

Usages:
- Manuel:        python3 btc_db_importer.py
- Daily/cron:    python3 btc_db_importer.py --update-daily
- Test lookup:   python3 btc_db_importer.py --test
- Plus rapide:   python3 btc_db_importer.py --update-daily --batch-size 10000
- VACUUM (lourd):python3 btc_db_importer.py --update-daily --vacuum
"""

from __future__ import annotations

import argparse
import gzip
import os
import sqlite3
import sys
import time
from typing import Iterable, List, Optional, Tuple

import requests


# -------------------- Defaults (LOW RAM) --------------------
BTC_ADDRESSES_URL = "http://addresses.loyce.club/Bitcoin_addresses_LATEST.txt.gz"

DEFAULT_BATCH_SIZE = 5000          # Safe pour petit VPS
PROGRESS_EVERY = 250_000           # Print toutes les X insertions
HTTP_TIMEOUT = (10, 180)           # connect/read
HTTP_RETRIES = 3
HTTP_CHUNK_SIZE = 1024 * 1024      # 1MB
SQLITE_TIMEOUT_SEC = 60.0          # en cas de lock


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str, log_file: Optional[str]) -> None:
    line = f"[{utc_iso()}] {msg}"
    print(line, flush=True)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def base_paths() -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return {
        "base_dir": base_dir,
        "cache_gz": os.path.join(base_dir, "bitcoin_addresses.txt.gz"),
        "db": os.path.join(base_dir, "bitcoin_addresses.db"),
        "db_tmp": os.path.join(base_dir, "bitcoin_addresses.db.tmp"),
        "log": os.path.join(base_dir, "btc_db_importer.log"),
    }


# -------------------- Download --------------------
def download_file(url: str, dest_path: str, force: bool, log_file: Optional[str]) -> str:
    if os.path.exists(dest_path) and not force:
        log(f"[Info] Cache présent, téléchargement ignoré: {dest_path}", log_file)
        return dest_path

    tmp_part = dest_path + ".part"
    if os.path.exists(tmp_part):
        try:
            os.remove(tmp_part)
        except Exception:
            pass

    last_err: Optional[Exception] = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            log(f"[Info] Téléchargement ({attempt}/{HTTP_RETRIES}) : {url}", log_file)
            t0 = time.time()

            with requests.get(url, stream=True, timeout=HTTP_TIMEOUT) as r:
                r.raise_for_status()
                total_size = int(r.headers.get("content-length", 0))
                downloaded = 0

                with open(tmp_part, "wb") as f:
                    for chunk in r.iter_content(chunk_size=HTTP_CHUNK_SIZE):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)

                        # logs discrets
                        if total_size > 0 and downloaded % (100 * 1024 * 1024) < HTTP_CHUNK_SIZE:
                            pct = downloaded / total_size * 100
                            log(f"[Info] Download ~{pct:.1f}% ({downloaded/1024/1024:.1f} MB)", log_file)

            os.replace(tmp_part, dest_path)
            log(f"[Info] Téléchargement OK: {dest_path} ({downloaded/1024/1024:.1f} MB) en {time.time()-t0:.1f}s", log_file)
            return dest_path

        except Exception as e:
            last_err = e
            log(f"[Warn] Download échoué tentative {attempt}: {e}", log_file)
            time.sleep(2 * attempt)

    if os.path.exists(tmp_part):
        try:
            os.remove(tmp_part)
        except Exception:
            pass

    raise RuntimeError(f"Échec téléchargement après {HTTP_RETRIES} tentatives: {last_err}")


# -------------------- SQLite --------------------
def connect_db(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SEC)


def apply_import_pragmas_low_ram(conn: sqlite3.Connection) -> None:
    """
    Pragmas "low RAM".
    OFF/Fast: OK car on rebuild une DB temporaire (et on swap si OK).
    """
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = OFF;")
    cur.execute("PRAGMA synchronous = OFF;")
    # IMPORTANT: FILE plutôt que MEMORY pour éviter gros pics RAM
    cur.execute("PRAGMA temp_store = FILE;")
    # Cache plus petit -> moins de RAM
    # cache_size en "pages". Valeur négative = KiB.
    cur.execute("PRAGMA cache_size = -20000;")  # ~20MB de cache
    cur.execute("PRAGMA locking_mode = EXCLUSIVE;")
    conn.commit()


def apply_runtime_pragmas_safe(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = DELETE;")
    cur.execute("PRAGMA synchronous = FULL;")
    cur.execute("PRAGMA temp_store = DEFAULT;")
    cur.execute("PRAGMA locking_mode = NORMAL;")
    conn.commit()


def create_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # PRIMARY KEY + WITHOUT ROWID => déjà indexé, pas besoin d'index supplémentaire
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS btc_addresses (
            address TEXT PRIMARY KEY NOT NULL
        ) WITHOUT ROWID;
        """
    )
    conn.commit()


def iter_gz_lines(path: str) -> Iterable[str]:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            yield line


def import_addresses(conn: sqlite3.Connection, gz_path: str, batch_size: int, log_file: Optional[str]) -> int:
    log(f"[Info] Import depuis: {gz_path}", log_file)
    log(f"[Info] Batch size: {batch_size:,}", log_file)

    cur = conn.cursor()
    insert_sql = "INSERT OR IGNORE INTO btc_addresses(address) VALUES (?);"

    total = 0
    batch: List[Tuple[str]] = []

    t0 = time.time()
    cur.execute("BEGIN;")
    try:
        for line in iter_gz_lines(gz_path):
            addr = line.strip()
            if not addr:
                continue

            batch.append((addr,))
            if len(batch) >= batch_size:
                cur.executemany(insert_sql, batch)
                total += len(batch)
                batch.clear()

                # commit "chunk" pour limiter RAM/temp
                cur.execute("COMMIT;")
                cur.execute("BEGIN;")

                if total % PROGRESS_EVERY == 0:
                    elapsed = time.time() - t0
                    speed = total / elapsed if elapsed > 0 else 0.0
                    log(f"[Info] Importé: {total:,}  |  {speed:,.0f} addr/sec", log_file)

        if batch:
            cur.executemany(insert_sql, batch)
            total += len(batch)
            batch.clear()

        cur.execute("COMMIT;")

    except Exception:
        cur.execute("ROLLBACK;")
        raise

    elapsed = time.time() - t0
    speed = total / elapsed if elapsed > 0 else 0.0
    log(f"[Info] Import terminé: {total:,} en {elapsed/60:.1f} min  |  {speed:,.0f} addr/sec", log_file)
    return total


def analyze_only(conn: sqlite3.Connection, log_file: Optional[str]) -> None:
    log("[Info] ANALYZE…", log_file)
    t0 = time.time()
    cur = conn.cursor()
    cur.execute("ANALYZE;")
    conn.commit()
    log(f"[Info] ANALYZE terminé en {time.time()-t0:.1f}s", log_file)


def vacuum(conn: sqlite3.Connection, log_file: Optional[str]) -> None:
    """
    VACUUM = lourd (disque + parfois RAM). À activer uniquement si tu as swap / disque OK.
    """
    log("[Info] VACUUM… (peut être long)", log_file)
    t0 = time.time()
    cur = conn.cursor()
    cur.execute("VACUUM;")
    conn.commit()
    log(f"[Info] VACUUM terminé en {time.time()-t0:.1f}s", log_file)


def db_stats(db_path: str) -> dict:
    size_mb = os.path.getsize(db_path) / 1024 / 1024 if os.path.exists(db_path) else 0.0
    conn = connect_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM btc_addresses;")
        count = int(cur.fetchone()[0])
    finally:
        conn.close()
    return {"count": count, "size_mb": size_mb}


def test_lookup(db_path: str, test_address: str, log_file: Optional[str]) -> None:
    log("=== Test lookup speed ===", log_file)
    log(f"Adresse test: {test_address}", log_file)

    conn = connect_db(db_path)
    try:
        cur = conn.cursor()

        t0 = time.time()
        cur.execute("SELECT 1 FROM btc_addresses WHERE address = ? LIMIT 1;", (test_address,))
        found = cur.fetchone() is not None
        one_ms = (time.time() - t0) * 1000

        log(f"Résultat: {'TROUVÉE' if found else 'NON TROUVÉE'}", log_file)
        log(f"Lookup 1x: {one_ms:.3f} ms", log_file)

        loops = 200
        t0 = time.time()
        for _ in range(loops):
            cur.execute("SELECT 1 FROM btc_addresses WHERE address = ? LIMIT 1;", (test_address,))
            cur.fetchone()
        elapsed = time.time() - t0
        avg_ms = (elapsed / loops) * 1000
        rps = 1000 / avg_ms if avg_ms > 0 else 0

        log(f"Moyenne {loops}x: {avg_ms:.3f} ms  |  ~{rps:,.0f} lookups/sec", log_file)
    finally:
        conn.close()


# -------------------- Rebuild (temp + swap) --------------------
def rebuild_database(
    url: str,
    cache_gz: str,
    db_path: str,
    db_tmp_path: str,
    force_download: bool,
    keep_gz: bool,
    batch_size: int,
    do_vacuum: bool,
    log_file: Optional[str],
) -> int:
    log("============================================================", log_file)
    log("=== Rebuild BTC SQLite DB (LOW RAM, atomic swap) ===", log_file)
    log("============================================================", log_file)

    gz_path = download_file(url, cache_gz, force=force_download, log_file=log_file)

    # Nettoyage ancien tmp
    if os.path.exists(db_tmp_path):
        try:
            os.remove(db_tmp_path)
        except Exception:
            pass

    log(f"[Info] Création DB tmp: {db_tmp_path}", log_file)
    conn = connect_db(db_tmp_path)
    try:
        apply_import_pragmas_low_ram(conn)
        create_schema(conn)
        total = import_addresses(conn, gz_path, batch_size=batch_size, log_file=log_file)

        # ANALYZE toujours; VACUUM optionnel
        analyze_only(conn, log_file)
        if do_vacuum:
            vacuum(conn, log_file)

        apply_runtime_pragmas_safe(conn)
    finally:
        conn.close()

    log(f"[Info] Swap atomique: {db_tmp_path} -> {db_path}", log_file)
    os.replace(db_tmp_path, db_path)

    if not keep_gz and os.path.exists(gz_path):
        try:
            os.remove(gz_path)
            log(f"[Info] Cache supprimé: {gz_path}", log_file)
        except Exception as e:
            log(f"[Warn] Impossible de supprimer le cache: {e}", log_file)

    stats = db_stats(db_path)
    log(f"[Info] DB OK: {db_path}", log_file)
    log(f"[Info] Adresses: {stats['count']:,}", log_file)
    log(f"[Info] Taille: {stats['size_mb']:.1f} MB", log_file)
    return total


def main() -> int:
    paths = base_paths()

    p = argparse.ArgumentParser(description="Importer/rebuilder une DB SQLite d'adresses BTC (low RAM).")
    p.add_argument("--update-daily", action="store_true", help="Mode cron: force download + rebuild.")
    p.add_argument("--force-download", action="store_true", help="Force téléchargement du .gz.")
    p.add_argument("--keep-gz", action="store_true", help="Garde le .gz après import.")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Taille des lots d'insertion.")
    p.add_argument("--vacuum", action="store_true", help="Fait VACUUM (lourd).")
    p.add_argument("--test", action="store_true", help="Fait un test lookup après rebuild.")
    p.add_argument("--test-address", default="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", help="Adresse utilisée pour le test.")
    p.add_argument("--no-log-file", action="store_true", help="N'écrit pas de fichier log (stdout uniquement).")

    args = p.parse_args()

    log_file = None if args.no_log_file else paths["log"]

    # update-daily => force download
    force_download = args.force_download or args.update_daily

    try:
        rebuild_database(
            url=BTC_ADDRESSES_URL,
            cache_gz=paths["cache_gz"],
            db_path=paths["db"],
            db_tmp_path=paths["db_tmp"],
            force_download=force_download,
            keep_gz=args.keep_gz,
            batch_size=max(1000, int(args.batch_size)),
            do_vacuum=bool(args.vacuum),
            log_file=log_file,
        )

        if args.test:
            test_lookup(paths["db"], args.test_address, log_file)

        log("[OK] Terminé.", log_file)
        return 0

    except Exception as e:
        log(f"[ERROR] {e}", log_file)
        return 1


if __name__ == "__main__":
    sys.exit(main())
