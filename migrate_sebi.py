"""migrate_sebi.py V2 — Tech logic + tickers + markers + weighting."""

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

    print("\n[1/7] Creating engine/tech_v8.py...")
    write_tech_v8()

    print("\n[2/7] Patching app.py...")
    patch_app_py()

    print("\n[3/7] Writing engine/tickers.py...")
    write_tickers_py()

    print("\n[4/7] Skipping update_tickers.yml (already exists)...")
    # write_update_tickers_yml()
    
    print("\n[5/7] Patching screener files...")
    patch_screener_files()

    print("\n[6/7] Patching dashboard.html...")
    patch_dashboard()

    print("\n[7/7] Staging changes...")
    subprocess.run(["git", "add", "-A"], capture_output=True)

    print("\n" + "=" * 60)
    print("  MIGRATION V2 COMPLETE")
    print("=" * 60)
    print("""
  Next steps:
    1. Workflow commits automatically
    2. Trigger "Update Tickers" to scrape screener.in
    3. Trigger "Run Trading Engine" to verify
    4. Delete migrate_sebi.py after success
""")


# ══════════════════════════════════════════════════════════════
# FILE WRITERS
# ══════════════════════════════════════════════════════════════

def write_tech_v8():
    code = [
        '"""engine/tech_v8.py -- Corrected technical scoring logic v8.',
        '',
        'MEGA/LARGE (Hard Gate):',
        '  Entry: Close < SMA9 < SMA22 < SMA200 AND SMA9 rising',
        '  Exit:  Close > SMA9 > SMA22 > SMA200 AND SMA9 falling',
        '  Gate:  If neither -> tech=0 -> composite=0 (news/fund/macro CANNOT override)',
        '',
        'MID/SMALL (BB + SMA9 Reversal):',
        '  Entry: Close < BB_Lower AND SMA9 rising',
        '  Exit:  Close > BB_Mid',
        '  Weight: 75% tech + 25% (macro+fund+news)/3',
        '"""',
        '',
        'import numpy as np',
        'import pandas as pd',
        '',
        '',
        'def _safe(v, default=0.0):',
        '    try:',
        '        f = float(v)',
        '        return default if (f != f) else f',
        '    except (TypeError, ValueError):',
        '        return default',
        '',
        '',
        'def score_tech_row(close, sma9, sma22, sma200, sma9_prev,',
        '                   bb_lower, bb_mid, category):',
        '    """Compute tech score for a single row."""',
        '    close = _safe(close)',
        '    sma9 = _safe(sma9)',
        '    sma22 = _safe(sma22)',
        '    sma200 = _safe(sma200)',
        '    sma9_prev = _safe(sma9_prev, sma9)',
        '    bb_lower = _safe(bb_lower)',
        '    bb_mid = _safe(bb_mid)',
        '',
        '    if close <= 0 or sma9 <= 0 or sma22 <= 0:',
        '        return 0',
        '',
        '    sma9_rising = sma9 > sma9_prev',
        '    sma9_falling = sma9 < sma9_prev',
        '',
        '    if category in ("MEGA", "LARGE"):',
        '        # ENTRY: Bearish stack + SMA9 just turned up',
        '        if (close < sma9 and sma9 < sma22 and sma22 < sma200',
        '                and sma200 > 0 and sma9_rising):',
        '            return 40',
        '        # EXIT: Bullish stack + SMA9 just turned down',
        '        elif (close > sma9 and sma9 > sma22 and sma22 > sma200',
        '              and sma200 > 0 and sma9_falling):',
        '            return -40',
        '        else:',
        '            return 0  # Hard gate: no signal',
        '',
        '    else:  # MID / SMALL',
        '        if bb_lower <= 0 or bb_mid <= 0:',
        '            return 0',
        '        # ENTRY: Price below lower BB + SMA9 recovering',
        '        if close < bb_lower and sma9_rising:',
        '            return 40',
        '        # EXIT: Price crosses above BB midline',
        '        elif close > bb_mid:',
        '            return -40',
        '        else:',
        '            return 0',
        '',
        '',
        'def _col(df, name):',
        '    """Safely get column as array, zeros if missing."""',
        '    if name in df.columns:',
        '        return pd.to_numeric(df[name], errors="coerce").fillna(0).values',
        '    return np.zeros(len(df))',
        '',
        '',
        'def compute_tech_scores(stock_df):',
        '    """Recompute Tech_Score for entire DataFrame using v8 logic."""',
        '    df = stock_df.copy()',
        '',
        '    # Ensure SMA_9_prev exists',
        '    if "SMA_9_prev" not in df.columns:',
        '        df["SMA_9_prev"] = df.groupby("Ticker")["SMA_9"].shift(1)',
        '',
        '    cat_col = "Category" if "Category" in df.columns else "BT_Category"',
        '    if cat_col not in df.columns:',
        '        df[cat_col] = "MID"',
        '',
        '    # Detect BB column names',
        '    bb_mid_col = None',
        '    bb_lower_col = None',
        '    for c in df.columns:',
        '        cl = c.lower()',
        '        if "bb" in cl and "mid" in cl:',
        '            bb_mid_col = c',
        '        elif "bb" in cl and ("lower" in cl or "low" in cl):',
        '            bb_lower_col = c',
        '        elif cl == "bb_middle":',
        '            bb_mid_col = c',
        '',
        '    # Also check SMA_22 as BB mid proxy if no BB columns',
        '    if bb_mid_col is None:',
        '        bb_mid_col = "SMA_22"',
        '    if bb_lower_col is None:',
        '        bb_lower_col = "BB_Lower"',
        '',
        '    close = _col(df, "Close")',
        '    sma9 = _col(df, "SMA_9")',
        '    sma22 = _col(df, "SMA_22")',
        '    sma200 = _col(df, "SMA_200")',
        '    sma9_prev = _col(df, "SMA_9_prev")',
        '    bb_lower = _col(df, bb_lower_col)',
        '    bb_mid = _col(df, bb_mid_col)',
        '    cats = df[cat_col].fillna("MID").values',
        '',
        '    scores = np.zeros(len(df), dtype=int)',
        '    for i in range(len(df)):',
        '        scores[i] = score_tech_row(',
        '            close[i], sma9[i], sma22[i], sma200[i], sma9_prev[i],',
        '            bb_lower[i], bb_mid[i], str(cats[i])',
        '        )',
        '',
        '    # Count stats',
        '    entry = (scores > 0).sum()',
        '    exit_ = (scores < 0).sum()',
        '    neutral = (scores == 0).sum()',
        '    print(f"  [v8] Tech scores: Entry={entry} Exit={exit_} Neutral={neutral}")',
        '',
        '    df["Tech_Score"] = scores',
        '    if "Technical_Score" in df.columns:',
        '        df["Technical_Score"] = scores',
        '',
        '    return df',
        '',
        '',
        'def compute_composites(stock_df):',
        '    """Recompute Composite_Score with hard gate (LC) and 75/25 weighting (SC)."""',
        '    df = stock_df.copy()',
        '',
        '    tech = _col(df, "Tech_Score")',
        '    macro = _col(df, "Macro_Score")',
        '    fund = _col(df, "Fund_Score")',
        '    if fund.sum() == 0:',
        '        fund = _col(df, "Fundamental_Score")',
        '    news = _col(df, "News_Score")',
        '    if news.sum() == 0:',
        '        news = _col(df, "Forecast_Score")',
        '',
        '    cat_col = "Category" if "Category" in df.columns else "BT_Category"',
        '    cats = df[cat_col].fillna("MID").values if cat_col in df.columns else np.full(len(df), "MID")',
        '',
        '    composites = np.zeros(len(df))',
        '    directions = np.zeros(len(df), dtype=int)',
        '',
        '    for i in range(len(df)):',
        '        t = tech[i]',
        '        m = macro[i]',
        '        f = fund[i]',
        '        n = news[i]',
        '        cat = str(cats[i])',
        '',
        '        if cat in ("MEGA", "LARGE"):',
        '            # HARD GATE: tech must be non-zero',
        '            if t == 0:',
        '                composites[i] = 0.0',
        '                directions[i] = 0',
        '            else:',
        '                # Tech is the signal, others add conviction',
        '                composites[i] = t + m + f + n',
        '                directions[i] = 1 if composites[i] > 20 else (-1 if composites[i] < -20 else 0)',
        '        else:  # MID / SMALL',
        '            # 75% tech + 25% average of others',
        '            if t == 0:',
        '                others_avg = (m + f + n) / 3.0',
        '                composites[i] = 0.25 * others_avg',
        '            else:',
        '                others_avg = (m + f + n) / 3.0',
        '                composites[i] = 0.75 * t + 0.25 * others_avg',
        '            directions[i] = 1 if composites[i] > 20 else (-1 if composites[i] < -20 else 0)',
        '',
        '    n_dir = (directions != 0).sum()',
        '    n_pos = (directions == 1).sum()',
        '    n_neg = (directions == -1).sum()',
        '    print(f"  [v8] Composites: {n_dir} directional (pos={n_pos}, neg={n_neg})")',
        '',
        '    df["Composite_Score"] = np.round(composites, 1)',
        '    col_dir = "Momentum_Direction" if "Momentum_Direction" in df.columns else "Composite_Direction"',
        '    df[col_dir] = directions',
        '',
        '    return df',
        '',
        '',
        'def fix_chart_markers(markers):',
        '    """Filter chart markers to show only transitions + use neutral symbols."""',
        '    if not markers:',
        '        return markers',
        '',
        '    # Sort by time',
        '    markers = sorted(markers, key=lambda m: m.get("time", ""))',
        '',
        '    # Keep only transitions (direction changed from previous marker)',
        '    filtered = []',
        '    prev_dir = None',
        '    for m in markers:',
        '        text = m.get("text", "")',
        '        shape = m.get("shape", "")',
        '        # Determine direction from shape',
        '        if "Up" in shape or "up" in shape:',
        '            cur_dir = "up"',
        '        elif "Down" in shape or "down" in shape:',
        '            cur_dir = "down"',
        '        else:',
        '            cur_dir = "none"',
        '',
        '        if cur_dir != prev_dir:',
        '            # Clean text: remove BULL/BEAR/POSITIVE/NEGATIVE',
        '            import re as _re',
        '            clean = _re.sub(r"(?i)(BULL|BEAR|POSITIVE|NEGATIVE)\\s*", "", text).strip()',
        '            if not clean:',
        '                clean = "entry" if cur_dir == "up" else "exit"',
        '            m_copy = dict(m)',
        '            m_copy["text"] = clean',
        '            filtered.append(m_copy)',
        '            prev_dir = cur_dir',
        '',
        '    return filtered',
    ]
    write_file("engine/tech_v8.py", "\n".join(code) + "\n")


def write_tickers_py():
    code = [
        '"""engine/tickers.py -- Ticker loading + screener.in scraper."""',
        '',
        'import os',
        'import time',
        'import pandas as pd',
        'from pathlib import Path',
        '',
        'TICKERS_FILE = Path("output/tickers.csv")',
        '',
        '',
        'def is_bad_str(s):',
        '    s = str(s).strip().lower()',
        '    return s in ("", "nan", "none", "0", "other")',
        '',
        '',
        'def load_tickers():',
        '    """Load tickers from output/tickers.csv."""',
        '    if TICKERS_FILE.exists():',
        '        try:',
        '            df = pd.read_csv(TICKERS_FILE)',
        '            df.columns = df.columns.str.strip()',
        '            if "Ticker" not in df.columns:',
        '                df.rename(columns={df.columns[0]: "Ticker"}, inplace=True)',
        '            tks = [t.replace(".NS", "") for t in df["Ticker"].dropna().str.strip().str.upper().tolist() if t]',
        '            s = set()',
        '            u = []',
        '            for t in tks:',
        '                if t not in s:',
        '                    s.add(t)',
        '                    u.append(t)',
        '            sm = {}',
        '            if "Sector" in df.columns:',
        '                for _, r in df.iterrows():',
        '                    tk = str(r["Ticker"]).strip().upper().replace(".NS", "")',
        '                    sc = str(r.get("Sector", "")).strip()',
        '                    if tk and sc and not is_bad_str(sc):',
        '                        sm[tk] = sc',
        '            print(f"Loaded {len(u)} tickers from {TICKERS_FILE} (sector map: {len(sm)} entries)")',
        '            return u, sm',
        '        except Exception as e:',
        '            print(f"Error loading tickers: {e}")',
        '    return ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ICICIBANK", "ITC"], {}',
        '',
        '',
        'def update_tickers():',
        '    """Scrape screener.in public screen and write output/tickers.csv."""',
        '    try:',
        '        import requests',
        '        from bs4 import BeautifulSoup',
        '    except ImportError:',
        '        print("ERROR: requests/beautifulsoup4 not installed")',
        '        return',
        '',
        '    print("=" * 70)',
        '    print("  Screener.in Ticker Scraper -> output/tickers.csv")',
        '    print("=" * 70)',
        '',
        '    base_url = "https://www.screener.in/screens/2650136/good-stocks/?page="',
        '    hrefs = []',
        '    headers = {',
        '        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",',
        '        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",',
        '        "Accept-Language": "en-IN,en;q=0.9",',
        '    }',
        '',
        '    for page_num in range(1, 15):',
        '        url = base_url + str(page_num)',
        '        try:',
        '            response = requests.get(url, headers=headers, timeout=15)',
        '            response.raise_for_status()',
        '            soup = BeautifulSoup(response.content, "html.parser")',
        '            page_links = []',
        '            for a_tag in soup.find_all("a", href=True):',
        '                href = a_tag["href"]',
        '                if "/company/" in href:',
        '                    page_links.append(href)',
        '            hrefs.extend(page_links)',
        '            print(f"  Page {page_num}: {len(page_links)} company links")',
        '            if len(page_links) == 0:',
        '                print("  No more results — stopping.")',
        '                break',
        '            time.sleep(1.5)',
        '        except Exception as e:',
        '            print(f"  Page {page_num}: Error - {e}")',
        '            break',
        '',
        '    print(f"  Total raw links: {len(hrefs)}")',
        '',
        '    if not hrefs:',
        '        print("  ERROR: No tickers scraped! Keeping existing tickers.csv.")',
        '        return',
        '',
        '    df_scraped = pd.DataFrame(hrefs, columns=["Column1"])',
        '    df_scraped["Company Name"] = df_scraped["Column1"].str.split("/").str[2]',
        '    df_scraped = df_scraped.drop_duplicates(subset="Company Name")',
        '    df_scraped["Ticker"] = df_scraped["Company Name"].str.upper()',
        '    df_scraped["Ticker"] = df_scraped["Ticker"].str.replace(".NS", "", regex=False).str.strip()',
        '    df_scraped = df_scraped[df_scraped["Ticker"].str.len() > 0]',
        '',
        '    df_final = pd.DataFrame({"Ticker": df_scraped["Ticker"].values, "Sector": ""})',
        '    df_final = df_final.sort_values("Ticker").reset_index(drop=True)',
        '',
        '    # Safety: dont overwrite with fewer tickers than existing',
        '    if TICKERS_FILE.exists():',
        '        existing = pd.read_csv(TICKERS_FILE)',
        '        if len(df_final) < len(existing) * 0.5:',
        '            print(f"  WARNING: Scraped {len(df_final)} but existing has {len(existing)}. Keeping existing.")',
        '            return',
        '',
        '    TICKERS_FILE.parent.mkdir(parents=True, exist_ok=True)',
        '    df_final.to_csv(TICKERS_FILE, index=False)',
        '',
        '    print(f"  output/tickers.csv written — {len(df_final)} unique tickers")',
        '    print(f"  First 10: {df_final[\'Ticker\'].head(10).tolist()}")',
        '    print(f"  Last 10:  {df_final[\'Ticker\'].tail(10).tolist()}")',
    ]
    write_file("engine/tickers.py", "\n".join(code) + "\n")


def write_update_tickers_yml():
    yml = """name: Update Tickers

on:
  schedule:
    - cron: '0 5 * * 0'
  workflow_dispatch:

permissions:
  contents: write

jobs:
  update-tickers:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install pandas requests beautifulsoup4

      - name: Update tickers
        run: python -c "from engine.tickers import update_tickers; update_tickers()"

      - name: Commit and push
        run: |
          git config user.name "GitHub Actions Automation"
          git config user.email "actions@github.com"
          git add output/tickers.csv
          git diff --staged --quiet || git commit -m "Tickers update $(date -u +%Y-%m-%d)"
          git pull --rebase origin master
          git push
"""
    write_file(".github/workflows/update_tickers.yml", yml)


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
    v8_tech = '\n    # ── v8 Tech Scoring Override ──\n    print("  [v8] Applying corrected tech scoring...")\n    stock_df = compute_tech_scores(stock_df)\n    # ─────────────────────────────\n'
    if "[v8] Applying corrected tech" not in content:
        for marker in ["PHASE 3b", "Backtest (ATR", "Backtest(ATR", "Per-category accuracy"]:
            idx = content.find(marker)
            if idx >= 0:
                line_start = content.rfind('\n', 0, idx) + 1
                prev_line_start = content.rfind('\n', 0, line_start - 1) + 1
                content = content[:prev_line_start] + v8_tech + content[prev_line_start:]
                changes += 1
                print(f"  Injected v8 tech scoring before '{marker}'")
                break
        else:
            print("  WARNING: Could not find backtest section!")

    # 3. Inject v8 composite scoring AFTER old composite
    v8_comp = '\n    # ── v8 Composite Override ──\n    print("  [v8] Applying corrected composite scoring...")\n    stock_df = compute_composites(stock_df)\n    # ─────────────────────────────\n'
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
            print("  WARNING: Could not find composite section!")

    # 4. Fix chart marker generation
    if "fix_chart_markers(markers)" not in content:
        patterns = ["'markers': markers", '"markers": markers',
                    "'markers':markers", '"markers":markers']
        for pat in patterns:
            idx = content.find(pat)
            if idx >= 0:
                line_start = content.rfind('\n', 0, idx) + 1
                indent = " " * (len(content[line_start:idx]) - len(content[line_start:idx].lstrip()) + 8)
                inject = indent + "markers = fix_chart_markers(markers)\n"
                content = content[:line_start] + inject + content[line_start:]
                changes += 1
                print("  Injected marker fix")
                break
        else:
            print("  WARNING: Could not find markers dict!")

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print(f"  app.py patched ({changes} changes)")


def patch_screener_files():
    # run_fundamentals.py — stop writing to output/tickers.csv
    rf = Path("screener/run_fundamentals.py")
    if rf.exists():
        content = rf.read_text(encoding="utf-8")
        if "save_premium_tickers(premium_tickers" in content and "# v8:" not in content:
            content = content.replace(
                "save_premium_tickers(premium_tickers",
                "# v8: Screener.in scraper handles output/tickers.csv now\n    # save_premium_tickers(premium_tickers"
            )
            rf.write_text(content, encoding="utf-8")
            print("  Patched run_fundamentals.py (disabled tickers.csv write)")
        else:
            print("  run_fundamentals.py: already patched or pattern not found")

    # premium_filter.py — change output path to screener_data/
    pf_path = Path("screener/premium_filter.py")
    if pf_path.exists():
        content = pf_path.read_text(encoding="utf-8")
        if 'output/tickers.csv' in content:
            content = content.replace('output/tickers.csv', 'screener_data/premium_tickers.csv')
            pf_path.write_text(content, encoding="utf-8")
            print("  Patched premium_filter.py (writes to screener_data/ now)")
        else:
            print("  premium_filter.py: already patched")


def patch_dashboard():
    fp = Path("dashboard.html")
    if not fp.exists():
        print("  dashboard.html not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content

    # Fix marker display
    old = "if(CD.markers&&CD.markers.length)CS.setMarkers(CD.markers)"
    new = "if(CD.markers&&CD.markers.length){var sm=CD.markers.map(function(m){var n=Object.assign({},m);n.text=(n.text||'').replace(/BULL/gi,'\\u25B2').replace(/BEAR/gi,'\\u25BC').replace(/POSITIVE/gi,'\\u25B2').replace(/NEGATIVE/gi,'\\u25BC');return n});CS.setMarkers(sm)}"

    if old in content:
        content = content.replace(old, new)
        print("  Fixed marker display (symbols)")
    elif "replace(/BULL/" not in content:
        # Try alternate
        alt = "CS.setMarkers(CD.markers)"
        alt_new = "CS.setMarkers((CD.markers||[]).map(function(m){var n=Object.assign({},m);n.text=(n.text||'').replace(/BULL|POSITIVE/gi,'\\u25B2').replace(/BEAR|NEGATIVE/gi,'\\u25BC');return n}))"
        if alt in content:
            content = content.replace(alt, alt_new, 1)
            print("  Fixed marker display (alternate)")
    else:
        print("  Markers already fixed")

    if content != original:
        fp.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
