"""screener/run_fundamentals.py -- Weekly entry point for fundamental screening.

Pipeline:
  1. Fetch Nifty 500 ticker list (NSE)
  2. Fetch fundamentals for all 500 (yfinance + NSE API)
  3. Run premium filter (your exact screener.in criteria)
  4. Compute quality scores (dynamic 0-100 for public)
  5. Save premium tickers to tickers.csv (feeds existing engine)

Usage:
  python -m screener.run_fundamentals              # normal run
  python -m screener.run_fundamentals --force       # force re-fetch all data
"""

import sys
import time
from datetime import datetime
from pathlib import Path
from screener.config import SCREENER_DIR, PREMIUM_TICKERS_FILE


def main(force=False):
    start = time.time()
    today = datetime.now().strftime("%Y-%m-%d")

    print("\n" + "=" * 70)
    print(f"  NIFTY 500 FUNDAMENTAL SCREENING PIPELINE")
    print(f"  Date: {today}")
    print(f"  Mode: {'FORCE' if force else 'Normal (cached if fresh)'}")
    print("=" * 70)

    # Ensure output directory
    Path(SCREENER_DIR).mkdir(parents=True, exist_ok=True)

    # ── Step 1: Fetch Nifty 500 ticker list ──
    print(f"\n[STEP 1/5] Fetching Nifty 500 ticker list...")
    from screener.nifty500 import fetch_nifty500_list, load_nifty500_list

    if force:
        tickers = fetch_nifty500_list()
    else:
        tickers = load_nifty500_list()
        if not tickers or len(tickers) < 400:
            tickers = fetch_nifty500_list()

    if not tickers:
        print("  FATAL: Could not get Nifty 500 list. Aborting.")
        return False

    print(f"  -> {len(tickers)} tickers loaded")

    # ── Step 2: Fetch fundamentals ──
    print(f"\n[STEP 2/5] Fetching fundamentals ({len(tickers)} tickers)...")
    from screener.fundamentals import fetch_all_fundamentals

    fund_df = fetch_all_fundamentals(tickers, force=force)
    if fund_df.empty:
        print("  FATAL: Fundamentals fetch failed. Aborting.")
        return False

    mcap_ok = (fund_df['Market_Cap'] > 0).sum()
    print(f"  -> {mcap_ok}/{len(tickers)} with valid MCap")

    # ── Step 3: Run premium filter (YOUR exact criteria) ──
    print(f"\n[STEP 3/5] Running premium filter (screener.in criteria)...")
    from screener.premium_filter import run_premium_filter

    premium_tickers, filter_results = run_premium_filter(fund_df)
    print(f"  -> {len(premium_tickers)} premium tickers selected")

    # ── Step 4: Compute quality scores (dynamic, for public) ──
    print(f"\n[STEP 4/5] Computing quality scores (dynamic 0-100)...")
    from screener.quality_score import score_all_tickers

    scored_df = score_all_tickers(fund_df)
    if not scored_df.empty:
        avg = scored_df['Quality_Score'].mean()
        print(f"  -> Avg quality score: {avg:.1f}")

    # ── Step 5: Verify premium tickers.csv ──
    print(f"\n[STEP 5/5] Verifying outputs...")

    if Path(PREMIUM_TICKERS_FILE).exists():
        import pandas as pd
        tk_df = pd.read_csv(PREMIUM_TICKERS_FILE)
        n_premium = len(tk_df)
        has_sector = False
        if 'Sector' in tk_df.columns and n_premium > 0:
            try:
                has_sector = (tk_df['Sector'].astype(str).str.strip() != '').sum() > 0
            except Exception:
                pass
        print(f"  -> tickers.csv: {n_premium} premium tickers" +
              (f" ({(tk_df['Sector'].str.strip() != '').sum()} with sectors)" if has_sector else ""))
    else:
        print(f"  -> WARNING: {PREMIUM_TICKERS_FILE} not created!")

    # ── Summary ──
    elapsed = time.time() - start
    print(f"\n{'=' * 70}")
    print(f"  SCREENING COMPLETE")
    print(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"  Nifty 500: {len(tickers)} tickers")
    print(f"  Premium:   {len(premium_tickers)} selected")
    print(f"  Files:")
    for f in [
        SCREENER_DIR / "nifty500_tickers.csv",
        SCREENER_DIR / "nifty500_fundamentals.csv",
        SCREENER_DIR / "nifty500_scores.csv",
        SCREENER_DIR / "premium_filter_results.csv",
        PREMIUM_TICKERS_FILE,
    ]:
        exists = "OK" if Path(f).exists() else "MISSING"
        print(f"    [{exists}] {f}")
    print("=" * 70)

    return True


if __name__ == "__main__":
    force = '--force' in sys.argv
    success = main(force=force)
    sys.exit(0 if success else 1)
