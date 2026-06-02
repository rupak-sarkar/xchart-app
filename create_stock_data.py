import pandas as pd
import yfinance as yf
import numpy as np
import os
import time
from datetime import datetime, timezone, timedelta
from pandas.tseries.offsets import BDay

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_STR = NOW_IST.strftime("%Y-%m-%d")
TODAY_DATE = NOW_IST.date()

TICKERS_FILE = "tickers.csv"
STOCK_DATA_FILE = "stock_data.csv"
LOOKBACK_DAYS = 250  # ~200 trading days needed for SMA_200
FUTURE_DAYS = 26     # For Ichimoku cloud projection

print(f"Stock Data Engine | Date: {TODAY_STR}")
print("=" * 90)

def load_tickers():
    if os.path.exists(TICKERS_FILE):
        df = pd.read_csv(TICKERS_FILE)
        df.columns = df.columns.str.strip()
        if "Ticker" not in df.columns:
            df.rename(columns={df.columns[0]: "Ticker"}, inplace=True)
        tickers = [t.replace(".NS","").strip().upper() for t in df["Ticker"].dropna().tolist() if t.strip()]
        seen = set(); unique = []
        for t in tickers:
            if t not in seen: seen.add(t); unique.append(t)
        return unique
    return ["RELIANCE","TCS","INFY","HDFCBANK","SBIN"]


def download_ticker_data(ticker, period_days):
    """Download OHLCV + Market Cap, Debt/Equity, Industry from yfinance."""
    try:
        yf_ticker = yf.Ticker(f"{ticker}.NS")
        end_date = TODAY_DATE + timedelta(days=1)
        start_date = TODAY_DATE - timedelta(days=period_days)
        hist = yf_ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
        if hist.empty or len(hist) < 2:
            return None, {}

        hist = hist.reset_index()
        hist["Ticker"] = ticker
        hist["Date"] = pd.to_datetime(hist["Date"]).dt.strftime("%Y-%m-%d")
        hist = hist[["Ticker","Date","Open","High","Low","Close","Volume"]]
        hist[["Open","High","Low","Close"]] = hist[["Open","High","Low","Close"]].round(2)
        hist["Volume"] = hist["Volume"].astype(int)

        # Fetch fundamentals (Market Cap, Debt/Equity, Industry)
        info = {}
        try:
            stock_info = yf_ticker.info
            market_cap = stock_info.get("marketCap", None)
            industry = stock_info.get("industry", None)
            # Market Cap in INR Crores (yfinance returns in local currency for .NS)
            market_cap_cr = round(market_cap / 10_000_000, 2) if market_cap else None

            # Debt/Equity from balance sheet
            debt_eq = None
            try:
                bs = yf_ticker.balance_sheet
                if not bs.empty:
                    total_debt = bs.loc["Total Debt"][0] if "Total Debt" in bs.index else None
                    total_equity = bs.loc["Stockholders Equity"][0] if "Stockholders Equity" in bs.index else (
                        bs.loc["Total Stockholder Equity"][0] if "Total Stockholder Equity" in bs.index else None
                    )
                    if total_debt and total_equity and total_equity != 0:
                        debt_eq = round(float(total_debt) / float(total_equity), 2)
            except: pass

            info = {"Market_Cap": market_cap_cr, "Debt_Eq": debt_eq, "Industry": industry}
        except: pass

        return hist, info
    except Exception as e:
        return None, {}


def compute_all_indicators(df):
    """
    Computes ALL indicators matching screener_view repo:
    SMA (9/22/52/200), STD_22, RSI_14, BB (Upper/Lower/Flag),
    Senkou_Span_A/B (shifted), Knoxville_Divergence,
    gain, up_20, up_true, VWAP, Tenkan, Kijun, BB_Middle, index
    """
    result_frames = []

    for ticker, group in df.groupby("Ticker"):
        g = group.sort_values("Date").copy()
        c = g["Close"]

        # Index (row counter per ticker)
        g["index"] = range(1, len(g) + 1)

        # --- SMAs ---
        g["SMA_9"] = c.rolling(window=9, min_periods=1).mean().round(2)
        g["SMA_22"] = c.rolling(window=20, min_periods=1).mean().round(2)
        g["STD_22"] = c.rolling(window=20, min_periods=1).std().round(4)
        g["SMA_50"] = c.rolling(window=50, min_periods=1).mean().round(2)
        g["SMA_52"] = c.rolling(window=52, min_periods=1).mean().round(2)
        g["SMA_200"] = c.rolling(window=200, min_periods=1).mean().round(2)

        # --- RSI (14) ---
        delta = c.diff()
        gain = delta.clip(lower=0)
        loss = (-delta.clip(upper=0))
        avg_gain = gain.rolling(window=14, min_periods=1).mean()
        avg_loss = loss.rolling(window=14, min_periods=1).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        g["RSI_14"] = (100 - (100 / (1 + rs))).round(2)

        # --- Bollinger Bands (20, 2) ---
        g["BB_Upper"] = (g["SMA_22"] + 2 * g["STD_22"]).round(2)
        g["BB_Middle"] = g["SMA_22"]
        g["BB_Lower"] = (g["SMA_22"] - 2 * g["STD_22"]).round(2)

        # BB_Flag: BBH if Close > Upper, BBL if Close < Lower
        def bb_flag(row):
            if pd.isna(row["BB_Upper"]) or pd.isna(row["BB_Lower"]): return None
            elif row["Close"] > row["BB_Upper"]: return "BBH"
            elif row["Close"] < row["BB_Lower"]: return "BBL"
            else: return None
        g["BB_Flag"] = g.apply(bb_flag, axis=1)

        # --- VWAP ---
        cum_vol = g["Volume"].replace(0, np.nan).cumsum()
        g["VWAP"] = ((g["Close"] * g["Volume"]).cumsum() / cum_vol).round(2)

        # --- Ichimoku (with Tenkan, Kijun, and SHIFTED Senkou) ---
        high9 = g["High"].rolling(window=9, min_periods=1).max()
        low9 = g["Low"].rolling(window=9, min_periods=1).min()
        high20 = g["High"].rolling(window=20, min_periods=1).max()
        low20 = g["Low"].rolling(window=20, min_periods=1).min()
        high50 = g["High"].rolling(window=50, min_periods=1).max()
        low50 = g["Low"].rolling(window=50, min_periods=1).min()

        conv_line = ((high9 + low9) / 2)
        base_line = ((high20 + low20) / 2)

        g["Tenkan"] = conv_line.round(2)
        g["Kijun"] = base_line.round(2)
        # Senkou Span A/B shifted forward by 20 periods (cloud projection)
        g["Senkou_Span_A"] = ((conv_line + base_line) / 2).shift(20).round(2)
        span_b = ((high50 + low50) / 2)
        g["Senkou_Span_B"] = span_b.shift(20).round(2)

        # --- Knoxville Divergence ---
        momentum = c - c.shift(20)
        rsi_vals = g["RSI_14"]
        divergence = []
        start_price = None
        for i in range(len(g)):
            r = rsi_vals.iloc[i]; m = momentum.iloc[i]; p = c.iloc[i]
            if pd.isna(r) or pd.isna(m):
                divergence.append(None)
            elif r < 30 and m > 0:
                start_price = p; divergence.append("Bullish Start")
            elif start_price is not None and r < 30 and m < 0:
                divergence.append(f"Bullish End ({start_price:.0f}->{p:.0f})")
                start_price = None
            elif r > 70 and m < 0:
                start_price = p; divergence.append("Bearish Start")
            elif start_price is not None and r > 70 and m > 0:
                divergence.append(f"Bearish End ({start_price:.0f}->{p:.0f})")
                start_price = None
            else:
                divergence.append(None)
        g["Knoxville_Divergence"] = divergence

        # --- Trading Signals ---
        g["gain"] = c.pct_change().mul(100).round(2)  # Daily return %
        g["up_20"] = (c > g["SMA_22"]).astype(int)    # Close > SMA_22
        g["up_true"] = (c > c.shift(1)).astype(int)   # Close > previous close

        result_frames.append(g)

    return pd.concat(result_frames, ignore_index=True)


def extend_with_future_days(df):
    """Append 26 future business days per ticker for Ichimoku cloud projection."""
    latest_date = pd.to_datetime(TODAY_STR)
    future_dates = pd.date_range(start=latest_date + BDay(1), periods=FUTURE_DAYS, freq=BDay())
    tickers = df["Ticker"].unique()

    future_rows = pd.DataFrame(
        [(d.strftime("%Y-%m-%d"), t) for t in tickers for d in future_dates],
        columns=["Date", "Ticker"]
    )
    for col in ["Open","High","Low","Close","Volume"]:
        future_rows[col] = np.nan

    combined = pd.concat([df, future_rows], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Ticker","Date"], keep="first")
    combined = combined.sort_values(["Ticker","Date"]).reset_index(drop=True)
    return combined


def run():
    tickers = load_tickers()
    total = len(tickers)
    print(f"Tickers: {total}")

    # Check existing data
    existing_df = None
    if os.path.exists(STOCK_DATA_FILE):
        try:
            existing_df = pd.read_csv(STOCK_DATA_FILE)
            existing_dates = sorted(existing_df["Date"].unique())
            latest = existing_dates[-1] if existing_dates else None
            print(f"Existing: {len(existing_df)} rows | Latest: {latest} | {len(existing_dates)} dates")
            if latest == TODAY_STR:
                print(f"Today's data exists. Skipping.")
                return
            fetch_days = 10  # Append mode
            print(f"Append mode: fetching last {fetch_days} days")
        except:
            existing_df = None

    if existing_df is None:
        fetch_days = LOOKBACK_DAYS
        print(f"Fresh download: {fetch_days} days (~200 trading days for SMA_200)")

    print("-" * 90)

    all_data = []
    fundamentals = {}
    success = 0; failed = 0

    for idx, ticker in enumerate(tickers, 1):
        print(f"[{idx:3d}/{total}] {ticker}...", end=" ")
        df, info = download_ticker_data(ticker, fetch_days)
        if df is not None and len(df) > 0:
            all_data.append(df)
            if info:
                fundamentals[ticker] = info
            print(f"{len(df)} rows" + (f" | MCap:{info.get('Market_Cap','-')} D/E:{info.get('Debt_Eq','-')}" if info.get("Market_Cap") else ""))
            success += 1
        else:
            print("no data")
            failed += 1
        if idx % 10 == 0:
            time.sleep(1)

    if not all_data:
        print("No data!"); return

    new_df = pd.concat(all_data, ignore_index=True)

    # Add fundamentals
    new_df["Market_Cap"] = new_df["Ticker"].map(lambda t: fundamentals.get(t, {}).get("Market_Cap"))
    new_df["Debt_Eq"] = new_df["Ticker"].map(lambda t: fundamentals.get(t, {}).get("Debt_Eq"))
    new_df["Industry"] = new_df["Ticker"].map(lambda t: fundamentals.get(t, {}).get("Industry"))

    if existing_df is not None:
        # Merge
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["Ticker","Date"], keep="last")
        combined = combined.sort_values(["Ticker","Date"]).reset_index(drop=True)
        # Keep raw OHLCV columns, drop old indicators (will recompute)
        keep_cols = ["Ticker","Date","Open","High","Low","Close","Volume","Market_Cap","Debt_Eq","Industry"]
        drop_cols = [c for c in combined.columns if c not in keep_cols]
        combined = combined.drop(columns=drop_cols, errors="ignore")
        raw_df = combined
    else:
        raw_df = new_df

    raw_df = raw_df.sort_values(["Ticker","Date"]).reset_index(drop=True)

    # Extend with future days for Ichimoku projection
    print("\nExtending with 26 future business days for Ichimoku...")
    extended_df = extend_with_future_days(raw_df)

    # Compute ALL indicators
    print("Computing indicators (SMA/RSI/BB/Ichimoku/Knoxville/signals)...")
    final_df = compute_all_indicators(extended_df)

    # Round numeric columns
    numeric_cols = final_df.select_dtypes(include=[np.number]).columns
    final_df[numeric_cols] = final_df[numeric_cols].round(2)

    # Column order matching screener_view repo + extras
    col_order = [
        "Ticker","Date","Open","High","Low","Close","Volume",
        "Market_Cap","Debt_Eq","Industry","index",
        "SMA_9","SMA_22","STD_22","SMA_50","SMA_52","SMA_200",
        "RSI_14","BB_Upper","BB_Middle","BB_Lower","BB_Flag",
        "VWAP","Tenkan","Kijun","Senkou_Span_A","Senkou_Span_B",
        "Knoxville_Divergence","gain","up_20","up_true",
    ]
    # Only include columns that exist
    final_cols = [c for c in col_order if c in final_df.columns]
    final_df = final_df[final_cols]

    final_df.to_csv(STOCK_DATA_FILE, index=False)

    ut = final_df["Ticker"].nunique()
    ud = final_df["Date"].nunique()
    actual_rows = final_df.dropna(subset=["Close"])
    print("-" * 90)
    print(f"stock_data.csv: {len(final_df)} rows | {ut} tickers | {ud} dates")
    print(f"  Actual data rows: {len(actual_rows)} | Future projection rows: {len(final_df)-len(actual_rows)}")
    print(f"  Date range: {final_df['Date'].min()} to {final_df['Date'].max()}")
    print(f"  Success: {success} | Failed: {failed}")
    print(f"  Columns: {len(final_cols)} → {', '.join(final_cols)}")
    print("=" * 90)

if __name__ == "__main__":
    run()
