"""Smart data fetcher — auto-detects ticker changes, syncs everything.
Handles: new tickers, removed tickers, daily updates, full resets."""
import os
import time
import shutil
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

from engine.config import TODAY_IST

DATA_FILE = 'stock_data.csv'
HISTORY_FILE = 'history.csv'
CHARTS_DIR = 'charts'
ML_FILE = 'ml_predictions.csv'
ENSEMBLE_FILE = 'ensemble_predictions.csv'
TICKERS_FILE = 'tickers.csv'

LOOKBACK_YEARS = 2
BATCH_SIZE = 20
SLEEP_BETWEEN = 1.5

# Columns we expect in stock_data.csv
REQUIRED_COLS = [
    'Ticker', 'Date', 'Open', 'High', 'Low', 'Close', 'Volume',
    'SMA_9', 'SMA_22', 'SMA_50', 'SMA_52', 'SMA_200',
    'EMA_9', 'EMA_21',
    'RSI_14', 'MACD_Line', 'MACD_Signal', 'MACD_Hist',
    'ADX_14', 'BB_Upper', 'BB_Lower',
    'SuperTrend', 'ST_Direction', 'Market_Cap',
]


def _get_tickers_from_csv():
    """Load tickers from tickers.csv."""
    if not os.path.exists(TICKERS_FILE):
        return []
    df = pd.read_csv(TICKERS_FILE)
    col = 'Ticker' if 'Ticker' in df.columns else df.columns[0]
    return [str(t).strip() for t in df[col].dropna().unique() if str(t).strip()]


def _get_tickers_in_data():
    """Get tickers currently in stock_data.csv."""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        df = pd.read_csv(DATA_FILE, usecols=['Ticker'])
        return list(df['Ticker'].dropna().unique())
    except Exception:
        return []


def _compute_indicators(df):
    """Compute all technical indicators for a single ticker dataframe."""
    df = df.sort_values('Date').reset_index(drop=True)
    c = df['Close']
    h = df['High']
    l = df['Low']

    # SMAs
    df['SMA_9'] = c.rolling(9).mean()
    df['SMA_22'] = c.rolling(22).mean()
    df['SMA_50'] = c.rolling(50).mean()
    df['SMA_52'] = c.rolling(52).mean()
    df['SMA_200'] = c.rolling(200).mean()

    # EMAs
    df['EMA_9'] = c.ewm(span=9, adjust=False).mean()
    df['EMA_21'] = c.ewm(span=21, adjust=False).mean()

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI_14'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df['MACD_Line'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD_Line'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD_Line'] - df['MACD_Signal']

    # Bollinger Bands
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    df['BB_Upper'] = sma20 + 2 * std20
    df['BB_Lower'] = sma20 - 2 * std20

    # ADX
    df['ADX_14'] = _compute_adx(h, l, c, 14)

    # SuperTrend
    st, st_dir = _compute_supertrend(h, l, c, period=10, multiplier=3)
    df['SuperTrend'] = st
    df['ST_Direction'] = st_dir

    return df


def _compute_adx(high, low, close, period=14):
    """Compute ADX."""
    plus_dm = high.diff()
    minus_dm = low.diff().abs()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr.replace(0, np.nan))
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.rolling(period).mean()
    return adx


def _compute_supertrend(high, low, close, period=10, multiplier=3):
    """Compute SuperTrend indicator."""
    hl2 = (high + low) / 2
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    st = pd.Series(np.nan, index=close.index)
    direction = pd.Series(1, index=close.index)

    for i in range(period, len(close)):
        if i == period:
            st.iloc[i] = upper.iloc[i]
            direction.iloc[i] = -1 if close.iloc[i] > upper.iloc[i] else 1
            continue

        if direction.iloc[i - 1] == 1:  # bearish
            if close.iloc[i] > st.iloc[i - 1]:
                direction.iloc[i] = -1  # flip to bullish
                st.iloc[i] = lower.iloc[i]
            else:
                direction.iloc[i] = 1
                st.iloc[i] = min(upper.iloc[i], st.iloc[i - 1])
        else:  # bullish
            if close.iloc[i] < st.iloc[i - 1]:
                direction.iloc[i] = 1  # flip to bearish
                st.iloc[i] = upper.iloc[i]
            else:
                direction.iloc[i] = -1
                st.iloc[i] = max(lower.iloc[i], st.iloc[i - 1])

    return st, direction


def _fetch_ticker_data(ticker, start_date, end_date):
    """Fetch OHLCV data for a single ticker from yfinance."""
    if not HAS_YF:
        return None
    try:
        symbol = f"{ticker}.NS"
        data = yf.download(symbol, start=start_date, end=end_date,
                           progress=False, auto_adjust=True)
        if data.empty:
            # Try BSE
            symbol = f"{ticker}.BO"
            data = yf.download(symbol, start=start_date, end=end_date,
                               progress=False, auto_adjust=True)
        if data.empty:
            return None

        # Handle multi-level columns
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = data.reset_index()
        data['Ticker'] = ticker
        data['Date'] = pd.to_datetime(data['Date']).dt.strftime('%Y-%m-%d')

        # Get market cap
        try:
            info = yf.Ticker(f"{ticker}.NS").info
            data['Market_Cap'] = info.get('marketCap', 0)
            if data['Market_Cap'].iloc[0]:
                data['Market_Cap'] = data['Market_Cap'] / 1e7  # Convert to Cr
        except Exception:
            data['Market_Cap'] = 0

        return data
    except Exception as e:
        print(f"    Error fetching {ticker}: {e}")
        return None


def _fetch_batch(tickers, start_date, end_date, label=""):
    """Fetch data for a batch of tickers."""
    all_data = []
    total = len(tickers)

    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  {label} Batch {batch_num}/{total_batches}: {', '.join(batch[:5])}{'...' if len(batch) > 5 else ''}")

        for tk in batch:
            df = _fetch_ticker_data(tk, start_date, end_date)
            if df is not None and not df.empty:
                df = _compute_indicators(df)
                all_data.append(df)
            else:
                print(f"    ⚠️ No data for {tk}")

        if i + BATCH_SIZE < total:
            time.sleep(SLEEP_BETWEEN)

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return pd.DataFrame()


def _detect_changes():
    """Detect ticker additions and removals."""
    wanted = set(_get_tickers_from_csv())
    existing = set(_get_tickers_in_data())

    added = wanted - existing
    removed = existing - wanted
    kept = wanted & existing

    return {
        'wanted': wanted,
        'existing': existing,
        'added': sorted(added),
        'removed': sorted(removed),
        'kept': sorted(kept),
    }


def _get_last_date_per_ticker(stock_df):
    """Get the last date for each ticker in stock_data.csv."""
    if stock_df.empty:
        return {}
    stock_df['Date'] = pd.to_datetime(stock_df['Date'])
    return stock_df.groupby('Ticker')['Date'].max().to_dict()


def _cleanup_removed_tickers(removed):
    """Remove stale data for removed tickers."""
    if not removed:
        return

    print(f"\n  Cleaning up {len(removed)} removed tickers...")

    # Remove from stock_data.csv
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        before = len(df)
        df = df[~df['Ticker'].isin(removed)]
        df.to_csv(DATA_FILE, index=False)
        print(f"    stock_data.csv: {before} → {len(df)} rows")

    # Remove from history.csv
    if os.path.exists(HISTORY_FILE):
        try:
            hdf = pd.read_csv(HISTORY_FILE)
            hdf = hdf[~hdf['Ticker'].isin(removed)]
            hdf.to_csv(HISTORY_FILE, index=False)
            print(f"    history.csv: cleaned")
        except Exception:
            pass

    # Remove chart files
    for tk in removed:
        chart_file = os.path.join(CHARTS_DIR, f'{tk}.json')
        if os.path.exists(chart_file):
            os.remove(chart_file)
    print(f"    charts/: removed {len(removed)} stale files")

    # Remove from ML/ensemble predictions
    for f in [ML_FILE, ENSEMBLE_FILE]:
        if os.path.exists(f):
            try:
                mdf = pd.read_csv(f)
                mdf = mdf[~mdf['Ticker'].isin(removed)]
                mdf.to_csv(f, index=False)
            except Exception:
                pass

    print(f"    ✅ Cleanup done for: {', '.join(removed[:10])}{'...' if len(removed) > 10 else ''}")


def _update_existing_tickers(kept, stock_df):
    """Fetch only missing recent days for existing tickers."""
    if not kept:
        return pd.DataFrame()

    last_dates = _get_last_date_per_ticker(stock_df[stock_df['Ticker'].isin(kept)])
    today = datetime.now()
    tickers_to_update = []

    for tk in kept:
        last = last_dates.get(tk)
        if last is None:
            tickers_to_update.append(tk)
            continue
        days_behind = (today - last).days
        if days_behind > 1:
            tickers_to_update.append(tk)

    if not tickers_to_update:
        print(f"  All {len(kept)} existing tickers are up to date")
        return pd.DataFrame()

    # Find the earliest gap
    min_last = min(
        (last_dates.get(tk, datetime(2020, 1, 1)) for tk in tickers_to_update),
        default=datetime(2020, 1, 1)
    )
    start = (min_last + timedelta(days=1)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')

    print(f"\n  Updating {len(tickers_to_update)}/{len(kept)} existing tickers ({start} → {end})...")
    new_data = _fetch_batch(tickers_to_update, start, end, label="[UPDATE]")

    if not new_data.empty:
        # Remove any overlapping dates
        existing_dates = stock_df[stock_df['Ticker'].isin(tickers_to_update)].copy()
        existing_dates['Date'] = pd.to_datetime(existing_dates['Date']).dt.strftime('%Y-%m-%d')
        new_data['Date'] = pd.to_datetime(new_data['Date']).dt.strftime('%Y-%m-%d')

        # Create key for dedup
        existing_keys = set(
            existing_dates.apply(lambda r: f"{r['Ticker']}_{r['Date']}", axis=1)
        )
        new_data['_key'] = new_data.apply(lambda r: f"{r['Ticker']}_{r['Date']}", axis=1)
        new_data = new_data[~new_data['_key'].isin(existing_keys)].drop('_key', axis=1)

        print(f"    → {len(new_data)} new rows fetched")

    return new_data


def _fetch_new_tickers(added):
    """Fetch full history for new tickers."""
    if not added:
        return pd.DataFrame()

    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=LOOKBACK_YEARS * 365)).strftime('%Y-%m-%d')

    print(f"\n  Fetching {len(added)} NEW tickers ({start} → {end})...")
    return _fetch_batch(added, start, end, label="[NEW]")


def ensure_data_exists():
    """Main entry point — smart sync of stock data.

    1. Detect added/removed tickers
    2. Clean up removed tickers from all files
    3. Fetch full history for new tickers
    4. Fetch missing recent days for existing tickers
    5. Merge everything into stock_data.csv
    """
    print(f"Smart Data Sync | {TODAY_IST}")
    print("=" * 80)

    # Detect changes
    changes = _detect_changes()
    print(f"\n  Tickers wanted:   {len(changes['wanted'])}")
    print(f"  Tickers in data:  {len(changes['existing'])}")
    print(f"  New tickers:      {len(changes['added'])}")
    print(f"  Removed tickers:  {len(changes['removed'])}")
    print(f"  Kept tickers:     {len(changes['kept'])}")

    if changes['added']:
        print(f"  → NEW: {', '.join(changes['added'][:15])}{'...' if len(changes['added']) > 15 else ''}")
    if changes['removed']:
        print(f"  → REMOVED: {', '.join(changes['removed'][:15])}{'...' if len(changes['removed']) > 15 else ''}")

    # Step 1: Cleanup removed tickers
    _cleanup_removed_tickers(changes['removed'])

    # Step 2: Load existing data (after cleanup)
    if os.path.exists(DATA_FILE):
        stock_df = pd.read_csv(DATA_FILE)
        print(f"\n  Loaded {DATA_FILE}: {len(stock_df)} rows, {stock_df['Ticker'].nunique()} tickers")
    else:
        stock_df = pd.DataFrame()
        print(f"\n  No existing {DATA_FILE} — full fetch needed")

    # Step 3: Fetch new tickers (full history)
    new_data = _fetch_new_tickers(changes['added'])

    # Step 4: Update existing tickers (recent days only)
    update_data = _update_existing_tickers(changes['kept'], stock_df)

    # Step 5: Merge everything
    frames = [stock_df]
    if not new_data.empty:
        frames.append(new_data)
    if not update_data.empty:
        frames.append(update_data)

    if len(frames) > 1 or stock_df.empty:
        merged = pd.concat(frames, ignore_index=True)

        # Ensure all required columns exist
        for col in REQUIRED_COLS:
            if col not in merged.columns:
                merged[col] = np.nan

        # Sort
        merged = merged.sort_values(['Ticker', 'Date']).reset_index(drop=True)

        # Deduplicate
        before = len(merged)
        merged = merged.drop_duplicates(subset=['Ticker', 'Date'], keep='last')
        if len(merged) < before:
            print(f"  Deduped: {before} → {len(merged)} rows")

        # Save
        merged.to_csv(DATA_FILE, index=False)
        n_tickers = merged['Ticker'].nunique()
        avg_days = len(merged) // max(n_tickers, 1)
        print(f"\n  ✅ Saved {DATA_FILE}: {len(merged):,} rows, {n_tickers} tickers (~{avg_days} days/ticker)")
    else:
        print(f"\n  ✅ No changes needed — {DATA_FILE} is up to date")

    # Validate
    _validate_data()
    print("=" * 80)


def _validate_data():
    """Quick validation of stock_data.csv."""
    if not os.path.exists(DATA_FILE):
        print("  ⚠️ WARNING: stock_data.csv not found!")
        return

    df = pd.read_csv(DATA_FILE)
    wanted = set(_get_tickers_from_csv())
    in_data = set(df['Ticker'].unique())

    missing = wanted - in_data
    if missing:
        print(f"  ⚠️ Missing {len(missing)} tickers: {', '.join(sorted(missing)[:10])}")

    # Check data freshness
    df['Date'] = pd.to_datetime(df['Date'])
    latest = df['Date'].max()
    days_old = (datetime.now() - latest).days
    if days_old > 3:
        print(f"  ⚠️ Data is {days_old} days old (latest: {latest.strftime('%Y-%m-%d')})")
    else:
        print(f"  ✅ Data fresh — latest: {latest.strftime('%Y-%m-%d')}")

    # Check for tickers with very little data
    counts = df.groupby('Ticker').size()
    thin = counts[counts < 30]
    if len(thin) > 0:
        print(f"  ⚠️ {len(thin)} tickers with <30 days: {', '.join(thin.index[:5])}")


def fetch_daily():
    """Quick daily update — just fetch today's data for all tickers."""
    ensure_data_exists()


if __name__ == "__main__":
    ensure_data_exists()
