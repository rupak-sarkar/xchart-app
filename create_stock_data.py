"""create_stock_data.py — Recompute all technical indicators + refresh fundamentals.

Call after data_fetcher sync to ensure indicators are current.
Usage:
  python create_stock_data.py                    # recompute indicators only
  python create_stock_data.py --force-fundamentals  # also refresh Market_Cap/Sector
"""
import os
import sys
import time
import numpy as np
import pandas as pd

DATA_FILE = 'stock_data.csv'
TICKERS_FILE = 'tickers.csv'

# ═══════════════════════════════════════════════════════════════
# INDICATOR COMPUTATIONS
# ═══════════════════════════════════════════════════════════════

def compute_sma(series, period):
    return series.rolling(window=period, min_periods=period).mean()


def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(close, period=14):
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist


def compute_bollinger(close, period=20, std_dev=2):
    sma = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return upper, lower


def compute_adx(high, low, close, period=14):
    """Wilder's ADX."""
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - high.shift()
    down_move = low.shift() - low

    plus_dm = pd.Series(0.0, index=high.index, dtype=float)
    minus_dm = pd.Series(0.0, index=high.index, dtype=float)

    mask_plus = (up_move > down_move) & (up_move > 0)
    mask_minus = (down_move > up_move) & (down_move > 0)
    plus_dm[mask_plus] = up_move[mask_plus]
    minus_dm[mask_minus] = down_move[mask_minus]

    alpha = 1 / period
    atr = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    smooth_plus = plus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    smooth_minus = minus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    plus_di = 100 * (smooth_plus / atr.replace(0, np.nan))
    minus_di = 100 * (smooth_minus / atr.replace(0, np.nan))

    di_sum = plus_di + minus_di
    dx = 100 * ((plus_di - minus_di).abs() / di_sum.replace(0, np.nan))
    adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    return adx


def compute_supertrend(high, low, close, period=10, multiplier=3):
    """SuperTrend: direction -1 = Bullish, +1 = Bearish."""
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()

    hl2 = (high + low) / 2
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    n = len(close)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)

    close_arr = close.values
    upper_arr = upper_basic.values
    lower_arr = lower_basic.values
    atr_arr = atr.values

    # Initialize
    if n > 0:
        final_upper[0] = upper_arr[0]
        final_lower[0] = lower_arr[0]

    for i in range(1, n):
        if np.isnan(atr_arr[i]):
            final_upper[i] = upper_arr[i] if not np.isnan(upper_arr[i]) else final_upper[i - 1]
            final_lower[i] = lower_arr[i] if not np.isnan(lower_arr[i]) else final_lower[i - 1]
            direction[i] = direction[i - 1]
            continue

        # Final lower band
        if lower_arr[i] > final_lower[i - 1] or close_arr[i - 1] < final_lower[i - 1]:
            final_lower[i] = lower_arr[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # Final upper band
        if upper_arr[i] < final_upper[i - 1] or close_arr[i - 1] > final_upper[i - 1]:
            final_upper[i] = upper_arr[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # Direction
        if direction[i - 1] <= 0 and close_arr[i] > final_upper[i - 1]:
            direction[i] = -1  # Bullish
        elif direction[i - 1] >= 0 and close_arr[i] < final_lower[i - 1]:
            direction[i] = 1   # Bearish
        else:
            direction[i] = direction[i - 1]

    return pd.Series(direction, index=close.index)


def compute_ichimoku(high, low, tenkan_period=9, kijun_period=26):
    tenkan = (high.rolling(tenkan_period).max() + low.rolling(tenkan_period).min()) / 2
    kijun = (high.rolling(kijun_period).max() + low.rolling(kijun_period).min()) / 2
    return tenkan, kijun


def compute_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


# ═══════════════════════════════════════════════════════════════
# MAIN RECOMPUTATION
# ═══════════════════════════════════════════════════════════════

def recompute_all_indicators(df):
    """Recompute all technical indicators for every ticker."""
    print("\n  Recomputing technical indicators...")

    results = []
    tickers = df['Ticker'].unique()
    total = len(tickers)

    for idx, ticker in enumerate(tickers):
        if (idx + 1) % 30 == 0 or idx == 0 or idx == total - 1:
            print(f"    [{idx + 1}/{total}] {ticker}...")

        tk = df[df['Ticker'] == ticker].sort_values('Date').copy()

        if len(tk) < 5:
            results.append(tk)
            continue

        # Ensure numeric
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col in tk.columns:
                tk[col] = pd.to_numeric(tk[col], errors='coerce')

        close = tk['Close'].astype(float)
        high = tk['High'].astype(float)
        low = tk['Low'].astype(float)

        # ── SMAs ──
        tk['SMA_9'] = compute_sma(close, 9)
        tk['SMA_22'] = compute_sma(close, 22)
        tk['SMA_50'] = compute_sma(close, 50)
        tk['SMA_52'] = compute_sma(close, 52)
        tk['SMA_200'] = compute_sma(close, 200)

        # ── EMAs ──
        tk['EMA_9'] = compute_ema(close, 9)
        tk['EMA_21'] = compute_ema(close, 21)

        # ── RSI ──
        tk['RSI_14'] = compute_rsi(close, 14)

        # ── MACD ──
        tk['MACD_Line'], tk['MACD_Signal'], tk['MACD_Hist'] = compute_macd(close)

        # ── Bollinger Bands ──
        tk['BB_Upper'], tk['BB_Lower'] = compute_bollinger(close)

        # ── ADX ──
        tk['ADX_14'] = compute_adx(high, low, close, 14)

        # ── SuperTrend ──
        tk['ST_Direction'] = compute_supertrend(high, low, close)

        # ── Ichimoku ──
        tk['Ichi_Tenkan'], tk['Ichi_Kijun'] = compute_ichimoku(high, low)

        # ── ATR ──
        tk['ATR_14'] = compute_atr(high, low, close, 14)

        results.append(tk)

    result_df = pd.concat(results, ignore_index=True)
    print(f"  ✅ Indicators recomputed for {total} tickers")
    return result_df


# ═══════════════════════════════════════════════════════════════
# FUNDAMENTALS (Market_Cap, Sector)
# ═══════════════════════════════════════════════════════════════

def refresh_fundamentals(df, force=False):
    """Fetch Market_Cap, Sector, Industry from yfinance. Cached unless forced."""
    import yfinance as yf

    tickers = df['Ticker'].unique()
    total = len(tickers)

    # Ensure columns exist
    for col in ['Market_Cap', 'Sector', 'Industry', 'Sub_Industry']:
        if col not in df.columns:
            df[col] = 0 if col == 'Market_Cap' else ''

    # Check existing data
    if not force:
        last_mcap = df.groupby('Ticker')['Market_Cap'].last()
        last_mcap = pd.to_numeric(last_mcap, errors='coerce').fillna(0)
        filled = (last_mcap > 0).sum()
        if filled > total * 0.7:
            missing = last_mcap[last_mcap <= 0].index.tolist()
            if not missing:
                print(f"  ✅ Fundamentals already present ({filled}/{total} tickers)")
                return df
            tickers_to_fetch = missing
            print(f"  Refreshing {len(missing)} tickers with missing fundamentals...")
        else:
            tickers_to_fetch = list(tickers)
            print(f"  Fetching fundamentals for all {total} tickers...")
    else:
        tickers_to_fetch = list(tickers)
        print(f"  Force-refreshing fundamentals for {total} tickers...")

    fund_data = {}
    batch_size = 20
    fetched = 0

    for i in range(0, len(tickers_to_fetch), batch_size):
        batch = tickers_to_fetch[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(tickers_to_fetch) + batch_size - 1) // batch_size
        print(f"    Batch {batch_num}/{total_batches}: {batch[0]}..{batch[-1]}")

        for ticker in batch:
            for suffix in ['.NS', '.BO']:
                try:
                    info = yf.Ticker(f"{ticker}{suffix}").info
                    mcap = info.get('marketCap', 0) or 0
                    if mcap > 0:
                        fund_data[ticker] = {
                            'Market_Cap': round(mcap / 1e7, 2),  # → Crores
                            'Sector': info.get('sector', '') or '',
                            'Industry': info.get('industry', '') or '',
                            'Sub_Industry': info.get('industry', '') or '',
                        }
                        fetched += 1
                        break
                except Exception:
                    continue

            if ticker not in fund_data:
                fund_data[ticker] = {
                    'Market_Cap': 0, 'Sector': '', 'Industry': '', 'Sub_Industry': ''
                }

        if i + batch_size < len(tickers_to_fetch):
            time.sleep(1.5)  # Rate limit

    # Apply to all rows of each ticker
    for ticker, data in fund_data.items():
        mask = df['Ticker'] == ticker
        for col, val in data.items():
            df.loc[mask, col] = val

    total_filled = df.groupby('Ticker')['Market_Cap'].last()
    total_filled = pd.to_numeric(total_filled, errors='coerce').fillna(0)
    print(f"  ✅ Fundamentals: {(total_filled > 0).sum()}/{total} tickers with Market_Cap")

    return df


# ═══════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════

def validate_indicators(df):
    """Quick sanity check on recomputed indicators."""
    print("\n  Validating indicators...")
    tickers = df['Ticker'].unique()
    issues = 0

    # Sample 5 tickers
    sample = np.random.choice(tickers, min(5, len(tickers)), replace=False)

    for ticker in sample:
        tk = df[df['Ticker'] == ticker].sort_values('Date')
        last = tk.iloc[-1]
        close = float(last['Close'])

        sma9 = float(last.get('SMA_9', 0))
        sma200 = float(last.get('SMA_200', 0))
        rsi = float(last.get('RSI_14', 0))

        # SMA should not equal Close (unless very short history)
        if len(tk) > 20 and abs(sma9 - close) < 0.001:
            print(f"    ⚠️ {ticker}: SMA_9 = Close ({sma9:.2f}) — possible issue")
            issues += 1

        # RSI should not be exactly 50 (default/uncomputed)
        if len(tk) > 20 and abs(rsi - 50.0) < 0.01:
            print(f"    ⚠️ {ticker}: RSI_14 = 50.0 — possible issue")
            issues += 1

        # SMA200 should exist for tickers with 200+ rows
        if len(tk) > 210 and (pd.isna(sma200) or sma200 == 0):
            print(f"    ⚠️ {ticker}: SMA_200 missing with {len(tk)} rows")
            issues += 1

    if issues == 0:
        print(f"  ✅ Validation passed (sampled {len(sample)} tickers)")
    else:
        print(f"  ⚠️ {issues} issues found — check data pipeline")

    # Summary stats
    last_rows = df.groupby('Ticker').last()
    mcap_filled = pd.to_numeric(last_rows.get('Market_Cap', 0), errors='coerce').gt(0).sum()
    rsi_valid = last_rows['RSI_14'].between(1, 99).sum() if 'RSI_14' in last_rows.columns else 0
    sma9_valid = (last_rows['SMA_9'] != last_rows['Close']).sum() if 'SMA_9' in last_rows.columns else 0
    sector_filled = last_rows.get('Sector', pd.Series()).ne('').sum()

    print(f"\n  Summary:")
    print(f"    Tickers:       {len(tickers)}")
    print(f"    RSI valid:     {rsi_valid}/{len(tickers)}")
    print(f"    SMA9 ≠ Close:  {sma9_valid}/{len(tickers)}")
    print(f"    Market_Cap:    {mcap_filled}/{len(tickers)}")
    print(f"    Sector:        {sector_filled}/{len(tickers)}")


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def recompute_indicators(force_fundamentals=False):
    """Main entry — recompute all indicators on existing stock_data.csv."""
    if not os.path.exists(DATA_FILE):
        print(f"  ⚠️ {DATA_FILE} not found — run data_fetcher first")
        return False

    print(f"\n{'=' * 80}")
    print(f"Recomputing Indicators + Fundamentals")
    print(f"{'=' * 80}")

    df = pd.read_csv(DATA_FILE)
    n_tickers = df['Ticker'].nunique()
    n_rows = len(df)
    print(f"  Loaded: {n_rows:,} rows, {n_tickers} tickers")

    # Step 1: Recompute all technical indicators
    df = recompute_all_indicators(df)

    # Step 2: Refresh fundamentals (Market_Cap, Sector)
    df = refresh_fundamentals(df, force=force_fundamentals)

    # Step 3: Validate
    validate_indicators(df)

    # Step 4: Save
    df.to_csv(DATA_FILE, index=False)
    print(f"\n  ✅ Saved {DATA_FILE}: {n_rows:,} rows, {n_tickers} tickers")
    print(f"{'=' * 80}\n")
    return True


if __name__ == '__main__':
    force = '--force-fundamentals' in sys.argv
    recompute_indicators(force_fundamentals=force)
