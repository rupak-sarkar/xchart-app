"""Strategy-based technical scoring — THE CORE SCORING ENGINE
Used by both live prediction AND backtesting"""
import os
import pandas as pd
from engine.config import STOCK_DATA_FILE, SECTOR_MAP
from engine.utils import is_bad_str, safe_int, safe_float, fv_row, sv_row


def load_stock_data():
    try:
        if os.path.exists(STOCK_DATA_FILE):
            df = pd.read_csv(STOCK_DATA_FILE)
            if 'Ticker' in df.columns:
                df['Ticker'] = df['Ticker'].astype(str).str.replace('.NS', '', regex=False).str.strip().str.upper()
                if 'Date' in df.columns: df = df.sort_values(['Ticker', 'Date'])
                print(f"  -> Loaded stock_data.csv: {df['Ticker'].nunique()} tickers, {len(df)} rows")
                key_cols = ['RSI_14', 'BB_Flag', 'SMA_9', 'SMA_22', 'SMA_50', 'SMA_52', 'SMA_200',
                            'Knoxville_Divergence', 'up_true', 'Close', 'High', 'Low', 'Market_Cap',
                            'Industry', 'MACD_Line', 'MACD_Signal', 'ADX_14', 'ST_Direction', 'EMA_9', 'EMA_21', 'OBV']
                found = [c for c in key_cols if c in df.columns]
                print(f"  -> Found: {len(found)}/{len(key_cols)} key columns")
                return df
    except Exception as e: print(f"  -> Error: {e}")
    print("  -> stock_data.csv not found"); return pd.DataFrame()


def detect_mcap_scale(stock_df):
    if stock_df is None or stock_df.empty or 'Market_Cap' not in stock_df.columns: return 10000
    mcap_max = stock_df['Market_Cap'].dropna().max()
    if pd.isna(mcap_max): return 10000
    return 1e11 if mcap_max > 1e9 else 10000


def get_sector_from_stock_data(ticker, stock_df):
    if stock_df is None or stock_df.empty: return ""
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty: return ""
    for cn in ['Industry', 'Sector']:
        if cn not in tk_data.columns: continue
        vals = tk_data[cn].dropna().astype(str).str.strip()
        vals = vals[vals.apply(lambda x: not is_bad_str(x))]
        if len(vals) > 0: return vals.iloc[-1]
    return ""


def get_broad_sector(sub):
    if not sub: return ""
    for broad, subs in SECTOR_MAP.items():
        if sub in subs: return broad
    return sub


def get_latest_valid_rows(stock_df):
    """Get latest row per ticker where Close AND SMA_22 are valid"""
    if stock_df is None or stock_df.empty: return pd.DataFrame()
    sdf = stock_df.sort_values(['Ticker', 'Date']) if 'Date' in stock_df.columns else stock_df
    results = []
    for ticker in sdf['Ticker'].unique():
        tk = sdf[sdf['Ticker'] == ticker]; valid = tk[tk['Close'].notna()]
        if 'SMA_22' in tk.columns:
            v2 = valid[valid['SMA_22'].notna()]
            if not v2.empty: results.append(v2.iloc[-1]); continue
        if not valid.empty: results.append(valid.iloc[-1])
    return pd.DataFrame(results).reset_index(drop=True) if results else pd.DataFrame()


def compute_tech_score(valid_df, mcap_threshold):
    """CORE SCORING — used by both live prediction and backtest.
    Input: valid_df = sorted dataframe of a single ticker's historical rows
    Returns: (score, signals_list)"""
    if len(valid_df) < 2: return 0, []
    score = 0; signals = []
    last = valid_df.iloc[-1]

    close = fv_row(last, ['Close'])
    if close is None: return 0, []
    sma9 = fv_row(last, ['SMA_9']); sma22 = fv_row(last, ['SMA_22'])
    sma52 = fv_row(last, ['SMA_52', 'SMA_50']); sma200 = fv_row(last, ['SMA_200'])
    rsi = fv_row(last, ['RSI_14', 'RSI']); adx = fv_row(last, ['ADX_14'])
    st_dir = fv_row(last, ['ST_Direction']); macd_line = fv_row(last, ['MACD_Line'])
    macd_signal = fv_row(last, ['MACD_Signal']); macd_hist = fv_row(last, ['MACD_Hist'])
    ema9 = fv_row(last, ['EMA_9']); ema21 = fv_row(last, ['EMA_21'])
    mcap = fv_row(last, ['Market_Cap'])
    is_large = mcap is not None and mcap > mcap_threshold
    tag = "LC" if is_large else "SMC"
    is_trending = adx is not None and adx > 25

    # ── SUPPORT / RESISTANCE ──
    support = None; resistance = None
    if 'Low' in valid_df.columns and 'High' in valid_df.columns:
        recent = valid_df.tail(20)
        lows = recent['Low'].dropna(); highs = recent['High'].dropna()
        if len(lows) > 0: support = lows.min()
        if len(highs) > 0: resistance = highs.max()
    near_support = support is not None and close <= support * 1.02
    near_resistance = resistance is not None and close >= resistance * 0.98
    at_breakout = resistance is not None and close > resistance
    at_breakdown = support is not None and close < support

    # ═══ TIER 1: SMA HIERARCHY ═══
    has_all = all(v is not None for v in [sma9, sma22, sma52, sma200])
    has_short = all(v is not None for v in [sma9, sma22])

    if is_large and has_all:
        if close < sma9 < sma22 < sma52 < sma200:
            if is_trending: score += 25; signals.append(f"{tag} FULL oversold (trending)")
            else: score += 40; signals.append(f"{tag} FULL oversold (mean reversion)")
        elif close < sma9 < sma22 < sma52:
            score += 20; signals.append(f"{tag} 4-level oversold")
        elif close < sma9 < sma22:
            score += 12; signals.append(f"{tag} short-term oversold")
        elif close > sma9 > sma22 > sma52 > sma200:
            if is_trending: score += 15; signals.append(f"{tag} FULL uptrend (ADX={adx:.0f})")
            else: score -= 25; signals.append(f"{tag} overextended")
        elif close > sma9 > sma22 > sma52:
            if is_trending: score += 10; signals.append(f"{tag} 4-level uptrend")
            else: score -= 15; signals.append(f"{tag} 4-level stretched")
        elif close > sma9 > sma22:
            score += 8; signals.append(f"{tag} short uptrend")
        else:
            if close < sma22: score -= 8; signals.append("Below SMA22")
            else: score += 5
            if close < sma200: score -= 15; signals.append("Below SMA200")
            elif close > sma200: score += 8
    elif not is_large and has_short:
        if close > sma9 > sma22:
            score += 15; signals.append(f"{tag} uptrend")
            if sma52 is not None and sma22 > sma52: score += 10; signals.append("Medium confirmed")
        elif close < sma9 < sma22:
            score -= 15; signals.append(f"{tag} downtrend")
            if sma52 is not None and sma22 < sma52: score -= 10; signals.append("Medium confirms down")
        elif close > sma22 and sma9 is not None and sma9 <= sma22:
            score += 20; signals.append(f"{tag} breakout SMA22")
        elif close < sma22 and sma9 is not None and sma9 >= sma22:
            score -= 20; signals.append(f"{tag} breakdown SMA22")
        else:
            if close < sma22: score -= 8
            else: score += 5
        if at_breakout: score += 20; signals.append(f"Breakout R={resistance:.0f}")
        elif at_breakdown: score -= 20; signals.append(f"Breakdown S={support:.0f}")
        elif near_support: score += 12; signals.append(f"Near support S={support:.0f}")
        elif near_resistance: score -= 8; signals.append(f"Near resistance R={resistance:.0f}")
    else:
        if sma22 is not None:
            if close < sma22: score -= 10
            else: score += 5
        if sma200 is not None:
            if close < sma200: score -= 12
            else: score += 5

    # ═══ TIER 2: CONFIRMATION ═══
    bb = sv_row(last, ['BB_Flag'])
    if bb is not None:
        bbs = bb.strip().upper()
        if bbs == 'BBL':
            if near_support and rsi is not None and rsi < 35: score += 35; signals.append(f"BBL+S+RSI({rsi:.0f})")
            elif rsi is not None and rsi < 35: score += 30; signals.append(f"BBL+RSI({rsi:.0f})")
            elif near_support: score += 25; signals.append("BBL at support")
            else: score += 20; signals.append("BBL reversal")
        elif bbs == 'BBH':
            if near_resistance and rsi is not None and rsi > 65: score -= 35; signals.append(f"BBH+R+RSI({rsi:.0f})")
            elif rsi is not None and rsi > 65: score -= 30; signals.append(f"BBH+RSI({rsi:.0f})")
            elif near_resistance: score -= 25; signals.append("BBH at resistance")
            else: score -= 20; signals.append("BBH reversal")

    knox = sv_row(last, ['Knoxville_Divergence'])
    if knox is not None:
        ks = knox.lower()
        if 'bullish' in ks:
            if near_support: score += 35; signals.append("Knox bull at support")
            elif rsi is not None and rsi < 40: score += 25; signals.append(f"Knox bull+RSI({rsi:.0f})")
            else: score += 15; signals.append("Knox bullish")
        elif 'bearish' in ks:
            if near_resistance: score -= 35; signals.append("Knox bear at resistance")
            elif rsi is not None and rsi > 60: score -= 25; signals.append(f"Knox bear+RSI({rsi:.0f})")
            else: score -= 15; signals.append("Knox bearish")

    # UP20 Reconsolidation
    if 'up_true' in valid_df.columns and len(valid_df) >= 7:
        recent_7 = valid_df.tail(7)
        try: up_rows = recent_7[recent_7['up_true'].apply(lambda x: safe_int(x) == 1)]
        except: up_rows = pd.DataFrame()
        latest_up = safe_int(last.get('up_true', 0)) == 1
        if len(up_rows) > 0 and not latest_up and 'Low' in up_rows.columns:
            up_low = up_rows['Low'].dropna().min()
            if up_low is not None and pd.notna(up_low):
                if close <= up_low * 1.02: score += 30; signals.append(f"UP20 recons at {up_low:.0f}")
                elif close <= up_low * 1.05: score += 15; signals.append("UP20 pullback")

    # ═══ TIER 3: SUPPORTING ═══
    if macd_line is not None and macd_signal is not None:
        if macd_line > macd_signal: score += 12; signals.append("MACD bull")
        else: score -= 12; signals.append("MACD bear")
    if macd_hist is not None: score += 3 if macd_hist > 0 else -3

    if ema9 is not None and ema21 is not None:
        if ema9 > ema21: score += 10; signals.append("EMA golden")
        else: score -= 10; signals.append("EMA death")

    if st_dir is not None:
        try:
            st = int(float(st_dir))
            if st == 1: score += 8; signals.append("ST up")
            elif st == -1: score -= 8; signals.append("ST down")
        except: pass

    if len(valid_df) >= 6:
        try:
            pc = valid_df.iloc[-6].get('Close')
            if pc and close and pd.notna(pc) and pc > 0:
                mom = ((close - pc) / pc) * 100
                if mom > 5: score += 15; signals.append(f"Mom5d +{mom:.1f}%")
                elif mom > 2: score += 8; signals.append(f"Mom5d +{mom:.1f}%")
                elif mom < -5: score -= 15; signals.append(f"Mom5d {mom:.1f}%")
                elif mom < -2: score -= 8; signals.append(f"Mom5d {mom:.1f}%")
        except: pass

    rsi_used = any('RSI' in s for s in signals)
    if rsi is not None and not rsi_used:
        if rsi > 80: score -= 12; signals.append(f"RSI OB({rsi:.0f})")
        elif rsi > 70: score -= 6; signals.append(f"RSI high({rsi:.0f})")
        elif rsi < 20: score += 12; signals.append(f"RSI OS({rsi:.0f})")
        elif rsi < 30: score += 6; signals.append(f"RSI low({rsi:.0f})")

    # ═══ TIER 4: ADX MODIFIER ═══
    if adx is not None and adx > 25 and st_dir is not None:
        try:
            st = int(float(st_dir))
            if st == 1 and score < 0:
                adj = min(15, int(abs(score) * 0.25)); score += adj
            elif st == -1 and score > 0:
                adj = min(15, int(abs(score) * 0.25)); score -= adj
        except: pass

    return max(-100, min(100, score)), signals


def get_technical_score(ticker, stock_df, mcap_threshold, debug=False):
    if stock_df is None or stock_df.empty: return {"score": 0, "signals": []}
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty: return {"score": 0, "signals": []}
    valid = tk_data[tk_data['Close'].notna()]
    if 'Date' in valid.columns: valid = valid.sort_values('Date')
    if valid.empty: return {"score": 0, "signals": []}
    score, signals = compute_tech_score(valid, mcap_threshold)
    if debug:
        last = valid.iloc[-1]; mc = safe_float(last.get('Market_Cap', 0), 0)
        ct = "LC" if mc > mcap_threshold else "SMC"
        print(f"    DEBUG {ticker}({ct}): RSI={last.get('RSI_14')}, Close={last.get('Close')}, SMA9={last.get('SMA_9')}, SMA22={last.get('SMA_22')}, SMA52={last.get('SMA_52')}, SMA200={last.get('SMA_200')}, BB={last.get('BB_Flag')}, Knox={last.get('Knoxville_Divergence')}, ADX={last.get('ADX_14')}, MCap={mc:.0f}")
    return {"score": score, "signals": signals}
