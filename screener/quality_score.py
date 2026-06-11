"""screener/quality_score.py -- Dynamic 0-100 quality scoring for public backtesting.

Unlike premium_filter.py (binary pass/fail), this provides a continuous
quality score for EVERY Nifty 500 ticker. Used for:
  - Public backtester (free tier) to rank/filter stocks
  - Dashboard display of quality metrics
  - Comparison: "your strategy" vs "quality-filtered universe"

Score Breakdown (0-100):
  Quality:    0-30 pts (ROCE, ROE, OPM, 3Y avg ROE)
  Growth:     0-25 pts (YoY sales, YoY profit, 3Y profit growth)
  Value:      0-20 pts (PE vs industry, D/E)
  Governance: 0-20 pts (pledged, shareholding)
  Maturity:   0-5  pts (MCap 3Y ago)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from screener.config import (
    QUALITY_WEIGHTS, PREMIUM_SCORE_THRESHOLD,
    NIFTY500_FUNDAMENTALS_FILE, NIFTY500_SCORES_FILE, SCREENER_DIR,
)
from screener.premium_filter import compute_industry_pe


def _sf(val, default=0):
    try:
        v = float(val)
        return default if (pd.isna(v) or np.isinf(v)) else v
    except (ValueError, TypeError):
        return default


def _clamp(v, lo, hi):
    return max(lo, min(v, hi))


# ===================================================================
# SCORING FUNCTIONS (each returns 0-100 normalized sub-score)
# ===================================================================

def score_quality(row):
    """Quality layer: ROCE, ROE, OPM, 3Y Avg ROE. Returns 0-100."""
    score = 0
    max_score = 100

    # ROCE (0-30)
    roce = _sf(row.get('ROCE', 0))
    if roce >= 20:
        score += 30
    elif roce >= 15:
        score += 25
    elif roce >= 10:
        score += 18
    elif roce >= 5:
        score += 8
    elif roce > 0:
        score += 3

    # ROE (0-30)
    roe = _sf(row.get('ROE', 0))
    if roe >= 20:
        score += 30
    elif roe >= 15:
        score += 25
    elif roe >= 10:
        score += 18
    elif roe >= 5:
        score += 8
    elif roe > 0:
        score += 3

    # OPM (0-20)
    opm = _sf(row.get('OPM', 0))
    if opm >= 25:
        score += 20
    elif opm >= 15:
        score += 15
    elif opm >= 10:
        score += 10
    elif opm > 0:
        score += 5

    # 3Y Avg ROE (0-20)
    avg_roe = _sf(row.get('Avg_ROE_3Y', 0))
    if avg_roe >= 20:
        score += 20
    elif avg_roe >= 15:
        score += 15
    elif avg_roe >= 10:
        score += 10
    elif avg_roe >= 5:
        score += 5

    return _clamp(score / max_score * 100, 0, 100)


def score_growth(row):
    """Growth layer: YoY sales, YoY profit, 3Y profit growth. Returns 0-100."""
    score = 0
    max_score = 100

    # YoY Qtr Sales Growth (0-35)
    sales_g = _sf(row.get('YoY_Qtr_Sales_Growth', 0))
    if sales_g >= 25:
        score += 35
    elif sales_g >= 15:
        score += 28
    elif sales_g >= 5:
        score += 20
    elif sales_g > 0:
        score += 12
    elif sales_g > -10:
        score += 3

    # YoY Qtr Profit Growth (0-35)
    profit_g = _sf(row.get('YoY_Qtr_Profit_Growth', 0))
    if profit_g >= 30:
        score += 35
    elif profit_g >= 15:
        score += 28
    elif profit_g >= 5:
        score += 20
    elif profit_g > 0:
        score += 12
    elif profit_g > -10:
        score += 3

    # 3Y Profit Growth (0-30)
    p3y = _sf(row.get('Profit_Growth_3Y', 0))
    if p3y >= 20:
        score += 30
    elif p3y >= 10:
        score += 22
    elif p3y >= 5:
        score += 15
    elif p3y > 0:
        score += 8

    return _clamp(score / max_score * 100, 0, 100)


def score_value(row, industry_pe_map=None):
    """Value layer: PE vs industry, D/E. Returns 0-100."""
    score = 0
    max_score = 100

    pe = _sf(row.get('PE', 0))
    industry = str(row.get('Industry', '')).strip()
    sector = str(row.get('Sector', '')).strip()

    ind_pe = 0
    if industry_pe_map:
        ind_pe = industry_pe_map.get(industry, 0) or industry_pe_map.get(sector, 0)

    # PE vs Industry PE (0-55)
    if pe > 0 and ind_pe > 0:
        ratio = pe / ind_pe
        if ratio < 0.5:
            score += 55   # Deep value
        elif ratio < 0.8:
            score += 45   # Undervalued
        elif ratio < 1.0:
            score += 35   # Fair
        elif ratio < 1.5:
            score += 20   # Slightly overvalued
        elif ratio < 1.8:
            score += 10   # Overvalued but within threshold
        # > 1.8: 0 points
    elif pe > 0:
        # No industry PE available, use absolute PE
        if pe < 10:
            score += 45
        elif pe < 15:
            score += 35
        elif pe < 25:
            score += 20
        elif pe < 40:
            score += 10

    # D/E (0-45)
    de = _sf(row.get('Debt_to_Equity', 0))
    if de == 0:
        score += 45   # Debt-free
    elif de < 0.1:
        score += 40
    elif de < 0.3:
        score += 32
    elif de < 0.5:
        score += 22
    elif de < 1.0:
        score += 10
    elif de < 2.0:
        score += 3

    return _clamp(score / max_score * 100, 0, 100)


def score_governance(row):
    """Governance layer: Pledged %, shareholding pattern. Returns 0-100."""
    score = 0
    max_score = 100

    # Pledged % (0-35)
    pledged = _sf(row.get('Pledged_Pct', 0))
    if pledged == 0:
        score += 35   # Zero pledging = perfect
    elif pledged < 5:
        score += 20
    elif pledged < 15:
        score += 10
    elif pledged < 30:
        score += 3

    # (DII + Promoter) > 50% (0-35)
    promoter = _sf(row.get('Promoter_Holding', 0))
    dii = _sf(row.get('DII_Holding', 0))
    prom_dii = promoter + dii

    if prom_dii >= 70:
        score += 35
    elif prom_dii >= 60:
        score += 28
    elif prom_dii >= 50:
        score += 20
    elif prom_dii >= 40:
        score += 10
    elif prom_dii > 0:
        score += 3

    # (FII + DII) vs Public (0-30)
    fii = _sf(row.get('FII_Holding', 0))
    public = _sf(row.get('Public_Holding', 0))
    inst = fii + dii

    if public > 0 and inst > 0:
        ratio = inst / public
        if ratio >= 1.0:
            score += 30   # Institutions dominate
        elif ratio >= 0.5:
            score += 22
        elif ratio >= 0.25:
            score += 15
        elif ratio > 0:
            score += 5
    elif promoter > 0:
        # No detailed holding data but promoter exists
        score += 10

    return _clamp(score / max_score * 100, 0, 100)


def score_maturity(row):
    """Maturity layer: Company existed 3Y ago. Returns 0-100."""
    mcap_3y = _sf(row.get('MCap_3Y_Ago', 0))
    mcap_now = _sf(row.get('Market_Cap', 0))

    if mcap_3y > 0 and mcap_now > 0:
        # Bonus for MCap growth
        growth = (mcap_now - mcap_3y) / mcap_3y * 100
        if growth > 100:
            return 100  # 2x+ in 3 years
        elif growth > 50:
            return 80
        elif growth > 0:
            return 60
        else:
            return 40   # Shrunk but existed
    elif mcap_3y > 0:
        return 50
    return 0


# ===================================================================
# COMPOSITE SCORING
# ===================================================================

def compute_quality_score(row, industry_pe_map=None):
    """
    Compute overall quality score (0-100) with layer breakdown.

    Returns:
        dict with total score and per-layer scores
    """
    q = score_quality(row)
    g = score_growth(row)
    v = score_value(row, industry_pe_map)
    gov = score_governance(row)
    m = score_maturity(row)

    w = QUALITY_WEIGHTS
    total_weight = sum(w.values())

    # Weighted composite
    composite = (
        q * w['quality'] / 100 +
        g * w['growth'] / 100 +
        v * w['value'] / 100 +
        gov * w['governance'] / 100 +
        m * w['maturity'] / 100
    )
    # Normalize to 0-100
    composite = round(composite / total_weight * 100, 1)

    return {
        'Quality_Score': composite,
        'Q_Quality': round(q, 1),
        'Q_Growth': round(g, 1),
        'Q_Value': round(v, 1),
        'Q_Governance': round(gov, 1),
        'Q_Maturity': round(m, 1),
        'Premium_Eligible': composite >= PREMIUM_SCORE_THRESHOLD,
    }


def score_all_tickers(fundamentals_df=None):
    """
    Score all tickers in the fundamentals DataFrame.

    Returns:
        DataFrame with scores merged with fundamentals
    """
    if fundamentals_df is None:
        if not Path(NIFTY500_FUNDAMENTALS_FILE).exists():
            print("  ERROR: No fundamentals data.")
            return pd.DataFrame()
        fundamentals_df = pd.read_csv(NIFTY500_FUNDAMENTALS_FILE)

    total = len(fundamentals_df)
    print(f"\n{'=' * 60}")
    print(f"Computing Quality Scores ({total} tickers)")
    print(f"{'=' * 60}")

    # Compute industry PE medians
    industry_pe_map = compute_industry_pe(fundamentals_df)
    print(f"  Industry PE groups: {len(industry_pe_map)}")

    # Score each ticker
    score_rows = []
    for _, row in fundamentals_df.iterrows():
        ticker = str(row.get('Ticker', '')).strip()
        if not ticker or ticker == 'nan':
            continue

        scores = compute_quality_score(row, industry_pe_map)
        scores['Ticker'] = ticker
        score_rows.append(scores)

    scores_df = pd.DataFrame(score_rows)

    # Merge with fundamentals
    merged = fundamentals_df.merge(scores_df, on='Ticker', how='left')

    # Sort by quality score
    merged = merged.sort_values('Quality_Score', ascending=False).reset_index(drop=True)

    # Save
    Path(SCREENER_DIR).mkdir(parents=True, exist_ok=True)
    merged.to_csv(NIFTY500_SCORES_FILE, index=False)

    # Report
    avg_score = scores_df['Quality_Score'].mean()
    premium_count = (scores_df['Quality_Score'] >= PREMIUM_SCORE_THRESHOLD).sum()

    print(f"\n  Score Distribution:")
    for threshold in [80, 70, 60, 50, 40]:
        count = (scores_df['Quality_Score'] >= threshold).sum()
        pct = count / total * 100
        marker = " <-- Premium threshold" if threshold == PREMIUM_SCORE_THRESHOLD else ""
        print(f"    >= {threshold}: {count:>4d} ({pct:>5.1f}%){marker}")

    below_30 = (scores_df['Quality_Score'] < 30).sum()
    print(f"    <  30: {below_30:>4d} ({below_30/total*100:>5.1f}%)")

    print(f"\n  Avg Score: {avg_score:.1f}")
    print(f"  Premium eligible (>={PREMIUM_SCORE_THRESHOLD}): {premium_count}/{total}")

    # Top 10 and Bottom 10
    print(f"\n  -- TOP 10 --")
    print(f"  {'Ticker':<16s} {'Score':>6s}  {'Quality':>7s} {'Growth':>7s} {'Value':>6s} {'Gov':>5s} {'Mat':>5s}")
    print(f"  {'-' * 55}")
    for _, r in scores_df.nlargest(10, 'Quality_Score').iterrows():
        print(f"  {r['Ticker']:<16s} {r['Quality_Score']:>5.1f}  "
              f"{r['Q_Quality']:>6.1f} {r['Q_Growth']:>6.1f} "
              f"{r['Q_Value']:>5.1f} {r['Q_Governance']:>4.1f} {r['Q_Maturity']:>4.1f}")

    print(f"\n  -- BOTTOM 10 --")
    print(f"  {'Ticker':<16s} {'Score':>6s}  {'Quality':>7s} {'Growth':>7s} {'Value':>6s} {'Gov':>5s} {'Mat':>5s}")
    print(f"  {'-' * 55}")
    for _, r in scores_df.nsmallest(10, 'Quality_Score').iterrows():
        print(f"  {r['Ticker']:<16s} {r['Quality_Score']:>5.1f}  "
              f"{r['Q_Quality']:>6.1f} {r['Q_Growth']:>6.1f} "
              f"{r['Q_Value']:>5.1f} {r['Q_Governance']:>4.1f} {r['Q_Maturity']:>4.1f}")

    print(f"\n  Saved: {NIFTY500_SCORES_FILE}")
    return merged


def load_scores():
    """Load cached quality scores."""
    if Path(NIFTY500_SCORES_FILE).exists():
        return pd.read_csv(NIFTY500_SCORES_FILE)
    return pd.DataFrame()


if __name__ == "__main__":
    merged = score_all_tickers()
    if not merged.empty:
        premium = merged[merged['Quality_Score'] >= PREMIUM_SCORE_THRESHOLD]
        print(f"\nPremium eligible: {len(premium)} tickers")
