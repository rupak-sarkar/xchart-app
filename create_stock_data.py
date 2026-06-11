"""create_stock_data.py -- Recompute all technical indicators + refresh fundamentals.

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

# ===================================================================
# INDICATOR COMPUTATIONS
# ===================================================================

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
    """SuperTrend: returns (direction, st_value).
    direction: -1 = Bullish, +1 = Bearish.
    st_value: the actual SuperTrend line value for charting/signals.
    """
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
    st_value = np.full(n, np.nan)

    close_arr = close.values
    upper_arr = upper_basic.values
    lower_arr = lower_basic.values
    atr_arr = atr.values

    # -- FIX: Find first valid ATR index and initialize bands there --
    # Without this, NaN propagates forever through final_upper/final_lower
    # because comparisons like `lower_arr[i] > final_lower[i-1]` return
    # False when final_lower[i-1] is NaN, so the else branch copies NaN.
    first_valid = None
    for i in range(n):
        if not np.isnan(atr_arr[i]):
            first_valid = i
            break

    if first_valid is None:
        # No valid ATR at all — return empty
        return (pd.Series(direction, index=close.index),
                pd.Series(st_value, index=close.index))

    # Initialize at first valid index
    final_upper[first_valid] = upper_arr[first_valid]
    final_lower[first_valid] = lower_arr[first_valid]

    # Set initial direction based on price vs bands
    if close_arr[first_valid] > final_upper[first_valid]:
        direction[first_valid] = -1  # Bullish
    elif close_arr[first_valid] < final_lower[first_valid]:
        direction[first_valid] = 1   # Bearish
    else:
        direction[first_valid] = -1  # Default bullish if between bands

    # Main loop starts from first_valid + 1
    for i in range(first_valid + 1, n):
        if np.isnan(atr_arr[i]):
            final_upper[i] = final_upper[i - 1]
            final_lower[i] = final_lower[i - 1]
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
        if direction[i - 1] <= 0 and close_arr[i] > final_upper[i]:
            direction[i] = -1  # Bullish
        elif direction[i - 1] >= 0 and close_arr[i] < final_lower[i]:
            direction[i] = 1   # Bearish
        else:
            direction[i] = direction[i - 1]

    # Compute ST value line (lower band when bullish, upper when bearish)
    for i in range(n):
        if direction[i] == -1:  # Bullish -> support line
            st_value[i] = final_lower[i]
        elif direction[i] == 1:  # Bearish -> resistance line
            st_value[i] = final_upper[i]
        # direction == 0 (before first_valid) stays NaN

    return (pd.Series(direction, index=close.index),
            pd.Series(st_value, index=close.index))


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


# ===================================================================
# MAIN RECOMPUTATION
# ===================================================================

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

        # -- SMAs --
        tk['SMA_9'] = compute_sma(close, 9)
        tk['SMA_22'] = compute_sma(close, 22)
        tk['SMA_50'] = compute_sma(close, 50)
        tk['SMA_52'] = compute_sma(close, 52)
        tk['SMA_200'] = compute_sma(close, 200)

        # -- EMAs --
        tk['EMA_9'] = compute_ema(close, 9)
        tk['EMA_21'] = compute_ema(close, 21)

        # -- RSI --
        tk['RSI_14'] = compute_rsi(close, 14)

        # -- MACD --
        tk['MACD_Line'], tk['MACD_Signal'], tk['MACD_Hist'] = compute_macd(close)

        # -- Bollinger Bands --
        tk['BB_Upper'], tk['BB_Lower'] = compute_bollinger(close)

        # -- ADX --
        tk['ADX_14'] = compute_adx(high, low, close, 14)

        # -- SuperTrend (returns both direction AND value) --
        tk['ST_Direction'], tk['ST_Value'] = compute_supertrend(high, low, close)
        # Ensure ST_Value is clean numeric (NaN -> 0 for early rows)
        tk['ST_Value'] = pd.to_numeric(tk['ST_Value'], errors='coerce').fillna(0)

        # -- Ichimoku --
        tk['Ichi_Tenkan'], tk['Ichi_Kijun'] = compute_ichimoku(high, low)

        # -- ATR --
        tk['ATR_14'] = compute_atr(high, low, close, 14)

        # -- ATR_Pct (ATR as % of close, used by app.py for SL calc) --
        tk['ATR_Pct'] = (tk['ATR_14'] / close.replace(0, np.nan) * 100).round(2)

        results.append(tk)

    result_df = pd.concat(results, ignore_index=True)
    print(f"  Indicators recomputed for {total} tickers")
    return result_df


# ===================================================================
# FUNDAMENTALS (Market_Cap, Sector, PE, PB, ROE, etc.)
# ===================================================================

def refresh_fundamentals(df, force=False):
    """Fetch Market_Cap, Sector, and valuation ratios from yfinance."""
    import yfinance as yf

    tickers = df['Ticker'].unique()
    total = len(tickers)

    # Ensure columns exist with correct dtypes
    FUND_COLS_NUM = ['Market_Cap', 'PE_Ratio', 'PB_Ratio', 'ROE', 'Dividend_Yield', 'Debt_to_Equity']
    FUND_COLS_STR = ['Sector', 'Industry', 'Sub_Industry']

    for col in FUND_COLS_NUM:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

    for col in FUND_COLS_STR:
        if col not in df.columns:
            df[col] = ''
        else:
            df[col] = df[col].astype(str).replace('nan', '').replace('0', '').fillna('')

    # Check existing data
    if not force:
        last_mcap = df.groupby('Ticker')['Market_Cap'].last()
        last_mcap = pd.to_numeric(last_mcap, errors='coerce').fillna(0)
        filled = (last_mcap > 0).sum()

        last_sector = df.groupby('Ticker')['Sector'].last().fillna('')
        sector_filled = (last_sector.str.strip() != '').sum()
        sector_missing = sector_filled < total * 0.5

        last_pe = df.groupby('Ticker')['PE_Ratio'].last()
        last_pe = pd.to_numeric(last_pe, errors='coerce').fillna(0)
        pe_filled = (last_pe > 0).sum()
        pe_missing = pe_filled < total * 0.3

        if filled > total * 0.7 and not sector_missing and not pe_missing:
            missing = last_mcap[last_mcap <= 0].index.tolist()
            if not missing:
                print(f"  Fundamentals already present ({filled}/{total} MCap, {sector_filled} sectors, {pe_filled} PE)")
                return df
            tickers_to_fetch = missing
            print(f"  Refreshing {len(missing)} tickers with missing fundamentals...")
        elif sector_missing or pe_missing:
            tickers_to_fetch = list(tickers)
            reason = []
            if sector_missing: reason.append(f"sectors {sector_filled}/{total}")
            if pe_missing: reason.append(f"PE {pe_filled}/{total}")
            print(f"  Data incomplete ({', '.join(reason)}). Refreshing all {total} tickers...")
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
                        sector = (
                            info.get('sector', '') or
                            info.get('sectorDisp', '') or
                            info.get('industryDisp', '') or
                            ''
                        )
                        industry = (
                            info.get('industry', '') or
                            info.get('industryDisp', '') or
                            ''
                        )

                        pe = info.get('trailingPE', 0) or info.get('forwardPE', 0) or 0
                        pb = info.get('priceToBook', 0) or 0
                        roe = info.get('returnOnEquity', 0) or 0
                        dy = info.get('dividendYield', 0) or info.get('trailingAnnualDividendYield', 0) or 0
                        de = info.get('debtToEquity', 0) or 0

                        fund_data[ticker] = {
                            'Market_Cap': round(mcap / 1e7, 2),
                            'Sector': str(sector),
                            'Industry': str(industry),
                            'Sub_Industry': str(industry),
                            'PE_Ratio': round(float(pe), 2) if pe else 0.0,
                            'PB_Ratio': round(float(pb), 2) if pb else 0.0,
                            'ROE': round(float(roe) * 100, 2) if roe and abs(float(roe)) < 1 else round(float(roe), 2) if roe else 0.0,
                            'Dividend_Yield': round(float(dy) * 100, 2) if dy and abs(float(dy)) < 1 else round(float(dy), 2) if dy else 0.0,
                            'Debt_to_Equity': round(float(de) / 100, 2) if de and float(de) > 10 else round(float(de), 2) if de else 0.0,
                        }
                        fetched += 1
                        break
                except Exception:
                    continue

            if ticker not in fund_data:
                fund_data[ticker] = {
                    'Market_Cap': 0.0, 'Sector': '', 'Industry': '', 'Sub_Industry': '',
                    'PE_Ratio': 0.0, 'PB_Ratio': 0.0, 'ROE': 0.0,
                    'Dividend_Yield': 0.0, 'Debt_to_Equity': 0.0,
                }

        if i + batch_size < len(tickers_to_fetch):
            time.sleep(1.5)

    # Cast numeric columns to float before assignment (avoids int64 vs float TypeError)
    for col in FUND_COLS_NUM:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

    # Apply to all rows of each ticker
    for ticker, data in fund_data.items():
        mask = df['Ticker'] == ticker
        for col, val in data.items():
            df.loc[mask, col] = val

    # Report
    total_mcap = df.groupby('Ticker')['Market_Cap'].last()
    total_mcap = pd.to_numeric(total_mcap, errors='coerce').fillna(0)
    mcap_ok = (total_mcap > 0).sum()

    sector_last = df.groupby('Ticker')['Sector'].last().fillna('')
    sector_ok = (sector_last.str.strip() != '').sum()

    pe_last = df.groupby('Ticker')['PE_Ratio'].last()
    pe_last = pd.to_numeric(pe_last, errors='coerce').fillna(0)
    pe_ok = (pe_last > 0).sum()

    print(f"  Fundamentals: {mcap_ok}/{total} MCap | {sector_ok}/{total} Sector | {pe_ok}/{total} PE")

    return df


# ===================================================================
# VALIDATION
# ===================================================================

def validate_indicators(df):
    """Quick sanity check on recomputed indicators."""
    print("\n  Validating indicators...")
    tickers = df['Ticker'].unique()
    issues = 0

    sample = np.random.choice(tickers, min(5, len(tickers)), replace=False)

    for ticker in sample:
        tk = df[df['Ticker'] == ticker].sort_values('Date')
        last = tk.iloc[-1]
        close = float(last['Close'])

        sma9 = float(last.get('SMA_9', 0))
        sma200 = float(last.get('SMA_200', 0))
        rsi = float(last.get('RSI_14', 0))

        if len(tk) > 20 and abs(sma9 - close) < 0.001:
            print(f"    Warning: {ticker}: SMA_9 = Close ({sma9:.2f}) -- possible issue")
            issues += 1

        if len(tk) > 20 and abs(rsi - 50.0) < 0.01:
            print(f"    Warning: {ticker}: RSI_14 = 50.0 -- possible issue")
            issues += 1

        if len(tk) > 210 and (pd.isna(sma200) or sma200 == 0):
            print(f"    Warning: {ticker}: SMA_200 missing with {len(tk)} rows")
            issues += 1

    if issues == 0:
        print(f"  Validation passed (sampled {len(sample)} tickers)")
    else:
        print(f"  {issues} issues found -- check data pipeline")

    last_rows = df.groupby('Ticker').last()
    mcap_filled = pd.to_numeric(last_rows.get('Market_Cap', 0), errors='coerce').gt(0).sum()
    rsi_valid = last_rows['RSI_14'].between(1, 99).sum() if 'RSI_14' in last_rows.columns else 0
    sma9_valid = (last_rows['SMA_9'] != last_rows['Close']).sum() if 'SMA_9' in last_rows.columns else 0
    sector_filled = last_rows.get('Sector', pd.Series()).ne('').sum()
    pe_filled = pd.to_numeric(last_rows.get('PE_Ratio', 0), errors='coerce').gt(0).sum()
    st_valid = pd.to_numeric(last_rows.get('ST_Value', 0), errors='coerce').gt(0).sum()
    atr_valid = pd.to_numeric(last_rows.get('ATR_Pct', 0), errors='coerce').gt(0).sum()

    print(f"\n  Summary:")
    print(f"    Tickers:       {len(tickers)}")
    print(f"    RSI valid:     {rsi_valid}/{len(tickers)}")
    print(f"    SMA9 != Close: {sma9_valid}/{len(tickers)}")
    print(f"    Market_Cap:    {mcap_filled}/{len(tickers)}")
    print(f"    Sector:        {sector_filled}/{len(tickers)}")
    print(f"    PE_Ratio:      {pe_filled}/{len(tickers)}")
    print(f"    ST_Value:      {st_valid}/{len(tickers)}")
    print(f"    ATR_Pct:       {atr_valid}/{len(tickers)}")


# ===================================================================
# ENTRY POINT
# ===================================================================

def recompute_indicators(force_fundamentals=False):
    """Main entry -- recompute all indicators on existing stock_data.csv."""
    if not os.path.exists(DATA_FILE):
        print(f"  {DATA_FILE} not found -- run data_fetcher first")
        return False

    print(f"\n{'=' * 80}")
    print(f"Recomputing Indicators + Fundamentals")
    print(f"{'=' * 80}")

    df = pd.read_csv(DATA_FILE, low_memory=False)
    df['Ticker'] = df['Ticker'].astype(str).str.strip()
    n_tickers = df['Ticker'].nunique()
    n_rows = len(df)
    print(f"  Loaded: {n_rows:,} rows, {n_tickers} tickers")

    # Step 1: Recompute all technical indicators
    df = recompute_all_indicators(df)

    # Step 2: Refresh fundamentals
    df = refresh_fundamentals(df, force=force_fundamentals)

    # Step 3: Validate
    validate_indicators(df)

    # Step 4: Save
    df.to_csv(DATA_FILE, index=False)
    print(f"\n  Saved {DATA_FILE}: {n_rows:,} rows, {n_tickers} tickers")
    print(f"{'=' * 80}\n")
    return True


if __name__ == '__main__':
    force = '--force-fundamentals' in sys.argv
    recompute_indicators(force_fundamentals=force)
