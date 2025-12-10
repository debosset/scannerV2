import os

# API endpoint BTC uniquement
BLOCKCHAIN_API_ENDPOINT = "https://blockchain.info/balance"  # Bitcoin

# Rate limiting settings
# 1 API call par adresse (BTC uniquement)
API_RATE_LIMIT = 2          # 2 jetons par seconde (à adapter si besoin)
MAX_API_CALLS = 10_000_000  # Nombre max d'appels API autorisés

# Max retries for API calls
MAX_RETRIES = 2
RETRY_DELAY = 1  # délai entre les retries (en secondes)