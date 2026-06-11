"""screener/config.py -- Configuration for Nifty 500 screening pipeline."""

from pathlib import Path

# ===================================================================
# PATHS
# ===================================================================
SCREENER_DIR = Path("screener_data")
NIFTY500_TICKERS_FILE = SCREENER_DIR / "nifty500_tickers.csv"
NIFTY500_FUNDAMENTALS_FILE = SCREENER_DIR / "nifty500_fundamentals.csv"
NIFTY500_SCORES_FILE = SCREENER_DIR / "nifty500_scores.csv"
NIFTY500_OHLCV_DIR = SCREENER_DIR / "ohlcv"
NIFTY500_BACKTEST_DIR = SCREENER_DIR / "backtest_data"
PREMIUM_TICKERS_FILE = Path("tickers.csv")  # Feeds existing premium engine

# ===================================================================
# OHLCV SETTINGS
# ===================================================================
OHLCV_PERIOD = "3y"
OHLCV_INTERVAL = "1d"
OHLCV_BATCH_SIZE = 25
OHLCV_SLEEP = 1.5  # seconds between batches

# ===================================================================
# PREMIUM FILTER (exact screener.in criteria)
# ===================================================================
PREMIUM_FILTER = {
    "min_market_cap": 500,               # Cr
    "min_roce": 10,                      # %
    "min_roe": 10,                       # %
    "max_pledged_pct": 0,                # % (zero tolerance)
    "max_debt_to_equity": 0.5,           # ratio
    "min_yoy_qtr_sales_growth": 0,       # % (must be positive)
    "min_yoy_qtr_profit_growth": 0,      # % (must be positive)
    "pe_industry_multiplier": 1.8,       # PE < Industry PE * 1.8
    "min_profit_growth_3y": 0,           # % (must be positive)
    "min_opm": 0,                        # % (must be positive)
    "min_avg_roe_3y": 10,                # %
    "min_promoter_dii_holding": 50,      # % combined
    "institutional_public_ratio": 0.25,  # (FII+DII) > Public * 0.25
    "require_mcap_3y_ago": True,         # Company must have existed 3Y ago
}

# ===================================================================
# DYNAMIC QUALITY SCORING (for public backtesting)
# ===================================================================
QUALITY_WEIGHTS = {
    "quality": 30,      # ROCE, ROE, OPM, 3Y avg ROE
    "growth": 25,       # YoY sales, YoY profit, 3Y profit growth
    "value": 20,        # PE vs industry, D/E
    "governance": 20,   # Pledged, shareholding
    "maturity": 5,      # MCap 3Y ago exists
}
PREMIUM_SCORE_THRESHOLD = 60  # Score >= 60 qualifies as premium

# ===================================================================
# YFINANCE SETTINGS
# ===================================================================
YF_BATCH_SIZE = 20
YF_SLEEP = 2.0  # seconds between batches
YF_TIMEOUT = 15

# Row name aliases in yfinance financials DataFrames
REVENUE_NAMES = ['Total Revenue', 'Revenue', 'Operating Revenue', 'Total Operating Revenue']
NET_INCOME_NAMES = ['Net Income', 'Net Income From Continuing Operations',
                    'Net Income Common Stockholders', 'Net Income Including Noncontrolling Interests']
EBIT_NAMES = ['Operating Income', 'EBIT', 'Ebit', 'Operating Profit']
TOTAL_ASSETS_NAMES = ['Total Assets']
CURRENT_LIAB_NAMES = ['Current Liabilities', 'Total Current Liabilities', 'Current Debt And Capital Lease Obligation']
EQUITY_NAMES = ['Total Stockholder Equity', "Stockholders' Equity",
                'Total Equity Gross Minority Interest', 'Stockholders Equity',
                'Common Stock Equity']

# NSE API for shareholding (rate-limited, best effort)
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
