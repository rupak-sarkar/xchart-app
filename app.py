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
LOOKBACK_DAYS = 250
FUTURE_DAYS = 26

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
    try:
        yf_ticker = yf.Ticker(f"{ticker}.NS")
        end_date = TODAY_DATE + timedelta(days=1)
        start_date = TODAY_DATE - timedelta(days=period_days)
        hist = yf_ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
        if hist.empty or len(hist) < 2: return None, {}
        hist = hist.reset_index()
        hist["Ticker"] = ticker
        hist["Date"] = pd.to_datetime(hist["Date"]).dt.strftime("%Y-%m-%d")
        hist = hist[["Ticker","Date","Open","High","Low","Close","Volume"]]
        hist[["Open","High","Low","Close"]] = hist[["Open","High","Low","Close"]].round(2)
        hist["Volume"] = hist["Volume"].astype(int)
        info = {}
        try:
            si = yf_ticker.info
            mc = si.get("marketCap")
            info["Market_Cap"] = round(mc / 10_000_000, 2) if mc else None
            info["Industry"] = si.get("industry")
            try:
                bs = yf_ticker.balance_sheet
                if not bs.empty:
                    td = bs.loc["Total Debt"][0] if "Total Debt" in bs.index else None
                    te = bs.loc["Stockholders Equity"][0] if "Stockholders Equity" in bs.index else (bs.loc["Total Stockholder Equity"][0] if "Total Stockholder Equity" in bs.index else None)
                    if td and te and te != 0: info["Debt_Eq"] = round(float(td)/float(te), 2)
            except: pass
        except: pass
        return hist, info
    except: return None, {}

def compute_all_indicators(df):
    result_frames = []
    for ticker, group in df.groupby("Ticker"):
        g = group.sort_values("Date").copy()
        c = g["Close"]; h = g["High"]; l = g["Low"]
        g["index"] = range(1, len(g) + 1)

        # SMAs
        g["SMA_9"] = c.rolling(9, min_periods=1).mean().round(2)
        g["SMA_22"] = c.rolling(20, min_periods=1).mean().round(2)
        g["STD_22"] = c.rolling(20, min_periods=1).std().round(4)
        g["SMA_50"] = c.rolling(50, min_periods=1).mean().round(2)
        g["SMA_52"] = c.rolling(52, min_periods=1).mean().round(2)
        g["SMA_200"] = c.rolling(200, min_periods=1).mean().round(2)

        # RSI
        delta = c.diff()
        avg_gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
        avg_loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        g["RSI_14"] = (100 - (100 / (1 + rs))).round(2)

        # Bollinger Bands
        g["BB_Upper"] = (g["SMA_22"] + 2 * g["STD_22"]).round(2)
        g["BB_Middle"] = g["SMA_22"]
        g["BB_Lower"] = (g["SMA_22"] - 2 * g["STD_22"]).round(2)
        g["BB_Flag"] = g.apply(lambda r: "BBH" if pd.notna(r["BB_Upper"]) and r["Close"]>r["BB_Upper"] else ("BBL" if pd.notna(r["BB_Lower"]) and r["Close"]<r["BB_Lower"] else None), axis=1)

        # VWAP
        cv = g["Volume"].replace(0, np.nan).cumsum()
        g["VWAP"] = ((c * g["Volume"]).cumsum() / cv).round(2)

        # Ichimoku
        h9 = h.rolling(9, min_periods=1).max(); l9 = l.rolling(9, min_periods=1).min()
        h20 = h.rolling(20, min_periods=1).max(); l20 = l.rolling(20, min_periods=1).min()
        h50 = h.rolling(50, min_periods=1).max(); l50 = l.rolling(50, min_periods=1).min()
        conv = (h9 + l9) / 2; base = (h20 + l20) / 2
        g["Tenkan"] = conv.round(2); g["Kijun"] = base.round(2)
        g["Senkou_Span_A"] = ((conv + base) / 2).shift(20).round(2)
        g["Senkou_Span_B"] = ((h50 + l50) / 2).shift(20).round(2)

        # Knoxville Divergence
        mom = c - c.shift(20)
        rsi = g["RSI_14"]
        div_list = []; sp = None
        for i in range(len(g)):
            r_val = rsi.iloc[i]; m_val = mom.iloc[i]; p_val = c.iloc[i]
            if pd.isna(r_val) or pd.isna(m_val): div_list.append(None)
            elif r_val < 30 and m_val > 0: sp = p_val; div_list.append("Bullish Start")
            elif sp is not None and r_val < 30 and m_val < 0: div_list.append(f"Bullish End ({sp:.0f}->{p_val:.0f})"); sp = None
            elif r_val > 70 and m_val < 0: sp = p_val; div_list.append("Bearish Start")
            elif sp is not None and r_val > 70 and m_val > 0: div_list.append(f"Bearish End ({sp:.0f}->{p_val:.0f})"); sp = None
            else: div_list.append(None)
        g["Knoxville_Divergence"] = div_list

        # Daily signals
        g["gain"] = c.pct_change().mul(100).round(2)
        g["up_20"] = (c > g["SMA_22"]).astype(int)

        # UP_TRUE: Momentum Burst Detector (FII/DII signal)
        # 1 = stock gained >=20% cumulatively in last 3 consecutive UP days
        up_true = []
        for i in range(len(g)):
            if i < 2:
                up_true.append(0); continue
            c0 = c.iloc[i]; c1 = c.iloc[i-1]; c2 = c.iloc[i-2]; c3 = c.iloc[i-3] if i >= 3 else c.iloc[i-2]
            # Check 3 consecutive up days
            if c0 > c1 and c1 > c2 and c2 > c3:
                cumul_return = ((c0 - c3) / c3) * 100 if c3 > 0 else 0
                up_true.append(1 if cumul_return >= 20 else 0)
            else:
                up_true.append(0)
        g["up_true"] = up_true

        result_frames.append(g)
    return pd.concat(result_frames, ignore_index=True)

def extend_with_future_days(df):
    latest_date = pd.to_datetime(TODAY_STR)
    future_dates = pd.date_range(start=latest_date + BDay(1), periods=FUTURE_DAYS, freq=BDay())
    tickers = df["Ticker"].unique()
    future_rows = pd.DataFrame([(d.strftime("%Y-%m-%d"), t) for t in tickers for d in future_dates], columns=["Date","Ticker"])
    for col in ["Open","High","Low","Close","Volume"]: future_rows[col] = np.nan
    combined = pd.concat([df, future_rows], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Ticker","Date"], keep="first")
    return combined.sort_values(["Ticker","Date"]).reset_index(drop=True)

def run():
    tickers = load_tickers()
    total = len(tickers)
    print(f"Tickers: {total}")
    existing_df = None
    if os.path.exists(STOCK_DATA_FILE):
        try:
            existing_df = pd.read_csv(STOCK_DATA_FILE)
            latest = sorted(existing_df["Date"].unique())[-1] if len(existing_df) > 0 else None
            print(f"Existing: {len(existing_df)} rows | Latest: {latest}")
            if latest == TODAY_STR: print("Today exists. Skipping."); return
            fetch_days = 10; print(f"Append mode: {fetch_days} days")
        except: existing_df = None
    if existing_df is None:
        fetch_days = LOOKBACK_DAYS; print(f"Fresh: {fetch_days} days")
    print("-" * 90)
    all_data = []; fundamentals = {}; success = 0; failed = 0
    for idx, ticker in enumerate(tickers, 1):
        print(f"[{idx:3d}/{total}] {ticker}...", end=" ")
        df, info = download_ticker_data(ticker, fetch_days)
        if df is not None and len(df) > 0:
            all_data.append(df); fundamentals[ticker] = info if info else {}
            mc_str = f" MCap:{info.get('Market_Cap','-')}" if info.get("Market_Cap") else ""
            print(f"{len(df)} rows{mc_str}"); success += 1
        else: print("no data"); failed += 1
        if idx % 10 == 0: time.sleep(1)
    if not all_data: print("No data!"); return
    new_df = pd.concat(all_data, ignore_index=True)
    new_df["Market_Cap"] = new_df["Ticker"].map(lambda t: fundamentals.get(t,{}).get("Market_Cap"))
    new_df["Debt_Eq"] = new_df["Ticker"].map(lambda t: fundamentals.get(t,{}).get("Debt_Eq"))
    new_df["Industry"] = new_df["Ticker"].map(lambda t: fundamentals.get(t,{}).get("Industry"))
    if existing_df is not None:
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["Ticker","Date"], keep="last")
        keep = ["Ticker","Date","Open","High","Low","Close","Volume","Market_Cap","Debt_Eq","Industry"]
        combined = combined[[c for c in keep if c in combined.columns]]
        raw_df = combined
    else: raw_df = new_df
    raw_df = raw_df.sort_values(["Ticker","Date"]).reset_index(drop=True)
    print("\nExtending +26 future days & computing indicators...")
    extended = extend_with_future_days(raw_df)
    final_df = compute_all_indicators(extended)
    numeric_cols = final_df.select_dtypes(include=[np.number]).columns
    final_df[numeric_cols] = final_df[numeric_cols].round(2)
    col_order = ["Ticker","Date","Open","High","Low","Close","Volume","Market_Cap","Debt_Eq","Industry","index","SMA_9","SMA_22","STD_22","SMA_50","SMA_52","SMA_200","RSI_14","BB_Upper","BB_Middle","BB_Lower","BB_Flag","VWAP","Tenkan","Kijun","Senkou_Span_A","Senkou_Span_B","Knoxville_Divergence","gain","up_20","up_true"]
    final_df = final_df[[c for c in col_order if c in final_df.columns]]
    final_df.to_csv(STOCK_DATA_FILE, index=False)
    # Report up_true tickers
    actual = final_df.dropna(subset=["Close"])
    latest_date = actual["Date"].max()
    latest_data = actual[actual["Date"]==latest_date]
    burst_tickers = latest_data[latest_data["up_true"]==1]["Ticker"].tolist()
    print("-" * 90)
    print(f"stock_data.csv: {len(final_df)} rows | {final_df['Ticker'].nunique()} tickers | {final_df['Date'].nunique()} dates")
    print(f"  Columns: {len([c for c in col_order if c in final_df.columns])}")
    print(f"  Success: {success} | Failed: {failed}")
    if burst_tickers:
        print(f"  FII/DII MOMENTUM BURST (up_true=1): {', '.join(burst_tickers)}")
    else:
        print(f"  FII/DII Momentum Burst: None detected today")
    print("=" * 90)

if __name__ == "__main__":
    run()
