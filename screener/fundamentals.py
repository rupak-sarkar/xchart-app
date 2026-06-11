"""screener/fundamentals.py -- Fetch fundamental data for all Nifty 500 tickers."""

import time
import numpy as np
import pandas as pd
from pathlib import Path
from screener.config import (
    SCREENER_DIR, NIFTY500_FUNDAMENTALS_FILE, YF_BATCH_SIZE, YF_SLEEP,
    REVENUE_NAMES, NET_INCOME_NAMES, EBIT_NAMES,
    TOTAL_ASSETS_NAMES, CURRENT_LIAB_NAMES, EQUITY_NAMES, NSE_HEADERS,
)


# ===================================================================
# HELPERS
# ===================================================================

def _sf(val, default=0):
    """Safe float conversion."""
    try:
        v = float(val)
        return default if (pd.isna(v) or np.isinf(v)) else v
    except (ValueError, TypeError):
        return default


def _get_row(df, names):
    """Get first matching row from a financials DataFrame."""
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            row = df.loc[name]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            return row
    return None


def _yoy_qtr_growth(qf, row_names):
    """YoY quarterly growth: latest quarter vs same quarter last year."""
    row = _get_row(qf, row_names)
    if row is None:
        return None
    vals = row.dropna()
    if len(vals) >= 5:
        curr = _sf(vals.iloc[0])
        year_ago = _sf(vals.iloc[4])
        if year_ago > 0:
            return round((curr - year_ago) / abs(year_ago) * 100, 2)
    # Fallback: latest vs oldest available
    if len(vals) >= 2:
        curr = _sf(vals.iloc[0])
        prev = _sf(vals.iloc[-1])
        if prev > 0:
            return round((curr - prev) / abs(prev) * 100, 2)
    return None


def _compute_opm(qf):
    """Operating Profit Margin = Operating Income / Revenue * 100."""
    rev_row = _get_row(qf, REVENUE_NAMES)
    oi_row = _get_row(qf, EBIT_NAMES)
    if rev_row is None or oi_row is None:
        return None
    rev = _sf(rev_row.iloc[0])
    oi = _sf(oi_row.iloc[0])
    if rev <= 0:
        return None
    return round(oi / rev * 100, 2)


def _compute_roce(financials, balance_sheet):
    """ROCE = EBIT / (Total Assets - Current Liabilities) * 100."""
    if financials is None or financials.empty:
        return None
    if balance_sheet is None or balance_sheet.empty:
        return None

    ebit_row = _get_row(financials, EBIT_NAMES)
    ta_row = _get_row(balance_sheet, TOTAL_ASSETS_NAMES)
    cl_row = _get_row(balance_sheet, CURRENT_LIAB_NAMES)

    if ebit_row is None or ta_row is None or cl_row is None:
        return None

    ebit = _sf(ebit_row.iloc[0])
    ta = _sf(ta_row.iloc[0])
    cl = _sf(cl_row.iloc[0])
    capital_employed = ta - cl

    if capital_employed <= 0:
        return None
    return round(ebit / capital_employed * 100, 2)


def _profit_growth_3y(financials):
    """3-year profit CAGR from annual financials."""
    ni_row = _get_row(financials, NET_INCOME_NAMES)
    if ni_row is None:
        return None
    vals = ni_row.dropna()
    if len(vals) < 3:
        return None
    latest = _sf(vals.iloc[0])
    oldest = _sf(vals.iloc[-1])
    if oldest <= 0 or latest <= 0:
        return None
    years = len(vals) - 1
    if years <= 0:
        return None
    cagr = ((latest / oldest) ** (1.0 / years) - 1) * 100
    return round(cagr, 2)


def _avg_roe_3y(financials, balance_sheet):
    """Average ROE over available years (up to 3)."""
    ni_row = _get_row(financials, NET_INCOME_NAMES)
    eq_row = _get_row(balance_sheet, EQUITY_NAMES)
    if ni_row is None or eq_row is None:
        return None

    ni_vals = ni_row.dropna()
    eq_vals = eq_row.dropna()
    n = min(len(ni_vals), len(eq_vals), 3)
    if n == 0:
        return None

    roes = []
    for i in range(n):
        ni = _sf(ni_vals.iloc[i])
        eq = _sf(eq_vals.iloc[i])
        if eq > 0:
            roes.append(ni / eq * 100)

    if not roes:
        return None
    return round(np.mean(roes), 2)


def _estimate_mcap_3y_ago(ticker_yf, current_mcap_cr):
    """Estimate market cap 3 years ago from price ratio."""
    try:
        hist = ticker_yf.history(period="3y")
        if len(hist) < 500:
            return 0
        old_price = float(hist['Close'].iloc[0])
        new_price = float(hist['Close'].iloc[-1])
        if new_price <= 0:
            return 0
        return round(current_mcap_cr * (old_price / new_price), 2)
    except Exception:
        return 0


def _fetch_shareholding_nse(ticker):
    """Try fetching shareholding pattern from NSE (best effort)."""
    import requests
    result = {'Promoter_Holding': 0, 'DII_Holding': 0, 'FII_Holding': 0,
              'Public_Holding': 0, 'Pledged_Pct': 0}
    try:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        session.get("https://www.nseindia.com", timeout=10)
        url = f"https://www.nseindia.com/api/corporate-shareholding?symbol={ticker}"
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            return result
        data = resp.json()

        for item in data.get('data', []):
            category = str(item.get('category', '')).lower()
            pct = _sf(item.get('percentage', 0))

            if 'promoter' in category and 'pledge' not in category:
                result['Promoter_Holding'] += pct
            elif 'mutual fund' in category or 'dii' in category or 'insurance' in category:
                result['DII_Holding'] += pct
            elif 'fii' in category or 'fpi' in category or 'foreign' in category:
                result['FII_Holding'] += pct
            elif 'public' in category or 'retail' in category:
                result['Public_Holding'] += pct
            elif 'pledge' in category:
                result['Pledged_Pct'] = pct

        # Ensure holdings sum makes sense
        total = result['Promoter_Holding'] + result['DII_Holding'] + result['FII_Holding'] + result['Public_Holding']
        if total < 50 or total > 110:
            # Data looks wrong, reset
            return {'Promoter_Holding': 0, 'DII_Holding': 0, 'FII_Holding': 0,
                    'Public_Holding': 0, 'Pledged_Pct': 0}

    except Exception:
        pass
    return result


# ===================================================================
# MAIN FETCH FUNCTION
# ===================================================================

def fetch_ticker_fundamentals(ticker):
    """Fetch all fundamental metrics for a single ticker."""
    import yfinance as yf

    result = {
        'Ticker': ticker,
        'Market_Cap': 0.0, 'Sector': '', 'Industry': '',
        'ROE': 0.0, 'ROCE': 0.0, 'PE': 0.0, 'PB': 0.0,
        'Debt_to_Equity': 0.0, 'OPM': 0.0, 'Dividend_Yield': 0.0,
        'YoY_Qtr_Sales_Growth': 0.0, 'YoY_Qtr_Profit_Growth': 0.0,
        'Profit_Growth_3Y': 0.0, 'Avg_ROE_3Y': 0.0,
        'Pledged_Pct': 0.0, 'Promoter_Holding': 0.0,
        'DII_Holding': 0.0, 'FII_Holding': 0.0, 'Public_Holding': 0.0,
        'MCap_3Y_Ago': 0.0, 'Data_Quality': 0,
    }

    for suffix in ['.NS', '.BO']:
        try:
            t = yf.Ticker(f"{ticker}{suffix}")
            info = t.info or {}
            mcap = _sf(info.get('marketCap', 0))
            if mcap <= 0:
                continue

            mcap_cr = round(mcap / 1e7, 2)
            result['Market_Cap'] = mcap_cr

            # -- Basic info from .info --
            result['Sector'] = str(
                info.get('sector', '') or
                info.get('sectorDisp', '') or ''
            )
            result['Industry'] = str(
                info.get('industry', '') or
                info.get('industryDisp', '') or ''
            )

            roe_raw = _sf(info.get('returnOnEquity', 0))
            result['ROE'] = round(roe_raw * 100, 2) if 0 < abs(roe_raw) < 1 else round(roe_raw, 2)

            pe = _sf(info.get('trailingPE', 0)) or _sf(info.get('forwardPE', 0))
            result['PE'] = round(pe, 2)
            result['PB'] = round(_sf(info.get('priceToBook', 0)), 2)

            de_raw = _sf(info.get('debtToEquity', 0))
            result['Debt_to_Equity'] = round(de_raw / 100, 2) if de_raw > 10 else round(de_raw, 2)

            dy_raw = _sf(info.get('dividendYield', 0))
            result['Dividend_Yield'] = round(dy_raw * 100, 2) if 0 < dy_raw < 1 else round(dy_raw, 2)

            # -- Quarterly financials --
            qf = t.quarterly_financials
            if qf is not None and not qf.empty:
                v = _yoy_qtr_growth(qf, REVENUE_NAMES)
                if v is not None:
                    result['YoY_Qtr_Sales_Growth'] = v

                v = _yoy_qtr_growth(qf, NET_INCOME_NAMES)
                if v is not None:
                    result['YoY_Qtr_Profit_Growth'] = v

                v = _compute_opm(qf)
                if v is not None:
                    result['OPM'] = v

            # -- Annual financials + balance sheet --
            af = t.financials
            bs = t.balance_sheet

            v = _compute_roce(af, bs)
            if v is not None:
                result['ROCE'] = v

            v = _profit_growth_3y(af)
            if v is not None:
                result['Profit_Growth_3Y'] = v

            v = _avg_roe_3y(af, bs)
            if v is not None:
                result['Avg_ROE_3Y'] = v

            # -- MCap 3Y ago --
            result['MCap_3Y_Ago'] = _estimate_mcap_3y_ago(t, mcap_cr)

            # -- Data quality --
            score_fields = [
                'Market_Cap', 'ROE', 'ROCE', 'PE', 'Debt_to_Equity', 'OPM',
                'YoY_Qtr_Sales_Growth', 'YoY_Qtr_Profit_Growth',
                'Profit_Growth_3Y', 'Avg_ROE_3Y', 'MCap_3Y_Ago',
            ]
            filled = sum(1 for f in score_fields if result[f] != 0)
            result['Data_Quality'] = round(filled / len(score_fields) * 100)

            break  # Success, don't try .BO

        except Exception:
            continue

    return result


def fetch_all_fundamentals(tickers, force=False):
    """Fetch fundamentals for all tickers. Caches results."""
    Path(SCREENER_DIR).mkdir(parents=True, exist_ok=True)

    # Check cache (skip if fresh and not forced)
    if not force and Path(NIFTY500_FUNDAMENTALS_FILE).exists():
        cached = pd.read_csv(NIFTY500_FUNDAMENTALS_FILE)
        if len(cached) >= len(tickers) * 0.9:
            from datetime import datetime
            mtime = Path(NIFTY500_FUNDAMENTALS_FILE).stat().st_mtime
            age_days = (time.time() - mtime) / 86400
            if age_days < 6:
                print(f"  Fundamentals cache fresh ({age_days:.1f} days old, {len(cached)} tickers)")
                return cached

    total = len(tickers)
    all_results = []
    failed = []

    print(f"\nFetching fundamentals for {total} tickers...")
    print("=" * 60)

    for i in range(0, total, YF_BATCH_SIZE):
        batch = tickers[i:i + YF_BATCH_SIZE]
        batch_num = i // YF_BATCH_SIZE + 1
        total_batches = (total + YF_BATCH_SIZE - 1) // YF_BATCH_SIZE
        print(f"  Batch {batch_num}/{total_batches}: {batch[0]}..{batch[-1]}")

        for ticker in batch:
            result = fetch_ticker_fundamentals(ticker)
            all_results.append(result)
            if result['Market_Cap'] == 0:
                failed.append(ticker)

        # Rate limiting
        if i + YF_BATCH_SIZE < total:
            time.sleep(YF_SLEEP)

    # Fetch shareholding from NSE (best effort, separate pass)
    print(f"\nFetching shareholding from NSE (best effort)...")
    sh_count = 0
    for i, result in enumerate(all_results):
        tk = result['Ticker']
        if result['Market_Cap'] <= 0:
            continue
        sh = _fetch_shareholding_nse(tk)
        if sh['Promoter_Holding'] > 0:
            result.update(sh)
            sh_count += 1
        if (i + 1) % 50 == 0:
            print(f"    Shareholding: {i+1}/{total} ({sh_count} fetched)")
            time.sleep(1)

    # Build DataFrame and save
    df = pd.DataFrame(all_results)
    df.to_csv(NIFTY500_FUNDAMENTALS_FILE, index=False)

    # Report
    mcap_ok = (df['Market_Cap'] > 0).sum()
    sector_ok = (df['Sector'].str.strip() != '').sum()
    pe_ok = (df['PE'] > 0).sum()
    roce_ok = (df['ROCE'] != 0).sum()
    opm_ok = (df['OPM'] != 0).sum()
    sh_ok = (df['Promoter_Holding'] > 0).sum()
    avg_q = df['Data_Quality'].mean()

    print(f"\n{'=' * 60}")
    print(f"  MCap:    {mcap_ok}/{total}")
    print(f"  Sector:  {sector_ok}/{total}")
    print(f"  PE:      {pe_ok}/{total}")
    print(f"  ROCE:    {roce_ok}/{total}")
    print(f"  OPM:     {opm_ok}/{total}")
    print(f"  Holding: {sh_ok}/{total}")
    print(f"  Quality: {avg_q:.0f}% avg")
    if failed:
        print(f"  Failed:  {len(failed)} ({', '.join(failed[:10])}{'...' if len(failed) > 10 else ''})")
    print(f"  Saved: {NIFTY500_FUNDAMENTALS_FILE}")

    return df


def load_fundamentals():
    """Load cached fundamentals DataFrame."""
    if Path(NIFTY500_FUNDAMENTALS_FILE).exists():
        return pd.read_csv(NIFTY500_FUNDAMENTALS_FILE)
    return pd.DataFrame()


if __name__ == "__main__":
    from screener.nifty500 import load_nifty500_list
    tickers = load_nifty500_list()
    if tickers:
        df = fetch_all_fundamentals(tickers[:10])  # Test with 10
        print(f"\nSample:\n{df[['Ticker', 'Market_Cap', 'ROE', 'ROCE', 'PE', 'OPM', 'Data_Quality']].to_string()}")
