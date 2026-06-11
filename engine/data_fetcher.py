"""
data_fetcher.py  – v7.4  Smart Data Sync for xchart-app
"""
import os, time, math
from datetime import datetime, timedelta, date
from pathlib import Path
import numpy as np, pandas as pd

DATA_DIR     = Path(".")
DATA_FILE    = DATA_DIR / "output/stock_data.csv"
TICKER_FILE  = DATA_DIR / "output/tickers.csv"
BATCH_SIZE   = 20
LOOKBACK_DAYS= 500
MCAP_THRESHOLD=10000
KEY_COLUMNS  = ["Ticker","Date","Open","High","Low","Close","Volume",
                "RSI","MACD","MACD_Signal","SMA_9","SMA_22","SMA_200",
                "EMA_9","EMA_21","BB_Upper","BB_Lower","ADX",
                "SuperTrend","ATR_Pct","Market_Cap"]

def _load_tickers():
    if not TICKER_FILE.exists(): print(f"  ERROR: {TICKER_FILE} not found!"); return []
    tdf=pd.read_csv(TICKER_FILE)
    return sorted(set(str(t).strip() for t in tdf["Ticker"].dropna() if str(t).strip()))

def _yf_symbol(tk):
    tk=str(tk).strip()
    return tk if tk.endswith(".NS") or tk.endswith(".BO") else tk+".NS"

def _batch_download(symbols,start,end,label=""):
    import yfinance as yf
    if not symbols: return pd.DataFrame()
    syms=[_yf_symbol(s) for s in symbols]
    try: raw=yf.download(" ".join(syms),start=start,end=end,group_by="ticker",auto_adjust=True,threads=True,progress=False)
    except Exception as e: print(f"  [WARN] batch failed: {e}"); return pd.DataFrame()
    if raw.empty: return pd.DataFrame()
    rows=[]
    for otk,ysm in zip(symbols,syms):
        try:
            df_tk=raw.copy() if len(symbols)==1 else (raw[ysm].copy() if ysm in raw.columns.get_level_values(0) else None)
            if df_tk is None or df_tk.empty: continue
            df_tk=df_tk.dropna(subset=["Close"])
            for dt,r in df_tk.iterrows():
                rows.append({"Ticker":otk,"Date":str(dt.date()),
                  "Open":round(float(r.get("Open",0) or 0),2),"High":round(float(r.get("High",0) or 0),2),
                  "Low":round(float(r.get("Low",0) or 0),2),"Close":round(float(r.get("Close",0) or 0),2),
                  "Volume":int(r.get("Volume",0) or 0)})
        except: pass
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def smart_sync():
    today=date.today(); ts=today.strftime("%Y-%m-%d")
    # ── CRITICAL FIX: yfinance end date is EXCLUSIVE ──
    end_str=(today+timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Smart Data Sync | {ts}"); print("="*80)
    wanted=_load_tickers()
    if not wanted: print("  No tickers!"); return
    existing=set(); stock_df=pd.DataFrame()
    if DATA_FILE.exists():
        stock_df=pd.read_csv(DATA_FILE,low_memory=False)
        if "Ticker" in stock_df.columns:
            stock_df["Ticker"]=stock_df["Ticker"].astype(str).str.strip()
            existing=set(stock_df["Ticker"].unique())
    ws=set(wanted); new_tk=sorted(ws-existing); rem=sorted(existing-ws); kept=sorted(ws&existing)
    print(f"\n  Tickers wanted:   {len(wanted)}\n  Tickers in data:  {len(existing)}")
    print(f"  New tickers:      {len(new_tk)}\n  Removed tickers:  {len(rem)}\n  Kept tickers:     {len(kept)}")
    if rem and not stock_df.empty: stock_df=stock_df[stock_df["Ticker"].isin(ws)]
    print(f"  Loaded stock_data.csv: {len(stock_df)} rows, {stock_df['Ticker'].nunique() if not stock_df.empty else 0} tickers")
    # ── New tickers ──
    if new_tk:
        sd=(today-timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        print(f"\n  Downloading {len(new_tk)} new tickers ({sd} -> {end_str})...")
        nf=[]
        for bi in range(0,len(new_tk),BATCH_SIZE):
            b=new_tk[bi:bi+BATCH_SIZE]; pv=", ".join(b[:5])+("..." if len(b)>5 else "")
            print(f"  [NEW] Batch {bi//BATCH_SIZE+1}/{math.ceil(len(new_tk)/BATCH_SIZE)}: {pv}")
            df_b=_batch_download(b,sd,end_str)
            if not df_b.empty: nf.append(df_b)
            time.sleep(1)
        if nf:
            nd=pd.concat(nf,ignore_index=True)
            print(f"    -> {len(nd)} new rows for {nd['Ticker'].nunique()} tickers")
            stock_df=pd.concat([stock_df,nd],ignore_index=True)
    # ── Update existing ──
    utk=sorted(ws&existing) if not stock_df.empty else []
    if utk and not stock_df.empty:
        stock_df["Date"]=stock_df["Date"].astype(str).str[:10]
        gl=stock_df["Date"].max()
        su=(datetime.strptime(gl,"%Y-%m-%d")+timedelta(days=1)).strftime("%Y-%m-%d")
        # ╔══════════════════════════════════════════════════════════════╗
        # ║  FIX: changed  su <= end_str  →  su < end_str             ║
        # ║  When data is already fresh (last_date == today),          ║
        # ║  su == end_str == tomorrow, so the old <= allowed a        ║
        # ║  zero-range download (tomorrow→tomorrow) causing 158       ║
        # ║  false "possibly delisted" errors.                         ║
        # ╚══════════════════════════════════════════════════════════════╝
        if su < end_str:
            print(f"\n  Updating {len(utk)}/{len(wanted)} existing tickers ({gl} -> {ts})...")
            uf=[]
            for bi in range(0,len(utk),BATCH_SIZE):
                b=utk[bi:bi+BATCH_SIZE]; pv=", ".join(b[:5])+("..." if len(b)>5 else "")
                print(f"  [UPDATE] Batch {bi//BATCH_SIZE+1}/{-(-len(utk)//BATCH_SIZE)}: {pv}")
                df_b=_batch_download(b,su,end_str)
                if not df_b.empty: uf.append(df_b)
                time.sleep(1)
            if uf:
                ud=pd.concat(uf,ignore_index=True)
                print(f"    -> {len(ud)} new rows fetched")
                stock_df=pd.concat([stock_df,ud],ignore_index=True)
                stock_df=stock_df.drop_duplicates(subset=["Ticker","Date"],keep="last")
        else: print(f"\n  ⏭️  Data already up to date ({gl}). Skipping download.")
    if not stock_df.empty:
        stock_df=stock_df.sort_values(["Ticker","Date"]).reset_index(drop=True)
        nt=stock_df["Ticker"].nunique(); ad=len(stock_df)//nt if nt else 0
        stock_df.to_csv(DATA_FILE,index=False)
        print(f"\n  Saved stock_data.csv: {len(stock_df):,} rows, {nt} tickers (~{ad} days/ticker)")
    _validate_freshness(); print("="*80)

def _validate_freshness():
    if not DATA_FILE.exists(): print("  No data file!"); return False
    df=pd.read_csv(DATA_FILE,low_memory=False)
    if df.empty or "Date" not in df.columns: print("  Data empty!"); return False
    latest=df["Date"].astype(str).str[:10].max()
    gap=(date.today()-datetime.strptime(latest,"%Y-%m-%d").date()).days
    if gap<=3: print(f"  Data fresh - latest: {latest}"); return True
    else: print(f"  Data may be stale - latest: {latest} ({gap}d ago)"); return False

def load_stock_data(data_file=None,mcap_threshold=MCAP_THRESHOLD):
    fp=data_file or DATA_FILE
    if not Path(fp).exists(): return pd.DataFrame(),[],0
    df=pd.read_csv(fp,low_memory=False); df["Ticker"]=df["Ticker"].astype(str).str.strip()
    tickers=sorted(df["Ticker"].unique())
    print(f"  -> Loaded {fp}: {len(tickers)} tickers, {len(df):,} rows")
    return df,tickers,mcap_threshold

def detect_mcap_scale(df):
    if df.empty or "Market_Cap" not in df.columns: return 1
    m=df.groupby("Ticker")["Market_Cap"].last().dropna().median()
    return 1e7 if m>1e10 else 1

def get_broad_sector(s):
    if not s or s in ("Other","nan","0",""): return "Other"
    s=str(s).lower()
    for kw,br in {"technology":"IT","software":"IT","financial":"BFSI","bank":"BFSI","pharma":"Pharma",
      "auto":"Auto","fmcg":"FMCG","consumer":"FMCG","energy":"Energy","oil":"Energy","power":"Energy",
      "metal":"Metals","infra":"Infra","cement":"Infra","telecom":"Telecom","chem":"Chemicals","capital":"CapGoods"}.items():
        if kw in s: return br
    return "Other"

ensure_data_exists=smart_sync
