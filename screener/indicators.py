"""screener/indicators.py -- Compute technical indicators for Nifty 500 tickers.

Reuses the same indicator functions from create_stock_data.py but operates
on the screener data pipeline (per-ticker JSON for backtester).

Indicators computed:
  - SMA (9, 22, 50, 200)
  - EMA (9, 21)
  - RSI (14)
  - MACD (12/26/9)
  - Bollinger Bands (20, 2σ)
  - ADX (14)
  - SuperTrend (10, 3x)
  - ATR (14) + ATR_Pct
"""

import numpy as np
import pandas as pd
from pathlib import Path
from screener.config import NIFTY500_BACKTEST_DIR


# ===================================================================
# INDICATOR FUNCTIONS (standalone, no dependency on create_stock_data)
# ===================================================================

def sma(series, period):
    return series.rolling(window=period, min_periods=period).mean()


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    line = ema_f - ema_s
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist


def bollinger(close, period=20, std_dev=2):
    mid = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std()
    return mid + std_dev * std, mid - std_dev * std


def adx(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up = high - high.shift()
    down = low.shift() - low
    plus_dm = pd.Series(0.0, index=high.index)
    minus_dm = pd.Series(0.0, index=high.index)
    plus_dm[(up > down) & (up > 0)] = up[(up > down) & (up > 0)]
    minus_dm[(down > up) & (down > 0)] = down[(down > up) & (down > 0)]

    alpha = 1 / period
    atr = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    sp = plus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    sm = minus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    pdi = 100 * (sp / atr.replace(0, np.nan))
    mdi = 100 * (sm / atr.replace(0, np.nan))
    dx = 100 * ((pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan))
    return dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()


def supertrend(high, low, close, period=10, multiplier=3):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_val = tr.rolling(window=period, min_periods=period).mean()

    hl2 = (high + low) / 2
    ub = hl2 + multiplier * atr_val
    lb = hl2 - multiplier * atr_val

    n = len(close)
    fu = np.full(n, np.nan)
    fl = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)
    st_val = np.full(n, np.nan)

    c = close.values
    ua = ub.values
    la = lb.values
    aa = atr_val.values

    # Find first valid ATR index
    fv = None
    for idx in range(n):
        if not np.isnan(aa[idx]):
            fv = idx
            break
    if fv is None:
        return pd.Series(0, index=close.index), pd.Series(0.0, index=close.index)

    fu[fv] = ua[fv]
    fl[fv] = la[fv]
    direction[fv] = -1 if c[fv] > fu[fv] else 1

    for i in range(fv + 1, n):
        if np.isnan(aa[i]):
            fu[i] = fu[i - 1]
            fl[i] = fl[i - 1]
            direction[i] = direction[i - 1]
            continue

        fl[i] = la[i] if (la[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        fu[i] = ua[i] if (ua[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]

        if direction[i - 1] <= 0 and c[i] > fu[i - 1]:
            direction[i] = -1
        elif direction[i - 1] >= 0 and c[i] < fl[i - 1]:
            direction[i] = 1
        else:
            direction[i] = direction[i - 1]

    for i in range(n):
        if direction[i] == -1:
            st_val[i] = fl[i]
        elif direction[i] == 1:
            st_val[i] = fu[i]

    return pd.Series(direction, index=close.index), pd.Series(st_val, index=close.index)


def atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


# ===================================================================
# COMPUTE ALL INDICATORS FOR A SINGLE TICKER
# ===================================================================

def compute_indicators(df):
    """
    Compute all technical indicators for a single ticker's OHLCV DataFrame.

    Args:
        df: DataFrame with Date, Open, High, Low, Close, Volume columns

    Returns:
        DataFrame with all indicator columns added
    """
    if df is None or len(df) < 5:
        return df

    df = df.sort_values('Date').copy()

    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    c = df['Close'].astype(float)
    h = df['High'].astype(float)
    l = df['Low'].astype(float)

    # SMAs
    df['SMA_9'] = sma(c, 9)
    df['SMA_22'] = sma(c, 22)
    df['SMA_50'] = sma(c, 50)
    df['SMA_200'] = sma(c, 200)

    # EMAs
    df['EMA_9'] = ema(c, 9)
    df['EMA_21'] = ema(c, 21)

    # RSI
    df['RSI_14'] = rsi(c, 14)

    # MACD
    df['MACD_Line'], df['MACD_Signal'], df['MACD_Hist'] = macd(c)

    # Bollinger
    df['BB_Upper'], df['BB_Lower'] = bollinger(c)

    # ADX
    df['ADX_14'] = adx(h, l, c, 14)

    # SuperTrend
    df['ST_Direction'], df['ST_Value'] = supertrend(h, l, c)
    df['ST_Value'] = pd.to_numeric(df['ST_Value'], errors='coerce').fillna(0)

    # ATR
    df['ATR_14'] = atr(h, l, c, 14)
    df['ATR_Pct'] = (df['ATR_14'] / c.replace(0, np.nan) * 100).round(2)

    return df


# ===================================================================
# BATCH PROCESSING
# ===================================================================

def compute_all_indicators(all_data):
    """
    Compute indicators for all tickers.

    Args:
        all_data: dict of {ticker: DataFrame}

    Returns:
        dict of {ticker: DataFrame_with_indicators}
    """
    total = len(all_data)
    results = {}
    failed = 0

    print(f"\nComputing indicators for {total} tickers...")
    print("=" * 60)

    for i, (ticker, df) in enumerate(all_data.items()):
        if (i + 1) % 50 == 0 or i == 0 or i == total - 1:
            print(f"  [{i+1}/{total}] {ticker}...")

        try:
            result = compute_indicators(df)
            if result is not None:
                results[ticker] = result
            else:
                failed += 1
        except Exception as e:
            print(f"    WARNING: {ticker} failed: {e}")
            failed += 1

    print(f"\n  Computed: {len(results)} | Failed: {failed}")
    return results


def build_indicator_json(all_data_with_indicators):
    """
    Build per-ticker indicator data for backtest JSON.

    Returns dict of {ticker: indicator_dict} where indicator_dict
    contains arrays ready to embed in backtest JSON.
    """
    indicators_data = {}

    for ticker, df in all_data_with_indicators.items():
        if df is None or len(df) < 10:
            continue

        df = df.sort_values('Date').copy()

        ind = {
            "sma9": [], "sma22": [], "sma200": [],
            "ema9": [], "ema21": [],
            "bb_upper": [], "bb_lower": [],
            "rsi": [], "adx": [],
            "macd_line": [], "macd_signal": [], "macd_hist": [],
            "st_value": [], "st_dir": [],
            "atr_pct": [],
        }

        for _, row in df.iterrows():
            d = str(row['Date'])[:10]
            c = float(row.get('Close', 0))
            if c <= 0:
                continue

            def _v(col, decimals=2):
                val = float(row.get(col, 0) or 0)
                if pd.isna(val) or val == 0:
                    return None
                return round(val, decimals)

            ind["sma9"].append({"d": d, "v": _v("SMA_9")})
            ind["sma22"].append({"d": d, "v": _v("SMA_22")})
            ind["sma200"].append({"d": d, "v": _v("SMA_200")})
            ind["ema9"].append({"d": d, "v": _v("EMA_9")})
            ind["ema21"].append({"d": d, "v": _v("EMA_21")})
            ind["bb_upper"].append({"d": d, "v": _v("BB_Upper")})
            ind["bb_lower"].append({"d": d, "v": _v("BB_Lower")})
            ind["rsi"].append({"d": d, "v": _v("RSI_14")})
            ind["adx"].append({"d": d, "v": _v("ADX_14")})
            ind["macd_line"].append({"d": d, "v": _v("MACD_Line", 4)})
            ind["macd_signal"].append({"d": d, "v": _v("MACD_Signal", 4)})
            ind["macd_hist"].append({"d": d, "v": _v("MACD_Hist", 4)})
            ind["st_value"].append({"d": d, "v": _v("ST_Value")})
            ind["st_dir"].append({"d": d, "v": int(row.get("ST_Direction", 0) or 0)})
            ind["atr_pct"].append({"d": d, "v": _v("ATR_Pct")})

        # Clean: remove entries where value is None
        for key in ind:
            ind[key] = [e for e in ind[key] if e["v"] is not None]

        indicators_data[ticker] = ind

    return indicators_data


if __name__ == "__main__":
    from screener.ohlcv import _load_all_from_cache
    from screener.nifty500 import load_nifty500_list

    tickers = load_nifty500_list()[:5]  # Test with 5
    data = _load_all_from_cache(tickers)
    if data:
        results = compute_all_indicators(data)
        print(f"\nSample columns: {list(list(results.values())[0].columns)}")
