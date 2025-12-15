import time
import asyncio
import aiohttp
import secrets
import hashlib
from typing import Optional
from collections import deque
from threading import Lock
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


# ============================================================================
# OPTIMIZED KEY GENERATION - NO BIP39 DEPENDENCY
# ============================================================================

# Base58 alphabet for Bitcoin addresses
BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def base58_encode(data: bytes) -> str:
    """Encode bytes to Base58"""
    # Convert bytes to integer
    num = int.from_bytes(data, 'big')
    
    # Convert to base58
    encoded = ''
    while num > 0:
        num, remainder = divmod(num, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    
    # Add leading '1's for leading zero bytes
    for byte in data:
        if byte == 0:
            encoded = '1' + encoded
        else:
            break
    
    return encoded


def hash160(data: bytes) -> bytes:
    """SHA-256 followed by RIPEMD-160"""
    sha256_hash = hashlib.sha256(data).digest()
    ripemd160 = hashlib.new('ripemd160')
    ripemd160.update(sha256_hash)
    return ripemd160.digest()


def double_sha256(data: bytes) -> bytes:
    """Double SHA-256 hash"""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def private_key_to_wif(private_key_bytes: bytes, compressed: bool = True) -> str:
    """
    Convert private key bytes to WIF (Wallet Import Format)
    
    Args:
        private_key_bytes: 32-byte private key
        compressed: Whether to use compressed format
    
    Returns:
        WIF-encoded private key string
    """
    # Mainnet prefix
    extended = b'\x80' + private_key_bytes
    
    # Add compression flag if needed
    if compressed:
        extended += b'\x01'
    
    # Calculate checksum
    checksum = double_sha256(extended)[:4]
    
    # Encode to Base58
    return base58_encode(extended + checksum)


def private_key_to_public_key(private_key_bytes: bytes) -> bytes:
    """
    Convert private key to compressed public key using secp256k1
    
    Args:
        private_key_bytes: 32-byte private key
    
    Returns:
        33-byte compressed public key
    """
    try:
        import coincurve
        # Use coincurve for fast secp256k1 operations
        privkey = coincurve.PrivateKey(private_key_bytes)
        return privkey.public_key.format(compressed=True)
    except ImportError:
        # Fallback to ecdsa if coincurve not available
        from ecdsa import SigningKey, SECP256k1
        sk = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
        vk = sk.get_verifying_key()
        
        # Get uncompressed public key
        public_key_bytes = b'\x04' + vk.to_string()
        
        # Convert to compressed format
        x = int.from_bytes(vk.to_string()[:32], 'big')
        y = int.from_bytes(vk.to_string()[32:], 'big')
        
        # Compressed format: 0x02 if y is even, 0x03 if y is odd
        prefix = b'\x02' if y % 2 == 0 else b'\x03'
        return prefix + x.to_bytes(32, 'big')


def public_key_to_address(public_key: bytes) -> str:
    """
    Convert public key to Bitcoin P2PKH address
    
    Args:
        public_key: Compressed or uncompressed public key
    
    Returns:
        Bitcoin address string
    """
    # Hash160 of public key
    hash160_result = hash160(public_key)
    
    # Add version byte (0x00 for mainnet P2PKH)
    versioned = b'\x00' + hash160_result
    
    # Calculate checksum
    checksum = double_sha256(versioned)[:4]
    
    # Encode to Base58
    return base58_encode(versioned + checksum)


def bech32_polymod(values):
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= GEN[i]
    return chk


def bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def bech32_create_checksum(hrp, data):
    values = bech32_hrp_expand(hrp) + data
    polymod = bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


BECH32_CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'


def bech32_encode(hrp, data):
    combined = data + bech32_create_checksum(hrp, data)
    return hrp + '1' + ''.join([BECH32_CHARSET[d] for d in combined])


def convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def public_key_to_bech32(public_key: bytes, hrp: str = 'bc') -> str:
    """Convert pubkey to native segwit P2WPKH bech32 address (bc1...)."""
    prog = hash160(public_key)
    # witness version 0
    data = [0] + convertbits(prog, 8, 5)
    return bech32_encode(hrp, data)


def public_key_to_p2sh_p2wpkh(public_key: bytes) -> str:
    """Convert pubkey to P2SH-wrapped P2WPKH address (starts with 3)."""
    # redeemScript = 0x00 0x14 <hash160(pubkey)>
    redeem = b'\x00\x14' + hash160(public_key)
    redeem_hashed = hash160(redeem)
    versioned = b'\x05' + redeem_hashed
    checksum = double_sha256(versioned)[:4]
    return base58_encode(versioned + checksum)


def generate_random_private_key() -> bytes:
    """
    Generate a cryptographically secure random 32-byte private key
    
    Returns:
        32-byte private key
    """
    # Generate random 32 bytes using secrets module (cryptographically secure)
    while True:
        private_key = secrets.token_bytes(32)
        
        # Ensure the private key is within valid range for secp256k1
        # Must be between 1 and n-1 where n is the curve order
        # n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        key_int = int.from_bytes(private_key, 'big')
        
        if 1 <= key_int < 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141:
            return private_key


def derive_keys_optimized() -> dict:
    """
    Generate Bitcoin keys WITHOUT BIP39 mnemonic
    This is MUCH faster than BIP39 derivation
    
    Returns:
        {
            'btc': {'address': str, 'private_key': str}
        }
    """
    # Generate random private key (32 bytes)
    private_key_bytes = generate_random_private_key()
    
    # Convert to WIF format
    private_key_wif = private_key_to_wif(private_key_bytes, compressed=True)
    
    # Derive public key
    public_key = private_key_to_public_key(private_key_bytes)
    
    # Derive Bitcoin address (legacy P2PKH)
    p2pkh = public_key_to_address(public_key)
    # P2SH-wrapped segwit (starts with 3)
    p2sh = public_key_to_p2sh_p2wpkh(public_key)
    # Native segwit bech32 (bc1...)
    bech32 = public_key_to_bech32(public_key)

    return {
        'btc': {
            'p2pkh': p2pkh,
            'p2sh': p2sh,
            'bech32': bech32,
            'private_key': private_key_wif
        }
    }


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
    """Synchronous BTC balance check"""
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