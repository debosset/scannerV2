import time
import asyncio
import aiohttp
from typing import Optional
from collections import deque
from threading import Lock
from mnemonic import Mnemonic
from datetime import datetime


class RateLimiter:
    """Token bucket rate limiter - thread-safe"""
    
    def __init__(self, rate_limit: float):
        self.rate_limit = rate_limit
        self.tokens = rate_limit
        self.last_update = time.time()
        self.lock = Lock()
        from config import MAX_API_CALLS
        self.max_calls = MAX_API_CALLS
        self.total_calls = 0
    
    def acquire(self, tokens: int = 1) -> float:
        """Acquire tokens and return wait time"""
        with self.lock:
            if self.total_calls >= self.max_calls:
                raise Exception(f"Maximum API calls limit ({self.max_calls}) reached")
            
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.rate_limit, self.tokens + elapsed * self.rate_limit)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                self.total_calls += 1
                return 0.0
            else:
                wait_time = (tokens - self.tokens) / self.rate_limit
                return wait_time


class AddressCache:
    """LRU cache for checked addresses"""
    
    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self.cache = {}
        self.access_order = deque()
        self.lock = Lock()
    
    def get(self, address: str) -> Optional[float]:
        """Get cached balance"""
        with self.lock:
            return self.cache.get(address)
    
    def set(self, address: str, balance: float):
        """Cache balance"""
        with self.lock:
            if address in self.cache:
                return
            
            if len(self.cache) >= self.max_size:
                oldest = self.access_order.popleft()
                del self.cache[oldest]
            
            self.cache[address] = balance
            self.access_order.append(address)


def log_funds_found(address: str, private_key: str, balance: float, currency: str = "BTC"):
    """Log when funds are found"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] Found {balance:.8f} {currency}\n"
    log_entry += f"Address: {address}\n"
    log_entry += f"Private Key: {private_key}\n"
    log_entry += "-" * 50 + "\n"
    
    with open("found_funds.log", "a") as log_file:
        log_file.write(log_entry)


def generate_mnemonic() -> str:
    """Generate a secure 24-word BIP39 mnemonic"""
    mnemo = Mnemonic("english")
    return mnemo.generate(strength=256)


def derive_keys(mnemonic: str) -> dict:
    """
    Derive BTC keys from mnemonic - ETH removed.
    Returns:
        {
            'btc': {'address': str, 'private_key': str}
        }
    """
    try:
        from hdwallet import HDWallet
        from hdwallet.mnemonics import BIP39Mnemonic
        from hdwallet.cryptocurrencies import Bitcoin
        from hdwallet.hds import BIP44HD
        from hdwallet.derivations import BIP44Derivation
        
        # Derive Bitcoin
        btc_wallet = HDWallet(
            cryptocurrency=Bitcoin,
            hd=BIP44HD,
            network=Bitcoin.NETWORKS.MAINNET
        )
        btc_wallet.from_mnemonic(
            mnemonic=BIP39Mnemonic(mnemonic=mnemonic)
        ).from_derivation(
            derivation=BIP44Derivation(
                coin_type=Bitcoin.COIN_TYPE,
                account=0,
                change=0,
                address=0
            )
        )
        btc_address = btc_wallet.address()
        btc_private_key = btc_wallet.private_key()
        
        return {
            'btc': {'address': btc_address, 'private_key': btc_private_key}
        }
    
    except Exception as e:
        print(f"Error in key derivation: {str(e)}")
        raise


async def check_btc_balance_async(
    session: aiohttp.ClientSession,
    address: str,
    private_key: str,
    rate_limiter: RateLimiter,
    cache: Optional[AddressCache] = None
) -> Optional[float]:
    """Check BTC balance asynchronously"""
    from config import BLOCKCHAIN_API_ENDPOINT, MAX_RETRIES, RETRY_DELAY
    
    # Check cache
    if cache:
        cached = cache.get(address)
        if cached is not None:
            return cached
    
    for retry in range(MAX_RETRIES):
        try:
            # Rate limiting
            wait_time = rate_limiter.acquire()
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            url = f"{BLOCKCHAIN_API_ENDPOINT}?active={address}"
            async with session.get(url, timeout=10) as response:
                if response.status == 429:
                    if retry < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                        continue
                    return None
                
                response.raise_for_status()
                data = await response.json()
                
                if address in data:
                    balance_satoshi = data[address]['final_balance']
                    balance_btc = balance_satoshi / 100000000
                    
                    if cache:
                        cache.set(address, balance_btc)
                    
                    if balance_btc > 0:
                        log_funds_found(address, private_key, balance_btc, "BTC")
                    
                    return balance_btc
                
                return 0.0
        
        except Exception:
            if retry < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
    
    return None


def check_btc_balance(address: str, private_key: str, rate_limiter: RateLimiter) -> Optional[float]:
    """Synchronous BTC balance check (ETH removed)"""
    import requests
    from config import BLOCKCHAIN_API_ENDPOINT, MAX_RETRIES, RETRY_DELAY
    
    for retry in range(MAX_RETRIES):
        try:
            wait_time = rate_limiter.acquire()
            if wait_time > 0:
                time.sleep(wait_time)
            
            url = f"{BLOCKCHAIN_API_ENDPOINT}?active={address}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 429:
                if retry < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                return None
            
            response.raise_for_status()
            data = response.json()
            
            if address in data:
                balance_satoshi = data[address]['final_balance']
                balance_btc = balance_satoshi / 100000000
                
                if balance_btc > 0:
                    log_funds_found(address, private_key, balance_btc, "BTC")
                
                return balance_btc
            
            return 0.0
        
        except Exception:
            if retry < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    
    return None
