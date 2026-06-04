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
REQUIRED_COLUMNS = ["up_true","Knoxville_Divergence","BB_Flag","gain","Market_Cap","SMA_52"]

print(f"Stock Data Engine | {TODAY_STR}")
print("=" * 90)


def load_tickers():
    if os.path.exists(TICKERS_FILE):
        df = pd.read_csv(TICKERS_FILE); df.columns = df.columns.str.strip()
        if "Ticker" not in df.columns: df.rename(columns={df.columns[0]:"Ticker"}, inplace=True)
        tickers = [t.replace(".NS","").strip().upper() for t in df["Ticker"].dropna().tolist() if t.strip()]
        seen = set(); unique = []
        for t in tickers:
            if t not in seen: seen.add(t); unique.append(t)
        return unique
    return ["RELIANCE","TCS","INFY","HDFCBANK","SBIN"]


def sanitize_str(val):
    """Convert None, nan, 'nan', 'none', 'n/a' to empty string"""
    if val is None:
        return ""
    if isinstance(val, float) and np.isnan(val):
        return ""
    s = str(val).strip()
    if s.lower() in ('nan', 'none', 'n/a', 'null', ''):
        return ""
    return s


def download_ticker_data(ticker, period_days):
    try:
        yf_t = yf.Ticker(f"{ticker}.NS")
        end = TODAY_DATE + timedelta(days=1); start = TODAY_DATE - timedelta(days=period_days)
        hist = yf_t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if hist.empty or len(hist) < 2: return None, {}
        hist = hist.reset_index(); hist["Ticker"] = ticker
        hist["Date"] = pd.to_datetime(hist["Date"]).dt.strftime("%Y-%m-%d")
        hist = hist[["Ticker","Date","Open","High","Low","Close","Volume"]]
        hist[["Open","High","Low","Close"]] = hist[["Open","High","Low","Close"]].round(2)
        hist["Volume"] = hist["Volume"].astype(int)

        info = {}
        try:
            si = yf_t.info

            # ── FIX: Sanitize all info fields ──
            mc = si.get("marketCap")
            info["Market_Cap"] = round(mc / 10_000_000, 2) if mc else None

            raw_industry = si.get("industry")
            info["Industry"] = sanitize_str(raw_industry)

            raw_sector = si.get("sector")
            info["Sector_yf"] = sanitize_str(raw_sector)

            try:
                bs = yf_t.balance_sheet
                if not bs.empty:
                    td = bs.loc["Total Debt"][0] if "Total Debt" in bs.index else None
                    te = bs.loc["Stockholders Equity"][0] if "Stockholders Equity" in bs.index else (
                        bs.loc["Total Stockholder Equity"][0] if "Total Stockholder Equity" in bs.index else None)
                    if td and te and te != 0:
                        info["Debt_Eq"] = round(float(td) / float(te), 2)
            except:
                pass
        except:
            pass

        return hist, info
    except:
        return None, {}


def compute_all_indicators(df):
    frames = []
    for ticker, grp in df.groupby("Ticker"):
        g = grp.sort_values("Date").copy()
        c = g["Close"]; h = g["High"]; lo = g["Low"]

        g["index"] = range(1, len(g) + 1)
        g["SMA_9"] = c.rolling(9, min_periods=1).mean().round(2)
        g["SMA_22"] = c.rolling(20, min_periods=1).mean().round(2)
        g["STD_22"] = c.rolling(20, min_periods=1).std().round(4)
        g["SMA_50"] = c.rolling(50, min_periods=1).mean().round(2)
        g["SMA_52"] = c.rolling(52, min_periods=1).mean().round(2)
        g["SMA_200"] = c.rolling(200, min_periods=1).mean().round(2)

        delta = c.diff()
        ag = delta.clip(lower=0).rolling(14, min_periods=1).mean()
        al = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
        rs = ag / al.replace(0, np.nan)
        g["RSI_14"] = (100 - (100 / (1 + rs))).round(2)

        g["BB_Upper"] = (g["SMA_22"] + 2 * g["STD_22"]).round(2)
        g["BB_Middle"] = g["SMA_22"]
        g["BB_Lower"] = (g["SMA_22"] - 2 * g["STD_22"]).round(2)

        g["BB_Flag"] = g.apply(
            lambda r: "BBH" if pd.notna(r["BB_Upper"]) and r["Close"] > r["BB_Upper"]
            else ("BBL" if pd.notna(r["BB_Lower"]) and r["Close"] < r["BB_Lower"]
                  else ""), axis=1)

        cv = g["Volume"].replace(0, np.nan).cumsum()
        g["VWAP"] = ((c * g["Volume"]).cumsum() / cv).round(2)

        h9 = h.rolling(9, min_periods=1).max(); l9 = lo.rolling(9, min_periods=1).min()
        h20 = h.rolling(20, min_periods=1).max(); l20 = lo.rolling(20, min_periods=1).min()
        h50 = h.rolling(50, min_periods=1).max(); l50 = lo.rolling(50, min_periods=1).min()
        conv = (h9 + l9) / 2; base = (h20 + l20) / 2
        g["Tenkan"] = conv.round(2)
        g["Kijun"] = base.round(2)
        g["Senkou_Span_A"] = ((conv + base) / 2).shift(20).round(2)
        g["Senkou_Span_B"] = ((h50 + l50) / 2).shift(20).round(2)

        mom = c - c.shift(20)
        rsi = g["RSI_14"]
        div_list = []; sp = None
        for i in range(len(g)):
            rv = rsi.iloc[i]; mv = mom.iloc[i]; pv = c.iloc[i]
            if pd.isna(rv) or pd.isna(mv):
                div_list.append("")
            elif rv < 30 and mv > 0:
                sp = pv; div_list.append("Bullish Start")
            elif sp is not None and rv < 30 and mv < 0:
                div_list.append(f"Bullish End ({sp:.0f}->{pv:.0f})"); sp = None
            elif rv > 70 and mv < 0:
                sp = pv; div_list.append("Bearish Start")
            elif sp is not None and rv > 70 and mv > 0:
                div_list.append(f"Bearish End ({sp:.0f}->{pv:.0f})"); sp = None
            else:
                div_list.append("")
        g["Knoxville_Divergence"] = div_list

        g["gain"] = c.pct_change().mul(100).round(2)
        g["up_20"] = (c > g["SMA_22"]).astype(int)

        up_true = []
        for i in range(len(g)):
            if i < 3:
                up_true.append(0); continue
            c0 = c.iloc[i]; c1 = c.iloc[i - 1]; c2 = c.iloc[i - 2]; c3 = c.iloc[i - 3]
            if pd.isna(c0) or pd.isna(c3):
                up_true.append(0); continue
            if c0 > c1 and c1 > c2 and c2 > c3:
                cr = ((c0 - c3) / c3) * 100 if c3 > 0 else 0
                up_true.append(1 if cr >= 20 else 0)
            else:
                up_true.append(0)
        g["up_true"] = up_true

        frames.append(g)
    return pd.concat(frames, ignore_index=True)


def extend_future(df):
    ld = pd.to_datetime(TODAY_STR)
    fd = pd.date_range(start=ld + BDay(1), periods=FUTURE_DAYS, freq=BDay())
    tickers = df["Ticker"].unique()
    fr = pd.DataFrame([(d.strftime("%Y-%m-%d"), t) for t in tickers for d in fd], columns=["Date", "Ticker"])
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        fr[col] = np.nan
    combined = pd.concat([df, fr], ignore_index=True)
    return combined.drop_duplicates(subset=["Ticker", "Date"], keep="first").sort_values(["Ticker", "Date"]).reset_index(drop=True)


def run():
    tickers = load_tickers(); total = len(tickers)
    print(f"Tickers: {total}")

    existing_df = None; force_recompute = False
    if os.path.exists(STOCK_DATA_FILE):
        try:
            existing_df = pd.read_csv(STOCK_DATA_FILE)
            latest = sorted(existing_df["Date"].unique())[-1] if len(existing_df) > 0 else None
            print(f"Existing: {len(existing_df)} rows | Latest: {latest} | Cols: {len(existing_df.columns)}")
            missing_cols = [c for c in REQUIRED_COLUMNS if c not in existing_df.columns]
            if missing_cols:
                print(f"Missing columns: {missing_cols} -> Force full recompute")
                force_recompute = True
                existing_df = None
            elif latest == TODAY_STR:
                print("Today exists with all columns. Skipping."); return
            else:
                fetch_days = 10; print(f"Append mode: {fetch_days} days")
        except:
            existing_df = None

    if existing_df is None:
        fetch_days = LOOKBACK_DAYS
        print(f"{'Force recompute' if force_recompute else 'Fresh download'}: {fetch_days} days")

    print("-" * 90)

    all_data = []; fundamentals = {}; success = 0; failed = 0
    for idx, ticker in enumerate(tickers, 1):
        print(f"[{idx:3d}/{total}] {ticker}...", end=" ")
        df, info = download_ticker_data(ticker, fetch_days)
        if df is not None and len(df) > 0:
            all_data.append(df)
            fundamentals[ticker] = info if info else {}
            mc = f" MCap:{info.get('Market_Cap', '-')}" if info.get("Market_Cap") else ""
            ind = f" [{info.get('Industry', '')}]" if info.get("Industry") else ""
            print(f"{len(df)} rows{mc}{ind}")
            success += 1
        else:
            print("no data"); failed += 1
        if idx % 10 == 0:
            time.sleep(1)

    if not all_data:
        print("No data!"); return

    new_df = pd.concat(all_data, ignore_index=True)
    new_df["Market_Cap"] = new_df["Ticker"].map(lambda t: fundamentals.get(t, {}).get("Market_Cap"))
    new_df["Debt_Eq"] = new_df["Ticker"].map(lambda t: fundamentals.get(t, {}).get("Debt_Eq"))

    # ── FIX: Sanitize Industry — no more 'nan' strings in CSV ──
    new_df["Industry"] = new_df["Ticker"].map(
        lambda t: sanitize_str(fundamentals.get(t, {}).get("Industry")))

    if existing_df is not None and not force_recompute:
        # Also sanitize existing Industry column
        if "Industry" in existing_df.columns:
            existing_df["Industry"] = existing_df["Industry"].apply(sanitize_str)

        combined = pd.concat([existing_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["Ticker", "Date"], keep="last")
        keep = ["Ticker", "Date", "Open", "High", "Low", "Close", "Volume", "Market_Cap", "Debt_Eq", "Industry"]
        combined = combined[[c for c in keep if c in combined.columns]]
        raw_df = combined
    else:
        raw_df = new_df

    raw_df = raw_df.sort_values(["Ticker", "Date"]).reset_index(drop=True)

    print("\nExtending +26 future days & computing all indicators...")
    extended = extend_future(raw_df)
    final = compute_all_indicators(extended)

    nc = final.select_dtypes(include=[np.number]).columns
    final[nc] = final[nc].round(2)

    # ── FIX: Replace NaN/None with empty string for string columns before writing CSV ──
    str_cols = ["BB_Flag", "Knoxville_Divergence", "Industry"]
    for col in str_cols:
        if col in final.columns:
            final[col] = final[col].apply(sanitize_str)

    col_order = ["Ticker", "Date", "Open", "High", "Low", "Close", "Volume",
                 "Market_Cap", "Debt_Eq", "Industry", "index",
                 "SMA_9", "SMA_22", "STD_22", "SMA_50", "SMA_52", "SMA_200",
                 "RSI_14", "BB_Upper", "BB_Middle", "BB_Lower", "BB_Flag",
                 "VWAP", "Tenkan", "Kijun", "Senkou_Span_A", "Senkou_Span_B",
                 "Knoxville_Divergence", "gain", "up_20", "up_true"]
    final = final[[c for c in col_order if c in final.columns]]
    final.to_csv(STOCK_DATA_FILE, index=False)

    actual = final.dropna(subset=["Close"])
    ld2 = actual["Date"].max()
    burst = actual[actual["Date"] == ld2]
    bt = burst[burst["up_true"] == 1]["Ticker"].tolist()

    # Industry stats
    ind_col = final[final["Date"] == ld2]["Industry"] if "Industry" in final.columns else pd.Series()
    ind_valid = ind_col[ind_col != ""].nunique() if len(ind_col) > 0 else 0

    print("-" * 90)
    print(f"stock_data.csv: {len(final)} rows | {final['Ticker'].nunique()} tickers | {final['Date'].nunique()} dates | {len([c for c in col_order if c in final.columns])} columns")
    print(f"Success: {success} | Failed: {failed} | Industries: {ind_valid} unique")
    if bt:
        print(f"FII/DII BURST (up_true=1): {', '.join(bt)}")
    else:
        print("FII/DII Burst: None today")
    print("=" * 90)


if __name__ == "__main__":
    run()
