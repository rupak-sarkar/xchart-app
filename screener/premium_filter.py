"""screener/premium_filter.py -- YOUR exact screener.in criteria (binary pass/fail).

This is the PREMIUM selection filter. A ticker must pass ALL 14 criteria
to qualify for the premium engine (v7.4 AI signals).

Criteria (from screener.in):
  1.  Market Cap > 500 Cr
  2.  ROCE >= 10%
  3.  ROE >= 10%
  4.  Pledged % = 0
  5.  D/E < 0.5
  6.  YoY Qtr Sales Growth > 0
  7.  YoY Qtr Profit Growth > 0
  8.  PE < Industry PE * 1.8
  9.  3Y Profit Growth > 0
  10. OPM > 0
  11. 3Y Avg ROE > 10
  12. (DII + Promoter) > 50%
  13. (FII + DII) > Public * 0.25
  14. MCap 3Y ago > 0 (company existed 3 years)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from screener.config import (
    PREMIUM_FILTER, PREMIUM_TICKERS_FILE,
    NIFTY500_FUNDAMENTALS_FILE, SCREENER_DIR,
)


def _sf(val, default=0):
    try:
        v = float(val)
        return default if (pd.isna(v) or np.isinf(v)) else v
    except (ValueError, TypeError):
        return default


def compute_industry_pe(df):
    """Compute median PE per industry/sector for relative valuation."""
    pe_map = {}

    # Try Industry first, fall back to Sector
    for group_col in ['Industry', 'Sector']:
        if group_col not in df.columns:
            continue
        valid = df[(df['PE'] > 0) & (df[group_col].str.strip() != '')].copy()
        if valid.empty:
            continue

        for group_name, group_df in valid.groupby(group_col):
            if str(group_name).strip() == '' or str(group_name) == 'nan':
                continue
            median_pe = group_df['PE'].median()
            if median_pe > 0:
                pe_map[str(group_name).strip()] = round(median_pe, 2)

    return pe_map


def check_premium_criteria(row, industry_pe_map, cfg=None):
    """
    Check all 14 premium criteria for a single ticker.

    Returns:
        dict with:
            'passes': bool (True if ALL criteria met)
            'criteria': dict of {criterion_name: (passed: bool, value, threshold)}
            'fail_reasons': list of failed criteria names
    """
    if cfg is None:
        cfg = PREMIUM_FILTER

    mcap = _sf(row.get('Market_Cap', 0))
    roce = _sf(row.get('ROCE', 0))
    roe = _sf(row.get('ROE', 0))
    pledged = _sf(row.get('Pledged_Pct', 0))
    de = _sf(row.get('Debt_to_Equity', 0))
    yoy_sales = _sf(row.get('YoY_Qtr_Sales_Growth', 0))
    yoy_profit = _sf(row.get('YoY_Qtr_Profit_Growth', 0))
    pe = _sf(row.get('PE', 0))
    profit_3y = _sf(row.get('Profit_Growth_3Y', 0))
    opm = _sf(row.get('OPM', 0))
    avg_roe_3y = _sf(row.get('Avg_ROE_3Y', 0))
    promoter = _sf(row.get('Promoter_Holding', 0))
    dii = _sf(row.get('DII_Holding', 0))
    fii = _sf(row.get('FII_Holding', 0))
    public = _sf(row.get('Public_Holding', 0))
    mcap_3y = _sf(row.get('MCap_3Y_Ago', 0))

    # Determine industry PE
    industry = str(row.get('Industry', '')).strip()
    sector = str(row.get('Sector', '')).strip()
    ind_pe = industry_pe_map.get(industry, 0) or industry_pe_map.get(sector, 0)
    pe_threshold = ind_pe * cfg['pe_industry_multiplier'] if ind_pe > 0 else 999

    criteria = {}

    # 1. Market Cap > 500 Cr
    criteria['mcap_500'] = (mcap > cfg['min_market_cap'], mcap, cfg['min_market_cap'])

    # 2. ROCE >= 10%
    criteria['roce_10'] = (roce >= cfg['min_roce'], roce, cfg['min_roce'])

    # 3. ROE >= 10%
    criteria['roe_10'] = (roe >= cfg['min_roe'], roe, cfg['min_roe'])

    # 4. Pledged % = 0
    criteria['pledged_0'] = (pledged <= cfg['max_pledged_pct'], pledged, cfg['max_pledged_pct'])

    # 5. D/E < 0.5
    criteria['de_05'] = (de < cfg['max_debt_to_equity'], de, cfg['max_debt_to_equity'])

    # 6. YoY Qtr Sales Growth > 0
    criteria['yoy_sales'] = (yoy_sales > cfg['min_yoy_qtr_sales_growth'], yoy_sales, cfg['min_yoy_qtr_sales_growth'])

    # 7. YoY Qtr Profit Growth > 0
    criteria['yoy_profit'] = (yoy_profit > cfg['min_yoy_qtr_profit_growth'], yoy_profit, cfg['min_yoy_qtr_profit_growth'])

    # 8. PE < Industry PE * 1.8
    # If we don't have industry PE data, skip this check (pass by default)
    if ind_pe > 0 and pe > 0:
        criteria['pe_vs_industry'] = (pe < pe_threshold, pe, pe_threshold)
    else:
        criteria['pe_vs_industry'] = (True, pe, f"N/A (ind_pe={ind_pe})")

    # 9. 3Y Profit Growth > 0
    criteria['profit_3y'] = (profit_3y > cfg['min_profit_growth_3y'], profit_3y, cfg['min_profit_growth_3y'])

    # 10. OPM > 0
    criteria['opm_positive'] = (opm > cfg['min_opm'], opm, cfg['min_opm'])

    # 11. 3Y Avg ROE > 10
    criteria['avg_roe_3y'] = (avg_roe_3y > cfg['min_avg_roe_3y'], avg_roe_3y, cfg['min_avg_roe_3y'])

    # 12. (DII + Promoter) > 50%
    prom_dii = promoter + dii
    if promoter > 0 or dii > 0:
        criteria['promoter_dii'] = (prom_dii > cfg['min_promoter_dii_holding'], prom_dii, cfg['min_promoter_dii_holding'])
    else:
        criteria['promoter_dii'] = (True, 0, "N/A (no holding data)")

    # 13. (FII + DII) > Public * 0.25
    inst = fii + dii
    pub_threshold = public * cfg['institutional_public_ratio']
    # If we don't have shareholding data, skip this check
    if promoter > 0 or dii > 0 or fii > 0:
        criteria['inst_vs_public'] = (inst > pub_threshold, inst, round(pub_threshold, 2))
    else:
        criteria['inst_vs_public'] = (True, 0, "N/A (no holding data)")

    # 14. MCap 3Y ago > 0
    if cfg['require_mcap_3y_ago']:
        criteria['mcap_3y_ago'] = (mcap_3y > 0, mcap_3y, "> 0")
    else:
        criteria['mcap_3y_ago'] = (True, mcap_3y, "skipped")

    # Aggregate
    fail_reasons = [k for k, v in criteria.items() if not v[0]]
    passes = len(fail_reasons) == 0

    return {
        'passes': passes,
        'criteria': criteria,
        'fail_reasons': fail_reasons,
        'n_pass': sum(1 for v in criteria.values() if v[0]),
        'n_total': len(criteria),
    }


def run_premium_filter(fundamentals_df=None):
    """
    Run the premium filter on all tickers.

    Returns:
        premium_tickers: list of tickers that pass ALL criteria
        results_df: DataFrame with pass/fail details per ticker
    """
    if fundamentals_df is None:
        if not Path(NIFTY500_FUNDAMENTALS_FILE).exists():
            print("  ERROR: No fundamentals data. Run fundamentals fetch first.")
            return [], pd.DataFrame()
        fundamentals_df = pd.read_csv(NIFTY500_FUNDAMENTALS_FILE)

    total = len(fundamentals_df)
    print(f"\n{'=' * 60}")
    print(f"Running Premium Filter ({total} tickers)")
    print(f"{'=' * 60}")

    # Compute industry PE medians
    industry_pe_map = compute_industry_pe(fundamentals_df)
    print(f"  Industry PE medians: {len(industry_pe_map)} groups")
    for ind, pe in sorted(industry_pe_map.items(), key=lambda x: -x[1])[:5]:
        print(f"    {ind}: {pe:.1f}")
    print(f"    ... ({len(industry_pe_map)} total)")

    # Run filter on each ticker
    results = []
    for _, row in fundamentals_df.iterrows():
        ticker = str(row.get('Ticker', '')).strip()
        if not ticker or ticker == 'nan':
            continue

        check = check_premium_criteria(row, industry_pe_map)
        results.append({
            'Ticker': ticker,
            'Premium_Pass': check['passes'],
            'Criteria_Met': check['n_pass'],
            'Criteria_Total': check['n_total'],
            'Fail_Reasons': '|'.join(check['fail_reasons']) if check['fail_reasons'] else '',
            'Market_Cap': _sf(row.get('Market_Cap', 0)),
            'Sector': row.get('Sector', ''),
        })

    results_df = pd.DataFrame(results)

    # Extract premium tickers
    premium = results_df[results_df['Premium_Pass'] == True]
    premium_tickers = premium['Ticker'].tolist()

    # Report
    n_pass = len(premium_tickers)
    n_fail = total - n_pass
    print(f"\n  Results:")
    print(f"    PASS (premium): {n_pass}/{total} ({n_pass/total*100:.0f}%)")
    print(f"    FAIL:           {n_fail}/{total}")

    # Failure analysis
    if n_fail > 0:
        fail_df = results_df[results_df['Premium_Pass'] == False]
        all_reasons = []
        for reasons in fail_df['Fail_Reasons']:
            all_reasons.extend(str(reasons).split('|'))
        if all_reasons:
            reason_counts = pd.Series(all_reasons).value_counts()
            print(f"\n  Top failure reasons:")
            for reason, count in reason_counts.head(8).items():
                pct = count / n_fail * 100
                print(f"    {reason}: {count} ({pct:.0f}%)")

    # Near-miss tickers (12-13 out of 14 criteria met)
    near_miss = results_df[
        (results_df['Premium_Pass'] == False) &
        (results_df['Criteria_Met'] >= results_df['Criteria_Total'] - 2)
    ]
    if len(near_miss) > 0:
        print(f"\n  Near-miss ({len(near_miss)} tickers, met {near_miss['Criteria_Total'].iloc[0]-2}+ criteria):")
        for _, r in near_miss.head(10).iterrows():
            print(f"    {r['Ticker']:<18s} {int(r['Criteria_Met'])}/{int(r['Criteria_Total'])}  fail: {r['Fail_Reasons']}")

    # Save premium tickers for existing engine
    save_premium_tickers(premium_tickers, results_df)

    # Save full results
    results_path = SCREENER_DIR / "premium_filter_results.csv"
    results_df.to_csv(results_path, index=False)
    print(f"\n  Saved: {results_path}")

    return premium_tickers, results_df


def save_premium_tickers(tickers, results_df=None):
    """Save premium tickers to tickers.csv (feeds existing engine)."""
    if not tickers:
        print("  WARNING: No premium tickers to save!")
        return

    out_df = pd.DataFrame({'Ticker': tickers})

    # Add Sector if available
    if results_df is not None and 'Sector' in results_df.columns:
        sector_map = dict(zip(results_df['Ticker'], results_df['Sector']))
        out_df['Sector'] = out_df['Ticker'].map(sector_map).fillna('')

    out_df.to_csv(PREMIUM_TICKERS_FILE, index=False)
    print(f"  Saved: {PREMIUM_TICKERS_FILE} ({len(tickers)} premium tickers)")


if __name__ == "__main__":
    premium_tickers, results_df = run_premium_filter()
    if premium_tickers:
        print(f"\nPremium tickers ({len(premium_tickers)}):")
        for i, tk in enumerate(premium_tickers):
            print(f"  [{i+1:>3d}] {tk}")
