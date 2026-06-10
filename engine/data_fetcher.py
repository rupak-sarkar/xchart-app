"""
data_fetcher.py – v7.4 Smart Data Sync for xchart-app
"""

import os, sys, time, math
from datetime import datetime, timedelta, date
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────
DATA_DIR    = Path(".")
DATA_FILE   = DATA_DIR / "stock_data.csv"
TICKER_FILE = DATA_DIR / "tickers.csv"

BATCH_SIZE      = 20
LOOKBACK_DAYS   = 500   # initial download window
MCAP_THRESHOLD  = 10000

KEY_COLUMNS = [
    "Ticker", "Date", "Open", "High", "Low", "Close", "Volume",
    "RSI", "MACD", "MACD_Signal", "SMA_9", "SMA_22", "SMA_200",
    "EMA_9", "EMA_21", "BB_Upper", "BB_Lower", "ADX",
    "SuperTrend", "ATR_Pct", "Market_Cap",
]


# ── Helpers ───────────────────────────────────────────────────────────────

def _load_tickers():
    """Load ticker list from tickers.csv."""
    if not TICKER_FILE.exists():
        print(f"  ERROR: {TICKER_FILE} not found!")
        return []
    tdf = pd.read_csv(TICKER_FILE)
    tickers = sorted(set(str(t).strip() for t in tdf["Ticker"].dropna() if str(t).strip()))
    return tickers


def _yf_symbol(ticker):
    """Convert ticker to Yahoo Finance NSE symbol."""
    tk = str(ticker).strip()
    if not tk.endswith(".NS") and not tk.endswith(".BO"):
        return tk + ".NS"
    return tk


def _batch_download(symbols, start, end, batch_label=""):
    """Download OHLCV for a batch of symbols via yfinance."""
    import yfinance as yf

    if not symbols:
        return pd.DataFrame()

    syms = [_yf_symbol(s) for s in symbols]
    sym_str = " ".join(syms)

    try:
        raw = yf.download(sym_str, start=start, end=end,
                          group_by="ticker", auto_adjust=True,
                          threads=True, progress=False)
    except Exception as e:
        print(f"  [WARN] batch download failed: {e}")
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    rows = []
    for orig_tk, yf_sym in zip(symbols, syms):
        try:
            if len(symbols) == 1:
                df_tk = raw.copy()
            else:
                if yf_sym in raw.columns.get_level_values(0):
                    df_tk = raw[yf_sym].copy()
                else:
                    continue

            if df_tk.empty:
                continue

            df_tk = df_tk.dropna(subset=["Close"])
            if df_tk.empty:
                continue

            for dt, row in df_tk.iterrows():
                rows.append({
                    "Ticker": orig_tk,
                    "Date": str(dt.date()),
                    "Open": round(float(row.get("Open", 0) or 0), 2),
                    "High": round(float(row.get("High", 0) or 0), 2),
                    "Low": round(float(row.get("Low", 0) or 0), 2),
                    "Close": round(float(row.get("Close", 0) or 0), 2),
                    "Volume": int(row.get("Volume", 0) or 0),
                })
        except Exception as e:
            pass

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _fetch_fundamentals(tickers, batch_size=20):
    """Fetch fundamental data (Market_Cap, PE, PB, ROE, etc.) from yfinance."""
    import yfinance as yf

    results = {}
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]

    for bi, batch in enumerate(batches):
        batch_names = "..".join([batch[0], batch[-1]]) if len(batch) > 1 else batch[0]
        print(f"    Batch {bi + 1}/{len(batches)}: {batch_names}")

        for tk in batch:
            try:
                info = yf.Ticker(_yf_symbol(tk)).info
                results[tk] = {
                    "Market_Cap": info.get("marketCap", 0) or 0,
                    "PE": info.get("trailingPE", 0) or 0,
                    "PB": info.get("priceToBook", 0) or 0,
                    "ROE": (info.get("returnOnEquity", 0) or 0) * 100,
                    "Dividend_Yield": (info.get("dividendYield", 0) or 0) * 100,
                    "Debt_Equity": info.get("debtToEquity", 0) or 0,
                    "Sector": info.get("sector", ""),
                    "Sub_Industry": info.get("industry", ""),
                }
            except Exception:
                pass

        time.sleep(0.5)

    return results


# ── Smart Sync ────────────────────────────────────────────────────────────

def smart_sync():
    """
    Smart data sync:
    - Compare tickers wanted (tickers.csv) vs data on disk (stock_data.csv)
    - Download new tickers from scratch
    - Update existing tickers incrementally
    - Remove tickers no longer wanted
    - Fetch fundamentals for tickers missing Market_Cap
    """
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    print(f"Smart Data Sync | {today_str}")
    print("=" * 80)

    wanted = _load_tickers()
    if not wanted:
        print("  No tickers found in tickers.csv!")
        return

    # ── Load existing data ──
    existing_tickers = set()
    stock_df = pd.DataFrame()
    if DATA_FILE.exists():
        stock_df = pd.read_csv(DATA_FILE)
        if "Ticker" in stock_df.columns:
            stock_df["Ticker"] = stock_df["Ticker"].astype(str).str.strip()
            existing_tickers = set(stock_df["Ticker"].unique())

    wanted_set = set(wanted)
    new_tickers = sorted(wanted_set - existing_tickers)
    removed_tickers = sorted(existing_tickers - wanted_set)
    kept_tickers = sorted(wanted_set & existing_tickers)

    print(f"\n  Tickers wanted:   {len(wanted)}")
    print(f"  Tickers in data:  {len(existing_tickers)}")
    print(f"  New tickers:      {len(new_tickers)}")
    print(f"  Removed tickers:  {len(removed_tickers)}")
    print(f"  Kept tickers:     {len(kept_tickers)}")

    # ── Remove tickers no longer wanted ──
    if removed_tickers and not stock_df.empty:
        stock_df = stock_df[stock_df["Ticker"].isin(wanted_set)]

    print(f"  Loaded stock_data.csv: {len(stock_df)} rows, {stock_df['Ticker'].nunique() if not stock_df.empty else 0} tickers")

    # ── Download new tickers ──
    if new_tickers:
        start_date = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        end_date = today_str
        print(f"\n  Downloading {len(new_tickers)} new tickers ({start_date} → {end_date})...")

        batches = [new_tickers[i:i + BATCH_SIZE] for i in range(0, len(new_tickers), BATCH_SIZE)]
        new_frames = []
        for bi, batch in enumerate(batches):
            preview = ", ".join(batch[:5])
            if len(batch) > 5:
                preview += "..."
            print(f"  [NEW] Batch {bi + 1}/{len(batches)}: {preview}")
            df_batch = _batch_download(batch, start_date, end_date)
            if not df_batch.empty:
                new_frames.append(df_batch)
            time.sleep(1)

        if new_frames:
            new_df = pd.concat(new_frames, ignore_index=True)
            print(f"    → {len(new_df)} new rows fetched for {new_df['Ticker'].nunique()} tickers")
            stock_df = pd.concat([stock_df, new_df], ignore_index=True)

    # ── Update existing tickers ──
    update_tickers = sorted(wanted_set & existing_tickers) if not stock_df.empty else []
    if update_tickers and not stock_df.empty:
        # Find last date in data
        stock_df["Date"] = stock_df["Date"].astype(str).str[:10]
        last_dates = stock_df.groupby("Ticker")["Date"].max()
        global_last = stock_df["Date"].max()

        start_update = (datetime.strptime(global_last, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") if global_last else today_str
        end_update = today_str

        if start_update <= end_update:
            print(f"\n  Updating {len(update_tickers)}/{len(wanted)} existing tickers ({global_last} → {end_update})...")

            batches = [update_tickers[i:i + BATCH_SIZE] for i in range(0, len(update_tickers), BATCH_SIZE)]
            update_frames = []
            for bi, batch in enumerate(batches):
                preview = ", ".join(batch[:5])
                if len(batch) > 5:
                    preview += "..."
                print(f"  [UPDATE] Batch {bi + 1}/{len(batches)}: {preview}")
                df_batch = _batch_download(batch, start_update, end_update)
                if not df_batch.empty:
                    update_frames.append(df_batch)
                time.sleep(1)

            if update_frames:
                update_df = pd.concat(update_frames, ignore_index=True)
                total_new = len(update_df)
                print(f"    → {total_new} new rows fetched")

                # Remove duplicates (same ticker + date)
                stock_df = pd.concat([stock_df, update_df], ignore_index=True)
                stock_df = stock_df.drop_duplicates(subset=["Ticker", "Date"], keep="last")
        else:
            print(f"\n  Data already up to date ({global_last})")

    # ── Sort and save ──
    if not stock_df.empty:
        stock_df = stock_df.sort_values(["Ticker", "Date"]).reset_index(drop=True)
        n_tickers = stock_df["Ticker"].nunique()
        avg_days = len(stock_df) // n_tickers if n_tickers else 0

        stock_df.to_csv(DATA_FILE, index=False)
        print(f"\n  ✅ Saved stock_data.csv: {len(stock_df):,} rows, {n_tickers} tickers (~{avg_days} days/ticker)")

    # ── Validate freshness ──
    _validate_freshness()
    print("=" * 80)


def _validate_freshness():
    """Check if data is reasonably fresh."""
    if not DATA_FILE.exists():
        print("  ❌ No data file found!")
        return False

    df = pd.read_csv(DATA_FILE)
    if df.empty or "Date" not in df.columns:
        print("  ❌ Data file is empty!")
        return False

    latest = df["Date"].astype(str).str[:10].max()
    today = date.today().strftime("%Y-%m-%d")

    # Allow 3-day gap (weekends/holidays)
    latest_dt = datetime.strptime(latest, "%Y-%m-%d").date()
    gap = (date.today() - latest_dt).days

    if gap <= 3:
        print(f"  ✅ Data fresh — latest: {latest}")
        return True
    else:
        print(f"  ⚠️  Data may be stale — latest: {latest} ({gap} days ago)")
        return False


# ── Load helpers (used by other modules) ──────────────────────────────────

def load_stock_data(data_file=None, mcap_threshold=MCAP_THRESHOLD):
    """Load stock_data.csv and return DataFrame + metadata."""
    fpath = data_file or DATA_FILE
    if not Path(fpath).exists():
        print(f"  ERROR: {fpath} not found!")
        return pd.DataFrame(), [], 0

    df = pd.read_csv(fpath, low_memory=False)
    if df.empty:
        return pd.DataFrame(), [], 0

    df["Ticker"] = df["Ticker"].astype(str).str.strip()
    tickers = sorted(df["Ticker"].unique())

    found_cols = [c for c in KEY_COLUMNS if c in df.columns]
    print(f"  -> Loaded {fpath}: {len(tickers)} tickers, {len(df):,} rows (~{len(df)//len(tickers) if tickers else 0} days/ticker)")
    print(f"  -> Found: {len(found_cols)}/{len(KEY_COLUMNS)} key columns")
    print(f"  -> MCap threshold: {mcap_threshold}")

    return df, tickers, mcap_threshold


def detect_mcap_scale(df):
    """Detect market cap scale (crores vs raw)."""
    if df.empty or "Market_Cap" not in df.columns:
        return 1

    mcaps = df.groupby("Ticker")["Market_Cap"].last().dropna()
    if mcaps.empty:
        return 1

    median = mcaps.median()
    if median > 1e10:
        return 1e7  # raw → crores
    return 1


def get_sector_from_stock_data(df, ticker):
    """Get sector for a ticker from stock_data columns."""
    tdf = df[df["Ticker"].astype(str).str.strip() == str(ticker).strip()]
    if tdf.empty:
        return "Other"
    sec = str(tdf.iloc[-1].get("Sector", "")).strip()
    if sec and sec not in ("", "nan", "0", "None"):
        return sec
    return "Other"


def get_broad_sector(sector_str):
    """Map detailed sector/industry to broad sector."""
    if not sector_str or sector_str in ("Other", "nan", "0", ""):
        return "Other"

    s = str(sector_str).lower()

    mapping = {
        "technology": "IT", "software": "IT", "information": "IT",
        "financial": "BFSI", "bank": "BFSI", "insurance": "BFSI", "nbfc": "BFSI",
        "pharma": "Pharma", "health": "Pharma", "drug": "Pharma",
        "auto": "Auto", "vehicle": "Auto", "motor": "Auto",
        "fmcg": "FMCG", "consumer": "FMCG", "food": "FMCG", "beverag": "FMCG",
        "energy": "Energy", "oil": "Energy", "gas": "Energy", "power": "Energy",
        "metal": "Metals", "mining": "Metals", "steel": "Metals",
        "infra": "Infra", "construct": "Infra", "cement": "Infra", "real estate": "Infra",
        "telecom": "Telecom", "media": "Telecom",
        "chem": "Chemicals", "fertil": "Chemicals",
        "capital": "CapGoods", "industrial": "CapGoods", "engineer": "CapGoods",
    }

    for keyword, broad in mapping.items():
        if keyword in s:
            return broad

    return "Other"


# ── Backward compatibility ────────────────────────────────────────────────
ensure_data_exists = smart_sync
