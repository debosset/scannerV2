**Purpose**

This repo contains a Bitcoin key/address generator/checker and a minimal dashboard. These instructions help AI coding agents be productive quickly by explaining repo structure, runtime flows, conventions, and exact run/debug commands.

**Big picture architecture**
- `generator/`: key generation and checker tools. `generator/btc_checker_db.py` is the main long-running worker. It calls `derive_keys_optimized()` from `generator/utils.py`, checks addresses against a local SQLite DB (`bitcoin_addresses.db`), and (if matched) calls `check_btc_balance_async` to confirm balances.
- `dashboard/`: lightweight UI (see `dashboard/app.py`) that reads `status.json` for progress/telemetry.
- Shared config and helpers live in `generator/config.py` and `generator/utils.py`.

**Critical developer workflows**
- Build/data prep: create the SQLite dataset before running the checker:
```bash
python generator/btc_db_importer.py
```
- Run checker (long-running, async):
```bash
python generator/btc_checker_db.py
```
- Debugging: set breakpoints in `main_async()` or run `python -m pdb generator/btc_checker_db.py`. Avoid blocking calls inside the async main loop.

**Project-specific conventions & patterns**
- Buffered writes: use `LogBuffer` (in `btc_checker_db.py`) to batch writes to `found_funds.log` and `address_matches.log`.
- Atomic status writes: `write_status()` uses `.tmp` + `os.replace()` — follow this for reliable status files (`status.json`, `total_keys_generator.json`).
- DB access: `BTCAddressChecker` maintains one sqlite3 connection with `check_same_thread=False` and PRAGMA tuning (`cache_size`, `temp_store=MEMORY`) for read performance.
- Async-first network calls: `check_btc_balance_async` uses `aiohttp`; keep network logic async and rate-limited by `RateLimiter` configured in `generator/config.py`.

**Integration points & external dependencies**
- Network: blockchain balance checks go through `check_btc_balance_async` in `utils.py` — inspect that file for which external API endpoints are used and how caching is applied via `AddressCache`.
- Crypto libs: `coincurve` is recommended for performance (optional). If missing, code falls back to slower libs; check `utils.py` for the exact fallback.
- Files produced/consumed at runtime: `bitcoin_addresses.db`, `found_funds.log`, `address_matches.log`, `status.json`, `total_keys_generator.json`.

**Where to look when changing behaviour**
- Change generation rate: edit `BATCH_SIZE` in `generator/btc_checker_db.py` and `derive_keys_optimized()` in `generator/utils.py`.
- Change API throttling: update `API_RATE_LIMIT` in `generator/config.py` or adjust `RateLimiter` code.
- Add telemetry: extend `write_status()` (preserve atomic `.tmp` write pattern).

**Concrete examples**
- To add a new log stream, copy the `LogBuffer` pattern: buffer lines and call `.flush()` periodically (see `btc_checker_db.py`).
- To speed key generation swap to `coincurve` in `utils.py` and keep a safe fallback for environments without native libs.

If you'd like, I can (1) extract exact API endpoints from `utils.py`, (2) expand the dashboard integration details from `dashboard/app.py`, or (3) merge any existing `.github/copilot-instructions.md` if one exists. Tell me which next step you prefer.
