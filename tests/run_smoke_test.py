#!/usr/bin/env python3
"""Simple smoke tests you can run from the terminal.

Usage:
  python tests/run_smoke_test.py

Exits with code 0 on success, 1 on failure.
"""
import sys
import os

# Ensure repo root is on sys.path so we can import generator/* modules
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

def test_derive_keys():
    from generator.utils import derive_keys_optimized
    print('Running test_derive_keys...')
    k = derive_keys_optimized()
    assert isinstance(k, dict) and 'btc' in k, 'derive_keys_optimized must return a dict with key "btc"'
    btc = k['btc']
    for field in ('p2pkh', 'p2sh', 'bech32', 'private_key'):
        assert btc.get(field), f'missing field {field} in derived keys'
    print('  OK')


def test_generate_key_batch():
    from generator.btc_checker_db import generate_key_batch
    print('Running test_generate_key_batch...')
    batch = generate_key_batch(3)
    assert isinstance(batch, list) and len(batch) == 3, 'generate_key_batch must return list with requested size'
    for item in batch:
        assert 'btc_addrs' in item and 'btc_priv' in item, 'batch item missing expected keys'
    print('  OK')


def test_btc_checker_connect_failure():
    from generator.btc_checker_db import BTCAddressChecker
    print('Running test_btc_checker_connect_failure...')
    # Point to an obviously missing file to assert FileNotFoundError
    checker = BTCAddressChecker(os.path.join('/tmp', 'this_db_does_not_exist_12345.db'))
    try:
        checker.connect()
    except FileNotFoundError:
        print('  OK')
        return
    raise AssertionError('BTCAddressChecker.connect should raise FileNotFoundError for missing DB')


def main():
    tests = [
        test_derive_keys,
        test_generate_key_batch,
        test_btc_checker_connect_failure,
    ]

    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f'FAILED: {e}')
            failed += 1
        except Exception as e:
            print(f'ERROR running {t.__name__}: {e}')
            failed += 1

    if failed:
        print(f"{failed} test(s) failed")
        sys.exit(1)
    print('All smoke tests passed')
    sys.exit(0)


if __name__ == '__main__':
    main()
