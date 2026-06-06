"""Strategy-based technical scoring v6.0
S/R-CENTRIC SCORING: Position relative to Support/Resistance is PRIMARY.
SMA tells trend context. Knox/RSI/BB confirm reversals at S/R.
Momentum angle determines dynamic timeframe.
Used by both live prediction AND backtesting."""
import os
import math
import pandas as pd
import numpy as np
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


# ═══════════════════════════════════════════════════════════════
# MULTI-TIMEFRAME SUPPORT / RESISTANCE ENGINE
# ═══════════════════════════════════════════════════════════════

def compute_sr_levels(valid_df, close):
    """Compute multi-timeframe support and resistance levels.
    Uses 20d/60d/200d highs-lows + SMA as dynamic S/R.
    Returns: (nearest_support, nearest_resistance, all_supports, all_resistances)
    """
    n = len(valid_df)
    supports = []
    resistances = []

    # Short-term S/R (20 days)
    if n >= 20 and 'Low' in valid_df.columns and 'High' in valid_df.columns:
        r20 = valid_df.tail(20)
        s_20 = r20['Low'].dropna().min()
        r_20 = r20['High'].dropna().max()
        if pd.notna(s_20):
            supports.append(("S20", s_20))
        if pd.notna(r_20):
            resistances.append(("R20", r_20))

    # Medium-term S/R (60 days)
    if n >= 60 and 'Low' in valid_df.columns and 'High' in valid_df.columns:
        r60 = valid_df.tail(60)
        s_60 = r60['Low'].dropna().min()
        r_60 = r60['High'].dropna().max()
        if pd.notna(s_60):
            supports.append(("S60", s_60))
        if pd.notna(r_60):
            resistances.append(("R60", r_60))

    # Long-term S/R (200 days or all available)
    lt = min(200, n)
    if lt >= 50 and 'Low' in valid_df.columns and 'High' in valid_df.columns:
        rlt = valid_df.tail(lt)
        s_lt = rlt['Low'].dropna().min()
        r_lt = rlt['High'].dropna().max()
        if pd.notna(s_lt):
            supports.append(("S200", s_lt))
        if pd.notna(r_lt):
            resistances.append(("R200", r_lt))

    # SMA as dynamic support/resistance
    last = valid_df.iloc[-1]
    sma22 = fv_row(last, ['SMA_22'])
    sma200 = fv_row(last, ['SMA_200'])
    sma52 = fv_row(last, ['SMA_52', 'SMA_50'])

    if sma22 is not None:
        if sma22 < close:
            supports.append(("SMA22", sma22))
        else:
            resistances.append(("SMA22", sma22))

    if sma52 is not None:
        if sma52 < close:
            supports.append(("SMA52", sma52))
        else:
            resistances.append(("SMA52", sma52))

    if sma200 is not None:
        if sma200 < close:
            supports.append(("SMA200", sma200))
        else:
            resistances.append(("SMA200", sma200))

    # Find NEAREST support below and NEAREST resistance above
    valid_supports = [(label, val) for label, val in supports if val < close]
    valid_resistances = [(label, val) for label, val in resistances if val > close]

    if valid_supports:
        nearest_support = max(valid_supports, key=lambda x: x[1])
    else:
        # No support found below — use lowest available
        if supports:
            nearest_support = min(supports, key=lambda x: x[1])
        else:
            nearest_support = ("none", close * 0.95)

    if valid_resistances:
        nearest_resistance = min(valid_resistances, key=lambda x: x[1])
    else:
        if resistances:
            nearest_resistance = max(resistances, key=lambda x: x[1])
        else:
            nearest_resistance = ("none", close * 1.05)

    return nearest_support, nearest_resistance, valid_supports, valid_resistances


def get_position(close, support_val, resistance_val):
    """Determine price position relative to S/R.
    Returns: AT_SUPPORT, AT_RESISTANCE, BELOW_SUPPORT, ABOVE_RESISTANCE, BETWEEN
    """
    if support_val is None or resistance_val is None:
        return "BETWEEN"

    sr_range = resistance_val - support_val
    if sr_range <= 0:
        return "BETWEEN"

    # Proximity thresholds (% of S/R range)
    support_zone = support_val * 1.02
    resistance_zone = resistance_val * 0.98

    if close < support_val:
        return "BELOW_SUPPORT"
    elif close > resistance_val:
        return "ABOVE_RESISTANCE"
    elif close <= support_zone:
        return "AT_SUPPORT"
    elif close >= resistance_zone:
        return "AT_RESISTANCE"
    else:
        return "BETWEEN"


def compute_momentum_angle(valid_df, close):
    """Compute momentum slope (% per day) and estimated days to S/R.
    Steeper slope → shorter timeframe. Gentle slope → longer timeframe.
    """
    mom_5d = None
    mom_10d = None
    avg_daily_move = None

    if len(valid_df) >= 6:
        pc5 = valid_df.iloc[-6].get('Close')
        if pc5 and pd.notna(pc5) and pc5 > 0:
            mom_5d = ((close - pc5) / pc5) * 100

    if len(valid_df) >= 11:
        pc10 = valid_df.iloc[-11].get('Close')
        if pc10 and pd.notna(pc10) and pc10 > 0:
            mom_10d = ((close - pc10) / pc10) * 100

    # Average daily move (use 10d if available, else 5d)
    if mom_10d is not None:
        avg_daily_move = mom_10d / 10.0
    elif mom_5d is not None:
        avg_daily_move = mom_5d / 5.0
    else:
        avg_daily_move = 0.0

    return {
        "mom_5d": mom_5d,
        "mom_10d": mom_10d,
        "avg_daily_move": avg_daily_move,
        "direction": 1 if (avg_daily_move or 0) > 0.05 else (-1 if (avg_daily_move or 0) < -0.05 else 0),
    }


def estimate_horizon(close, target_price, avg_daily_move, mcap, default_horizon=7):
    """Estimate trading days to reach target based on momentum slope.
    Steep slope → few days. Gentle slope → many days.
    Clamped by MCap-based min/max.
    """
    if mcap is not None and mcap > 100000:
        min_h, max_h = 7, 28
    elif mcap is not None and mcap > 30000:
        min_h, max_h = 5, 22
    elif mcap is not None and mcap > 10000:
        min_h, max_h = 3, 14
    else:
        min_h, max_h = 2, 7

    if target_price is None or close is None or close <= 0:
        return default_horizon

    distance_pct = abs((target_price - close) / close) * 100

    if avg_daily_move is None or abs(avg_daily_move) < 0.05:
        # Very low momentum — use max horizon
        return max_h

    est_days = distance_pct / abs(avg_daily_move)
    est_days = max(min_h, min(max_h, int(round(est_days))))

    return est_days

# ═══════════════════════════════════════════════════════════════
# S/R-CENTRIC SCORING ENGINE v6.0
# ═══════════════════════════════════════════════════════════════

def compute_tech_score(valid_df, mcap_threshold):
    """CORE SCORING v6.0 — S/R Position is PRIMARY.

    Logic flow:
      1. WHERE is price? (relative to multi-TF S/R)
      2. WHAT is the trend? (SMA alignment = context)
      3. REVERSAL signal? (Knox + RSI + BB at S/R = trigger)
      4. MOMENTUM angle? (slope = dynamic horizon)

    Returns: (score, signals, estimated_horizon)
    """
    if len(valid_df) < 2:
        return 0, [], 7

    score = 0
    signals = []
    last = valid_df.iloc[-1]

    close = fv_row(last, ['Close'])
    if close is None:
        return 0, [], 7

    # ── Extract indicators ──
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
    bb = sv_row(last, ['BB_Flag'])
    knox = sv_row(last, ['Knoxville_Divergence'])

    is_large = mcap is not None and mcap > mcap_threshold
    tag = "LC" if is_large else "SMC"
    is_trending = adx is not None and adx > 25
    is_strong_trend = adx is not None and adx > 35

    # ═══ STEP 1: WHERE is the price? (S/R Position) ═══
    nearest_support, nearest_resistance, all_supports, all_resistances = compute_sr_levels(valid_df, close)
    s_label, s_val = nearest_support
    r_label, r_val = nearest_resistance
    position = get_position(close, s_val, r_val)

    # Distance to S/R (in %)
    dist_to_support = ((close - s_val) / close) * 100 if s_val and close > 0 else 999
    dist_to_resistance = ((r_val - close) / close) * 100 if r_val and close > 0 else 999

    signals.append(f"Pos:{position} S={s_label}:{s_val:.0f} R={r_label}:{r_val:.0f}")

    # ═══ STEP 2: WHAT is the trend? (SMA Context) ═══
    trend = "NEUTRAL"
    has_all = all(v is not None for v in [sma9, sma22, sma52, sma200])
    has_short = all(v is not None for v in [sma9, sma22])

    if has_all:
        if close > sma9 > sma22 > sma52 > sma200:
            trend = "STRONG_UP"
        elif close > sma9 > sma22 > sma52:
            trend = "UP"
        elif close > sma9 > sma22:
            trend = "MILD_UP"
        elif close < sma9 < sma22 < sma52 < sma200:
            trend = "STRONG_DOWN"
        elif close < sma9 < sma22 < sma52:
            trend = "DOWN"
        elif close < sma9 < sma22:
            trend = "MILD_DOWN"
        else:
            if close > sma22:
                trend = "ABOVE_SMA22"
            else:
                trend = "BELOW_SMA22"
    elif has_short:
        if close > sma9 > sma22:
            trend = "MILD_UP"
        elif close < sma9 < sma22:
            trend = "MILD_DOWN"
        else:
            trend = "ABOVE_SMA22" if close > sma22 else "BELOW_SMA22"

    signals.append(f"Trend:{trend}")

    # ═══ STEP 3: REVERSAL SIGNALS (Knox, RSI, BB) ═══
    has_bull_knox = knox is not None and 'bullish' in knox.lower()
    has_bear_knox = knox is not None and 'bearish' in knox.lower()
    rsi_oversold = rsi is not None and rsi < 30
    rsi_overbought = rsi is not None and rsi > 70
    rsi_extreme_os = rsi is not None and rsi < 20
    rsi_extreme_ob = rsi is not None and rsi > 80
    bb_lower = bb is not None and bb.strip().upper() == 'BBL'
    bb_upper = bb is not None and bb.strip().upper() == 'BBH'

    # Count reversal confluence
    bull_reversal_signals = sum([has_bull_knox, rsi_oversold, bb_lower])
    bear_reversal_signals = sum([has_bear_knox, rsi_overbought, bb_upper])

    # ═══ STEP 4: MOMENTUM ═══
    momentum = compute_momentum_angle(valid_df, close)
    mom_dir = momentum["direction"]
    avg_move = momentum["avg_daily_move"] or 0
    mom_5d = momentum["mom_5d"]

    # ═══ SCORING: Position-Based Decision Matrix ═══

    # ── AT SUPPORT ──
    if position == "AT_SUPPORT":
        if bull_reversal_signals >= 2:
            # Strong reversal: Knox + RSI<30 or Knox + BBL
            score += 45
            rev_tags = []
            if has_bull_knox:
                rev_tags.append("Knox")
            if rsi_oversold:
                rev_tags.append(f"RSI({rsi:.0f})")
            if bb_lower:
                rev_tags.append("BBL")
            signals.append(f"REVERSAL at {s_label}: {'+'.join(rev_tags)}")
        elif bull_reversal_signals == 1:
            # Moderate reversal: one signal
            score += 25
            if has_bull_knox:
                signals.append(f"Knox bull at {s_label}")
            elif rsi_oversold:
                signals.append(f"RSI OS({rsi:.0f}) at {s_label}")
            elif bb_lower:
                signals.append(f"BBL at {s_label}")
        elif trend in ("STRONG_DOWN", "DOWN") and is_strong_trend:
            # At support but strong downtrend with ADX — support may break
            score -= 20
            signals.append(f"Support risk: strong downtrend ADX={adx:.0f}")
        else:
            # At support, no reversal signal, no strong downtrend
            # Lean bullish — support bounce is more common
            score += 15
            signals.append(f"Support bounce likely at {s_label}")

    # ── AT RESISTANCE ──
    elif position == "AT_RESISTANCE":
        if bear_reversal_signals >= 2:
            # Strong reversal
            score -= 45
            rev_tags = []
            if has_bear_knox:
                rev_tags.append("Knox")
            if rsi_overbought:
                rev_tags.append(f"RSI({rsi:.0f})")
            if bb_upper:
                rev_tags.append("BBH")
            signals.append(f"REVERSAL at {r_label}: {'+'.join(rev_tags)}")
        elif bear_reversal_signals == 1:
            score -= 25
            if has_bear_knox:
                signals.append(f"Knox bear at {r_label}")
            elif rsi_overbought:
                signals.append(f"RSI OB({rsi:.0f}) at {r_label}")
            elif bb_upper:
                signals.append(f"BBH at {r_label}")
        elif trend in ("STRONG_UP", "UP") and is_strong_trend:
            # At resistance but strong uptrend — breakout likely
            score += 20
            signals.append(f"Breakout likely: strong uptrend ADX={adx:.0f}")
        else:
            # At resistance, no signal — lean bearish
            score -= 15
            signals.append(f"Resistance rejection likely at {r_label}")

    # ── BELOW SUPPORT (Breakdown) ──
    elif position == "BELOW_SUPPORT":
        if bull_reversal_signals >= 2:
            # Extreme oversold below support — snapback
            score += 30
            signals.append(f"Extreme oversold below {s_label}")
        elif is_strong_trend and trend in ("STRONG_DOWN", "DOWN"):
            # Strong breakdown — more downside
            score -= 40
            signals.append(f"Breakdown below {s_label} ADX={adx:.0f}")
        else:
            # Below support, moderate
            score -= 25
            signals.append(f"Below support {s_label}")

    # ── ABOVE RESISTANCE (Breakout) ──
    elif position == "ABOVE_RESISTANCE":
        if bear_reversal_signals >= 2:
            # Extreme overbought above resistance — pullback
            score -= 30
            signals.append(f"Extreme overbought above {r_label}")
        elif is_strong_trend and trend in ("STRONG_UP", "UP"):
            # Strong breakout — more upside
            score += 40
            signals.append(f"Breakout above {r_label} ADX={adx:.0f}")
        else:
            # Above resistance, moderate
            score += 25
            signals.append(f"Above resistance {r_label}")

    # ── BETWEEN S/R (use momentum direction) ──
    elif position == "BETWEEN":
        if mom_dir == 1:
            # Momentum UP → bull until resistance
            if dist_to_resistance < 3:
                # Close to resistance — smaller score
                score += 10
                signals.append(f"Approaching {r_label} ({dist_to_resistance:.1f}%)")
            else:
                score += 20
                signals.append(f"Bull toward {r_label} ({dist_to_resistance:.1f}%)")

            # Trend confirmation amplifies
            if trend in ("STRONG_UP", "UP"):
                score += 10
                signals.append("Trend confirms")

        elif mom_dir == -1:
            # Momentum DOWN → bear until support
            if dist_to_support < 3:
                score -= 10
                signals.append(f"Approaching {s_label} ({dist_to_support:.1f}%)")
            else:
                score -= 20
                signals.append(f"Bear toward {s_label} ({dist_to_support:.1f}%)")

            if trend in ("STRONG_DOWN", "DOWN"):
                score += -10
                signals.append("Trend confirms")

        else:
            # No clear momentum — use trend
            if trend in ("STRONG_UP", "UP", "MILD_UP"):
                score += 8
                signals.append("Mild bull (trend)")
            elif trend in ("STRONG_DOWN", "DOWN", "MILD_DOWN"):
                score -= 8
                signals.append("Mild bear (trend)")
            else:
                signals.append("No direction (range-bound)")

    # ═══ SUPPORTING SIGNALS (small weights) ═══

    # MACD confirmation
    if macd_line is not None and macd_signal is not None:
        if macd_line > macd_signal and score > 0:
            score += 5
            signals.append("MACD confirms")
        elif macd_line < macd_signal and score < 0:
            score += -5
            signals.append("MACD confirms")

    # EMA confirmation
    if ema9 is not None and ema21 is not None:
        if ema9 > ema21 and score > 0:
            score += 3
        elif ema9 < ema21 and score < 0:
            score -= 3

    # SuperTrend confirmation
    if st_dir is not None:
        try:
            st = int(float(st_dir))
            if st == 1 and score > 0:
                score += 3
            elif st == -1 and score < 0:
                score -= 3
        except Exception:
            pass

    # UP20 (FII/DII accumulation) — bonus for bull calls
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
                        score += 15
                        signals.append("UP20 recons")
                    elif close <= up_low * 1.05:
                        score += 8
                        signals.append("UP20 near")

    # 5d momentum magnitude (not direction — already used)
    if mom_5d is not None:
        if abs(mom_5d) > 8:
            signals.append(f"Mom5d:{mom_5d:+.1f}%")

    # ═══ ADX AMPLIFIER ═══
    if adx is not None and adx > 30 and abs(score) > 10:
        score = int(score * 1.12)
        signals.append(f"ADX({adx:.0f})")

    # ═══ DYNAMIC HORIZON ═══
    if score > 0:
        target = r_val
    elif score < 0:
        target = s_val
    else:
        target = close

    est_horizon = estimate_horizon(close, target, avg_move, mcap)
    signals.append(f"H:{est_horizon}d")

    score = max(-100, min(100, score))

    return score, signals, est_horizon

# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════

def get_technical_score(ticker, stock_df, mcap_threshold, debug=False):
    """Public API: returns score, signals, and estimated horizon."""
    if stock_df is None or stock_df.empty:
        return {"score": 0, "signals": [], "horizon": 7}
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty:
        return {"score": 0, "signals": [], "horizon": 7}
    valid = tk_data[tk_data['Close'].notna()]
    if 'Date' in valid.columns:
        valid = valid.sort_values('Date')
    if valid.empty:
        return {"score": 0, "signals": [], "horizon": 7}

    score, signals, horizon = compute_tech_score(valid, mcap_threshold)

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

    return {"score": score, "signals": signals, "horizon": horizon}
