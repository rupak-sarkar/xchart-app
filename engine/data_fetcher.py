"""Fetch 2Y historical OHLC data + compute all technical indicators.
Run modes:
    # keep current  - FULL: Download 2 years if stock_data.csv doesn't exist or is stale
        else:
            final_upper.iloc[i] = final_upper.iloc[i-1]
        # Final lower band
        if final_lower.iloc[i] > final_lower.iloc[i-1] or close.iloc[i-1] < final_lower.iloc[i-1]:
            pass
        else:
            final_lower.iloc[i] = final_lower.iloc[i-1]
        # Direction
        if st_direction.iloc[i-1] == 1:
            if close.iloc[i] < final_lower.iloc[i]:
                st_direction.iloc[i] = -1
            else:
                st_direction.iloc[i] = 1
        else:
            if close.iloc[i] > final_upper.iloc[i]:
                st_direction.iloc[i] = 1
            else:
                st_direction.iloc[i] = -1

    return st_direction

def compute_knoxville_divergence(close, rsi, period=20):
    """Simplified Knoxville Divergence detection"""
    knox = pd.Series("", index=close.index)
    if len(close) < period + 5:
        return knox
    for i in range(period, len(close)):
        window_close = close.iloc[i-period:i+1]
        window_rsi = rsi.iloc[i-period:i+1]
        if window_rsi.isna().any() or window_close.isna().any():
            continue
        # Bullish: price makes lower low but RSI makes higher low
        if close.iloc[i] <= window_close.min() * 1.01:
            rsi_at_prev_low = window_rsi.iloc[window_close.values.argmin()]
            if rsi.iloc[i] > rsi_at_prev_low + 3:
                knox.iloc[i] = "Bullish"
        # Bearish: price makes higher high but RSI makes lower high
        elif close.iloc[i] >= window_close.max() * 0.99:
            rsi_at_prev_high = window_rsi.iloc[window_close.values.argmax()]
            if rsi.iloc[i] < rsi_at_prev_high - 3:
                knox.iloc[i] = "Bearish"
    return knox

def compute_obv(close, volume):
    """On-Balance Volume"""
    obv = pd.Series(0.0, index=close.index)
    for i in range(1, len(close)):
        if close.iloc[i] > close.iloc[i-1]:
            obv.iloc[i] = obv.iloc[i-1] + volume.iloc[i]
        elif close.iloc[i] < close.iloc[i-1]:
            obv.iloc[i] = obv.iloc[i-1] - volume.iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i-1]
    return obv

def compute_fii_dii_proxy(close, volume, period=20):
    """UP20 flag: unusual volume + price up = institutional accumulation proxy"""
    avg_vol = volume.rolling(window=period, min_periods=period).mean()
    up_true = pd.Series(0, index=close.index)
    for i in range(1, len(close)):
        if pd.isna(avg_vol.iloc[i]) or avg_vol.iloc[i] == 0:
            continue
        vol_ratio = volume.iloc[i] / avg_vol.iloc[i]
        price_change = (close.iloc[i] - close.iloc[i-1]) / close.iloc[i-1] * 100
        if vol_ratio > 2.0 and price_change > 1.0:
            up_true.iloc[i] = 1
    return up_true


def compute_all_indicators(df):
    """Compute ALL technical indicators for a single ticker's dataframe"""
    if len(df) < 30:
        return df

    close = df['Close'].astype(float)
    high = df['High'].astype(float)
    low = df['Low'].astype(float)
    volume = df['Volume'].astype(float)

    # SMAs
    df['SMA_9'] = compute_sma(close, 9)
    df['SMA_22'] = compute_sma(close, 22)
    df['STD_22'] = close.rolling(window=22, min_periods=22).std()
    df['SMA_50'] = compute_sma(close, 50)
    df['SMA_52'] = compute_sma(close, 52)
    df['SMA_200'] = compute_sma(close, 200)

    # EMAs
    df['EMA_9'] = compute_ema(close, 9)
    df['EMA_21'] = compute_ema(close, 21)

    # RSI
    df['RSI_14'] = compute_rsi(close, 14)

    # MACD
    df['MACD_Line'], df['MACD_Signal'], df['MACD_Hist'] = compute_macd(close)

    # Bollinger Bands
    df['BB_Upper'], df['BB_Lower'], _, df['BB_Flag'] = compute_bollinger(close, 22)

    # ADX
    df['ADX_14'] = compute_adx(high, low, close, 14)

    # SuperTrend
    df['ST_Direction'] = compute_supertrend(high, low, close)

    # Knoxville Divergence
    rsi = df['RSI_14']
    df['Knoxville_Divergence'] = compute_knoxville_divergence(close, rsi)

    # OBV
    df['OBV'] = compute_obv(close, volume)

    # FII/DII proxy (UP20)
    df['up_true'] = compute_fii_dii_proxy(close, volume)

    return df


# ═══════════════════════════════════════════════════════════════
# FUNDAMENTAL DATA (from yfinance)
# ═══════════════════════════════════════════════════════════════

def get_fundamentals(ticker_ns):
    """Get Market_Cap, Debt_Eq, Industry from yfinance"""
    try:
        info = yf.Ticker(ticker_ns).info
        mcap = info.get('marketCap', None)
        if mcap and mcap > 1e7:
            mcap = round(mcap / 1e7)  # Convert to Crores
        debt_eq = info.get('debtToEquity', None)
        industry = info.get('industry', '')
        return {"Market_Cap": mcap, "Debt_Eq": debt_eq, "Industry": industry}
    except:
        return {"Market_Cap": None, "Debt_Eq": None, "Industry": ""}


# ═══════════════════════════════════════════════════════════════
# FULL FETCH: 2 Years Historical Data
# ═══════════════════════════════════════════════════════════════

def fetch_full_history(tickers, period="2y"):
    """Download 2Y OHLC for all tickers, compute indicators, save"""
    print(f"\n{'='*80}")
    print(f"FULL HISTORICAL DATA FETCH — {len(tickers)} tickers, period={period}")
    print(f"{'='*80}")

    all_data = []
    success = 0; failed = 0; fund_count = 0

    for i, tk in enumerate(tickers):
        symbol = f"{tk}.NS"
        try:
            hist = yf.Ticker(symbol).history(period=period)
            if hist.empty:
                # Try BSE
                symbol = f"{tk}.BO"
                hist = yf.Ticker(symbol).history(period=period)
            if hist.empty:
                print(f"  [{i+1:3d}] {tk:<14s} SKIP — no data")
                failed += 1; continue

            df = hist[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            df = df.reset_index()
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
            df['Ticker'] = tk

            # Fundamentals (once per ticker)
            fund = get_fundamentals(symbol)
            df['Market_Cap'] = fund['Market_Cap']
            df['Debt_Eq'] = fund['Debt_Eq']
            df['Industry'] = fund['Industry']

            if fund['Market_Cap'] is not None:
                fund_count += 1

            # Compute indicators
            df = compute_all_indicators(df)

            all_data.append(df)
            success += 1
            days = len(df)
            print(f"  [{i+1:3d}] {tk:<14s} OK — {days} days | MCap={fund['Market_Cap']} | {fund['Industry'][:30]}")

        except Exception as e:
            print(f"  [{i+1:3d}] {tk:<14s} ERROR — {str(e)[:60]}")
            failed += 1

        # Rate limiting
        if (i + 1) % 10 == 0:
            time.sleep(1)

    if not all_data:
        print("ERROR: No data fetched!"); return

    combined = pd.concat(all_data, ignore_index=True)

    # Reorder columns
    col_order = ['Ticker', 'Date', 'Open', 'High', 'Low', 'Close', 'Volume',
                 'Market_Cap', 'Debt_Eq', 'Industry', 'SMA_9', 'SMA_22', 'STD_22',
                 'SMA_50', 'SMA_52', 'SMA_200', 'EMA_9', 'EMA_21', 'RSI_14',
                 'MACD_Line', 'MACD_Signal', 'MACD_Hist', 'BB_Upper', 'BB_Lower',
                 'BB_Flag', 'ADX_14', 'ST_Direction', 'Knoxville_Divergence',
                 'OBV', 'up_true']
    existing = [c for c in col_order if c in combined.columns]
    extra = [c for c in combined.columns if c not in col_order]
    combined = combined[existing + extra]

    combined.to_csv(STOCK_DATA_FILE, index=False)

    print(f"\n{'='*80}")
    print(f"SAVED: {STOCK_DATA_FILE}")
    print(f"  Tickers: {success} success / {failed} failed")
    print(f"  Rows: {len(combined):,} | Days: ~{len(combined)//max(success,1)}")
    print(f"  Fundamentals: {fund_count} with Market Cap")
    print(f"  Indicators: SMA(9,22,50,52,200) EMA(9,21) RSI MACD BB ADX ST Knox OBV UP20")
    print(f"  File size: {os.path.getsize(STOCK_DATA_FILE)/1024/1024:.1f} MB")
    print(f"{'='*80}")


# ═══════════════════════════════════════════════════════════════
# DAILY UPDATE: Append today's data post-market
# ═══════════════════════════════════════════════════════════════

def update_daily(tickers):
    """Fetch latest data and append to existing stock_data.csv"""
    if not os.path.exists(STOCK_DATA_FILE):
        print("stock_data.csv not found — running full fetch instead")
        fetch_full_history(tickers)
        return

    print(f"\n{'='*80}")
    print(f"DAILY UPDATE — {len(tickers)} tickers")
    print(f"{'='*80}")

    existing = pd.read_csv(STOCK_DATA_FILE)
    existing['Ticker'] = existing['Ticker'].astype(str).str.replace('.NS', '', regex=False).str.strip().str.upper()

    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    updated = 0; skipped = 0; errors = 0

    for i, tk in enumerate(tickers):
        symbol = f"{tk}.NS"
        try:
            # Check last date in existing data
            tk_data = existing[existing['Ticker'] == tk]
            if not tk_data.empty and 'Date' in tk_data.columns:
                last_date = tk_data['Date'].max()
                if last_date >= today_str:
                    skipped += 1; continue
                # Fetch from last_date to today
                start = (pd.to_datetime(last_date) + timedelta(days=1)).strftime('%Y-%m-%d')
            else:
                # No existing data — fetch 2Y
                start = (datetime.now(IST) - timedelta(days=730)).strftime('%Y-%m-%d')

            hist = yf.Ticker(symbol).history(start=start)
            if hist.empty:
                hist = yf.Ticker(f"{tk}.BO").history(start=start)
            if hist.empty:
                skipped += 1; continue

            new_df = hist[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            new_df = new_df.reset_index()
            new_df['Date'] = pd.to_datetime(new_df['Date']).dt.strftime('%Y-%m-%d')
            new_df['Ticker'] = tk

            # Remove any dates already in existing
            existing_dates = set(tk_data['Date'].values) if not tk_data.empty else set()
            new_df = new_df[~new_df['Date'].isin(existing_dates)]

            if new_df.empty:
                skipped += 1; continue

            # Get fundamentals
            fund = get_fundamentals(symbol)
            new_df['Market_Cap'] = fund['Market_Cap']
            new_df['Debt_Eq'] = fund['Debt_Eq']
            new_df['Industry'] = fund['Industry']

            # Combine old + new for indicator computation
            if not tk_data.empty:
                combined_tk = pd.concat([tk_data, new_df], ignore_index=True)
            else:
                combined_tk = new_df.copy()

            combined_tk = combined_tk.sort_values('Date').reset_index(drop=True)

            # Recompute ALL indicators on full history
            combined_tk = compute_all_indicators(combined_tk)

            # Replace this ticker's data in existing
            existing = existing[existing['Ticker'] != tk]
            existing = pd.concat([existing, combined_tk], ignore_index=True)

            updated += 1
            print(f"  [{i+1:3d}] {tk:<14s} +{len(new_df)} days (total: {len(combined_tk)})")

        except Exception as e:
            errors += 1
            print(f"  [{i+1:3d}] {tk:<14s} ERROR: {str(e)[:60]}")

        if (i + 1) % 15 == 0:
            time.sleep(1)

    # Trim to 2 years max per ticker
    cutoff = (datetime.now(IST) - timedelta(days=730)).strftime('%Y-%m-%d')
    if 'Date' in existing.columns:
        existing = existing[existing['Date'] >= cutoff]

    existing = existing.sort_values(['Ticker', 'Date']).reset_index(drop=True)
    existing.to_csv(STOCK_DATA_FILE, index=False)

    print(f"\n  Updated: {updated} | Skipped: {skipped} | Errors: {errors}")
    print(f"  Total rows: {len(existing):,} | Tickers: {existing['Ticker'].nunique()}")
    print(f"  File size: {os.path.getsize(STOCK_DATA_FILE)/1024/1024:.1f} MB")
    print(f"{'='*80}")


# ═══════════════════════════════════════════════════════════════
# CHECK IF FULL FETCH NEEDED
# ═══════════════════════════════════════════════════════════════

def needs_full_fetch():
    """Check if stock_data.csv exists and has sufficient data"""
    if not os.path.exists(STOCK_DATA_FILE):
        print("stock_data.csv not found — full fetch needed")
        return True
    try:
        df = pd.read_csv(STOCK_DATA_FILE)
        if len(df) < 1000:
            print(f"stock_data.csv too small ({len(df)} rows) — full fetch needed")
            return True
        if 'Date' in df.columns:
            min_date = pd.to_datetime(df['Date']).min()
            days_span = (datetime.now(IST).date() - min_date.date()).days
            if days_span < 300:
                print(f"Only {days_span} days of data — full fetch needed (want 500+)")
                return True
        # Check if key columns exist
        required = ['SMA_9', 'SMA_22', 'SMA_200', 'RSI_14', 'MACD_Line', 'ADX_14']
        missing = [c for c in required if c not in df.columns]
        if missing:
            print(f"Missing columns {missing} — full fetch needed")
            return True
        print(f"stock_data.csv OK: {len(df):,} rows, {df['Ticker'].nunique()} tickers")
        return False
    except Exception as e:
        print(f"Error reading stock_data.csv: {e} — full fetch needed")
        return True


# ═══════════════════════════════════════════════════════════════
# ENTRY POINTS
# ═══════════════════════════════════════════════════════════════

def ensure_data_exists():
    """Called by main engine — ensures stock_data.csv has 2Y data"""
    tickers = load_ticker_list()
    if not tickers:
        print("ERROR: No tickers found"); return
    if needs_full_fetch():
        fetch_full_history(tickers)
    else:
        print("Historical data exists — skipping full fetch")

def run_daily_update():
    """Called by daily post-market cron job"""
    tickers = load_ticker_list()
    if not tickers:
        print("ERROR: No tickers found"); return
    if needs_full_fetch():
        fetch_full_history(tickers)
    else:
        update_daily(tickers)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "daily":
        run_daily_update()
    elif len(sys.argv) > 1 and sys.argv[1] == "full":
        tickers = load_ticker_list()
        fetch_full_history(tickers)
    else:
        ensure_data_exists()
  - DAILY: Append today's data post-market close
"""
import os
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone
import time

IST = timezone(timedelta(hours=5, minutes=30))
STOCK_DATA_FILE = "stock_data.csv"
TICKERS_FILE = "tickers.csv"


def load_ticker_list():
    if os.path.exists(TICKERS_FILE):
        df = pd.read_csv(TICKERS_FILE)
        df.columns = df.columns.str.strip()
        if 'Ticker' not in df.columns:
            df.rename(columns={df.columns[0]: 'Ticker'}, inplace=True)
        tks = [t.replace('.NS', '').strip().upper() for t in df['Ticker'].dropna().astype(str).tolist() if t.strip()]
        return list(dict.fromkeys(tks))
    return []


# ═══════════════════════════════════════════════════════════════
# TECHNICAL INDICATOR CALCULATIONS
# ═══════════════════════════════════════════════════════════════

def compute_sma(series, window):
    return series.rolling(window=window, min_periods=window).mean()

def compute_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    # Use Wilder's smoothing after initial SMA
    for i in range(period, len(avg_gain)):
        avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (period - 1) + loss.iloc[i]) / period
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_macd(close, fast=12, slow=26, signal=9):
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    macd_line = ema_fast - ema_slow
    macd_signal = compute_ema(macd_line, signal)
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist

def compute_bollinger(close, window=22):
    sma = compute_sma(close, window)
    std = close.rolling(window=window, min_periods=window).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    bb_flag = pd.Series("", index=close.index)
    bb_flag[close <= lower] = "BBL"
    bb_flag[close >= upper] = "BBH"
    return upper, lower, std, bb_flag

def compute_adx(high, low, close, period=14):
    """Average Directional Index"""
    plus_dm = high.diff()
    minus_dm = low.diff().apply(lambda x: -x)
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    # When both are positive, keep the larger one
    mask = plus_dm > minus_dm
    minus_dm[mask & (plus_dm > 0)] = 0
    plus_dm[~mask & (minus_dm > 0)] = 0

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period, min_periods=period).mean() / atr)

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx = dx.rolling(window=period, min_periods=period).mean()
    return adx

def compute_supertrend(high, low, close, period=10, multiplier=3):
    """SuperTrend indicator"""
    hl2 = (high + low) / 2
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    st_direction = pd.Series(1, index=close.index)
    final_upper = upper_band.copy()
    final_lower = lower_band.copy()

    for i in range(1, len(close)):
        if pd.isna(atr.iloc[i]):
            continue
        # Final upper band
        if final_upper.iloc[i] < final_upper.iloc[i-1] or close.iloc[i-1] > final_upper.iloc[i-1]:
