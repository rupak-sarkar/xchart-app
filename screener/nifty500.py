"""screener/nifty500.py -- Fetch Nifty 500 constituent list from NSE."""

import pandas as pd
import requests
from io import StringIO
from pathlib import Path
from screener.config import SCREENER_DIR, NIFTY500_TICKERS_FILE, NSE_HEADERS

NSE_NIFTY500_CSV = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
NSE_API_URL = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"
WIKI_URL = "https://en.wikipedia.org/wiki/NIFTY_500"


def fetch_nifty500_list():
    """Download current Nifty 500 constituents. Tries multiple sources."""
    Path(SCREENER_DIR).mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("Fetching Nifty 500 ticker list")
    print("=" * 60)

    # Source 1: NSE archives CSV (most reliable)
    tickers = _fetch_from_nse_csv()
    if tickers and len(tickers) >= 450:
        return tickers

    # Source 2: NSE API
    tickers = _fetch_from_nse_api()
    if tickers and len(tickers) >= 450:
        return tickers

    # Source 3: Wikipedia
    tickers = _fetch_from_wikipedia()
    if tickers and len(tickers) >= 450:
        return tickers

    # Source 4: Cached fallback
    return _load_cached_list()


def _fetch_from_nse_csv():
    """Fetch from NSE archives CSV download."""
    try:
        print("  Trying NSE archives CSV...")
        resp = requests.get(NSE_NIFTY500_CSV, headers=NSE_HEADERS, timeout=15)
        resp.raise_for_status()

        df = pd.read_csv(StringIO(resp.text))

        # Find Symbol column
        sym_col = None
        for col in df.columns:
            if 'symbol' in col.lower():
                sym_col = col
                break
        if sym_col is None:
            print("    WARNING: No Symbol column found")
            return None

        tickers = df[sym_col].astype(str).str.strip().unique().tolist()
        tickers = [t for t in tickers if t and t != 'nan']

        # Save full data
        save_cols = [sym_col]
        rename_map = {sym_col: 'Ticker'}
        for col in df.columns:
            if 'industry' in col.lower():
                save_cols.append(col)
                rename_map[col] = 'Industry'
            elif 'company' in col.lower() or 'name' in col.lower():
                save_cols.append(col)
                rename_map[col] = 'Company_Name'
            elif 'series' in col.lower():
                save_cols.append(col)
                rename_map[col] = 'Series'

        out_df = df[save_cols].rename(columns=rename_map)
        out_df.to_csv(NIFTY500_TICKERS_FILE, index=False)
        print(f"  -> NSE CSV: {len(tickers)} tickers saved")
        return tickers

    except Exception as e:
        print(f"  -> NSE CSV failed: {e}")
        return None


def _fetch_from_nse_api():
    """Fetch from NSE API (needs session cookie)."""
    try:
        print("  Trying NSE API...")
        session = requests.Session()
        session.headers.update(NSE_HEADERS)

        # Get session cookie first
        session.get("https://www.nseindia.com", timeout=10)

        resp = session.get(NSE_API_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        stocks = data.get('data', [])
        tickers = [s['symbol'] for s in stocks if s.get('symbol')]
        tickers = list(set(tickers))

        if tickers:
            df = pd.DataFrame({'Ticker': tickers})
            df.to_csv(NIFTY500_TICKERS_FILE, index=False)
            print(f"  -> NSE API: {len(tickers)} tickers saved")
        return tickers

    except Exception as e:
        print(f"  -> NSE API failed: {e}")
        return None


def _fetch_from_wikipedia():
    """Scrape Nifty 500 list from Wikipedia as last resort."""
    try:
        print("  Trying Wikipedia...")
        tables = pd.read_html(WIKI_URL, match="Symbol")
        if tables:
            df = tables[0]
            sym_col = None
            for col in df.columns:
                if 'symbol' in str(col).lower():
                    sym_col = col
                    break
            if sym_col:
                tickers = df[sym_col].astype(str).str.strip().unique().tolist()
                tickers = [t for t in tickers if t and t != 'nan' and len(t) <= 20]
                if tickers:
                    pd.DataFrame({'Ticker': tickers}).to_csv(NIFTY500_TICKERS_FILE, index=False)
                    print(f"  -> Wikipedia: {len(tickers)} tickers saved")
                    return tickers
    except Exception as e:
        print(f"  -> Wikipedia failed: {e}")
    return None


def _load_cached_list():
    """Load previously saved ticker list."""
    if Path(NIFTY500_TICKERS_FILE).exists():
        df = pd.read_csv(NIFTY500_TICKERS_FILE)
        col = 'Ticker' if 'Ticker' in df.columns else df.columns[0]
        tickers = df[col].astype(str).str.strip().unique().tolist()
        tickers = [t for t in tickers if t and t != 'nan']
        print(f"  -> Loaded {len(tickers)} tickers from cache")
        return tickers
    print("  -> ERROR: No cached list found!")
    return []


def load_nifty500_list():
    """Load ticker list (cache first, then fetch)."""
    if Path(NIFTY500_TICKERS_FILE).exists():
        return _load_cached_list()
    return fetch_nifty500_list()


if __name__ == "__main__":
    tickers = fetch_nifty500_list()
    print(f"\nTotal: {len(tickers)} tickers")
    print(f"First 10: {tickers[:10]}")
    print(f"Last 10:  {tickers[-10:]}")
