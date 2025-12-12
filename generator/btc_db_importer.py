#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bitcoin Address Database Importer (SQLite)
Télécharge et importe une liste d'adresses Bitcoin dans SQLite.

Optimisations / fiabilité :
- Chemins absolus basés sur le dossier du script (cron-safe)
- Download robuste (timeout + retries)
- Import en transactions + pragmas rapides
- Rebuild dans un .tmp puis swap atomique (os.replace)
- Pas d'index redondant (PRIMARY KEY + WITHOUT ROWID suffit)
"""

from __future__ import annotations

import argparse
import gzip
import os
import sqlite3
import sys
import time
from typing import Optional, Iterable, List, Tuple

import requests


# --------- Config ---------
BTC_ADDRESSES_URL = "http://addresses.loyce.club/Bitcoin_addresses_LATEST.txt.gz"

DEFAULT_BATCH_SIZE = 50_000          # Ajustable (10k ok, 50k souvent plus rapide)
PROGRESS_EVERY = 500_000             # Affichage progression toutes les X lignes
HTTP_TIMEOUT = (10, 180)             # (connect timeout, read timeout)
HTTP_RETRIES = 3
HTTP_CHUNK_SIZE = 1024 * 1024        # 1MB chunks
SQLITE_TIMEOUT_SEC = 60.0            # si DB lock (rare en rebuild)


def now_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str, log_file: Optional[str] = None) -> None:
    line = f"[{now_utc_iso()}] {msg}"
    print(line, flush=True)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # ne pas casser le job pour un problème de log disque
            pass


def script_paths(base_dir: str) -> dict:
    return {
        "base_dir": base_dir,
        "cache_gz": os.path.join(base_dir, "bitcoin_addresses.txt.gz"),
        "db": os.path.join(base_dir, "bitcoin_addresses.db"),
        "db_tmp": os.path.join(base_dir, "bitcoin_addresses.db.tmp"),
        "log": os.path.join(base_dir, "btc_db_importer.log"),
    }


# --------- Download ---------
def download_btc_addresses(url: str, dest_path: str, force: bool, log_file: Optional[str]) -> str:
    if os.path.exists(dest_path) and not force:
        log(f"[Info] Cache présent, téléchargement ignoré: {dest_path}", log_file)
        return dest_path

    tmp_path = dest_path + ".part"

    # Nettoyage d'un ancien .part
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
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

                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=HTTP_CHUNK_SIZE):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            pct = (downloaded / total_size) * 100
                            # print léger (sans spammer)
                            if downloaded % (50 * 1024 * 1024) < HTTP_CHUNK_SIZE:
                                log(f"[Info] Download: {pct:.1f}% ({downloaded/1024/1024:.1f} MB)", log_file)

            os.replace(tmp_path, dest_path)
            elapsed = time.time() - t0
            log(f"[Info] Téléchargement terminé: {dest_path} ({downloaded/1024/1024:.1f} MB) en {elapsed:.1f}s", log_file)
            return dest_path

        except Exception as e:
            last_err = e
            log(f"[Warn] Échec download tentative {attempt}: {e}", log_file)
            time.sleep(2 * attempt)

    # échec total
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass
    raise RuntimeError(f"Échec du téléchargement après {HTTP_RETRIES} tentatives: {last_err}")


# --------- SQLite helpers ---------
def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT_SEC)
    return conn


def apply_import_pragmas(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # Import rapide (acceptable pour rebuild)
    cur.execute("PRAGMA journal_mode = OFF;")
    cur.execute("PRAGMA synchronous = OFF;")
    cur.execute("PRAGMA temp_store = MEMORY;")
    cur.execute("PRAGMA cache_size = 200000;")  # ~200k pages (SQLite ajuste), peut accélérer
    cur.execute("PRAGMA locking_mode = EXCLUSIVE;")
    conn.commit()


def apply_runtime_pragmas(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # Mode runtime normal (plus sûr)
    cur.execute("PRAGMA journal_mode = DELETE;")
    cur.execute("PRAGMA synchronous = FULL;")
    cur.execute("PRAGMA temp_store = DEFAULT;")
    cur.execute("PRAGMA locking_mode = NORMAL;")
    conn.commit()


def create_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS btc_addresses (
            address TEXT PRIMARY KEY NOT NULL
        ) WITHOUT ROWID;
        """
    )
    conn.commit()


def iter_gz_lines(gz_path: str) -> Iterable[str]:
    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            yield line


def import_addresses(gz_path: str, conn: sqlite3.Connection, batch_size: int, log_file: Optional[str]) -> int:
    log(f"[Info] Import SQLite depuis: {gz_path}", log_file)
    log(f"[Info] Batch size: {batch_size:,}", log_file)
    t0 = time.time()

    cur = conn.cursor()

    insert_sql = "INSERT OR IGNORE INTO btc_addresses(address) VALUES (?);"
    batch: List[Tuple[str]] = []
    total = 0
    line_count = 0

    # Transaction globale + commits par lots (rapide + mémoire stable)
    cur.execute("BEGIN;")
    try:
        for line in iter_gz_lines(gz_path):
            line_count += 1
            addr = line.strip()
            if not addr:
                continue

            batch.append((addr,))
            if len(batch) >= batch_size:
                cur.executemany(insert_sql, batch)
                total += len(batch)
                batch.clear()

                cur.execute("COMMIT;")
                cur.execute("BEGIN;")

                if total % PROGRESS_EVERY == 0:
                    elapsed = time.time() - t0
                    speed = total / elapsed if elapsed > 0 else 0.0
                    log(f"[Info] Importé: {total:,} adresses  |  {speed:,.0f} addr/sec", log_file)

        # dernier lot
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
    log(f"[Info] Import terminé: {total:,} adresses en {elapsed/60:.1f} min  |  {speed:,.0f} addr/sec", log_file)
    return total


def vacuum_analyze(conn: sqlite3.Connection, log_file: Optional[str]) -> None:
    log("[Info] VACUUM + ANALYZE…", log_file)
    t0 = time.time()
    cur = conn.cursor()
    cur.execute("ANALYZE;")
    # VACUUM peut être long, mais rend la DB plus compacte/rapide ensuite
    cur.execute("VACUUM;")
    conn.commit()
    log(f"[Info] VACUUM/ANALYZE terminé en {time.time()-t0:.1f}s", log_file)


def db_stats(db_path: str) -> dict:
    conn = connect_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM btc_addresses;")
        count = int(cur.fetchone()[0])
    finally:
        conn.close()

    size_mb = os.path.getsize(db_path) / 1024 / 1024 if os.path.exists(db_path) else 0.0
    return {"count": count, "size_mb": size_mb}


def test_lookup_speed(db_path: str, test_address: str, log_file: Optional[str]) -> None:
    log("=== Test lookup speed ===", log_file)
    log(f"Adresse test: {test_address}", log_file)

    conn = connect_db(db_path)
    try:
        cur = conn.cursor()

        t0 = time.time()
        cur.execute("SELECT 1 FROM btc_addresses WHERE address = ? LIMIT 1;", (test_address,))
        found = cur.fetchone() is not None
        one = (time.time() - t0) * 1000.0

        log(f"Résultat: {'TROUVÉE' if found else 'NON TROUVÉE'}", log_file)
        log(f"Temps lookup 1x: {one:.3f} ms", log_file)

        loops = 200
        t0 = time.time()
        for _ in range(loops):
            cur.execute("SELECT 1 FROM btc_addresses WHERE address = ? LIMIT 1;", (test_address,))
            cur.fetchone()
        elapsed = time.time() - t0
        avg_ms = (elapsed / loops) * 1000.0
        rps = 1000.0 / avg_ms if avg_ms > 0 else 0.0

        log(f"Temps moyen ({loops}): {avg_ms:.3f} ms  |  ~{rps:,.0f} lookups/sec", log_file)
    finally:
        conn.close()


# --------- Main workflow ---------
def rebuild_database(
    url: str,
    cache_gz: str,
    db_path: str,
    db_tmp_path: str,
    batch_size: int,
    force_download: bool,
    keep_gz: bool,
    do_vacuum: bool,
    log_file: Optional[str],
) -> int:
    log("============================================================", log_file)
    log("=== Bitcoin DB Importer (rebuild + atomic swap) ===", log_file)
    log("============================================================", log_file)

    # download
    gz_path = download_btc_addresses(url, cache_gz, force_download, log_file)

    # Nettoyer une vieille tmp DB
    if os.path.exists(db_tmp_path):
        try:
            os.remove(db_tmp_path)
        except Exception:
            pass

    # build temp db
    log(f"[Info] Rebuild DB temporaire: {db_tmp_path}", log_file)
    conn = connect_db(db_tmp_path)
    try:
        apply_import_pragmas(conn)
        create_schema(conn)
        total = import_addresses(gz_path, conn, batch_size, log_file)

        if do_vacuum:
            vacuum_analyze(conn, log_file)
        else:
            # Au moins analyze pour le query planner
            cur = conn.cursor()
            cur.execute("ANALYZE;")
            conn.commit()

        apply_runtime_pragmas(conn)
    finally:
        conn.close()

    # swap atomique
    log(f"[Info] Swap atomique -> {db_path}", log_file)
    os.replace(db_tmp_path, db_path)

    # cleanup gz
    if not keep_gz and os.path.exists(gz_path):
        try:
            os.remove(gz_path)
            log(f"[Info] Cache supprimé: {gz_path}", log_file)
        except Exception:
            log(f"[Warn] Impossible de supprimer le cache: {gz_path}", log_file)

    stats = db_stats(db_path)
    log(f"[Info] DB prête: {db_path}", log_file)
    log(f"[Info] Adresses: {stats['count']:,}", log_file)
    log(f"[Info] Taille: {stats['size_mb']:.1f} MB", log_file)
    return total


def main() -> int:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    paths = script_paths(base_dir)

    parser = argparse.ArgumentParser(description="Importer/rebuild une DB SQLite d'adresses BTC (cron-safe).")
    parser.add_argument("--update-daily", action="store_true", help="Mode cron: force download + rebuild.")
    parser.add_argument("--force-download", action="store_true", help="Force le téléchargement du .gz.")
    parser.add_argument("--keep-gz", action="store_true", help="Garde le fichier .gz après import.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Taille des lots d'insertion.")
    parser.add_argument("--no-vacuum", action="store_true", help="Ne fait pas VACUUM (plus rapide, DB potentiellement plus grosse).")
    parser.add_argument("--no-log-file", action="store_true", help="N'écrit pas de fichier log.")
    parser.add_argument("--test", action="store_true", help="Fait un test lookup après rebuild.")
    parser.add_argument("--test-address", default="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", help="Adresse pour test lookup.")

    args = parser.parse_args()

    log_file = None if args.no_log_file else paths["log"]

    # En mode daily: force download
    force_download = args.force_download or args.update_daily

    # rebuild
    try:
        rebuild_database(
            url=BTC_ADDRESSES_URL,
            cache_gz=paths["cache_gz"],
            db_path=paths["db"],
            db_tmp_path=paths["db_tmp"],
            batch_size=max(1_000, int(args.batch_size)),
            force_download=force_download,
            keep_gz=args.keep_gz,
            do_vacuum=not args.no_vacuum,
            log_file=log_file,
        )

        if args.test:
            test_lookup_speed(paths["db"], args.test_address, log_file)

        log("[OK] Terminé.", log_file)
        return 0

    except Exception as e:
        log(f"[ERROR] {e}", log_file)
        return 1


if __name__ == "__main__":
    sys.exit(main())
