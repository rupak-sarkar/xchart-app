"""Feature extraction for ML model.
Extracts 25 normalized features from stock_data for LightGBM.
All features are ratios/normalized — no absolute prices."""
import numpy as np
import pandas as pd
from engine.utils import safe_float


FEATURE_NAMES = [
    'close_sma9_ratio',
    'close_sma22_ratio',
    'close_sma52_ratio',
    'close_sma200_ratio',
    'sma9_sma22_ratio',
    'sma22_sma52_ratio',
    'sma52_sma200_ratio',
    'rsi',
    'adx',
    'macd_hist_norm',
    'macd_diff_norm',
    'ema_cross_norm',
    'bb_position',
    'st_direction',
    'mom_5d',
    'mom_10d',
    'mom_20d',
    'volume_ratio_20d',
    'dist_to_support_pct',
    'dist_to_resistance_pct',
    'sr_position',
    'mcap_log',
    'avg_daily_range_20d',
    'up20_recent',
    'close_above_sma200',
]


def _safe_ratio(a, b):
    if a is None or b is None:
        return np.nan
    a = float(a)
    b = float(b)
    if b == 0 or np.isnan(a) or np.isnan(b):
        return np.nan
    return a / b - 1.0


def get_category(mcap, mcap_threshold=10000):
    if mcap is not None and mcap > 100000:
        return "MEGA"
    elif mcap is not None and mcap > 30000:
        return "LARGE"
    elif mcap is not None and mcap > mcap_threshold:
        return "MID"
    else:
        return "SMALL"


def get_horizon_and_threshold(category):
    params = {
        "MEGA": (14, 1.0),
        "LARGE": (10, 0.8),
        "MID": (7, 0.5),
        "SMALL": (5, 0.5),
    }
    return params.get(category, (7, 0.5))


def extract_features_for_point(valid_df, idx):
    """Extract features for a single prediction point.
    valid_df: sorted DataFrame for one ticker.
    idx: row index (the 'today' we predict from).
    Returns dict or None.
    """
    if idx < 20 or idx >= len(valid_df):
        return None

    row = valid_df.iloc[idx]
    close = safe_float(row.get('Close'), None)
    if close is None or close <= 0:
        return None

    sma9 = safe_float(row.get('SMA_9'), None)
    sma22 = safe_float(row.get('SMA_22'), None)
    sma52 = safe_float(row.get('SMA_52', row.get('SMA_50')), None)
    sma200 = safe_float(row.get('SMA_200'), None)
    rsi_val = safe_float(row.get('RSI_14'), None)
    adx_val = safe_float(row.get('ADX_14'), None)
    macd_line = safe_float(row.get('MACD_Line'), None)
    macd_signal = safe_float(row.get('MACD_Signal'), None)
    macd_hist = safe_float(row.get('MACD_Hist'), None)
    ema9 = safe_float(row.get('EMA_9'), None)
    ema21 = safe_float(row.get('EMA_21'), None)
    bb_upper = safe_float(row.get('BB_Upper'), None)
    bb_lower = safe_float(row.get('BB_Lower'), None)
    st_dir = safe_float(row.get('ST_Direction'), None)
    mcap = safe_float(row.get('Market_Cap'), None)
    volume = safe_float(row.get('Volume'), None)

    f = {}

    # ── Price position ratios ──
    f['close_sma9_ratio'] = _safe_ratio(close, sma9)
    f['close_sma22_ratio'] = _safe_ratio(close, sma22)
    f['close_sma52_ratio'] = _safe_ratio(close, sma52)
    f['close_sma200_ratio'] = _safe_ratio(close, sma200)

    # ── SMA alignment ──
    f['sma9_sma22_ratio'] = _safe_ratio(sma9, sma22)
    f['sma22_sma52_ratio'] = _safe_ratio(sma22, sma52)
    f['sma52_sma200_ratio'] = _safe_ratio(sma52, sma200)

    # ── Oscillators ──
    f['rsi'] = rsi_val if rsi_val is not None else np.nan
    f['adx'] = adx_val if adx_val is not None else np.nan

    # ── MACD normalised ──
    if macd_hist is not None:
        f['macd_hist_norm'] = macd_hist / close * 100
    else:
        f['macd_hist_norm'] = np.nan

    if macd_line is not None and macd_signal is not None:
        f['macd_diff_norm'] = (macd_line - macd_signal) / close * 100
    else:
        f['macd_diff_norm'] = np.nan

    # ── EMA cross ──
    if ema9 is not None and ema21 is not None:
        f['ema_cross_norm'] = (ema9 - ema21) / close * 100
    else:
        f['ema_cross_norm'] = np.nan

    # ── Bollinger position (0 = lower band, 1 = upper band) ──
    if bb_upper is not None and bb_lower is not None and bb_upper > bb_lower:
        f['bb_position'] = (close - bb_lower) / (bb_upper - bb_lower)
    else:
        f['bb_position'] = np.nan

    # ── SuperTrend ──
    f['st_direction'] = st_dir if st_dir is not None else np.nan

    # ── Momentum ──
    for lookback, name in [(5, 'mom_5d'), (10, 'mom_10d'), (20, 'mom_20d')]:
        if idx >= lookback:
            prev = safe_float(valid_df.iloc[idx - lookback].get('Close'), None)
            if prev and prev > 0:
                f[name] = (close - prev) / prev * 100
            else:
                f[name] = np.nan
        else:
            f[name] = np.nan

    # ── Volume ratio ──
    if idx >= 20 and volume is not None and 'Volume' in valid_df.columns:
        vol_slice = valid_df.iloc[max(0, idx - 19):idx + 1]['Volume'].dropna()
        avg_vol = vol_slice.mean() if len(vol_slice) > 0 else 0
        f['volume_ratio_20d'] = volume / avg_vol if avg_vol > 0 else np.nan
    else:
        f['volume_ratio_20d'] = np.nan

    # ── S/R distance ──
    recent = valid_df.iloc[max(0, idx - 19):idx + 1]
    support = None
    resistance = None
    if 'Low' in recent.columns and 'High' in recent.columns:
        lows = recent['Low'].dropna()
        highs = recent['High'].dropna()
        if len(lows) > 0:
            support = lows.min()
        if len(highs) > 0:
            resistance = highs.max()

    if support and support > 0:
        f['dist_to_support_pct'] = (close - support) / close * 100
    else:
        f['dist_to_support_pct'] = np.nan

    if resistance and resistance > 0:
        f['dist_to_resistance_pct'] = (resistance - close) / close * 100
    else:
        f['dist_to_resistance_pct'] = np.nan

    if support and resistance and resistance > support:
        f['sr_position'] = (close - support) / (resistance - support)
    else:
        f['sr_position'] = np.nan

    # ── Market cap (log₁₀) ──
    if mcap and mcap > 0:
        f['mcap_log'] = np.log10(mcap)
    else:
        f['mcap_log'] = np.nan

    # ── Avg daily range (volatility proxy) ──
    if idx >= 20 and 'High' in valid_df.columns and 'Low' in valid_df.columns:
        rng = valid_df.iloc[max(0, idx - 19):idx + 1]
        h = rng['High'].dropna().values
        l = rng['Low'].dropna().values
        c = rng['Close'].dropna().values
        n = min(len(h), len(l), len(c))
        if n > 0:
            f['avg_daily_range_20d'] = float(np.nanmean((h[:n] - l[:n]) / c[:n])) * 100
        else:
            f['avg_daily_range_20d'] = np.nan
    else:
        f['avg_daily_range_20d'] = np.nan

    # ── UP20 (institutional accumulation) ──
    if 'up_true' in valid_df.columns and idx >= 7:
        r7 = valid_df.iloc[max(0, idx - 6):idx + 1]
        try:
            f['up20_recent'] = int(
                r7['up_true'].apply(lambda x: 1 if int(float(x)) == 1 else 0).sum()
            )
        except Exception:
            f['up20_recent'] = 0
    else:
        f['up20_recent'] = 0

    # ── Above SMA200 (binary) ──
    if sma200 is not None:
        f['close_above_sma200'] = 1 if close > sma200 else 0
    else:
        f['close_above_sma200'] = np.nan

    return f


def extract_all_features(stock_df, mcap_threshold):
    """Extract features + labels for ALL tickers × ALL dates.
    Returns DataFrame with features, labels, metadata.
    """
    if stock_df is None or stock_df.empty:
        return pd.DataFrame()

    all_rows = []
    tickers = stock_df['Ticker'].unique()

    for tk in tickers:
        tk_data = stock_df[stock_df['Ticker'] == tk].sort_values('Date').reset_index(drop=True)
        valid =
