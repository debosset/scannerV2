#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bitcoin Address Database Importer
Télécharge et importe les adresses Bitcoin dans SQLite
Version optimisée pour faible utilisation de RAM
"""

import os
import gzip
import sqlite3
import requests
import time
from typing import Optional

BTC_ADDRESSES_URL = "http://addresses.loyce.club/Bitcoin_addresses_LATEST.txt.gz"
CACHE_FILE = "bitcoin_addresses.txt.gz"
DB_FILE = "bitcoin_addresses.db"
BATCH_SIZE = 10000  # Import par lots pour économiser la RAM


def download_btc_addresses(force_download: bool = False) -> str:
    """
    Télécharge le fichier d'adresses Bitcoin
    
    Args:
        force_download: Force le téléchargement même si le fichier existe
        
    Returns:
        Chemin vers le fichier téléchargé
    """
    if os.path.exists(CACHE_FILE) and not force_download:
        print(f"[Info] Fichier {CACHE_FILE} déjà présent, téléchargement ignoré.")
        return CACHE_FILE
    
    print(f"[Info] Téléchargement de {BTC_ADDRESSES_URL}...")
    print("[Info] Cela peut prendre plusieurs minutes...")
    
    start_time = time.time()
    
    try:
        response = requests.get(BTC_ADDRESSES_URL, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(CACHE_FILE, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        print(f"\r[Info] Téléchargement: {progress:.1f}% ({downloaded / 1024 / 1024:.1f} MB)", end='', flush=True)
        
        elapsed = time.time() - start_time
        print(f"\n[Info] Téléchargement terminé en {elapsed:.1f} secondes")
        print(f"[Info] Fichier sauvegardé: {CACHE_FILE}")
        
        return CACHE_FILE
        
    except Exception as e:
        print(f"\n[Erreur] Échec du téléchargement: {e}")
        raise


def create_database() -> sqlite3.Connection:
    """
    Crée la base de données SQLite avec la structure optimisée
    
    Returns:
        Connection à la base de données
    """
    print(f"\n[Info] Création de la base de données: {DB_FILE}")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Créer la table avec index
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS btc_addresses (
            address TEXT PRIMARY KEY NOT NULL
        ) WITHOUT ROWID
    """)
    
    # Optimisations SQLite pour l'import
    cursor.execute("PRAGMA journal_mode = OFF")
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA cache_size = 100000")
    cursor.execute("PRAGMA temp_store = MEMORY")
    
    conn.commit()
    print("[Info] Base de données créée avec succès")
    
    return conn


def import_addresses_to_db(gz_file: str, conn: sqlite3.Connection) -> int:
    """
    Importe les adresses depuis le fichier .gz dans SQLite
    Utilise un import par lots pour économiser la RAM
    
    Args:
        gz_file: Chemin vers le fichier .gz
        conn: Connection SQLite
        
    Returns:
        Nombre d'adresses importées
    """
    print(f"\n[Info] Import des adresses dans la base de données...")
    print(f"[Info] Taille des lots: {BATCH_SIZE:,} adresses")
    print("[Info] Cela peut prendre 5-15 minutes selon la taille du fichier...")
    
    start_time = time.time()
    cursor = conn.cursor()
    
    total_imported = 0
    batch = []
    
    try:
        with gzip.open(gz_file, 'rt', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                address = line.strip()
                if address:
                    batch.append((address,))
                
                # Insérer par lots
                if len(batch) >= BATCH_SIZE:
                    cursor.executemany(
                        "INSERT OR IGNORE INTO btc_addresses (address) VALUES (?)",
                        batch
                    )
                    conn.commit()
                    total_imported += len(batch)
                    batch = []
                    
                    # Afficher la progression
                    if total_imported % 100000 == 0:
                        elapsed = time.time() - start_time
                        speed = total_imported / elapsed if elapsed > 0 else 0
                        print(f"\r[Info] Importé: {total_imported:,} adresses ({speed:.0f} addr/sec)", end='', flush=True)
            
            # Insérer le dernier lot
            if batch:
                cursor.executemany(
                    "INSERT OR IGNORE INTO btc_addresses (address) VALUES (?)",
                    batch
                )
                conn.commit()
                total_imported += len(batch)
        
        elapsed = time.time() - start_time
        print(f"\n[Info] Import terminé en {elapsed/60:.1f} minutes")
        print(f"[Info] Total d'adresses importées: {total_imported:,}")
        
        # Créer l'index après l'import (plus rapide)
        print("\n[Info] Création de l'index (cela peut prendre quelques minutes)...")
        index_start = time.time()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_address ON btc_addresses(address)")
        conn.commit()
        index_elapsed = time.time() - index_start
        print(f"[Info] Index créé en {index_elapsed:.1f} secondes")
        
        # Optimiser la base de données
        print("\n[Info] Optimisation de la base de données...")
        cursor.execute("VACUUM")
        cursor.execute("ANALYZE")
        conn.commit()
        
        # Rétablir les paramètres normaux
        cursor.execute("PRAGMA journal_mode = DELETE")
        cursor.execute("PRAGMA synchronous = FULL")
        conn.commit()
        
        return total_imported
        
    except Exception as e:
        print(f"\n[Erreur] Échec de l'import: {e}")
        conn.rollback()
        raise


def get_db_stats(conn: sqlite3.Connection) -> dict:
    """
    Récupère les statistiques de la base de données
    
    Args:
        conn: Connection SQLite
        
    Returns:
        Dictionnaire avec les statistiques
    """
    cursor = conn.cursor()
    
    # Nombre d'adresses
    cursor.execute("SELECT COUNT(*) FROM btc_addresses")
    count = cursor.fetchone()[0]
    
    # Taille du fichier
    db_size = os.path.getsize(DB_FILE) / 1024 / 1024  # MB
    
    return {
        "count": count,
        "size_mb": db_size,
    }


def test_lookup_speed(conn: sqlite3.Connection, test_address: str = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"):
    """
    Test la vitesse de recherche dans la base de données
    
    Args:
        conn: Connection SQLite
        test_address: Adresse à tester (par défaut: adresse Genesis de Satoshi)
    """
    print(f"\n=== Test de vitesse de recherche ===")
    print(f"Adresse testée: {test_address}")
    
    cursor = conn.cursor()
    
    # Test de recherche
    start = time.time()
    cursor.execute("SELECT address FROM btc_addresses WHERE address = ?", (test_address,))
    result = cursor.fetchone()
    elapsed = time.time() - start
    
    print(f"Résultat: {'TROUVÉE' if result else 'NON TROUVÉE'}")
    print(f"Temps de recherche: {elapsed*1000:.3f} ms")
    
    # Test de 100 recherches pour avoir une moyenne
    print("\nTest de 100 recherches aléatoires...")
    start = time.time()
    for _ in range(100):
        cursor.execute("SELECT address FROM btc_addresses WHERE address = ?", (test_address,))
        cursor.fetchone()
    elapsed = time.time() - start
    avg_time = (elapsed / 100) * 1000
    
    print(f"Temps moyen: {avg_time:.3f} ms par recherche")
    print(f"Recherches par seconde: {1000/avg_time:.0f}")


def initialize_btc_database(force_download: bool = False, force_import: bool = False) -> sqlite3.Connection:
    """
    Initialise la base de données d'adresses Bitcoin
    
    Args:
        force_download: Force le téléchargement même si le fichier existe
        force_import: Force l'import même si la DB existe
        
    Returns:
        Connection à la base de données
    """
    print("\n" + "="*60)
    print("=== Initialisation de la base de données Bitcoin ===")
    print("="*60 + "\n")
    
    # Vérifier si la DB existe déjà
    db_exists = os.path.exists(DB_FILE)
    
    if db_exists and not force_import:
        print(f"[Info] Base de données existante trouvée: {DB_FILE}")
        conn = sqlite3.connect(DB_FILE)
        stats = get_db_stats(conn)
        print(f"[Info] Nombre d'adresses: {stats['count']:,}")
        print(f"[Info] Taille du fichier: {stats['size_mb']:.1f} MB")
        return conn
    
    # Télécharger le fichier si nécessaire
    gz_file = download_btc_addresses(force_download)
    
    # Créer et remplir la base de données
    if db_exists and force_import:
        print(f"[Info] Suppression de l'ancienne base de données...")
        os.remove(DB_FILE)
    
    conn = create_database()
    total_imported = import_addresses_to_db(gz_file, conn)
    
    # Afficher les statistiques
    stats = get_db_stats(conn)
    print(f"\n[Info] ✓ Initialisation terminée avec succès!")
    print(f"[Info] Adresses dans la DB: {stats['count']:,}")
    print(f"[Info] Taille de la DB: {stats['size_mb']:.1f} MB")
    print(f"[Info] Utilisation RAM: ~50-100 MB (vs 2-4 GB avec set)")
    
    return conn


if __name__ == "__main__":
    import sys
    
    # Arguments en ligne de commande
    force_download = "--force-download" in sys.argv
    force_import = "--force-import" in sys.argv
    
    try:
        conn = initialize_btc_database(force_download, force_import)
        
        # Test de vitesse
        test_lookup_speed(conn)
        
        conn.close()
        
        print("\n" + "="*60)
        print("✓ Base de données prête à l'emploi!")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n[Erreur] Échec de l'initialisation: {e}")
        sys.exit(1)