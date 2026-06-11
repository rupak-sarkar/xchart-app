"""screener/run_ohlcv.py -- Daily entry point for OHLCV download + indicators.

Pipeline:
  1. Load Nifty 500 ticker list (from cache)
  2. Daily OHLCV update (incremental: only fetch latest 5 days)
  3. Compute technical indicators for all tickers
  4. Generate per-ticker backtest JSON (for browser)
  5. Save combined CSV

Usage:
  python -m screener.run_ohlcv                  # daily incremental update
  python -m screener.run_ohlcv --full           # full 3Y re-download
  python -m screener.run_ohlcv --indicators-only  # recompute indicators only
"""

import sys
import time
from datetime import datetime, date
from pathlib import Path
from screener.config import SCREENER_DIR, NIFTY500_OHLCV_DIR, NIFTY500_BACKTEST_DIR


def main(full=False, indicators_only=False):
    start = time.time()
    today = date.today().strftime("%Y-%m-%d")

    print("\n" + "=" * 70)
    print(f"  NIFTY 500 DAILY OHLCV PIPELINE")
    print(f"  Date: {today}")
    print(f"  Mode: {'FULL 3Y' if full else 'INDICATORS ONLY' if indicators_only else 'Daily incremental'}")
    print("=" * 70)

    Path(SCREENER_DIR).mkdir(parents=True, exist_ok=True)
    Path(NIFTY500_OHLCV_DIR).mkdir(parents=True, exist_ok=True)
    Path(NIFTY500_BACKTEST_DIR).mkdir(parents=True, exist_ok=True)

    # ── Step 1: Load ticker list ──
    print(f"\n[STEP 1/4] Loading Nifty 500 ticker list...")
    from screener.nifty500 import load_nifty500_list, fetch_nifty500_list

    tickers = load_nifty500_list()
    if not tickers or len(tickers) < 100:
        print("  Ticker list empty or too small. Fetching fresh...")
        tickers = fetch_nifty500_list()

    if not tickers:
        print("  FATAL: No tickers available. Aborting.")
        return False

    print(f"  -> {len(tickers)} tickers")

    # ── Step 2: Download OHLCV ──
    from screener.ohlcv import download_all_ohlcv, update_daily, _load_all_from_cache

    if indicators_only:
        print(f"\n[STEP 2/4] Skipping download (indicators-only mode)...")
        all_data = _load_all_from_cache(tickers)
        if not all_data:
            print("  ERROR: No cached data. Run full download first.")
            return False
        print(f"  -> Loaded {len(all_data)} tickers from cache")
    elif full:
        print(f"\n[STEP 2/4] Full 3Y OHLCV download...")
        all_data = download_all_ohlcv(tickers, force=True)
    else:
        print(f"\n[STEP 2/4] Daily incremental update...")
        all_data = update_daily(tickers)

    if not all_data:
        print("  FATAL: No OHLCV data. Aborting.")
        return False

    print(f"  -> {len(all_data)} tickers with data")

    # ── Step 3: Compute indicators ──
    print(f"\n[STEP 3/4] Computing technical indicators...")
    from screener.indicators import compute_all_indicators, build_indicator_json

    all_data_ind = compute_all_indicators(all_data)
    print(f"  -> {len(all_data_ind)} tickers with indicators")

    # ── Step 4: Generate backtest JSON ──
    print(f"\n[STEP 4/4] Generating backtest JSON for browser...")
    from screener.ohlcv import generate_backtest_json

    # Build indicator data for embedding in JSON
    indicators_json = build_indicator_json(all_data_ind)
    n_generated = generate_backtest_json(all_data, indicators_json)

    # ── Summary ──
    elapsed = time.time() - start

    # Count total rows
    total_rows = sum(len(df) for df in all_data.values())
    avg_days = total_rows // len(all_data) if all_data else 0

    # Backtest data size
    bt_size = sum(f.stat().st_size for f in Path(NIFTY500_BACKTEST_DIR).glob("*.json")) / 1024 / 1024

    print(f"\n{'=' * 70}")
    print(f"  OHLCV PIPELINE COMPLETE")
    print(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"  Tickers: {len(all_data)}/{len(tickers)}")
    print(f"  Rows: {total_rows:,} (~{avg_days} days/ticker)")
    print(f"  Backtest JSON: {n_generated} files ({bt_size:.1f} MB)")
    print(f"  Files:")

    for desc, path in [
        ("OHLCV cache", NIFTY500_OHLCV_DIR),
        ("Backtest JSON", NIFTY500_BACKTEST_DIR),
        ("Combined CSV", SCREENER_DIR / "nifty500_ohlcv.csv"),
        ("Sync meta", SCREENER_DIR / "ohlcv_sync_meta.json"),
    ]:
        exists = "OK" if Path(path).exists() else "MISSING"
        print(f"    [{exists}] {desc}: {path}")

    print("=" * 70)
    return True


if __name__ == "__main__":
    full = '--full' in sys.argv
    ind_only = '--indicators-only' in sys.argv
    success = main(full=full, indicators_only=ind_only)
    sys.exit(0 if success else 1)
