"""migrate_sebi.py V3 — Fix v8 tech scoring (Category, BB exit, output override)."""

import re, subprocess
from pathlib import Path


def write_file(fp, content):
    Path(fp).parent.mkdir(parents=True, exist_ok=True)
    Path(fp).write_text(content, encoding="utf-8")
    print(f"  WROTE {fp}")


def main():
    print("=" * 60)
    print("  MIGRATION V3: Fix v8 Tech Scoring")
    print("=" * 60)

    print("\n[1/3] Rewriting engine/tech_v8.py...")
    write_tech_v8()

    print("\n[2/3] Patching app.py...")
    patch_app_py()

    print("\n[3/3] Staging changes...")
    subprocess.run(["git", "add", "-A"], capture_output=True)

    print("\n" + "=" * 60)
    print("  MIGRATION V3 COMPLETE")
    print("=" * 60)
    print("""
  Fixes:
    1. Category column added to stock_df before v8 scoring
    2. MID/SMALL exit now requires SMA9 falling (not just Close > BB_Mid)
    3. v8 scores feed back into output (LUPIN will be NEUTRAL)
    4. get_v8_latest_scores added to import + output override

  Next: Trigger "Run Trading Engine"
""")


def write_tech_v8():
    lines = []
    lines.append('"""engine/tech_v8.py -- Corrected technical scoring logic v8.')
    lines.append('')
    lines.append('MEGA/LARGE (Hard Gate):')
    lines.append('  Entry: Close < SMA9 < SMA22 < SMA200 AND SMA9 rising')
    lines.append('  Exit:  Close > SMA9 > SMA22 > SMA200 AND SMA9 falling')
    lines.append('  Gate:  If neither -> tech=0 -> composite=0')
    lines.append('')
    lines.append('MID/SMALL (BB + SMA9 Reversal):')
    lines.append('  Entry: Close < BB_Lower AND SMA9 rising')
    lines.append('  Exit:  Close > BB_Mid AND SMA9 falling')
    lines.append('  Weight: 75% tech + 25% (macro+fund+news)/3')
    lines.append('"""')
    lines.append('')
    lines.append('import numpy as np')
    lines.append('import pandas as pd')
    lines.append('')
    lines.append('')
    lines.append('def _safe(v, default=0.0):')
    lines.append('    try:')
    lines.append('        f = float(v)')
    lines.append('        return default if (f != f) else f')
    lines.append('    except (TypeError, ValueError):')
    lines.append('        return default')
    lines.append('')
    lines.append('')
    lines.append('def classify_cap(mcap, threshold=10000):')
    lines.append('    if mcap >= threshold * 10:')
    lines.append('        return "MEGA"')
    lines.append('    elif mcap >= threshold * 2:')
    lines.append('        return "LARGE"')
    lines.append('    elif mcap >= threshold * 0.5:')
    lines.append('        return "MID"')
    lines.append('    return "SMALL"')
    lines.append('')
    lines.append('')
    lines.append('def score_tech_row(close, sma9, sma22, sma200, sma9_prev,')
    lines.append('                   bb_lower, bb_mid, category):')
    lines.append('    """Compute tech score for a single row."""')
    lines.append('    close = _safe(close)')
    lines.append('    sma9 = _safe(sma9)')
    lines.append('    sma22 = _safe(sma22)')
    lines.append('    sma200 = _safe(sma200)')
    lines.append('    sma9_prev = _safe(sma9_prev, sma9)')
    lines.append('    bb_lower = _safe(bb_lower)')
    lines.append('    bb_mid = _safe(bb_mid)')
    lines.append('')
    lines.append('    if close <= 0 or sma9 <= 0 or sma22 <= 0:')
    lines.append('        return 0')
    lines.append('')
    lines.append('    sma9_rising = sma9 > sma9_prev')
    lines.append('    sma9_falling = sma9 < sma9_prev')
    lines.append('')
    lines.append('    if category in ("MEGA", "LARGE"):')
    lines.append('        # ENTRY: Bearish stack + SMA9 just turned up')
    lines.append('        if (close < sma9 and sma9 < sma22 and sma22 < sma200')
    lines.append('                and sma200 > 0 and sma9_rising):')
    lines.append('            return 40')
    lines.append('        # EXIT: Bullish stack + SMA9 just turned down')
    lines.append('        elif (close > sma9 and sma9 > sma22 and sma22 > sma200')
    lines.append('              and sma200 > 0 and sma9_falling):')
    lines.append('            return -40')
    lines.append('        else:')
    lines.append('            return 0  # Hard gate')
    lines.append('')
    lines.append('    else:  # MID / SMALL')
    lines.append('        if bb_lower <= 0 or bb_mid <= 0:')
    lines.append('            return 0')
    lines.append('        # ENTRY: Price below lower BB + SMA9 recovering')
    lines.append('        if close < bb_lower and sma9_rising:')
    lines.append('            return 40')
    lines.append('        # EXIT: Price above BB midline + SMA9 turning down')
    lines.append('        elif close > bb_mid and sma9_falling:')
    lines.append('            return -40')
    lines.append('        else:')
    lines.append('            return 0')
    lines.append('')
    lines.append('')
    lines.append('def _col(df, name):')
    lines.append('    """Safely get column as array, zeros if missing."""')
    lines.append('    if name in df.columns:')
    lines.append('        return pd.to_numeric(df[name], errors="coerce").fillna(0).values')
    lines.append('    return np.zeros(len(df))')
    lines.append('')
    lines.append('')
    lines.append('def _ensure_category(stock_df):')
    lines.append('    """Add Category column to stock_df if missing, based on Market_Cap."""')
    lines.append('    if "Category" in stock_df.columns:')
    lines.append('        # Verify it is not all MID (might be default)')
    lines.append('        cats = stock_df["Category"].unique()')
    lines.append('        if len(cats) > 1 or (len(cats) == 1 and cats[0] != "MID"):')
    lines.append('            return stock_df')
    lines.append('')
    lines.append('    df = stock_df.copy()')
    lines.append('')
    lines.append('    if "Market_Cap" in df.columns:')
    lines.append('        mcap = pd.to_numeric(df["Market_Cap"], errors="coerce").fillna(0)')
    lines.append('        # Forward-fill MCap per ticker so latest rows have values')
    lines.append('        mcap = df.groupby("Ticker")["Market_Cap"].transform(')
    lines.append('            lambda x: pd.to_numeric(x, errors="coerce").ffill().bfill().fillna(0)')
    lines.append('        )')
    lines.append('        # Auto-detect scale')
    lines.append('        med = mcap[mcap > 0].median()')
    lines.append('        if med > 1e10:')
    lines.append('            mcap = mcap / 1e7')
    lines.append('        df["Category"] = mcap.apply(classify_cap)')
    lines.append('        vc = df.groupby("Ticker")["Category"].last().value_counts()')
    lines.append('        print(f"  [v8] Category assigned: {dict(vc)}")')
    lines.append('    else:')
    lines.append('        df["Category"] = "MID"')
    lines.append('        print("  [v8] WARNING: No Market_Cap column, defaulting all to MID")')
    lines.append('')
    lines.append('    return df')
    lines.append('')
    lines.append('')
    lines.append('def compute_tech_scores(stock_df):')
    lines.append('    """Recompute Tech_Score for entire DataFrame using v8 logic."""')
    lines.append('    df = _ensure_category(stock_df)')
    lines.append('')
    lines.append('    # Ensure SMA_9_prev exists')
    lines.append('    if "SMA_9_prev" not in df.columns:')
    lines.append('        df["SMA_9_prev"] = df.groupby("Ticker")["SMA_9"].shift(1)')
    lines.append('')
    lines.append('    # Detect BB column names')
    lines.append('    bb_mid_col = None')
    lines.append('    bb_lower_col = None')
    lines.append('    for c in df.columns:')
    lines.append('        cl = c.lower()')
    lines.append('        if "bb" in cl and "mid" in cl:')
    lines.append('            bb_mid_col = c')
    lines.append('        elif "bb" in cl and ("lower" in cl or "low" in cl):')
    lines.append('            bb_lower_col = c')
    lines.append('        elif cl == "bb_middle":')
    lines.append('            bb_mid_col = c')
    lines.append('')
    lines.append('    if bb_mid_col is None:')
    lines.append('        bb_mid_col = "SMA_22"')
    lines.append('    if bb_lower_col is None:')
    lines.append('        bb_lower_col = "BB_Lower"')
    lines.append('')
    lines.append('    close = _col(df, "Close")')
    lines.append('    sma9 = _col(df, "SMA_9")')
    lines.append('    sma22 = _col(df, "SMA_22")')
    lines.append('    sma200 = _col(df, "SMA_200")')
    lines.append('    sma9_prev = _col(df, "SMA_9_prev")')
    lines.append('    bb_lower = _col(df, bb_lower_col)')
    lines.append('    bb_mid = _col(df, bb_mid_col)')
    lines.append('    cats = df["Category"].fillna("MID").values')
    lines.append('')
    lines.append('    scores = np.zeros(len(df), dtype=int)')
    lines.append('    for i in range(len(df)):')
    lines.append('        scores[i] = score_tech_row(')
    lines.append('            close[i], sma9[i], sma22[i], sma200[i], sma9_prev[i],')
    lines.append('            bb_lower[i], bb_mid[i], str(cats[i])')
    lines.append('        )')
    lines.append('')
    lines.append('    entry = (scores > 0).sum()')
    lines.append('    exit_ = (scores < 0).sum()')
    lines.append('    neutral = (scores == 0).sum()')
    lines.append('    print(f"  [v8] Tech scores: Entry={entry} Exit={exit_} Neutral={neutral}")')
    lines.append('')
    lines.append('    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:')
    lines.append('        mask = np.array([str(c) == cat for c in cats])')
    lines.append('        if mask.sum() > 0:')
    lines.append('            e = (scores[mask] > 0).sum()')
    lines.append('            x = (scores[mask] < 0).sum()')
    lines.append('            n = (scores[mask] == 0).sum()')
    lines.append('            print(f"  [v8]   {cat}: Entry={e} Exit={x} Neutral={n} ({mask.sum()} rows)")')
    lines.append('')
    lines.append('    df["Tech_Score"] = scores')
    lines.append('    if "Technical_Score" in df.columns:')
    lines.append('        df["Technical_Score"] = scores')
    lines.append('')
    lines.append('    # Write back to original df')
    lines.append('    stock_df["Tech_Score"] = df["Tech_Score"].values')
    lines.append('    if "Technical_Score" in stock_df.columns:')
    lines.append('        stock_df["Technical_Score"] = df["Technical_Score"].values')
    lines.append('    if "Category" not in stock_df.columns or stock_df["Category"].nunique() <= 1:')
    lines.append('        stock_df["Category"] = df["Category"].values')
    lines.append('    if "SMA_9_prev" not in stock_df.columns:')
    lines.append('        stock_df["SMA_9_prev"] = df["SMA_9_prev"].values')
    lines.append('')
    lines.append('    return stock_df')
    lines.append('')
    lines.append('')
    lines.append('def compute_composites(stock_df):')
    lines.append('    """Recompute Composite_Score with hard gate (LC) and 75/25 weighting (SC)."""')
    lines.append('    df = _ensure_category(stock_df)')
    lines.append('')
    lines.append('    tech = _col(df, "Tech_Score")')
    lines.append('    macro = _col(df, "Macro_Score")')
    lines.append('    fund = _col(df, "Fund_Score")')
    lines.append('    if fund.sum() == 0:')
    lines.append('        fund = _col(df, "Fundamental_Score")')
    lines.append('    news = _col(df, "News_Score")')
    lines.append('    if news.sum() == 0:')
    lines.append('        news = _col(df, "Forecast_Score")')
    lines.append('')
    lines.append('    cats = df["Category"].fillna("MID").values')
    lines.append('')
    lines.append('    composites = np.zeros(len(df))')
    lines.append('    directions = np.zeros(len(df), dtype=int)')
    lines.append('')
    lines.append('    for i in range(len(df)):')
    lines.append('        t = tech[i]')
    lines.append('        m = macro[i]')
    lines.append('        f = fund[i]')
    lines.append('        n = news[i]')
    lines.append('        cat = str(cats[i])')
    lines.append('')
    lines.append('        if cat in ("MEGA", "LARGE"):')
    lines.append('            if t == 0:')
    lines.append('                composites[i] = 0.0')
    lines.append('                directions[i] = 0')
    lines.append('            else:')
    lines.append('                composites[i] = t + m + f + n')
    lines.append('                directions[i] = 1 if composites[i] > 20 else (-1 if composites[i] < -20 else 0)')
    lines.append('        else:')
    lines.append('            if t == 0:')
    lines.append('                others_avg = (m + f + n) / 3.0')
    lines.append('                composites[i] = 0.25 * others_avg')
    lines.append('            else:')
    lines.append('                others_avg = (m + f + n) / 3.0')
    lines.append('                composites[i] = 0.75 * t + 0.25 * others_avg')
    lines.append('            directions[i] = 1 if composites[i] > 20 else (-1 if composites[i] < -20 else 0)')
    lines.append('')
    lines.append('    n_dir = (directions != 0).sum()')
    lines.append('    n_pos = (directions == 1).sum()')
    lines.append('    n_neg = (directions == -1).sum()')
    lines.append('    print(f"  [v8] Composites: {n_dir} directional (pos={n_pos}, neg={n_neg})")')
    lines.append('')
    lines.append('    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:')
    lines.append('        mask = np.array([str(c) == cat for c in cats])')
    lines.append('        if mask.sum() > 0:')
    lines.append('            d = directions[mask]')
    lines.append('            print(f"  [v8]   {cat}: pos={(d == 1).sum()} neg={(d == -1).sum()} neut={(d == 0).sum()}")')
    lines.append('')
    lines.append('    stock_df["Composite_Score"] = np.round(composites, 1)')
    lines.append('    col_dir = "Momentum_Direction" if "Momentum_Direction" in stock_df.columns else "Composite_Direction"')
    lines.append('    stock_df[col_dir] = directions')
    lines.append('')
    lines.append('    return stock_df')
    lines.append('')
    lines.append('')
    lines.append('def get_v8_latest_scores(stock_df, tickers):')
    lines.append('    """Get the LATEST v8 tech scores per ticker for output override."""')
    lines.append('    results = {}')
    lines.append('    for tk in tickers:')
    lines.append('        tdf = stock_df[stock_df["Ticker"].astype(str).str.strip() == tk]')
    lines.append('        if tdf.empty:')
    lines.append('            continue')
    lines.append('        last = tdf.iloc[-1]')
    lines.append('        results[tk] = {')
    lines.append('            "Tech_Score": int(last.get("Tech_Score", 0)),')
    lines.append('            "Category": str(last.get("Category", "MID")),')
    lines.append('        }')
    lines.append('    return results')
    lines.append('')
    lines.append('')
    lines.append('def fix_chart_markers(markers):')
    lines.append('    """Filter chart markers to show only transitions + use neutral symbols."""')
    lines.append('    if not markers:')
    lines.append('        return markers')
    lines.append('')
    lines.append('    markers = sorted(markers, key=lambda m: m.get("time", ""))')
    lines.append('')
    lines.append('    filtered = []')
    lines.append('    prev_dir = None')
    lines.append('    for m in markers:')
    lines.append('        text = m.get("text", "")')
    lines.append('        shape = m.get("shape", "")')
    lines.append('        if "Up" in shape or "up" in shape:')
    lines.append('            cur_dir = "up"')
    lines.append('        elif "Down" in shape or "down" in shape:')
    lines.append('            cur_dir = "down"')
    lines.append('        else:')
    lines.append('            cur_dir = "none"')
    lines.append('')
    lines.append('        if cur_dir != prev_dir:')
    lines.append('            import re as _re')
    lines.append('            clean = _re.sub(r"(?i)(BULL|BEAR|POSITIVE|NEGATIVE)\\s*", "", text).strip()')
    lines.append('            if not clean:')
    lines.append('                clean = "entry" if cur_dir == "up" else "exit"')
    lines.append('            m_copy = dict(m)')
    lines.append('            m_copy["text"] = clean')
    lines.append('            filtered.append(m_copy)')
    lines.append('            prev_dir = cur_dir')
    lines.append('')
    lines.append('    return filtered')

    write_file("engine/tech_v8.py", "\n".join(lines) + "\n")


def patch_app_py():
    fp = Path("app.py")
    if not fp.exists():
        print("  ERROR: app.py not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content
    changes = 0

    # Fix 1: Add get_v8_latest_scores to import
    old_import = "from engine.tech_v8 import compute_tech_scores, compute_composites, fix_chart_markers"
    new_import = "from engine.tech_v8 import compute_tech_scores, compute_composites, fix_chart_markers, get_v8_latest_scores"

    if old_import in content and "get_v8_latest_scores" not in content:
        content = content.replace(old_import, new_import)
        changes += 1
        print("  Fixed: Added get_v8_latest_scores to import")
    elif "get_v8_latest_scores" in content:
        print("  OK: get_v8_latest_scores already imported")
    else:
        print("  WARNING: Could not find tech_v8 import line!")

    # Fix 2: Add v8 score override before output loop
    # Find the line after regime print and before the scored_rows output loop
    marker_line = "bull_damp={bull_damp} bear_damp={bear_damp}"
    v8_override = """
    # ── v8 Override: Feed corrected tech scores into output ──
    v8_scores = get_v8_latest_scores(stock_df, tickers)
    v8_applied = 0
    for sr in scored_rows:
        tk = sr["Ticker"]
        if tk in v8_scores:
            sr["Tech_Score"] = v8_scores[tk]["Tech_Score"]
            sr["Category"] = v8_scores[tk]["Category"]
            v8_applied += 1
    print(f"  [v8] Overrode {v8_applied}/{len(scored_rows)} ticker scores with v8 logic")
    # ─────────────────────────────────────────────────────────
"""

    if "v8_scores = get_v8_latest_scores" not in content:
        idx = content.find(marker_line)
        if idx >= 0:
            line_end = content.find('\n', idx) + 1
            content = content[:line_end] + v8_override + content[line_end:]
            changes += 1
            print("  Fixed: Added v8 score override before output loop")
        else:
            print("  WARNING: Could not find regime print line for v8 override!")
    else:
        print("  OK: v8 score override already present")

    # Fix 3: Make compute_composite respect v8 hard gate
    # After composite is computed per ticker, check if tech is 0 for LC
    # Find the line: "if comp >= entry: direction = 1"
    old_comp_block = """        if comp >= entry: direction = 1; dir_label = "POSITIVE"; tech_bull += 1
        elif comp <= -entry: direction = -1; dir_label = "NEGATIVE"; tech_bear += 1
        else: direction = 0; dir_label = "NEUTRAL"; tech_neut += 1"""

    new_comp_block = """        # v8 hard gate: if tech=0 for MEGA/LARGE, force NEUTRAL
        if cat in ("MEGA", "LARGE") and tech == 0:
            direction = 0; dir_label = "NEUTRAL"; tech_neut += 1
            comp = 0.0
        elif comp >= entry: direction = 1; dir_label = "POSITIVE"; tech_bull += 1
        elif comp <= -entry: direction = -1; dir_label = "NEGATIVE"; tech_bear += 1
        else: direction = 0; dir_label = "NEUTRAL"; tech_neut += 1"""

    if "v8 hard gate" not in content and old_comp_block in content:
        content = content.replace(old_comp_block, new_comp_block)
        changes += 1
        print("  Fixed: Added hard gate check in output composite logic")
    elif "v8 hard gate" in content:
        print("  OK: Hard gate already present in output logic")
    else:
        print("  WARNING: Could not find composite direction block for hard gate!")

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print(f"  app.py patched ({changes} changes)")
    else:
        print("  app.py: no changes needed")


if __name__ == "__main__":
    main()
