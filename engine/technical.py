"""Technical scoring v7.2 — Dampened LC scoring, better BB range for SC."""
import os
import pandas as pd
import numpy as np
from engine.utils import safe_float

DATA_FILE = 'stock_data.csv'


def load_stock_data():
    if not os.path.exists(DATA_FILE):
        print(f"  ⚠️ {DATA_FILE} not found")
        return pd.DataFrame()
    df = pd.read_csv(DATA_FILE)
    n_tickers = df['Ticker'].nunique()
    n_rows = len(df)
    avg_days = n_rows // max(n_tickers, 1)
    print(f"  -> Loaded {DATA_FILE}: {n_tickers} tickers, {n_rows:,} rows (~{avg_days} days/ticker)")
    key_cols = [
        'Ticker', 'Date', 'Open', 'High', 'Low', 'Close', 'Volume',
        'SMA_9', 'SMA_22', 'SMA_50', 'SMA_52', 'SMA_200',
        'EMA_9', 'EMA_21', 'RSI_14',
        'MACD_Line', 'MACD_Signal', 'MACD_Hist',
        'ADX_14', 'BB_Upper', 'BB_Lower',
    ]
    found = [c for c in key_cols if c in df.columns]
    print(f"  -> Found: {len(found)}/{len(key_cols)} key columns")
    return df


def detect_mcap_scale(stock_df):
    if stock_df is None or stock_df.empty:
        return 10000
    if 'Market_Cap' not in stock_df.columns:
        return 10000
    latest = stock_df.groupby('Ticker').last()
    mcaps = latest['Market_Cap'].dropna()
    mcaps = mcaps[mcaps > 0]
    if mcaps.empty:
        return 10000
    median = mcaps.median()
    if median > 1e9:
        return 50000 * 1e7
    elif median > 1e6:
        return 50000
    return 10000


def get_latest_valid_rows(stock_df, n=22):
    if stock_df is None or stock_df.empty:
        return pd.DataFrame()
    out = []
    for ticker in stock_df['Ticker'].unique():
        tk = stock_df[stock_df['Ticker'] == ticker].sort_values('Date')
        tk = tk[tk['Close'].notna()]
        if len(tk) >= n:
            out.append(tk.tail(n))
        elif not tk.empty:
            out.append(tk)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def get_broad_sector(sub_industry):
    if not sub_industry or str(sub_industry).lower() in ('nan', 'none', ''):
        return 'Other'
    s = str(sub_industry).lower()
    mapping = {
        'Technology': ['software', 'tech', 'it ', 'digital', 'computer', 'saas',
                       'cloud', 'cyber', 'semiconductor', 'internet'],
        'Financial Services': ['bank', 'financ', 'insur', 'capital', 'credit',
                               'lending', 'nbfc', 'broker', 'asset management',
                               'wealth', 'exchange', 'rating'],
        'Healthcare': ['pharma', 'health', 'hospital', 'medic', 'biotech',
                       'diagnos', 'drug', 'therapeutic'],
        'Consumer Discretionary': ['auto', 'vehicle', 'retail', 'hotel',
                                   'restaurant', 'textile', 'apparel', 'fashion',
                                   'consumer durable', 'jewel', 'footwear',
                                   'leisure', 'media', 'entertainment'],
        'Consumer Staples': ['fmcg', 'food', 'beverage', 'dairy', 'agri',
                             'tobacco', 'personal care', 'household',
                             'consumer staple', 'packaged'],
        'Industrials': ['engineer', 'industrial', 'manufactur', 'capital goods',
                        'defence', 'defense', 'aerospace', 'logistics',
                        'shipping', 'transport', 'infra', 'construct',
                        'electric equipment', 'machinery', 'power equipment'],
        'Materials': ['metal', 'steel', 'mining', 'cement', 'chemical',
                      'ceramic', 'glass', 'paper', 'plastic', 'rubber',
                      'fertiliz', 'paint', 'packaging', 'refractor'],
        'Energy': ['oil', 'gas', 'energy', 'petrol', 'coal', 'power',
                   'renewable', 'solar', 'wind', 'utility'],
        'Real Estate': ['real estate', 'property', 'housing', 'realty'],
        'Specialty': ['conglomerate', 'diversified', 'holding', 'specialty'],
    }
    for broad, keywords in mapping.items():
        if any(kw in s for kw in keywords):
            return broad
    return 'Other'


def get_sector_from_stock_data(ticker, stock_df):
    if stock_df is None or stock_df.empty:
        return ""
    tk = stock_df[stock_df['Ticker'] == ticker]
    if tk.empty:
        return ""
    for col in ['Sector', 'Industry', 'Sub_Industry', 'sector', 'industry']:
        if col in tk.columns:
            val = tk.iloc[-1].get(col, "")
            if val and str(val).strip() and str(val).lower() not in ('nan', 'none', ''):
                return str(val).strip()
    return ""


def _find_support_levels(lows, current_price, band):
    levels = []
    arr = lows.values
    for i in range(2, len(arr) - 2):
        try:
            if (arr[i] < arr[i-1] and arr[i] < arr[i-2] and
                    arr[i] < arr[i+1] and arr[i] < arr[i+2]):
                v = float(arr[i])
                if v < current_price:
                    levels.append(v)
        except (TypeError, ValueError):
            continue
    return sorted(set(levels))[-3:] if levels else []


def _find_resistance_levels(highs, current_price, band):
    levels = []
    arr = highs.values
    for i in range(2, len(arr) - 2):
        try:
            if (arr[i] > arr[i-1] and arr[i] > arr[i-2] and
                    arr[i] > arr[i+1] and arr[i] > arr[i+2]):
                v = float(arr[i])
                if v > current_price:
                    levels.append(v)
        except (TypeError, ValueError):
            continue
    return sorted(set(levels))[:3] if levels else []


def _detect_knox(window):
    if len(window) < 26:
        return None
    last = window.iloc[-1]
    tenkan = safe_float(last.get('Ichi_Tenkan'), None)
    kijun = safe_float(last.get('Ichi_Kijun'), None)
    if tenkan is None or kijun is None:
        try:
            h = window['High'].astype(float)
            l = window['Low'].astype(float)
            tenkan = (h.rolling(9).max().iloc[-1] + l.rolling(9).min().iloc[-1]) / 2
            kijun = (h.rolling(26).max().iloc[-1] + l.rolling(26).min().iloc[-1]) / 2
        except Exception:
            return None
    close = safe_float(last.get('Close'), 0)
    if tenkan > kijun and close > tenkan:
        return 'Bullish'
    elif tenkan < kijun and close < tenkan:
        return 'Bearish'
    return None


def compute_tech_score(window, mcap_threshold, debug=False):
    """v7.2 — Dampened LC scoring, wider BB scoring range for SC.

    MEGA/LARGE: Trend dampened so max bearish from trend alone = -21 (not -30)
    MID/SMALL:  Higher BB weights so score can exceed ±20 entry threshold
    """
    if len(window) < 20:
        return 0, [], {}

    last = window.iloc[-1]
    close = safe_float(last.get('Close'), None)
    if close is None or close <= 0:
        return 0, [], {}

    mcap = safe_float(last.get('Market_Cap', 0), 0)
    is_largecap = mcap > mcap_threshold

    signals = []
    score = 0

    # ─── Common indicators ───
    rsi = safe_float(last.get('RSI_14'), 50)
    adx = safe_float(last.get('ADX_14'), 20)
    macd_hist = safe_float(last.get('MACD_Hist'), 0)
    sma9 = safe_float(last.get('SMA_9'), close)
    sma22 = safe_float(last.get('SMA_22'), close)
    sma50 = safe_float(last.get('SMA_50'), None) or safe_float(last.get('SMA_52'), close)
    sma200 = safe_float(last.get('SMA_200'), close)
    ema9 = safe_float(last.get('EMA_9'), close)
    ema21 = safe_float(last.get('EMA_21'), close)
    bb_upper = safe_float(last.get('BB_Upper'), None)
    bb_lower = safe_float(last.get('BB_Lower'), None)
    st_dir = safe_float(last.get('ST_Direction'), 0)

    vol = window['Volume'].astype(float) if 'Volume' in window.columns else pd.Series([0])
    vol_avg = vol.rolling(20).mean().iloc[-1] if len(vol) >= 20 else vol.mean()
    vol_current = safe_float(last.get('Volume', 0), 0)
    vol_surge = vol_current > vol_avg * 1.5 if vol_avg > 0 else False

    knox = _detect_knox(window) if len(window) >= 26 else None

    if is_largecap:
        # ═══════════════════════════════════════
        # MEGA / LARGE — DAMPENED TREND + S/R
        # Max from trend alone: ±21 (below ±30 entry threshold)
        # Needs S/R or confirmations to trigger signal
        # ═══════════════════════════════════════

        # Trend: Price vs long-term SMAs (dampened: max ±16)
        if close > sma200 and sma50 > sma200:
            score += 10
            signals.append('Above SMA200+50 uptrend')
        elif close < sma200 and sma50 < sma200:
            score -= 10
            signals.append('Below SMA200+50 downtrend')

        if close > sma50:
            score += 6
            signals.append('Above SMA50')
        elif close < sma50:
            score -= 6
            signals.append('Below SMA50')

        # EMA cross (max ±5)
        if ema9 > ema21:
            score += 5
            signals.append('EMA9>21 bullish')
        elif ema9 < ema21:
            score -= 5
            signals.append('EMA9<21 bearish')

        # S/R proximity (3% band)
        sr_band = close * 0.03
        highs = window['High'].astype(float)
        lows = window['Low'].astype(float)

        support_levels = _find_support_levels(lows, close, sr_band)
        resistance_levels = _find_resistance_levels(highs, close, sr_band)

        near_support = any(abs(close - s) < sr_band for s in support_levels) if support_levels else False
        near_resistance = any(abs(close - r) < sr_band for r in resistance_levels) if resistance_levels else False

        if near_support and rsi < 45:
            score += 10
            signals.append('Near support + RSI weak')
        if near_resistance and rsi > 55:
            score -= 10
            signals.append('Near resistance + RSI high')

        # RSI extremes (new for LC — adds conviction)
        if rsi < 30:
            score += 6
            signals.append(f'RSI oversold ({rsi:.0f})')
        elif rsi > 70:
            score -= 6
            signals.append(f'RSI overbought ({rsi:.0f})')

        # ADX trend strength
        if adx > 30:
            if macd_hist > 0:
                score += 5
                signals.append('Strong trend + MACD bull')
            else:
                score -= 5
                signals.append('Strong trend + MACD bear')

        # SuperTrend
        if st_dir < 0:
            score += 4
            signals.append('SuperTrend bull')
        elif st_dir > 0:
            score -= 4
            signals.append('SuperTrend bear')

        # Ichimoku
        if knox == 'Bullish':
            score += 4
            signals.append('Ichimoku bull')
        elif knox == 'Bearish':
            score -= 4
            signals.append('Ichimoku bear')

        # Volume
        if vol_surge:
            if close > sma9:
                score += 3
                signals.append('Volume surge + price up')
            else:
                score -= 3
                signals.append('Volume surge + price down')

        horizon = 28 if mcap > mcap_threshold * 5 else 21

    else:
        # ═══════════════════════════════════════
        # MID / SMALL — BOLLINGER BAND CENTRIC
        # Higher weights so total can exceed ±20 entry threshold
        # Max possible: ~±45 (BB:±25 + RSI:±12 + MACD:±8 + trend:±5 + vol:±5)
        # ═══════════════════════════════════════

        if bb_upper is not None and bb_lower is not None and bb_upper > bb_lower:
            bb_mid = (bb_upper + bb_lower) / 2
            bb_width = bb_upper - bb_lower
            bb_pct = (close - bb_lower) / bb_width * 100

            bb_width_pct = bb_width / bb_mid * 100 if bb_mid > 0 else 5
            is_squeeze = bb_width_pct < 4

            # Primary BB scoring (max ±25)
            if bb_pct < 10:
                score += 18
                signals.append(f'Near BB lower ({bb_pct:.0f}%)')
                if is_squeeze:
                    score += 7
                    signals.append('BB squeeze + oversold')
            elif bb_pct < 25:
                score += 10
                signals.append(f'Below BB mid ({bb_pct:.0f}%)')
            elif bb_pct > 90:
                score -= 18
                signals.append(f'Near BB upper ({bb_pct:.0f}%)')
                if is_squeeze:
                    score -= 7
                    signals.append('BB squeeze + overbought')
            elif bb_pct > 75:
                score -= 10
                signals.append(f'Above BB mid ({bb_pct:.0f}%)')

            if close > bb_upper:
                score -= 12
                signals.append('Above BB upper - overbought')
            elif close < bb_lower:
                score += 12
                signals.append('Below BB lower - oversold')
        else:
            if close > sma22:
                score += 6
                signals.append('Above SMA22 (no BB)')
            elif close < sma22:
                score -= 6
                signals.append('Below SMA22 (no BB)')

        # RSI (max ±12)
        if rsi < 30:
            score += 12
            signals.append(f'RSI oversold ({rsi:.0f})')
        elif rsi < 40:
            score += 6
            signals.append(f'RSI weak ({rsi:.0f})')
        elif rsi > 70:
            score -= 12
            signals.append(f'RSI overbought ({rsi:.0f})')
        elif rsi > 60:
            score -= 6
            signals.append(f'RSI elevated ({rsi:.0f})')

        # MACD (max ±8)
        if macd_hist > 0:
            score += 5
            signals.append('MACD bull')
            if adx > 25:
                score += 3
                signals.append('MACD + trending')
        else:
            score -= 5
            signals.append('MACD bear')
            if adx > 25:
                score -= 3
                signals.append('MACD bear + trending')

        # Short-term trend (max ±5)
        if close > sma22:
            score += 5
            signals.append('Above SMA22')
        elif close < sma22:
            score -= 5
            signals.append('Below SMA22')

        # SuperTrend (max ±5)
        if st_dir < 0:
            score += 5
            signals.append('SuperTrend bull')
        elif st_dir > 0:
            score -= 5
            signals.append('SuperTrend bear')

        # Volume spike (max ±5)
        if vol_surge:
            if close > ema9:
                score += 5
                signals.append('Volume spike + bullish')
            else:
                score -= 5
                signals.append('Volume spike + bearish')

        horizon = 14 if mcap > mcap_threshold * 0.3 else 7

    info = {
        'score': score,
        'signals': signals,
        'horizon': horizon,
        'is_largecap': is_largecap,
    }

    if debug:
        cap_label = 'LC' if is_largecap else 'SMC'
        print(
            f"    DEBUG {last.get('Ticker', '?')}({cap_label}): "
            f"RSI={rsi:.1f}, Close={close}, SMA50={sma50}, SMA200={sma200}, "
            f"BB={'yes' if bb_upper else 'no'}, Knox={knox}, "
            f"ADX={adx:.1f}, MCap={mcap:.0f}, Score={score}"
        )

    return score, signals, info


def get_technical_score(ticker, stock_df, mcap_threshold, debug=False):
    if stock_df is None or stock_df.empty:
        return {'score': 0, 'signals': [], 'horizon': 7}
    tk = stock_df[stock_df['Ticker'] == ticker].sort_values('Date')
    tk = tk[tk['Close'].notna()]
    if len(tk) < 20:
        return {'score': 0, 'signals': [], 'horizon': 7}
    window = tk.tail(200).reset_index(drop=True)
    score, signals, info = compute_tech_score(window, mcap_threshold, debug=debug)
    return {
        'score': score,
        'signals': signals,
        'horizon': info.get('horizon', 7),
    }
