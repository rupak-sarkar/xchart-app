"""Generate per-ticker chart data with signal flip markers."""
import json, os
import pandas as pd
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

        markers = []
        cur = 0
        hold_since = -999
        for i in range(20, len(valid)):
            ss = max(0, i - 20)
            sc, _, _ = compute_tech_score(valid.iloc[ss:i + 1], mcap_threshold)
            ds = str(valid.iloc[i].get('Date', ''))[:10]
            hold = i - hold_since

            if cur == 0:
                if sc > ENTRY_THRESHOLD:
                    markers.append({'time': ds, 'position': 'belowBar',
                        'color': '#22c55e', 'shape': 'arrowUp', 'text': 'BULL'})
                    cur = 1; hold_since = i
                elif sc < -ENTRY_THRESHOLD:
                    markers.append({'time': ds, 'position': 'aboveBar',
                        'color': '#ef4444', 'shape': 'arrowDown', 'text': 'BEAR'})
                    cur = -1; hold_since = i
            elif cur == 1:
                if hold >= MIN_HOLD_DAYS and sc < -EXIT_THRESHOLD:
                    markers.append({'time': ds, 'position': 'aboveBar',
                        'color': '#ef4444', 'shape': 'arrowDown', 'text': 'BEAR'})
                    cur = -1; hold_since = i
            elif cur == -1:
                if hold >= MIN_HOLD_DAYS and sc > EXIT_THRESHOLD:
                    markers.append({'time': ds, 'position': 'belowBar',
                        'color': '#22c55e', 'shape': 'arrowUp', 'text': 'BULL'})
                    cur = 1; hold_since = i

        with open(f'{output_dir}/{ticker}.json', 'w') as f:
            json.dump({'ohlc': ohlc, 'markers': markers}, f)
        count += 1

    print(f"  -> Chart data: {count} tickers in {output_dir}/")
    return count
