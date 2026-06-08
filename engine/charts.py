"""Generate per-ticker chart data with signal flip markers + all indicators."""
import json, os
import pandas as pd
import numpy as np
from engine.technical import compute_tech_score
from engine.accuracy import ENTRY_THRESHOLD, EXIT_THRESHOLD, MIN_HOLD_DAYS
from engine.utils import safe_float


def _extract_line(valid, col):
    """Extract non-NaN line data for a column."""
    out = []
    for _, r in valid.iterrows():
        v = safe_float(r.get(col), None)
        ds = str(r.get('Date', ''))[:10]
        if v is not None and not pd.isna(v) and ds:
            out.append({'time': ds, 'value': round(v, 2)})
    return out


def generate_chart_data(stock_df, mcap_threshold, output_dir='charts'):
    os.makedirs(output_dir, exist_ok=True)
    count = 0

    for ticker in stock_df['Ticker'].unique():
        tk = (
            stock_df[stock_df['Ticker'] == ticker]
            .sort_values('Date').reset_index(drop=True)
        )
        valid = tk[tk['Close'].notna()].reset_index(drop=True)
        if len(valid) < 25:
            continue

        ohlc = []
        volume = []

        for _, r in valid.iterrows():
            c = safe_float(r.get('Close'), None)
            if c is None:
                continue
            ds = str(r.get('Date', ''))[:10]
            if not ds:
                continue
            ohlc.append({
                'time': ds,
                'open': round(safe_float(r.get('Open'), c), 2),
                'high': round(safe_float(r.get('High'), c), 2),
                'low': round(safe_float(r.get('Low'), c), 2),
                'close': round(c, 2),
            })
            v = safe_float(r.get('Volume'), None)
            if v is not None and not pd.isna(v):
                o = safe_float(r.get('Open'), c)
                volume.append({
                    'time': ds,
                    'value': int(v),
                    'color': 'rgba(34,197,94,0.3)' if c >= o else 'rgba(239,68,68,0.3)',
                })

        # Signal flip markers
        markers = []
        cur = 0
        hold_since = -999
        for i in range(20, len(valid)):
            ss = max(0, i - 20)
            sc_val, _, _ = compute_tech_score(valid.iloc[ss:i + 1], mcap_threshold)
            ds = str(valid.iloc[i].get('Date', ''))[:10]
            hold = i - hold_since
            if cur == 0:
                if sc_val > ENTRY_THRESHOLD:
                    markers.append({'time': ds, 'position': 'belowBar',
                        'color': '#22c55e', 'shape': 'arrowUp', 'text': 'BULL'})
                    cur = 1; hold_since = i
                elif sc_val < -ENTRY_THRESHOLD:
                    markers.append({'time': ds, 'position': 'aboveBar',
                        'color': '#ef4444', 'shape': 'arrowDown', 'text': 'BEAR'})
                    cur = -1; hold_since = i
            elif cur == 1:
                if hold >= MIN_HOLD_DAYS and sc_val < -EXIT_THRESHOLD:
                    markers.append({'time': ds, 'position': 'aboveBar',
                        'color': '#ef4444', 'shape': 'arrowDown', 'text': 'BEAR'})
                    cur = -1; hold_since = i
            elif cur == -1:
                if hold >= MIN_HOLD_DAYS and sc_val > EXIT_THRESHOLD:
                    markers.append({'time': ds, 'position': 'belowBar',
                        'color': '#22c55e', 'shape': 'arrowUp', 'text': 'BULL'})
                    cur = 1; hold_since = i

        # SuperTrend line (colored by direction)
        st_bull = []
        st_bear = []
        for _, r in valid.iterrows():
            ds = str(r.get('Date', ''))[:10]
            st_val = safe_float(r.get('SuperTrend'), None)
            st_dir = safe_float(r.get('ST_Direction'), None)
            if st_val is None or pd.isna(st_val) or not ds:
                continue
            if st_dir is not None and st_dir > 0:
                st_bull.append({'time': ds, 'value': round(st_val, 2)})
            else:
                st_bear.append({'time': ds, 'value': round(st_val, 2)})

        # MACD histogram (colored)
        macd_hist = []
        for _, r in valid.iterrows():
            ds = str(r.get('Date', ''))[:10]
            h = safe_float(r.get('MACD_Hist'), None)
            if h is not None and not pd.isna(h) and ds:
                macd_hist.append({
                    'time': ds, 'value': round(h, 4),
                    'color': 'rgba(34,197,94,0.6)' if h >= 0 else 'rgba(239,68,68,0.6)',
                })

        chart_data = {
            'ohlc': ohlc,
            'markers': markers,
            'volume': volume,
            # Moving averages
            'sma9': _extract_line(valid, 'SMA_9'),
            'sma22': _extract_line(valid, 'SMA_22'),
            'sma50': _extract_line(valid, 'SMA_50') or _extract_line(valid, 'SMA_52'),
            'sma200': _extract_line(valid, 'SMA_200'),
            'ema9': _extract_line(valid, 'EMA_9'),
            'ema21': _extract_line(valid, 'EMA_21'),
            # Bollinger Bands
            'bb_upper': _extract_line(valid, 'BB_Upper'),
            'bb_lower': _extract_line(valid, 'BB_Lower'),
            # SuperTrend
            'st_bull': st_bull,
            'st_bear': st_bear,
            # RSI
            'rsi': _extract_line(valid, 'RSI_14'),
            # MACD
            'macd_line': _extract_line(valid, 'MACD_Line'),
            'macd_signal': _extract_line(valid, 'MACD_Signal'),
            'macd_hist': macd_hist,
            # ADX
            'adx': _extract_line(valid, 'ADX_14'),
        }

        with open(f'{output_dir}/{ticker}.json', 'w') as f:
            json.dump(chart_data, f)
        count += 1

    print(f"  -> Chart data: {count} tickers in {output_dir}/")
    return count
