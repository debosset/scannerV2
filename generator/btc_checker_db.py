#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bitcoin Address Checker with Database Verification
Version 4.0 - BTC uniquement avec vérification SQLite

Fonctionnalités:
1. Génération de clés Bitcoin uniquement
2. Vérification contre base de données SQLite
3. Double logging: match d'adresse + balance confirmée
4. Optimisé pour faible utilisation RAM (~50-100 MB)

Performance attendue: 100-300 keys/sec
"""

import sys
import time
import json
import os
import asyncio
import aiohttp
import sqlite3
from typing import List, Dict, Tuple, Optional
from collections import deque

from utils import (
    generate_mnemonic,
    derive_keys,
    check_btc_balance_async,
    RateLimiter,
    AddressCache,
)
from config import API_RATE_LIMIT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "found_funds.log")
MATCH_LOG_PATH = os.path.join(BASE_DIR, "address_matches.log")
STATUS_PATH = os.path.join(BASE_DIR, "status.json")
TOTAL_KEYS_FILE = os.path.join(BASE_DIR, "total_keys_generator.json")
DB_FILE = os.path.join(BASE_DIR, "bitcoin_addresses.db")

# Optimization parameters
BATCH_SIZE = 50          # Keys per batch (augmenté car BTC uniquement)
BUFFER_SIZE = 100        # Log buffer size
CACHE_SIZE = 10000       # Address cache size
STATUS_INTERVAL = 30.0   # Status update interval (seconds)


class BTCAddressChecker:
    """Vérificateur d'adresses Bitcoin via SQLite"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor = None
    
    def connect(self):
        """Établit la connexion à la base de données"""
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(
                f"Base de données non trouvée: {self.db_path}\n"
                f"Veuillez d'abord exécuter: python btc_db_importer.py"
            )
        
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        # Optimisations pour les lectures
        self.cursor.execute("PRAGMA cache_size = 10000")
        self.cursor.execute("PRAGMA temp_store = MEMORY")
    
    def is_known_address(self, address: str) -> bool:
        """
        Vérifie si une adresse est dans la base de données
        
        Args:
            address: Adresse Bitcoin à vérifier
            
        Returns:
            True si l'adresse est connue, False sinon
        """
        if not self.cursor:
            return False
        
        try:
            self.cursor.execute(
                "SELECT 1 FROM btc_addresses WHERE address = ? LIMIT 1",
                (address,)
            )
            return self.cursor.fetchone() is not None
        except Exception as e:
            print(f"Erreur lors de la vérification d'adresse: {e}")
            return False
    
    def close(self):
        """Ferme la connexion à la base de données"""
        if self.conn:
            self.conn.close()


class LogBuffer:
    """Buffered logging to reduce disk I/O"""
    
    def __init__(self, filepath: str, buffer_size: int = BUFFER_SIZE):
        self.filepath = filepath
        self.buffer_size = buffer_size
        self.buffer = deque()
    
    def add(self, line: str):
        """Add line to buffer"""
        self.buffer.append(line)
        if len(self.buffer) >= self.buffer_size:
            self.flush()
    
    def flush(self):
        """Write buffer to disk"""
        if not self.buffer:
            return
        
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                while self.buffer:
                    f.write(self.buffer.popleft())
        except Exception as e:
            print(f"Erreur lors du flush du buffer: {e}")


def load_total_keys() -> int:
    """Load total keys tested from file"""
    if os.path.exists(TOTAL_KEYS_FILE):
        try:
            with open(TOTAL_KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return int(data.get("total", 0))
        except Exception:
            return 0
    return 0


def save_total_keys(total: int):
    """Save total keys tested to file"""
    tmp = TOTAL_KEYS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"total": int(total)}, f)
    os.replace(tmp, TOTAL_KEYS_FILE)


def write_status(total_checked: int, btc_hits: int, btc_matches: int,
                btc_addr: str, start_time: float, total_start: int):
    """Write status to JSON file"""
    elapsed = time.time() - start_time
    speed = total_checked / elapsed if elapsed > 0 else 0.0
    total_global = total_start + total_checked
    
    data = {
        "script": "btc_generator",
        "keys_tested": total_checked,
        "total_keys_tested": total_global,
        "btc_hits": btc_hits,
        "btc_address_matches": btc_matches,
        "last_btc_address": btc_addr,
        "speed_keys_per_sec": speed,
        "elapsed_seconds": elapsed,
        "last_update": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    
    tmp_path = STATUS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp_path, STATUS_PATH)
    
    save_total_keys(total_global)


def generate_key_batch(batch_size: int) -> List[Dict]:
    """Generate a batch of BTC keys"""
    batch = []
    for _ in range(batch_size):
        try:
            mnemonic = generate_mnemonic()
            keys = derive_keys(mnemonic)
            batch.append({
                "mnemonic": mnemonic,
                "btc_addr": keys["btc"]["address"],
                "btc_priv": keys["btc"]["private_key"],
            })
        except Exception as e:
            print(f"Erreur lors de la génération de clé: {e}")
            continue
    return batch


async def process_batch(batch: List[Dict], session: aiohttp.ClientSession,
                       rate_limiter: RateLimiter, cache: AddressCache,
                       log_buffer: LogBuffer, match_log_buffer: LogBuffer,
                       btc_checker: BTCAddressChecker) -> Tuple[int, int]:
    """
    Process a batch of keys and check balances
    
    Returns:
        Tuple[btc_hits, btc_matches]
    """
    btc_hits = 0
    btc_matches = 0
    
    for key_data in batch:
        # Vérifier si l'adresse BTC est dans la DB
        btc_is_known = btc_checker.is_known_address(key_data["btc_addr"])
        
        if btc_is_known:
            btc_matches += 1
            # LOG 1: Match d'adresse trouvé
            match_line = (
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"BTC_ADDRESS_MATCH "
                f"ADDR={key_data['btc_addr']} "
                f"PRIV={key_data['btc_priv']} "
                f"MNEMONIC=\"{key_data['mnemonic']}\"\n"
            )
            match_log_buffer.add(match_line)
            print(f"\n!!! ADRESSE BTC CONNUE TROUVÉE !!! {key_data['btc_addr']}\n", flush=True)
            
            # Vérifier la balance BTC seulement si l'adresse est connue
            btc_balance = await check_btc_balance_async(
                session, key_data["btc_addr"], key_data["btc_priv"], rate_limiter, cache
            )
            
            # LOG 2: Balance confirmée > 0
            if btc_balance and btc_balance > 0:
                btc_hits += 1
                line = (
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"ASSET=BTC BALANCE={btc_balance:.8f} "
                    f"ADDR={key_data['btc_addr']} PRIV={key_data['btc_priv']} "
                    f"MNEMONIC=\"{key_data['mnemonic']}\"\n"
                )
                log_buffer.add(line)
                print(f"\n!!! FONDS BTC TROUVÉS !!! {btc_balance:.8f} BTC at {key_data['btc_addr']}\n", flush=True)
    
    return btc_hits, btc_matches


async def main_async():
    """Main async function"""
    print("\n" + "="*60, flush=True)
    print("=== Bitcoin Address Checker v4.0 ===", flush=True)
    print("="*60, flush=True)
    print("\nFonctionnalités:", flush=True)
    print("  • Génération de clés Bitcoin uniquement", flush=True)
    print("  • Vérification contre base de données SQLite", flush=True)
    print("  • Double logging: match + balance confirmée", flush=True)
    print("  • Utilisation RAM: ~50-100 MB", flush=True)
    print(f"\nPerformance attendue: 100-300 keys/sec\n", flush=True)
    
    # Initialiser le vérificateur d'adresses Bitcoin
    print("[Info] Connexion à la base de données Bitcoin...", flush=True)
    try:
        btc_checker = BTCAddressChecker(DB_FILE)
        btc_checker.connect()
        print("[Info] ✓ Connexion établie avec succès", flush=True)
    except FileNotFoundError as e:
        print(f"\n[Erreur] {e}", flush=True)
        print("\nVeuillez d'abord créer la base de données:", flush=True)
        print("  python btc_db_importer.py\n", flush=True)
        return 1
    except Exception as e:
        print(f"[Erreur] Impossible de se connecter à la DB: {e}", flush=True)
        return 1
    
    print("\nAppuyez sur Ctrl+C pour arrêter.", flush=True)
    print("Les fonds trouvés seront loggés dans 'found_funds.log'", flush=True)
    print("Les matchs d'adresses seront loggés dans 'address_matches.log'\n", flush=True)
    
    # Load previous progress
    total_start = load_total_keys()
    print(f"[Info] Total de clés déjà testées: {total_start:,}\n", flush=True)
    
    # Initialize components
    rate_limiter = RateLimiter(API_RATE_LIMIT)
    cache = AddressCache(CACHE_SIZE)
    log_buffer = LogBuffer(LOG_PATH, BUFFER_SIZE)
    match_log_buffer = LogBuffer(MATCH_LOG_PATH, BUFFER_SIZE)
    
    total_checked = 0
    btc_hits = 0
    btc_matches = 0
    start_time = time.time()
    last_status_time = 0.0
    
    last_btc_addr = ""
    
    try:
        async with aiohttp.ClientSession() as session:
            while True:
                # Generate batch of keys
                batch = generate_key_batch(BATCH_SIZE)
                
                if not batch:
                    await asyncio.sleep(0.1)
                    continue
                
                # Process batch
                batch_btc_hits, batch_btc_matches = await process_batch(
                    batch, session, rate_limiter, cache, log_buffer, 
                    match_log_buffer, btc_checker
                )
                
                # Update counters
                total_checked += len(batch)
                btc_hits += batch_btc_hits
                btc_matches += batch_btc_matches
                
                # Update last address
                if batch:
                    last_btc_addr = batch[-1]["btc_addr"]
                
                now = time.time()
                need_status = False
                
                # Print stats every 1000 keys
                if total_checked % 1000 < BATCH_SIZE:
                    need_status = True
                    elapsed = now - start_time
                    speed = total_checked / elapsed if elapsed > 0 else 0.0
                    
                    print("\n" + "-"*60, flush=True)
                    print(f"Clés testées (session):      {total_checked:,}", flush=True)
                    print(f"Total de clés testées:       {total_start + total_checked:,}", flush=True)
                    print(f"BTC hits (balance > 0):      {btc_hits}", flush=True)
                    print(f"BTC matchs (adresse connue): {btc_matches}", flush=True)
                    print(f"Vitesse:                     {speed:.2f} keys/sec", flush=True)
                    print(f"Temps écoulé:                {elapsed/60:.2f} minutes", flush=True)
                    print("-"*60 + "\n", flush=True)
                
                # Update status file every 30s
                if (now - last_status_time) >= STATUS_INTERVAL:
                    need_status = True
                
                if need_status:
                    write_status(
                        total_checked,
                        btc_hits,
                        btc_matches,
                        last_btc_addr,
                        start_time,
                        total_start,
                    )
                    log_buffer.flush()
                    match_log_buffer.flush()
                    last_status_time = now
                
                # Small sleep to prevent CPU overload
                await asyncio.sleep(0.01)
    
    except KeyboardInterrupt:
        print("\n\nCtrl+C reçu, arrêt en cours...", flush=True)
        log_buffer.flush()
        match_log_buffer.flush()
        write_status(
            total_checked,
            btc_hits,
            btc_matches,
            last_btc_addr,
            start_time,
            total_start,
        )
        if btc_checker:
            btc_checker.close()
        return 0
    except Exception as e:
        print(f"\nErreur fatale: {e}", flush=True)
        log_buffer.flush()
        match_log_buffer.flush()
        if btc_checker:
            btc_checker.close()
        return 1


def main():
    """Entry point"""
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
