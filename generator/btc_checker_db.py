#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bitcoin Address Checker - VERSION PARALLÉLISÉE
Version 6.0 - Multiprocessing pour utiliser tous les cœurs CPU

Optimisations:
1. Génération directe de clés privées (sans BIP39 mnemonic)
2. Utilisation de coincurve pour secp256k1 (10x plus rapide)
3. Vérification contre base de données SQLite
4. MULTIPROCESSING - Utilise tous les cœurs CPU disponibles
5. Double logging: match d'adresse + balance confirmée
6. Utilisation RAM: ~100-300 MB (selon nombre de workers)

Performance attendue: 10,000-50,000+ keys/sec (selon CPU)
"""

import sys
import time
import json
import os
import asyncio
import aiohttp
import sqlite3
import multiprocessing as mp
from multiprocessing import Process, Queue, Value, Lock
from typing import List, Dict, Tuple, Optional
from collections import deque
from datetime import datetime

from utils import (
    derive_keys_optimized,
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
BATCH_SIZE = 500         # Keys per batch per worker
BUFFER_SIZE = 100        # Log buffer size
CACHE_SIZE = 10000       # Address cache size
STATUS_INTERVAL = 5.0    # Status update interval (seconds)


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
            print(f"[Worker] Erreur lors de la vérification d'adresse: {e}")
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


def generate_key_batch(batch_size: int) -> List[Dict]:
    """Generate a batch of BTC keys - OPTIMIZED VERSION"""
    batch = []
    for _ in range(batch_size):
        try:
            # Génération directe sans BIP39 (beaucoup plus rapide)
            keys = derive_keys_optimized()
            batch.append({
                "btc_addr": keys["btc"]["address"],
                "btc_priv": keys["btc"]["private_key"],
            })
        except Exception as e:
            continue
    return batch


def worker_process(worker_id: int, db_path: str, result_queue: Queue,
                   stats_queue: Queue, stop_flag: Value):
    """
    Processus worker qui génère et vérifie des clés
    
    Args:
        worker_id: ID du worker
        db_path: Chemin vers la base de données SQLite
        result_queue: Queue pour envoyer les résultats trouvés
        stats_queue: Queue pour envoyer les statistiques
        stop_flag: Flag partagé pour arrêter tous les workers
    """
    try:
        # Connexion à la DB (une par worker)
        btc_checker = BTCAddressChecker(db_path)
        btc_checker.connect()
        
        keys_checked = 0
        matches_found = 0
        start_time = time.time()
        last_report = start_time
        
        print(f"[Worker {worker_id}] Démarré")
        
        while not stop_flag.value:
            # Générer un lot de clés
            batch = generate_key_batch(BATCH_SIZE)
            
            if not batch:
                time.sleep(0.01)
                continue
            
            # Vérifier chaque clé dans la DB
            for key_data in batch:
                btc_is_known = btc_checker.is_known_address(key_data["btc_addr"])
                
                if btc_is_known:
                    matches_found += 1
                    # Envoyer le résultat à la queue
                    result_queue.put({
                        'worker_id': worker_id,
                        'timestamp': datetime.now().isoformat(),
                        'type': 'match',
                        'address': key_data['btc_addr'],
                        'private_key': key_data['btc_priv']
                    })
                    print(f"\n[Worker {worker_id}] !!! ADRESSE BTC CONNUE TROUVÉE !!! {key_data['btc_addr']}\n", flush=True)
            
            keys_checked += len(batch)
            
            # Envoyer les stats toutes les secondes
            current_time = time.time()
            if current_time - last_report >= 1.0:
                elapsed = current_time - start_time
                speed = keys_checked / elapsed if elapsed > 0 else 0
                
                stats_queue.put({
                    'worker_id': worker_id,
                    'keys_checked': keys_checked,
                    'matches_found': matches_found,
                    'speed': speed
                })
                
                last_report = current_time
        
        btc_checker.close()
        print(f"[Worker {worker_id}] Arrêté (total: {keys_checked:,} clés, {matches_found} matchs)")
        
    except Exception as e:
        print(f"[Worker {worker_id}] Erreur: {e}")
        import traceback
        traceback.print_exc()


async def balance_checker_process(result_queue: Queue, log_buffer: LogBuffer, 
                                  match_log_buffer: LogBuffer, stop_flag: Value):
    """
    Processus asynchrone qui vérifie les balances des adresses trouvées
    """
    rate_limiter = RateLimiter(API_RATE_LIMIT)
    cache = AddressCache(CACHE_SIZE)
    
    try:
        async with aiohttp.ClientSession() as session:
            while not stop_flag.value:
                if not result_queue.empty():
                    result = result_queue.get_nowait()
                    
                    # LOG 1: Match d'adresse trouvé
                    match_line = (
                        f"[{result['timestamp']}] "
                        f"BTC_ADDRESS_MATCH "
                        f"WORKER={result['worker_id']} "
                        f"ADDR={result['address']} "
                        f"PRIV={result['private_key']}\n"
                    )
                    match_log_buffer.add(match_line)
                    
                    # Vérifier la balance
                    btc_balance = await check_btc_balance_async(
                        session, result['address'], result['private_key'], 
                        rate_limiter, cache
                    )
                    
                    # LOG 2: Balance confirmée > 0
                    if btc_balance and btc_balance > 0:
                        line = (
                            f"[{result['timestamp']}] "
                            f"ASSET=BTC BALANCE={btc_balance:.8f} "
                            f"WORKER={result['worker_id']} "
                            f"ADDR={result['address']} PRIV={result['private_key']}\n"
                        )
                        log_buffer.add(line)
                        print(f"\n!!! FONDS BTC TROUVÉS !!! {btc_balance:.8f} BTC at {result['address']}\n", flush=True)
                
                await asyncio.sleep(0.1)
    except Exception as e:
        print(f"[Balance Checker] Erreur: {e}")


def stats_monitor(num_workers: int, stats_queue: Queue, stop_flag: Value,
                 log_buffer: LogBuffer, match_log_buffer: LogBuffer, total_start: int):
    """
    Processus qui affiche les statistiques en temps réel
    """
    worker_stats = {i: {'keys': 0, 'matches': 0, 'speed': 0} for i in range(num_workers)}
    start_time = time.time()
    last_status_write = start_time
    
    print("\n" + "="*80)
    print("Recherche de clés Bitcoin en cours...")
    print("="*80)
    print("Appuyez sur Ctrl+C pour arrêter\n")
    
    try:
        while not stop_flag.value:
            # Collecter les stats de tous les workers
            while not stats_queue.empty():
                stat = stats_queue.get_nowait()
                worker_id = stat['worker_id']
                worker_stats[worker_id] = {
                    'keys': stat['keys_checked'],
                    'matches': stat['matches_found'],
                    'speed': stat['speed']
                }
            
            # Calculer les totaux
            total_keys = sum(s['keys'] for s in worker_stats.values())
            total_matches = sum(s['matches'] for s in worker_stats.values())
            total_speed = sum(s['speed'] for s in worker_stats.values())
            elapsed = time.time() - start_time
            
            # Afficher les stats
            print(f"\r[{elapsed:.0f}s] Clés: {total_keys:,} | "
                  f"Matchs: {total_matches} | "
                  f"Vitesse: {total_speed:,.0f} clés/sec | "
                  f"Workers: {num_workers}", end='', flush=True)
            
            # Écrire le fichier status toutes les 5 secondes
            current_time = time.time()
            if current_time - last_status_write >= STATUS_INTERVAL:
                data = {
                    "script": "btc_checker_db_parallel",
                    "keys_tested": total_keys,
                    "total_keys_tested": total_start + total_keys,
                    "btc_address_matches": total_matches,
                    "speed_keys_per_sec": total_speed,
                    "elapsed_seconds": elapsed,
                    "workers": num_workers,
                    "last_update": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                
                tmp_path = STATUS_PATH + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(tmp_path, STATUS_PATH)
                
                save_total_keys(total_start + total_keys)
                log_buffer.flush()
                match_log_buffer.flush()
                
                last_status_write = current_time
            
            time.sleep(0.5)
    
    except KeyboardInterrupt:
        pass
    
    print("\n\nArrêt du monitoring...")


def main():
    """Fonction principale"""
    import argparse
    import signal
    
    parser = argparse.ArgumentParser(description='Bitcoin Address Checker - Version Parallélisée')
    parser.add_argument('--workers', type=int, default=None,
                       help='Nombre de workers (défaut: nombre de CPU - 1)')
    parser.add_argument('--db', type=str, default=DB_FILE,
                       help=f'Chemin vers la base de données (défaut: {DB_FILE})')
    
    args = parser.parse_args()
    
    # Vérifier que la DB existe
    if not os.path.exists(args.db):
        print(f"[Erreur] Base de données introuvable: {args.db}")
        print("Exécutez d'abord le script d'import des adresses Bitcoin.")
        return 1
    
    # Déterminer le nombre de workers
    cpu_count = mp.cpu_count()
    num_workers = args.workers if args.workers else max(1, cpu_count - 1)
    
    print("\n" + "="*80)
    print("=== Bitcoin Address Checker v6.0 - VERSION PARALLÉLISÉE ===")
    print("="*80)
    print(f"CPU disponibles: {cpu_count}")
    print(f"Workers lancés: {num_workers}")
    print(f"Base de données: {args.db}")
    print(f"Taille des lots: {BATCH_SIZE} clés par worker")
    print("="*80 + "\n")
    
    # Load previous progress
    total_start = load_total_keys()
    print(f"[Info] Total de clés déjà testées: {total_start:,}\n")
    
    # Créer les queues et flags partagés
    result_queue = Queue()
    stats_queue = Queue()
    stop_flag = Value('i', 0)
    
    # Créer les buffers de log
    log_buffer = LogBuffer(LOG_PATH, BUFFER_SIZE)
    match_log_buffer = LogBuffer(MATCH_LOG_PATH, BUFFER_SIZE)
    
    # Créer les processus workers
    workers = []
    for i in range(num_workers):
        p = Process(target=worker_process, 
                   args=(i, args.db, result_queue, stats_queue, stop_flag))
        p.start()
        workers.append(p)
    
    # Créer le processus de monitoring
    monitor = Process(target=stats_monitor, 
                     args=(num_workers, stats_queue, stop_flag, log_buffer, 
                           match_log_buffer, total_start))
    monitor.start()
    
    # Gestionnaire de signal pour arrêt propre
    def signal_handler(sig, frame):
        print("\n\n[Info] Signal d'arrêt reçu, fermeture des workers...")
        stop_flag.value = 1
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Démarrer le balance checker dans un thread asyncio
    import threading
    
    def run_balance_checker():
        asyncio.run(balance_checker_process(result_queue, log_buffer, 
                                            match_log_buffer, stop_flag))
    
    balance_thread = threading.Thread(target=run_balance_checker, daemon=True)
    balance_thread.start()
    
    try:
        # Attendre que tous les workers se terminent
        for w in workers:
            w.join()
        
        monitor.join()
        
    except KeyboardInterrupt:
        print("\n[Info] Interruption par l'utilisateur")
        stop_flag.value = 1
    
    finally:
        # Arrêter le monitoring
        stop_flag.value = 1
        
        if monitor.is_alive():
            monitor.join(timeout=2)
            if monitor.is_alive():
                monitor.terminate()
        
        # Attendre que tous les workers se terminent
        print("[Info] Attente de la fin des workers...")
        for w in workers:
            if w.is_alive():
                w.join(timeout=5)
                if w.is_alive():
                    w.terminate()
        
        # Flush final des logs
        log_buffer.flush()
        match_log_buffer.flush()
        
        print("\n" + "="*80)
        print("Recherche terminée")
        print("="*80 + "\n")
    
    return 0


if __name__ == "__main__":
    # Nécessaire pour Windows
    mp.freeze_support()
    sys.exit(main())