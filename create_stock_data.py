import pandas as pd
import yfinance as yf
import numpy as np
import os
import time
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_STR = NOW_IST.strftime("%Y-%m-%d")

TICKERS_FILE = "tickers.csv"
STOCK_DATA_FILE = "stock_data.csv"
LOOKBACK_DAYS = 45  # Fetch 45 calendar days to get ~30 trading days

print(f"Stock Data Engine | Date: {TODAY_STR}")
print("=" * 80)

# Load tickers
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

# Compute technical indicators
def compute_indicators(df):
    if len(df) < 2:
        return df

    c = df["Close"]

    # SMA
    for w in [9, 22, 50, 200]:
        df[f"SMA_{w}"] = c.rolling(window=w, min_periods=1).mean().round(2)

    # RSI (14)
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(window=14, min_periods=1).mean()
    avg_loss = loss.rolling(window=14, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI_14"] = (100 - (100 / (1 + rs))).round(2)

    # Bollinger Bands (20, 2)
    sma20 = c.rolling(window=20, min_periods=1).mean()
    std20 = c.rolling(window=20, min_periods=1).std()
    df["BB_Upper"] = (sma20 + 2 * std20).round(2)
    df["BB_Middle"] = sma20.round(2)
    df["BB_Lower"] = (sma20 - 2 * std20).round(2)

    # VWAP (cumulative for each day)
    df["VWAP"] = (df["Close"] * df["Volume"]).cumsum() / df["Volume"].replace(0, np.nan).cumsum()
    df["VWAP"] = df["VWAP"].round(2)

    # Ichimoku
    high9 = df["High"].rolling(window=9, min_periods=1).max()
    low9 = df["Low"].rolling(window=9, min_periods=1).min()
    high26 = df["High"].rolling(window=26, min_periods=1).max()
    low26 = df["Low"].rolling(window=26, min_periods=1).min()
    high52 = df["High"].rolling(window=52, min_periods=1).max()
    low52 = df["Low"].rolling(window=52, min_periods=1).min()
    df["Tenkan"] = ((high9 + low9) / 2).round(2)
    df["Kijun"] = ((high26 + low26) / 2).round(2)
    df["Senkou_A"] = ((df["Tenkan"] + df["Kijun"]) / 2).round(2)
    df["Senkou_B"] = ((high52 + low52) / 2).round(2)

    return df

# Download OHLCV data
def download_ticker_data(ticker, period_days):
    try:
        yf_ticker = yf.Ticker(f"{ticker}.NS")
        end_date = NOW_IST.date()
        start_date = end_date - timedelta(days=period_days)
        hist = yf_ticker.history(start=start_date.strftime("%Y-%m-%d"), end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"))
        if hist.empty or len(hist) < 2:
            return None
        hist = hist.reset_index()
        hist["Ticker"] = ticker
        hist["Date"] = pd.to_datetime(hist["Date"]).dt.strftime("%Y-%m-%d")
        hist = hist[["Ticker","Date","Open","High","Low","Close","Volume"]]
        hist[["Open","High","Low","Close"]] = hist[["Open","High","Low","Close"]].round(2)
        hist["Volume"] = hist["Volume"].astype(int)
        # Compute indicators
        hist = compute_indicators(hist)
        return hist
    except Exception as e:
        print(f"   {ticker}: Error - {e}")
        return None

def run():
    tickers = load_tickers()
    total = len(tickers)
    print(f"Tickers: {total}")

    # Check if stock_data.csv exists (append mode vs fresh download)
    existing_df = None
    if os.path.exists(STOCK_DATA_FILE):
        try:
            existing_df = pd.read_csv(STOCK_DATA_FILE)
            existing_dates = sorted(existing_df["Date"].unique())
            latest_date = existing_dates[-1] if existing_dates else None
            print(f"Existing data: {len(existing_df)} rows | Latest: {latest_date} | {len(existing_dates)} trading days")

            # If we already have today's data, skip
            if latest_date == TODAY_STR:
                print(f"Today's data already exists. Skipping download.")
                return

            # Append mode: only fetch last 5 days to get new data
            fetch_days = 7
            print(f"Append mode: fetching last {fetch_days} days to get new trading day(s)")
        except Exception as e:
            print(f"Error reading existing data: {e}")
            existing_df = None

    if existing_df is None:
        fetch_days = LOOKBACK_DAYS
        print(f"Fresh download: fetching last {fetch_days} days (~30 trading days)")

    print("-" * 80)

    all_data = []
    success = 0; failed = 0

    for idx, ticker in enumerate(tickers, 1):
        print(f"[{idx:3d}/{total}] {ticker}...", end=" ")
        df = download_ticker_data(ticker, fetch_days)
        if df is not None and len(df) > 0:
            all_data.append(df)
            print(f"{len(df)} rows")
            success += 1
        else:
            print("no data")
            failed += 1

        # Rate limiting
        if idx % 10 == 0:
            time.sleep(1)

    if not all_data:
        print("No data downloaded!")
        return

    new_df = pd.concat(all_data, ignore_index=True)

    if existing_df is not None:
        # Merge: keep existing + add new dates only
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        # Remove duplicates (same ticker + date)
        combined = combined.drop_duplicates(subset=["Ticker","Date"], keep="last")
        # Sort
        combined = combined.sort_values(["Ticker","Date"]).reset_index(drop=True)
        # Keep only last 30 trading days per ticker
        def trim_to_30(group):
            return group.tail(30)
        combined = combined.groupby("Ticker", group_keys=False).apply(trim_to_30).reset_index(drop=True)
        final_df = combined
    else:
        new_df = new_df.sort_values(["Ticker","Date"]).reset_index(drop=True)
        def trim_to_30(group):
            return group.tail(30)
        final_df = new_df.groupby("Ticker", group_keys=False).apply(trim_to_30).reset_index(drop=True)

    final_df.to_csv(STOCK_DATA_FILE, index=False)

    unique_tickers = final_df["Ticker"].nunique()
    unique_dates = final_df["Date"].nunique()
    print("-" * 80)
    print(f"stock_data.csv written: {len(final_df)} rows | {unique_tickers} tickers | {unique_dates} trading days")
    print(f"Success: {success} | Failed: {failed}")
    print(f"Date range: {final_df['Date'].min()} to {final_df['Date'].max()}")
    print("=" * 80)

if __name__ == "__main__":
    run()
