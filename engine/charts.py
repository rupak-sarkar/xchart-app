"""Generate per-ticker chart data with signal flip markers + indicators."""
import json, os
import pandas as pd
import numpy as np
from engine.technical import compute_tech_score
from engine.accuracy import ENTRY_THRESHOLD, EXIT_THRESHOLD, MIN_HOLD_DAYS
from engine.utils import safe_float


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
        sma9 = []
        sma22 = []
        sma200 = []
        ema9 = []
        ema21 = []
        rsi_data = []

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

            s9 = safe_float(r.get('SMA_9'), None)
            if s9 and not pd.isna(s9):
                sma9.append({'time': ds, 'value': round(s9, 2)})

            s22 = safe_float(r.get('SMA_22'), None)
            if s22 and not pd.isna(s22):
                sma22.append({'time': ds, 'value': round(s22, 2)})

            s200 = safe_float(r.get('SMA_200'), None)
            if s200 and not pd.isna(s200):
                sma200.append({'time': ds, 'value': round(s200, 2)})

            e9 = safe_float(r.get('EMA_9'), None)
            if e9 and not pd.isna(e9):
                ema9.append({'time': ds, 'value': round(e9, 2)})

            e21 = safe_float(r.get('EMA_21'), None)
            if e21 and not pd.isna(e21):
                ema21.append({'time': ds, 'value': round(e21, 2)})

            rsi = safe_float(r.get('RSI_14'), None)
            if rsi and not pd.isna(rsi):
                rsi_data.append({'time': ds, 'value': round(rsi, 2)})

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

        chart_data = {
            'ohlc': ohlc,
            'markers': markers,
            'volume': volume,
            'sma9': sma9,
            'sma22': sma22,
            'sma200': sma200,
            'ema9': ema9,
            'ema21': ema21,
            'rsi': rsi_data,
        }

        with open(f'{output_dir}/{ticker}.json', 'w') as f:
            json.dump(chart_data, f)
        count += 1

    print(f"  -> Chart data: {count} tickers in {output_dir}/")
    return count
