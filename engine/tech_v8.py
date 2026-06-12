"""engine/tech_v8.py -- Corrected technical scoring logic v8.

MEGA/LARGE (Hard Gate):
  Entry: Close < SMA9 < SMA22 < SMA200 AND SMA9 rising
  Exit:  Close > SMA9 > SMA22 > SMA200 AND SMA9 falling
  Gate:  If neither -> tech=0 -> composite=0 (news/fund/macro CANNOT override)

MID/SMALL (BB + SMA9 Reversal):
  Entry: Close < BB_Lower AND SMA9 rising
  Exit:  Close > BB_Mid
  Weight: 75% tech + 25% (macro+fund+news)/3
"""

import numpy as np
import pandas as pd


def _safe(v, default=0.0):
    try:
        f = float(v)
        return default if (f != f) else f
    except (TypeError, ValueError):
        return default


def score_tech_row(close, sma9, sma22, sma200, sma9_prev,
                   bb_lower, bb_mid, category):
    """Compute tech score for a single row."""
    close = _safe(close)
    sma9 = _safe(sma9)
    sma22 = _safe(sma22)
    sma200 = _safe(sma200)
    sma9_prev = _safe(sma9_prev, sma9)
    bb_lower = _safe(bb_lower)
    bb_mid = _safe(bb_mid)

    if close <= 0 or sma9 <= 0 or sma22 <= 0:
        return 0

    sma9_rising = sma9 > sma9_prev
    sma9_falling = sma9 < sma9_prev

    if category in ("MEGA", "LARGE"):
        # ENTRY: Bearish stack + SMA9 just turned up
        if (close < sma9 and sma9 < sma22 and sma22 < sma200
                and sma200 > 0 and sma9_rising):
            return 40
        # EXIT: Bullish stack + SMA9 just turned down
        elif (close > sma9 and sma9 > sma22 and sma22 > sma200
              and sma200 > 0 and sma9_falling):
            return -40
        else:
            return 0  # Hard gate: no signal

    else:  # MID / SMALL
        if bb_lower <= 0 or bb_mid <= 0:
            return 0
        # ENTRY: Price below lower BB + SMA9 recovering
        if close < bb_lower and sma9_rising:
            return 40
        # EXIT: Price crosses above BB midline
        elif close > bb_mid:
            return -40
        else:
            return 0


def _col(df, name):
    """Safely get column as array, zeros if missing."""
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").fillna(0).values
    return np.zeros(len(df))


def compute_tech_scores(stock_df):
    """Recompute Tech_Score for entire DataFrame using v8 logic."""
    df = stock_df.copy()

    # Ensure SMA_9_prev exists
    if "SMA_9_prev" not in df.columns:
        df["SMA_9_prev"] = df.groupby("Ticker")["SMA_9"].shift(1)

    cat_col = "Category" if "Category" in df.columns else "BT_Category"
    if cat_col not in df.columns:
        df[cat_col] = "MID"

    # Detect BB column names
    bb_mid_col = None
    bb_lower_col = None
    for c in df.columns:
        cl = c.lower()
        if "bb" in cl and "mid" in cl:
            bb_mid_col = c
        elif "bb" in cl and ("lower" in cl or "low" in cl):
            bb_lower_col = c
        elif cl == "bb_middle":
            bb_mid_col = c

    # Also check SMA_22 as BB mid proxy if no BB columns
    if bb_mid_col is None:
        bb_mid_col = "SMA_22"
    if bb_lower_col is None:
        bb_lower_col = "BB_Lower"

    close = _col(df, "Close")
    sma9 = _col(df, "SMA_9")
    sma22 = _col(df, "SMA_22")
    sma200 = _col(df, "SMA_200")
    sma9_prev = _col(df, "SMA_9_prev")
    bb_lower = _col(df, bb_lower_col)
    bb_mid = _col(df, bb_mid_col)
    cats = df[cat_col].fillna("MID").values

    scores = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        scores[i] = score_tech_row(
            close[i], sma9[i], sma22[i], sma200[i], sma9_prev[i],
            bb_lower[i], bb_mid[i], str(cats[i])
        )

    # Count stats
    entry = (scores > 0).sum()
    exit_ = (scores < 0).sum()
    neutral = (scores == 0).sum()
    print(f"  [v8] Tech scores: Entry={entry} Exit={exit_} Neutral={neutral}")

    df["Tech_Score"] = scores
    if "Technical_Score" in df.columns:
        df["Technical_Score"] = scores

    return df


def compute_composites(stock_df):
    """Recompute Composite_Score with hard gate (LC) and 75/25 weighting (SC)."""
    df = stock_df.copy()

    tech = _col(df, "Tech_Score")
    macro = _col(df, "Macro_Score")
    fund = _col(df, "Fund_Score")
    if fund.sum() == 0:
        fund = _col(df, "Fundamental_Score")
    news = _col(df, "News_Score")
    if news.sum() == 0:
        news = _col(df, "Forecast_Score")

    cat_col = "Category" if "Category" in df.columns else "BT_Category"
    cats = df[cat_col].fillna("MID").values if cat_col in df.columns else np.full(len(df), "MID")

    composites = np.zeros(len(df))
    directions = np.zeros(len(df), dtype=int)

    for i in range(len(df)):
        t = tech[i]
        m = macro[i]
        f = fund[i]
        n = news[i]
        cat = str(cats[i])

        if cat in ("MEGA", "LARGE"):
            # HARD GATE: tech must be non-zero
            if t == 0:
                composites[i] = 0.0
                directions[i] = 0
            else:
                # Tech is the signal, others add conviction
                composites[i] = t + m + f + n
                directions[i] = 1 if composites[i] > 20 else (-1 if composites[i] < -20 else 0)
        else:  # MID / SMALL
            # 75% tech + 25% average of others
            if t == 0:
                others_avg = (m + f + n) / 3.0
                composites[i] = 0.25 * others_avg
            else:
                others_avg = (m + f + n) / 3.0
                composites[i] = 0.75 * t + 0.25 * others_avg
            directions[i] = 1 if composites[i] > 20 else (-1 if composites[i] < -20 else 0)

    n_dir = (directions != 0).sum()
    n_pos = (directions == 1).sum()
    n_neg = (directions == -1).sum()
    print(f"  [v8] Composites: {n_dir} directional (pos={n_pos}, neg={n_neg})")

    df["Composite_Score"] = np.round(composites, 1)
    col_dir = "Momentum_Direction" if "Momentum_Direction" in df.columns else "Composite_Direction"
    df[col_dir] = directions

    return df


def fix_chart_markers(markers):
    """Filter chart markers to show only transitions + use neutral symbols."""
    if not markers:
        return markers

    # Sort by time
    markers = sorted(markers, key=lambda m: m.get("time", ""))

    # Keep only transitions (direction changed from previous marker)
    filtered = []
    prev_dir = None
    for m in markers:
        text = m.get("text", "")
        shape = m.get("shape", "")
        # Determine direction from shape
        if "Up" in shape or "up" in shape:
            cur_dir = "up"
        elif "Down" in shape or "down" in shape:
            cur_dir = "down"
        else:
            cur_dir = "none"

        if cur_dir != prev_dir:
            # Clean text: remove BULL/BEAR/POSITIVE/NEGATIVE
            import re as _re
            clean = _re.sub(r"(?i)(BULL|BEAR|POSITIVE|NEGATIVE)\s*", "", text).strip()
            if not clean:
                clean = "entry" if cur_dir == "up" else "exit"
            m_copy = dict(m)
            m_copy["text"] = clean
            filtered.append(m_copy)
            prev_dir = cur_dir

    return filtered
