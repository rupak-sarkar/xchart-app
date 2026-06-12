"""migrate_sebi.py V2 — Tech logic + tickers + markers + weighting.

Changes:
  1. engine/tech_v8.py    — Correct MEGA/LARGE + MID/SMALL scoring
  2. app.py               — Inject v8 override + fix markers
  3. engine/tickers.py    — Add screener.in scraper (update_tickers)
  4. update_tickers.yml   — Fix paths + deps
  5. screener files       — Stop overwriting output/tickers.csv
  6. dashboard.html       — Marker display fix (▲/▼)
"""

import os, re, subprocess
from pathlib import Path


def write_file(fp, content):
    Path(fp).parent.mkdir(parents=True, exist_ok=True)
    Path(fp).write_text(content, encoding="utf-8")
    print(f"  WROTE {fp}")


def replace_in_file(fp, replacements):
    p = Path(fp)
    if not p.exists():
        print(f"  SKIP (not found): {fp}")
        return 0
    content = p.read_text(encoding="utf-8")
    orig = content
    n = 0
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            n += 1
    if content != orig:
        p.write_text(content, encoding="utf-8")
        print(f"  PATCHED {fp} ({n} replacements)")
    return n


def main():
    print("=" * 60)
    print("  MIGRATION V2: Tech Logic + Tickers + Markers")
    print("=" * 60)

    # ══════════════════════════════════════════════════════════
    # STEP 1: Create engine/tech_v8.py
    # ══════════════════════════════════════════════════════════
    print("\n[1/7] Creating engine/tech_v8.py...")
    write_file("engine/tech_v8.py", TECH_V8_PY)

    # ══════════════════════════════════════════════════════════
    # STEP 2: Patch app.py
    # ══════════════════════════════════════════════════════════
    print("\n[2/7] Patching app.py...")
    patch_app_py()

    # ══════════════════════════════════════════════════════════
    # STEP 3: Write engine/tickers.py
    # ══════════════════════════════════════════════════════════
    print("\n[3/7] Writing engine/tickers.py...")
    write_file("engine/tickers.py", TICKERS_PY)

    # ══════════════════════════════════════════════════════════
    # STEP 4: Write update_tickers.yml
    # ══════════════════════════════════════════════════════════
    print("\n[4/7] Writing update_tickers.yml...")
    write_file(".github/workflows/update_tickers.yml", UPDATE_TICKERS_YML)

    # ══════════════════════════════════════════════════════════
    # STEP 5: Patch screener files
    # ══════════════════════════════════════════════════════════
    print("\n[5/7] Patching screener files...")
    patch_screener_files()

    # ══════════════════════════════════════════════════════════
    # STEP 6: Patch dashboard.html
    # ══════════════════════════════════════════════════════════
    print("\n[6/7] Patching dashboard.html...")
    patch_dashboard()

    # ══════════════════════════════════════════════════════════
    # STEP 7: Git add
    # ══════════════════════════════════════════════════════════
    print("\n[7/7] Staging changes...")
    subprocess.run(["git", "add", "-A"], capture_output=True)

    print(f"""
{'=' * 60}
  MIGRATION V2 COMPLETE
{'=' * 60}

  Changes:
    ✅ engine/tech_v8.py    — New scoring module
    ✅ app.py               — v8 override injected
    ✅ engine/tickers.py    — Screener.in scraper added
    ✅ update_tickers.yml   — Fixed paths + deps
    ✅ screener files       — Stop overwriting tickers.csv
    ✅ dashboard.html       — Marker display (▲/▼)

  Next steps:
    1. Workflow commits automatically
    2. Trigger "Run Trading Engine" to verify
    3. Trigger "Update Tickers" to scrape screener.in
    4. Delete migrate_sebi.py after success
""")


# ══════════════════════════════════════════════════════════════
# PATCH FUNCTIONS
# ══════════════════════════════════════════════════════════════

def patch_app_py():
    fp = Path("app.py")
    if not fp.exists():
        print("  ERROR: app.py not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content
    changes = 0

    # 1. Add import
    if "from engine.tech_v8" not in content:
        import_line = "from engine.tech_v8 import compute_tech_scores, compute_composites, fix_chart_markers\n"
        # Find last engine import
        last_engine = -1
        for m in re.finditer(r'from engine\.\w+ import [^\n]+\n', content):
            last_engine = m.end()
        if last_engine > 0:
            content = content[:last_engine] + import_line + content[last_engine:]
        else:
            content = import_line + content
        changes += 1
        print("  Added tech_v8 import")

    # 2. Inject v8 tech scoring BEFORE backtest
    v8_tech = '''
    # ── v8 Tech Scoring Override ──────────────────────────────
    print("  [v8] Applying corrected tech scoring...")
    stock_df = compute_tech_scores(stock_df)
    # ─────────────────────────────────────────────────────────
'''
    if "[v8] Applying corrected tech" not in content:
        for marker in ["PHASE 3b", "Backtest (ATR", "Backtest(ATR", "Per-category accuracy"]:
            idx = content.find(marker)
            if idx >= 0:
                line_start = content.rfind('\n', 0, idx) + 1
                # Go back one more line to inject before the print statement
                prev_line_start = content.rfind('\n', 0, line_start - 1) + 1
                content = content[:prev_line_start] + v8_tech + content[prev_line_start:]
                changes += 1
                print(f"  Injected v8 tech scoring before '{marker}'")
                break
        else:
            print("  WARNING: Could not find backtest section for tech injection!")

    # 3. Inject v8 composite scoring AFTER old composite
    v8_comp = '''
    # ── v8 Composite Override (hard gate LC + 75/25 SC) ───────
    print("  [v8] Applying corrected composite scoring...")
    stock_df = compute_composites(stock_df)
    # ─────────────────────────────────────────────────────────
'''
    if "[v8] Applying corrected composite" not in content:
        for marker in ["non-zero Composite_Score", "Adding Composite_Score", "Composite_Score to stock_df"]:
            idx = content.find(marker)
            if idx >= 0:
                line_end = content.find('\n', idx) + 1
                content = content[:line_end] + v8_comp + content[line_end:]
                changes += 1
                print(f"  Injected v8 composite after '{marker}'")
                break
        else:
            print("  WARNING: Could not find composite section for injection!")

    # 4. Fix chart marker generation — add fix_chart_markers call
    marker_fix = """
                markers = fix_chart_markers(markers)"""
    if "fix_chart_markers(markers)" not in content:
        # Find where markers are assigned to chart data dict
        patterns = [
            "'markers': markers",
            '"markers": markers',
            "'markers':markers",
            '"markers":markers',
        ]
        for pat in patterns:
            idx = content.find(pat)
            if idx >= 0:
                line_start = content.rfind('\n', 0, idx) + 1
                content = content[:line_start] + marker_fix + '\n' + content[line_start:]
                changes += 1
                print("  Injected marker fix before chart dict")
                break
        else:
            print("  WARNING: Could not find marker dict for fix injection!")

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print(f"  app.py patched ({changes} changes)")
    else:
        print("  app.py: no changes needed")


def patch_screener_files():
    # run_fundamentals.py — stop writing to output/tickers.csv
    rf = Path("screener/run_fundamentals.py")
    if rf.exists():
        content = rf.read_text(encoding="utf-8")
        # Comment out or skip the tickers.csv save
        replacements = [
            ("save_premium_tickers(premium_tickers", "# v8: Screener.in scraper handles tickers.csv now\n    # save_premium_tickers(premium_tickers"),
        ]
        n = 0
        for old, new in replacements:
            if old in content and "# v8:" not in content:
                content = content.replace(old, new, 1)
                n += 1
        if n:
            rf.write_text(content, encoding="utf-8")
            print(f"  Patched run_fundamentals.py (disabled tickers.csv write)")
        else:
            print("  run_fundamentals.py: already patched or pattern not found")

    # premium_filter.py — change output path
    pf = Path("screener/premium_filter.py")
    if pf.exists():
        replace_in_file("screener/premium_filter.py", [
            ("PREMIUM_TICKERS_FILE", "PREMIUM_TICKERS_FILE_SCREENER"),
            ('Path("output/tickers.csv")', 'Path("screener_data/premium_tickers.csv")'),
            ("Path('output/tickers.csv')", "Path('screener_data/premium_tickers.csv')"),
        ])


def patch_dashboard():
    fp = Path("dashboard.html")
    if not fp.exists():
        print("  dashboard.html not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content

    # Fix marker display: replace BULL/BEAR/POSITIVE/NEGATIVE with ▲/▼
    old_marker = "if(CD.markers&&CD.markers.length)CS.setMarkers(CD.markers)"
    new_marker = """if(CD.markers&&CD.markers.length){var sm=CD.markers.map(function(m){var n=Object.assign({},m);n.text=(n.text||'').replace(/BULL/gi,'▲').replace(/BEAR/gi,'▼').replace(/POSITIVE/gi,'▲').replace(/NEGATIVE/gi,'▼');return n});CS.setMarkers(sm)}"""

    if old_marker in content:
        content = content.replace(old_marker, new_marker)
        print("  Fixed marker display (▲/▼)")
    else:
        # Try alternate patterns
        for pat in ["CS.setMarkers(CD.markers)", "setMarkers(CD.markers)"]:
            if pat in content and "replace(/BULL/" not in content:
                content = content.replace(
                    pat,
                    pat.replace("CD.markers", "(CD.markers||[]).map(function(m){var n=Object.assign({},m);n.text=(n.text||'').replace(/BULL|POSITIVE/gi,'▲').replace(/BEAR|NEGATIVE/gi,'▼');return n})")
                )
                print("  Fixed marker display (alternate pattern)")
                break

    if content != original:
        fp.write_text(content, encoding="utf-8")
    else:
        print("  dashboard.html: no changes needed or already fixed")


# ══════════════════════════════════════════════════════════════
# EMBEDDED FILES
# ══════════════════════════════════════════════════════════════

TECH_V8_PY = '''"""engine/tech_v8.py -- Corrected technical scoring logic v8.

MEGA/LARGE (Hard Gate — SMA9 Reversal):
  Entry: Close < SMA9 < SMA22 < SMA200 AND SMA9 rising
  Exit:  Close > SMA9 > SMA22 > SMA200 AND SMA9 falling
  Gate:  If neither → tech=0 → composite=0 (news/fund/macro CANNOT override)

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
        return default if (f != f) else f  # NaN check without numpy
    except (TypeError, ValueError):
        return default


def score_tech_row(close, sma9, sma22, sma200, sma9_prev,
                   bb_lower, bb_mid, category):
    """Compute tech score for a single data point.

    Returns: int score (positive=entry, negative=exit, 0=neutral)
    """
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

    if category in ('MEGA', 'LARGE'):
        # ── HARD GATE: SMA9 Reversal ──
        # ENTRY: Bearish stack + first recovery sign
        #   Everything is falling (close < SMA9 < SMA22 < SMA200)
        #   But SMA9 just turned up → earliest reversal signal
        if (close < sma9 and sma9 < sma22 and sma22 < sma200
                and sma200 > 0 and sma9_rising):
            return 40

        # EXIT: Bullish stack + first breakdown sign
        #   Everything is rising (close > SMA9 > SMA22 > SMA200)
        #   But SMA9 just turned down → earliest breakdown signal
        elif (close > sma9 and sma9 > sma22 and sma22 > sma200
              and sma200 > 0 and sma9_falling):
            return -40

        else:
            return 0  # Hard gate: no signal possible

    else:  # MID / SMALL
        # ── BB + SMA9 Reversal ──
        if bb_lower <= 0 or bb_mid <= 0:
            return 0

        # ENTRY: Price dropped below lower BB + SMA9 starting to recover
        if close < bb_lower and sma9_rising:
            return 40

        # EXIT: Price crosses above BB midline (take profit, safer for volatile stocks)
        elif close > bb_mid:
            return -40

        else:
            return 0


def compute_tech_scores(stock_df):
    """Recompute Tech_Score for entire DataFrame using v8 logic.

    Overwrites existing Tech_Score column.
    """
    # Ensure SMA_9_prev exists
    if 'SMA_9_prev' not in stock_df.columns:
        stock_df = stock_df.copy()
        stock_df['SMA_9_prev'] = stock_df.groupby('Ticker')['SMA_9'].shift(1)

    # Detect column names
    cat_col = 'Category' if 'Category' in stock_df.columns else 'BT_Category'
    bb_mid_col =
