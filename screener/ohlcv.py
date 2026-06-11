"""screener/ohlcv.py -- Download 3Y OHLCV data for Nifty 500 tickers.

Stores data in two formats:
  1. Per-ticker JSON files (for client-side backtester)
  2. Combined CSV (for server-side analysis)

Smart sync: Only downloads new data if existing data is stale.
"""

import os
import json
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, date
from pathlib import Path
from screener.config import (
    SCREENER_DIR, NIFTY500_OHLCV_DIR, NIFTY500_BACKTEST_DIR,
    OHLCV_PERIOD, OHLCV_BATCH_SIZE, OHLCV_SLEEP,
)

COMBINED_CSV = SCREENER_DIR / "nifty500_ohlcv.csv"
SYNC_META = SCREENER_DIR / "ohlcv_sync_meta.json"


# ===================================================================
# HELPERS
# ===================================================================

def _is_market_day(d=None):
    """Check if date is a potential market day (Mon-Fri)."""
    if d is None:
        d = date.today()
    return d.weekday() < 5


def _last_market_day():
    """Get the most recent market day."""
    d = date.today()
    while d.weekday() >= 5:  # Skip weekends
        d -= timedelta(days=1)
    return d


def _load_sync_meta():
    """Load sync metadata (last sync date, ticker count, etc.)."""
    if Path(SYNC_META).exists():
        try:
            with open(SYNC_META, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_sync_meta(meta):
    """Save sync metadata."""
    try:
        with open(SYNC_META, "w") as f:
            json.dump(meta, f, indent=2, default=str)
    except Exception as e:
        print(f"  WARNING: Could not save sync meta: {e}")


def _data_is_fresh(meta, tickers):
    """Check if existing data is up-to-date."""
    if not meta:
        return False

    last_sync = meta.get("last_sync_date", "")
    last_market = _last_market_day().strftime("%Y-%m-%d")
    synced_count = meta.get("tickers_synced", 0)

    # Fresh if synced today/last market day AND has enough tickers
    if last_sync >= last_market and synced_count >= len(tickers) * 0.9:
        return True
    return False


# ===================================================================
# DOWNLOAD FUNCTIONS
# ===================================================================

def download_ticker_ohlcv(ticker, period="3y"):
    """Download OHLCV data for a single ticker from yfinance."""
    import yfinance as yf

    for suffix in ['.NS', '.BO']:
        try:
            symbol = f"{ticker}{suffix}"
            t = yf.Ticker(symbol)
            hist = t.history(period=period)

            if hist is None or hist.empty or len(hist) < 10:
                continue

            # Clean and standardize
            df = hist[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            df.index.name = 'Date'
            df = df.reset_index()
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
            df['Ticker'] = ticker

            # Remove any rows with all-zero prices
            df = df[df['Close'] > 0]

            # Round prices
            for col in ['Open', 'High', 'Low', 'Close']:
                df[col] = df[col].round(2)
            df['Volume'] = df['Volume'].astype(int)

            return df

        except Exception:
            continue

    return None


def download_all_ohlcv(tickers, force=False):
    """
    Download OHLCV for all tickers with smart sync.

    Args:
        tickers: list of ticker symbols
        force: if True, re-download everything

    Returns:
        dict of {ticker: DataFrame}
    """
    Path(NIFTY500_OHLCV_DIR).mkdir(parents=True, exist_ok=True)
    Path(NIFTY500_BACKTEST_DIR).mkdir(parents=True, exist_ok=True)

    total = len(tickers)
    meta = _load_sync_meta()

    # Check if data is fresh
    if not force and _data_is_fresh(meta, tickers):
        print(f"  OHLCV data already fresh (synced: {meta.get('last_sync_date', '?')})")
        print(f"  -> {meta.get('tickers_synced', 0)} tickers, skipping download")
        return _load_all_from_cache(tickers)

    print(f"\nDownloading OHLCV for {total} tickers ({OHLCV_PERIOD} history)...")
    print("=" * 60)

    all_data = {}
    success = 0
    failed = []
    skipped = 0

    for i in range(0, total, OHLCV_BATCH_SIZE):
        batch = tickers[i:i + OHLCV_BATCH_SIZE]
        batch_num = i // OHLCV_BATCH_SIZE + 1
        total_batches = (total + OHLCV_BATCH_SIZE - 1) // OHLCV_BATCH_SIZE

        print(f"  Batch {batch_num}/{total_batches}: {batch[0]}..{batch[-1]}", end="")

        batch_ok = 0
        for ticker in batch:
            # Check if cached data is fresh enough (avoid re-downloading)
            if not force:
                cached = _load_ticker_cache(ticker)
                if cached is not None and len(cached) > 100:
                    last_date = cached['Date'].max()
                    if last_date >= _last_market_day().strftime("%Y-%m-%d"):
                        all_data[ticker] = cached
                        skipped += 1
                        batch_ok += 1
                        continue

            df = download_ticker_ohlcv(ticker, period=OHLCV_PERIOD)
            if df is not None and len(df) >= 10:
                all_data[ticker] = df
                _save_ticker_cache(ticker, df)
                success += 1
                batch_ok += 1
            else:
                failed.append(ticker)

        print(f" -> {batch_ok}/{len(batch)} OK")

        # Rate limiting between batches
        if i + OHLCV_BATCH_SIZE < total:
            time.sleep(OHLCV_SLEEP)

    # Save combined CSV
    if all_data:
        combined = pd.concat(all_data.values(), ignore_index=True)
        combined.to_csv(COMBINED_CSV, index=False)
        print(f"\n  Combined CSV: {len(combined):,} rows, {len(all_data)} tickers")
    else:
        print("\n  WARNING: No data downloaded!")

    # Update sync meta
    _save_sync_meta({
        "last_sync_date": date.today().strftime("%Y-%m-%d"),
        "tickers_synced": len(all_data),
        "tickers_total": total,
        "tickers_failed": len(failed),
        "tickers_skipped": skipped,
        "rows_total": sum(len(df) for df in all_data.values()),
    })

    # Report
    print(f"\n{'=' * 60}")
    print(f"  Downloaded: {success}")
    print(f"  Skipped (fresh): {skipped}")
    print(f"  Failed: {len(failed)}")
    if failed:
        print(f"    {', '.join(failed[:20])}{'...' if len(failed) > 20 else ''}")
    print(f"  Total with data: {len(all_data)}/{total}")

    return all_data


def update_daily(tickers):
    """
    Incremental daily update: only fetch latest 5 days and append.
    Much faster than full 3Y download.
    """
    Path(NIFTY500_OHLCV_DIR).mkdir(parents=True, exist_ok=True)

    total = len(tickers)
    meta = _load_sync_meta()
    last_sync = meta.get("last_sync_date", "")
    today_str = date.today().strftime("%Y-%m-%d")

    if last_sync == today_str:
        print(f"  OHLCV already synced today ({today_str}). Skipping.")
        return _load_all_from_cache(tickers)

    print(f"\nDaily OHLCV update for {total} tickers...")
    print(f"  Last sync: {last_sync or 'never'}")
    print("=" * 60)

    import yfinance as yf

    updated = 0
    failed = []
    all_data = {}

    for i in range(0, total, OHLCV_BATCH_SIZE):
        batch = tickers[i:i + OHLCV_BATCH_SIZE]
        batch_num = i // OHLCV_BATCH_SIZE + 1
        total_batches = (total + OHLCV_BATCH_SIZE - 1) // OHLCV_BATCH_SIZE

        print(f"  Batch {batch_num}/{total_batches}: {batch[0]}..{batch[-1]}", end="")

        batch_ok = 0
        for ticker in batch:
            try:
                # Load existing cached data
                cached = _load_ticker_cache(ticker)

                if cached is not None and len(cached) > 0:
                    last_cached_date = cached['Date'].max()

                    # Skip if already has today's data
                    if last_cached_date >= today_str:
                        all_data[ticker] = cached
                        batch_ok += 1
                        continue

                    # Fetch only recent days
                    new_df = download_ticker_ohlcv(ticker, period="5d")
                    if new_df is not None and len(new_df) > 0:
                        # Merge: keep old data + append new dates
                        merged = pd.concat([cached, new_df], ignore_index=True)
                        merged = merged.drop_duplicates(subset=['Date', 'Ticker'], keep='last')
                        merged = merged.sort_values('Date').reset_index(drop=True)
                        all_data[ticker] = merged
                        _save_ticker_cache(ticker, merged)
                        updated += 1
                        batch_ok += 1
                    else:
                        all_data[ticker] = cached
                        batch_ok += 1
                else:
                    # No cache — full download
                    df = download_ticker_ohlcv(ticker, period=OHLCV_PERIOD)
                    if df is not None and len(df) >= 10:
                        all_data[ticker] = df
                        _save_ticker_cache(ticker, df)
                        updated += 1
                        batch_ok += 1
                    else:
                        failed.append(ticker)

            except Exception:
                failed.append(ticker)

        print(f" -> {batch_ok}/{len(batch)} OK")

        if i + OHLCV_BATCH_SIZE < total:
            time.sleep(OHLCV_SLEEP)

    # Save combined CSV
    if all_data:
        combined = pd.concat(all_data.values(), ignore_index=True)
        combined.to_csv(COMBINED_CSV, index=False)

    # Update meta
    _save_sync_meta({
        "last_sync_date": today_str,
        "tickers_synced": len(all_data),
        "tickers_total": total,
        "tickers_failed": len(failed),
        "tickers_updated": updated,
        "rows_total": sum(len(df) for df in all_data.values()),
    })

    print(f"\n  Updated: {updated} | Cached: {len(all_data) - updated - len(failed)} | Failed: {len(failed)}")
    print(f"  Total: {len(all_data)}/{total} tickers")

    return all_data


# ===================================================================
# CACHE MANAGEMENT (per-ticker JSON)
# ===================================================================

def _ticker_cache_path(ticker):
    return NIFTY500_OHLCV_DIR / f"{ticker}.csv"


def _save_ticker_cache(ticker, df):
    """Save ticker OHLCV to per-ticker CSV."""
    path = _ticker_cache_path(ticker)
    df.to_csv(path, index=False)


def _load_ticker_cache(ticker):
    """Load cached ticker OHLCV."""
    path = _ticker_cache_path(ticker)
    if path.exists():
        try:
            df = pd.read_csv(path)
            if 'Date' in df.columns and len(df) > 0:
                return df
        except Exception:
            pass
    return None


def _load_all_from_cache(tickers):
    """Load all ticker data from per-ticker CSV cache."""
    all_data = {}
    for ticker in tickers:
        df = _load_ticker_cache(ticker)
        if df is not None:
            all_data[ticker] = df
    return all_data


# ===================================================================
# BACKTEST DATA GENERATION (per-ticker JSON for browser)
# ===================================================================

def generate_backtest_json(all_data, indicators_data=None):
    """
    Generate per-ticker JSON files for the client-side backtester.

    Each JSON contains:
    {
        "ticker": "RELIANCE",
        "rows": 750,
        "first_date": "2023-06-11",
        "last_date": "2026-06-11",
        "ohlcv": [
            {"d": "2023-06-11", "o": 2450.50, "h": 2480.00, "l": 2440.10, "c": 2475.30, "v": 1234567},
            ...
        ]
    }
    Short keys (d/o/h/l/c/v) to minimize file size.
    """
    Path(NIFTY500_BACKTEST_DIR).mkdir(parents=True, exist_ok=True)

    total = len(all_data)
    generated = 0
    total_size = 0

    print(f"\nGenerating backtest JSON ({total} tickers)...")

    for ticker, df in all_data.items():
        if df is None or len(df) < 10:
            continue

        df = df.sort_values('Date').copy()

        # Build compact OHLCV array
        ohlcv = []
        for _, row in df.iterrows():
            ohlcv.append({
                "d": str(row['Date'])[:10],
                "o": round(float(row.get('Open', 0)), 2),
                "h": round(float(row.get('High', 0)), 2),
                "l": round(float(row.get('Low', 0)), 2),
                "c": round(float(row.get('Close', 0)), 2),
                "v": int(row.get('Volume', 0)),
            })

        payload = {
            "ticker": ticker,
            "rows": len(ohlcv),
            "first_date": ohlcv[0]["d"] if ohlcv else "",
            "last_date": ohlcv[-1]["d"] if ohlcv else "",
            "ohlcv": ohlcv,
        }

        # Add indicators if provided
        if indicators_data and ticker in indicators_data:
            payload["indicators"] = indicators_data[ticker]

        out_path = NIFTY500_BACKTEST_DIR / f"{ticker}.json"
        with open(out_path, "w") as f:
            json.dump(payload, f, separators=(",", ":"))

        file_size = out_path.stat().st_size
        total_size += file_size
        generated += 1

    avg_size = total_size / generated / 1024 if generated else 0
    total_mb = total_size / 1024 / 1024

    print(f"  -> {generated} files | {total_mb:.1f} MB total | {avg_size:.1f} KB avg")

    return generated


# ===================================================================
# ENTRY POINTS
# ===================================================================

def load_combined_ohlcv():
    """Load the combined OHLCV CSV."""
    if COMBINED_CSV.exists():
        return pd.read_csv(COMBINED_CSV, low_memory=False)
    return pd.DataFrame()


if __name__ == "__main__":
    from screener.nifty500 import load_nifty500_list
    tickers = load_nifty500_list()
    if tickers:
        # Test with first 10
        data = download_all_ohlcv(tickers[:10], force=True)
        generate_backtest_json(data)
