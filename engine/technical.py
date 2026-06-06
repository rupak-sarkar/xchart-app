"""Strategy-based technical scoring v5.2.1
CORE SCORING ENGINE - used by both live prediction AND backtesting"""
import os
import pandas as pd
from engine.config import STOCK_DATA_FILE, SECTOR_MAP
from engine.utils import is_bad_str, safe_int, safe_float, fv_row, sv_row


def load_stock_data():
    try:
        if os.path.exists(STOCK_DATA_FILE):
            df = pd.read_csv(STOCK_DATA_FILE)
            if 'Ticker' in df.columns:
                df['Ticker'] = (
                    df['Ticker'].astype(str)
                    .str.replace('.NS', '', regex=False)
                    .str.strip().str.upper()
                )
                if 'Date' in df.columns:
                    df = df.sort_values(['Ticker', 'Date'])
                tickers = df['Ticker'].nunique()
                rows = len(df)
                days_per = rows // max(tickers, 1)
                print(
                    f"  -> Loaded stock_data.csv: {tickers} tickers, "
                    f"{rows:,} rows (~{days_per} days/ticker)"
                )
                key_cols = [
                    'RSI_14', 'BB_Flag', 'SMA_9', 'SMA_22', 'SMA_50',
                    'SMA_52', 'SMA_200', 'Knoxville_Divergence', 'up_true',
                    'Close', 'High', 'Low', 'Market_Cap', 'Industry',
                    'MACD_Line', 'MACD_Signal', 'ADX_14', 'ST_Direction',
                    'EMA_9', 'EMA_21', 'OBV',
                ]
                found = [c for c in key_cols if c in df.columns]
                print(f"  -> Found: {len(found)}/{len(key_cols)} key columns")
                return df
    except Exception as e:
        print(f"  -> Error: {e}")
    print("  -> stock_data.csv not found")
    return pd.DataFrame()


def detect_mcap_scale(stock_df):
    if stock_df is None or stock_df.empty:
        return 10000
    if 'Market_Cap' not in stock_df.columns:
        return 10000
    mcap_max = stock_df['Market_Cap'].dropna().max()
    if pd.isna(mcap_max):
        return 10000
    return 1e11 if mcap_max > 1e9 else 10000


def get_sector_from_stock_data(ticker, stock_df):
    if stock_df is None or stock_df.empty:
        return ""
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty:
        return ""
    for cn in ['Industry', 'Sector']:
        if cn not in tk_data.columns:
            continue
        vals = tk_data[cn].dropna().astype(str).str.strip()
        vals = vals[vals.apply(lambda x: not is_bad_str(x))]
        if len(vals) > 0:
            return vals.iloc[-1]
    return ""


def get_broad_sector(sub):
    if not sub:
        return ""
    for broad, subs in SECTOR_MAP.items():
        if sub in subs:
            return broad
    return sub


def get_latest_valid_rows(stock_df):
    if stock_df is None or stock_df.empty:
        return pd.DataFrame()
    if 'Date' in stock_df.columns:
        sdf = stock_df.sort_values(['Ticker', 'Date'])
    else:
        sdf = stock_df
    results = []
    for ticker in sdf['Ticker'].unique():
        tk = sdf[sdf['Ticker'] == ticker]
        valid = tk[tk['Close'].notna()]
        if 'SMA_22' in tk.columns:
            v2 = valid[valid['SMA_22'].notna()]
            if not v2.empty:
                results.append(v2.iloc[-1])
                continue
        if not valid.empty:
            results.append(valid.iloc[-1])
    if results:
        return pd.DataFrame(results).reset_index(drop=True)
    return pd.DataFrame()

def compute_tech_score(valid_df, mcap_threshold):
    """CORE SCORING v5.2.1 - Trend-following PRIMARY."""
    if len(valid_df) < 2:
        return 0, []

    score = 0
    signals = []
    last = valid_df.iloc[-1]

    close = fv_row(last, ['Close'])
    if close is None:
        return 0, []

    sma9 = fv_row(last, ['SMA_9'])
    sma22 = fv_row(last, ['SMA_22'])
    sma52 = fv_row(last, ['SMA_52', 'SMA_50'])
    sma200 = fv_row(last, ['SMA_200'])
    rsi = fv_row(last, ['RSI_14', 'RSI'])
    adx = fv_row(last, ['ADX_14'])
    st_dir = fv_row(last, ['ST_Direction'])
    macd_line = fv_row(last, ['MACD_Line'])
    macd_signal = fv_row(last, ['MACD_Signal'])
    ema9 = fv_row(last, ['EMA_9'])
    ema21 = fv_row(last, ['EMA_21'])
    mcap = fv_row(last, ['Market_Cap'])

    is_large = mcap is not None and mcap > mcap_threshold
    tag = "LC" if is_large else "SMC"
    is_trending = adx is not None and adx > 25

    # ── SUPPORT / RESISTANCE ──
    support = None
    resistance = None
    if 'Low' in valid_df.columns and 'High' in valid_df.columns:
        recent = valid_df.tail(min(20, len(valid_df)))
        lows = recent['Low'].dropna()
        highs = recent['High'].dropna()
        if len(lows) > 0:
            support = lows.min()
        if len(highs) > 0:
            resistance = highs.max()

    near_support = support is not None and close <= support * 1.02
    near_resistance = resistance is not None and close >= resistance * 0.98
    at_breakout = resistance is not None and close > resistance
    at_breakdown = support is not None and close < support

    # ═══ TIER 1: TREND DIRECTION ═══
    has_all = all(v is not None for v in [sma9, sma22, sma52, sma200])
    has_short = all(v is not None for v in [sma9, sma22])

    if has_all:
        if close > sma9 > sma22 > sma52 > sma200:
            if is_trending:
                score += 30
                signals.append(f"{tag} FULL uptrend (ADX={adx:.0f})")
            else:
                score += 15
                signals.append(f"{tag} FULL up")
            if rsi is not None and rsi > 80:
                score -= 8
                signals.append("RSI extreme OB")

        elif close < sma9 < sma22 < sma52 < sma200:
            if is_trending:
                score -= 30
                signals.append(f"{tag} FULL downtrend (ADX={adx:.0f})")
            else:
                score -= 15
                signals.append(f"{tag} FULL down")
            if rsi is not None and rsi < 30:
                score += 8
                signals.append("RSI OS caution")

        elif close > sma9 > sma22 > sma52:
            if is_trending:
                score += 20
                signals.append(f"{tag} 4-up trend")
            else:
                score += 10
                signals.append(f"{tag} 4-up mild")

        elif close < sma9 < sma22 < sma52:
            if is_trending:
                score -= 20
                signals.append(f"{tag} 4-down trend")
            else:
                score -= 10
                signals.append(f"{tag} 4-down mild")

        elif close > sma9 > sma22:
            score += 12
            signals.append(f"{tag} short up")

        elif close < sma9 < sma22:
            score -= 12
            signals.append(f"{tag} short down")

        else:
            if close > sma22:
                score += 5
            else:
                score -= 5
            if close > sma200:
                score += 5
            elif close < sma200:
                score -= 8

    elif has_short:
        if close > sma9 > sma22:
            score += 15
            signals.append(f"{tag} uptrend")
            if sma52 is not None and sma22 > sma52:
                score += 8
        elif close < sma9 < sma22:
            score -= 15
            signals.append(f"{tag} downtrend")
            if sma52 is not None and sma22 < sma52:
                score -= 8
        elif close > sma22 and sma9 is not None and sma9 <= sma22:
            score += 12
            signals.append(f"{tag} crossing up")
        elif close < sma22 and sma9 is not None and sma9 >= sma22:
            score -= 12
            signals.append(f"{tag} crossing down")
        else:
            if close > sma22:
                score += 5
            else:
                score -= 5
    else:
        if sma22 is not None:
            if close > sma22:
                score += 5
            else:
                score -= 5

    # S/R breakout/breakdown
    if at_breakout:
        score += 15
        signals.append(f"Breakout R={resistance:.0f}")
    elif at_breakdown:
        score -= 15
        signals.append(f"Breakdown S={support:.0f}")
    elif near_support and score < 0:
        score += 8
        signals.append("Near support")
    elif near_resistance and score > 0:
        score -= 8
        signals.append("Near resistance")

    # ═══ TIER 2: REVERSAL SIGNALS ═══
    bb = sv_row(last, ['BB_Flag'])
    if bb is not None:
        bbs = bb.strip().upper()
        if bbs == 'BBL':
            if rsi is not None and rsi < 30:
                if near_support:
                    score += 30
                    signals.append(f"BBL+S+RSI({rsi:.0f})")
                else:
                    score += 20
                    signals.append(f"BBL+RSI({rsi:.0f})")
            else:
                score += 8
                signals.append("BBL mild")
        elif bbs == 'BBH':
            if rsi is not None and rsi > 70:
                if near_resistance:
                    score -= 30
                    signals.append(f"BBH+R+RSI({rsi:.0f})")
                else:
                    score -= 20
                    signals.append(f"BBH+RSI({rsi:.0f})")
            else:
                score -= 8
                signals.append("BBH mild")

    knox = sv_row(last, ['Knoxville_Divergence'])
    if knox is not None:
        ks = knox.lower()
        if 'bullish' in ks:
            if near_support and rsi is not None and rsi < 40:
                score += 25
                signals.append("Knox bull at support")
            else:
                score += 10
                signals.append("Knox bullish")
        elif 'bearish' in ks:
            if near_resistance and rsi is not None and rsi > 60:
                score -= 25
                signals.append("Knox bear at resistance")
            else:
                score -= 10
                signals.append("Knox bearish")

    # UP20 Reconsolidation
    if 'up_true' in valid_df.columns and len(valid_df) >= 7:
        recent_7 = valid_df.tail(min(7, len(valid_df)))
        try:
            up_rows = recent_7[
                recent_7['up_true'].apply(lambda x: safe_int(x) == 1)
            ]
        except Exception:
            up_rows = pd.DataFrame()
        latest_up = safe_int(last.get('up_true', 0)) == 1
        if len(up_rows) > 0 and not latest_up:
            if 'Low' in up_rows.columns:
                up_low = up_rows['Low'].dropna().min()
                if up_low is not None and pd.notna(up_low):
                    if close <= up_low * 1.02:
                        score += 20
                        signals.append("UP20 recons")
                    elif close <= up_low * 1.05:
                        score += 10
                        signals.append("UP20 near")

    # ═══ TIER 3: SUPPORTING (reduced weights) ═══
    if macd_line is not None and macd_signal is not None:
        if macd_line > macd_signal:
            score += 5
            signals.append("MACD bull")
        else:
            score -= 5
            signals.append("MACD bear")

    if ema9 is not None and ema21 is not None:
        if ema9 > ema21:
            score += 4
            signals.append("EMA golden")
        else:
            score -= 4
            signals.append("EMA death")

    if st_dir is not None:
        try:
            st = int(float(st_dir))
            if st == 1:
                score += 4
                signals.append("ST up")
            elif st == -1:
                score -= 4
                signals.append("ST down")
        except Exception:
            pass

    # 5d momentum
    if len(valid_df) >= 6:
        try:
            pc = valid_df.iloc[-6].get('Close')
            if pc and close and pd.notna(pc) and pc > 0:
                mom = ((close - pc) / pc) * 100
                if mom > 5:
                    score += 10
                    signals.append(f"Mom +{mom:.1f}%")
                elif mom > 2:
                    score += 5
                elif mom < -5:
                    score -= 10
                    signals.append(f"Mom {mom:.1f}%")
                elif mom < -2:
                    score -= 5
        except Exception:
            pass

    # RSI standalone
    rsi_used = any('RSI' in s for s in signals)
    if rsi is not None and not rsi_used:
        if rsi > 80:
            score -= 8
            signals.append(f"RSI OB({rsi:.0f})")
        elif rsi > 70:
            score -= 4
            signals.append(f"RSI high({rsi:.0f})")
        elif rsi < 20:
            score += 8
            signals.append(f"RSI extreme OS({rsi:.0f})")
        elif rsi < 30:
            score += 4
            signals.append(f"RSI OS({rsi:.0f})")

    # ═══ TIER 4: ADX AMPLIFIER ═══
    if adx is not None and adx > 30 and score != 0:
        score = int(score * 1.15)
        signals.append(f"ADX({adx:.0f}) amplify")

    return max(-100, min(100, score)), signals


def get_technical_score(ticker, stock_df, mcap_threshold, debug=False):
    if stock_df is None or stock_df.empty:
        return {"score": 0, "signals": []}
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty:
        return {"score": 0, "signals": []}
    valid = tk_data[tk_data['Close'].notna()]
    if 'Date' in valid.columns:
        valid = valid.sort_values('Date')
    if valid.empty:
        return {"score": 0, "signals": []}
    score, signals = compute_tech_score(valid, mcap_threshold)
    if debug:
        last = valid.iloc[-1]
        mc = safe_float(last.get('Market_Cap', 0), 0)
        ct = "LC" if mc > mcap_threshold else "SMC"
        print(
            f"    DEBUG {ticker}({ct}): "
            f"RSI={last.get('RSI_14')}, "
            f"Close={last.get('Close')}, "
            f"SMA9={last.get('SMA_9')}, "
            f"SMA22={last.get('SMA_22')}, "
            f"SMA52={last.get('SMA_52')}, "
            f"SMA200={last.get('SMA_200')}, "
            f"BB={last.get('BB_Flag')}, "
            f"Knox={last.get('Knoxville_Divergence')}, "
            f"ADX={last.get('ADX_14')}, "
            f"MCap={mc:.0f}"
        )
    return {"score": score, "signals": signals}
