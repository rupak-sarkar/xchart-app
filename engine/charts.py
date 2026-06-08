"""Generate per-ticker chart data. Computes indicators from OHLC
so charts always work regardless of stock_data.csv columns."""
import json, os
import pandas as pd
import numpy as np
from engine.technical import compute_tech_score
from engine.accuracy import ENTRY_THRESHOLD, EXIT_THRESHOLD, MIN_HOLD_DAYS
from engine.utils import safe_float


def _ensure_indicators(df):
    """Compute all indicators from OHLC if missing."""
    c = df['Close'].astype(float)
    h = df['High'].astype(float)
    l = df['Low'].astype(float)

    def _col_ok(col):
        return col in df.columns and df[col].notna().sum() > 20

    # SMAs
    if not _col_ok('SMA_9'):
        df['SMA_9'] = c.rolling(9).mean()
    if not _col_ok('SMA_22'):
        df['SMA_22'] = c.rolling(22).mean()
    if not _col_ok('SMA_50'):
        df['SMA_50'] = c.rolling(50).mean()
    if not _col_ok('SMA_52'):
        df['SMA_52'] = c.rolling(52).mean()
    if not _col_ok('SMA_200'):
        df['SMA_200'] = c.rolling(200).mean()

    # EMAs
    if not _col_ok('EMA_9'):
        df['EMA_9'] = c.ewm(span=9, adjust=False).mean()
    if not _col_ok('EMA_21'):
        df['EMA_21'] = c.ewm(span=21, adjust=False).mean()

    # RSI
    if not _col_ok('RSI_14'):
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['RSI_14'] = 100 - (100 / (1 + rs))

    # MACD
    if not _col_ok('MACD_Line'):
        e12 = c.ewm(span=12, adjust=False).mean()
        e26 = c.ewm(span=26, adjust=False).mean()
        df['MACD_Line'] = e12 - e26
        df['MACD_Signal'] = df['MACD_Line'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD_Line'] - df['MACD_Signal']

    # Bollinger Bands
    if not _col_ok('BB_Upper'):
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        df['BB_Upper'] = sma20 + 2 * std20
        df['BB_Lower'] = sma20 - 2 * std20

    # ADX
    if not _col_ok('ADX_14'):
        plus_dm = h.diff()
        minus_dm = l.diff().abs()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        pdi = 100 * (plus_dm.rolling(14).mean() / atr.replace(0, np.nan))
        mdi = 100 * (minus_dm.rolling(14).mean() / atr.replace(0, np.nan))
        dx = (abs(pdi - mdi) / (pdi + mdi).replace(0, np.nan)) * 100
        df['ADX_14'] = dx.rolling(14).mean()

    # SuperTrend
    if not _col_ok('SuperTrend'):
        period, mult = 10, 3
        hl2 = (h + l) / 2
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        upper = hl2 + mult * atr
        lower = hl2 - mult * atr
        st = pd.Series(np.nan, index=c.index)
        sd = pd.Series(1.0, index=c.index)
        for i in range(period, len(c)):
            if i == period:
                st.iloc[i] = upper.iloc[i]
                sd.iloc[i] = -1 if c.iloc[i] > upper.iloc[i] else 1
                continue
            if sd.iloc[i - 1] == 1:
                if c.iloc[i] > st.iloc[i - 1]:
                    sd.iloc[i] = -1; st.iloc[i] = lower.iloc[i]
                else:
                    sd.iloc[i] = 1; st.iloc[i] = min(upper.iloc[i], st.iloc[i - 1])
            else:
                if c.iloc[i] < st.iloc[i - 1]:
                    sd.iloc[i] = 1; st.iloc[i] = upper.iloc[i]
                else:
                    sd.iloc[i] = -1; st.iloc[i] = max(lower.iloc[i], st.iloc[i - 1])
        df['SuperTrend'] = st
        df['ST_Direction'] = sd

    # Ichimoku
    if not _col_ok('Ichi_Tenkan'):
        df['Ichi_Tenkan'] = (h.rolling(9).max() + l.rolling(9).min()) / 2
        df['Ichi_Kijun'] = (h.rolling(26).max() + l.rolling(26).min()) / 2
        df['Ichi_SpanA'] = ((df['Ichi_Tenkan'] + df['Ichi_Kijun']) / 2).shift(26)
        df['Ichi_SpanB'] = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)

    # VWAP (intraday proxy using cumulative)
    if not _col_ok('VWAP'):
        vol = df['Volume'].astype(float).replace(0, np.nan)
        tp = (h + l + c) / 3
        df['VWAP'] = (tp * vol).rolling(20).sum() / vol.rolling(20).sum()

    return df


def _line(valid, col):
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
        tk = stock_df[stock_df['Ticker'] == ticker].sort_values('Date').reset_index(drop=True)
        valid = tk[tk['Close'].notna()].reset_index(drop=True)
        if len(valid) < 25:
            continue

        # Compute all indicators
        valid = _ensure_indicators(valid)

        ohlc, volume = [], []
        for _, r in valid.iterrows():
            c = safe_float(r.get('Close'), None)
            if c is None: continue
            ds = str(r.get('Date', ''))[:10]
            if not ds: continue
            o = safe_float(r.get('Open'), c)
            ohlc.append({'time': ds, 'open': round(o, 2),
                'high': round(safe_float(r.get('High'), c), 2),
                'low': round(safe_float(r.get('Low'), c), 2), 'close': round(c, 2)})
            v = safe_float(r.get('Volume'), None)
            if v is not None and not pd.isna(v):
                volume.append({'time': ds, 'value': int(v),
                    'color': 'rgba(34,197,94,0.3)' if c >= o else 'rgba(239,68,68,0.3)'})

        # Signal markers
        markers = []
        cur, hold_since = 0, -999
        for i in range(20, len(valid)):
            sc_val, _, _ = compute_tech_score(valid.iloc[max(0, i - 20):i + 1], mcap_threshold)
            ds = str(valid.iloc[i].get('Date', ''))[:10]
            hold = i - hold_since
            if cur == 0:
                if sc_val > ENTRY_THRESHOLD:
                    markers.append({'time': ds, 'position': 'belowBar', 'color': '#22c55e', 'shape': 'arrowUp', 'text': 'BULL'})
                    cur, hold_since = 1, i
                elif sc_val < -ENTRY_THRESHOLD:
                    markers.append({'time': ds, 'position': 'aboveBar', 'color': '#ef4444', 'shape': 'arrowDown', 'text': 'BEAR'})
                    cur, hold_since = -1, i
            elif cur == 1 and hold >= MIN_HOLD_DAYS and sc_val < -EXIT_THRESHOLD:
                markers.append({'time': ds, 'position': 'aboveBar', 'color': '#ef4444', 'shape': 'arrowDown', 'text': 'BEAR'})
                cur, hold_since = -1, i
            elif cur == -1 and hold >= MIN_HOLD_DAYS and sc_val > EXIT_THRESHOLD:
                markers.append({'time': ds, 'position': 'belowBar', 'color': '#22c55e', 'shape': 'arrowUp', 'text': 'BULL'})
                cur, hold_since = 1, i

        # SuperTrend split
        st_bull, st_bear = [], []
        for _, r in valid.iterrows():
            ds = str(r.get('Date', ''))[:10]
            sv = safe_float(r.get('SuperTrend'), None)
            sd = safe_float(r.get('ST_Direction'), None)
            if sv is None or pd.isna(sv) or not ds: continue
            (st_bull if sd is not None and sd < 0 else st_bear).append({'time': ds, 'value': round(sv, 2)})

        # MACD histogram colored
        macd_hist = []
        for _, r in valid.iterrows():
            ds = str(r.get('Date', ''))[:10]
            hv = safe_float(r.get('MACD_Hist'), None)
            if hv is not None and not pd.isna(hv) and ds:
                macd_hist.append({'time': ds, 'value': round(hv, 4),
                    'color': 'rgba(34,197,94,0.6)' if hv >= 0 else 'rgba(239,68,68,0.6)'})

        data = {
            'ohlc': ohlc, 'markers': markers, 'volume': volume,
            'sma9': _line(valid, 'SMA_9'), 'sma22': _line(valid, 'SMA_22'),
            'sma50': _line(valid, 'SMA_50') or _line(valid, 'SMA_52'),
            'sma200': _line(valid, 'SMA_200'),
            'ema9': _line(valid, 'EMA_9'), 'ema21': _line(valid, 'EMA_21'),
            'bb_upper': _line(valid, 'BB_Upper'), 'bb_lower': _line(valid, 'BB_Lower'),
            'st_bull': st_bull, 'st_bear': st_bear,
            'rsi': _line(valid, 'RSI_14'),
            'macd_line': _line(valid, 'MACD_Line'), 'macd_signal': _line(valid, 'MACD_Signal'),
            'macd_hist': macd_hist,
            'adx': _line(valid, 'ADX_14'),
            'ichi_tenkan': _line(valid, 'Ichi_Tenkan'), 'ichi_kijun': _line(valid, 'Ichi_Kijun'),
            'ichi_spanA': _line(valid, 'Ichi_SpanA'), 'ichi_spanB': _line(valid, 'Ichi_SpanB'),
            'vwap': _line(valid, 'VWAP'),
        }

        with open(f'{output_dir}/{ticker}.json', 'w') as f:
            json.dump(data, f)
        count += 1

    print(f"  -> Chart data: {count} tickers in {output_dir}/")
    return count
