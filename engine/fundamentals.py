"""Fundamental scoring: Debt, FII/DII, OBV"""
import pandas as pd
from engine.utils import safe_int, safe_float

def score_fundamentals(ticker, stock_df):
    if stock_df is None or stock_df.empty: return {"score": 0, "concern": ""}
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty: return {"score": 0, "concern": ""}
    valid = tk_data[tk_data['Close'].notna()]
    if 'Date' in valid.columns: valid = valid.sort_values('Date')
    if valid.empty: return {"score": 0, "concern": ""}
    last = valid.iloc[-1]; score = 0; concerns = []

    de = safe_float(last.get('Debt_Eq'))
    if de is not None:
        if de > 200: score -= 20; concerns.append("Very high debt")
        elif de > 100: score -= 10; concerns.append("High debt")
        elif de < 30: score += 5

    if safe_int(last.get('up_true', 0)) == 1:
        score += 30; concerns.append("FII/DII accumulation")

    obv = safe_float(last.get('OBV'))
    if obv is not None and len(valid) >= 6 and 'OBV' in valid.columns:
        obv_prev = safe_float(valid.iloc[-6].get('OBV'))
        if obv_prev is not None and obv_prev != 0:
            oc = ((obv - obv_prev) / abs(obv_prev)) * 100
            if oc > 10: score += 15; concerns.append(f"OBV +{oc:.0f}%")
            elif oc < -10: score -= 15; concerns.append(f"OBV {oc:.0f}%")

    return {"score": max(-100, min(100, score)), "concern": "; ".join(concerns) if concerns else ""}
