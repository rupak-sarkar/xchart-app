"""Market regime detection + sector strength (data-driven, no API)"""
import pandas as pd
import yfinance as yf
from engine.config import SECTOR_MAP
from engine.utils import is_bad_str
from engine.technical import get_latest_valid_rows, get_broad_sector

def get_nifty_change():
    try:
        h = yf.Ticker("^NSEI").history(period="5d")
        if len(h) >= 2: return round(((h['Close'].iloc[-1] - h['Close'].iloc[0]) / h['Close'].iloc[0]) * 100, 2)
    except: pass
    return 0.0

def compute_market_regime(stock_df, nifty_change):
    regime_data = {"regime": "CHOPPY", "score": 0, "breadth": 0.5, "nifty": nifty_change, "avg_rsi": 50.0, "lt_breadth": 0.5, "detail": ""}
    if stock_df is None or stock_df.empty: return regime_data
    valid = get_latest_valid_rows(stock_df)
    if valid.empty: return regime_data

    breadth = 0.5
    if 'SMA_22' in valid.columns:
        sv2 = valid[valid['SMA_22'].notna() & valid['Close'].notna()]
        if len(sv2) > 0:
            above = (sv2['Close'] > sv2['SMA_22']).sum(); breadth = above / len(sv2)
            print(f"  -> SMA22 breadth: {above}/{len(sv2)} = {breadth:.0%}")

    avg_rsi = 50.0
    if 'RSI_14' in valid.columns:
        rv = valid['RSI_14'].dropna()
        if len(rv) > 0: avg_rsi = rv.mean(); print(f"  -> Avg RSI: {avg_rsi:.1f} ({len(rv)} tickers)")

    lt_breadth = 0.5
    if 'SMA_200' in valid.columns:
        sv3 = valid[valid['SMA_200'].notna() & valid['Close'].notna()]
        if len(sv3) > 0: lt_breadth = (sv3['Close'] > sv3['SMA_200']).sum() / len(sv3); print(f"  -> SMA200 breadth: {lt_breadth:.0%}")

    bull = 0; bear = 0
    if breadth > 0.60: bull += 2
    elif breadth > 0.50: bull += 1
    elif breadth < 0.35: bear += 2
    elif breadth < 0.45: bear += 1
    if nifty_change > 1.0: bull += 2
    elif nifty_change > 0.3: bull += 1
    elif nifty_change < -1.0: bear += 2
    elif nifty_change < -0.3: bear += 1
    if avg_rsi > 60: bull += 1
    elif avg_rsi < 40: bear += 1
    if lt_breadth > 0.65: bull += 1
    elif lt_breadth < 0.40: bear += 1
    net = bull - bear
    if net >= 4: regime, sc = "BULL", 15
    elif net >= 2: regime, sc = "MILD_BULL", 8
    elif net <= -4: regime, sc = "BEAR", -15
    elif net <= -2: regime, sc = "MILD_BEAR", -8
    else: regime, sc = "CHOPPY", 0
    detail = f"breadth={breadth:.0%} nifty={nifty_change:+.2f}% rsi={avg_rsi:.0f} lt={lt_breadth:.0%}"
    return {"regime": regime, "score": sc, "breadth": breadth, "nifty": nifty_change, "avg_rsi": avg_rsi, "lt_breadth": lt_breadth, "detail": detail}

def compute_sector_strength(stock_df):
    if stock_df is None or stock_df.empty: return {}, 0.5
    valid = get_latest_valid_rows(stock_df)
    if valid.empty or 'Industry' not in valid.columns or 'SMA_22' not in valid.columns: return {}, 0.5
    sv2 = valid[valid['SMA_22'].notna() & valid['Close'].notna()]
    if len(sv2) == 0: return {}, 0.5
    market_breadth = (sv2['Close'] > sv2['SMA_22']).sum() / len(sv2)
    sub_scores = {}; sub_to_broad = {}
    for sector in sv2['Industry'].dropna().unique():
        if is_bad_str(sector): continue
        sd = sv2[sv2['Industry'] == sector]
        if len(sd) < 1: continue
        s_breadth = (sd['Close'] > sd['SMA_22']).sum() / len(sd)
        s_rsi = sd['RSI_14'].dropna().mean() if 'RSI_14' in sd.columns and len(sd['RSI_14'].dropna()) > 0 else 50.0
        sc = round((s_breadth - market_breadth) * 40)
        if s_rsi > 65: sc -= 5
        elif s_rsi < 35: sc += 5
        sc = max(-20, min(20, sc))
        sub_scores[sector] = {"score": sc, "breadth": s_breadth, "rsi": s_rsi, "count": len(sd)}
        sub_to_broad[sector] = get_broad_sector(sector)
    broad_scores = {}
    for broad in set(sub_to_broad.values()):
        if not broad: continue
        members = [s for s, b in sub_to_broad.items() if b == broad]
        if members: broad_scores[broad] = round(sum(sub_scores[m]["score"] for m in members) / len(members))
    for sub in sub_scores:
        if sub_scores[sub]["count"] < 2:
            broad = sub_to_broad.get(sub, "")
            if broad in broad_scores: sub_scores[sub]["score"] = round((sub_scores[sub]["score"] + broad_scores[broad]) / 2)
    return sub_scores, market_breadth

def get_macro_scores(sectors, stock_df, regime):
    macro_cache = {}
    sector_strength, market_breadth = compute_sector_strength(stock_df)
    unique_sectors = list(set(s for s in sectors if s and not is_bad_str(s)))
    if not unique_sectors: return macro_cache
    sub_to_broad = {sub: get_broad_sector(sub) for sub in unique_sectors}
    broad_set = set(sub_to_broad.values()) - {""}
    print(f"  -> {len(unique_sectors)} sub-industries -> {len(broad_set)} broad sectors")
    print(f"  -> Market breadth: {market_breadth:.0%}")
    broad_agg = {}
    for sub in unique_sectors:
        ss = sector_strength.get(sub, {"score": 0})
        combined = max(-30, min(30, regime["score"] + ss["score"]))
        macro_cache[sub] = {"score": combined, "context": f"{regime['regime']}|{ss.get('score', 0):+d}"}
        broad = sub_to_broad.get(sub, sub)
        if broad not in broad_agg: broad_agg[broad] = []
        broad_agg[broad].append(combined)
    for broad in sorted(broad_agg.keys(), key=lambda b: sum(broad_agg[b]) / len(broad_agg[b])):
        avg = sum(broad_agg[broad]) / len(broad_agg[broad])
        print(f"    {broad} ({len(broad_agg[broad])}): {avg:+.0f} [data-driven]")
    return macro_cache
