#!/usr/bin/env python3
"""
app.py  –  xChart ANALYTICAL Engine v7.4
"""

import os, sys, json, re, time, math, traceback
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

# ── Engine imports ────────────────────────────────────────────────────────
from engine.data_fetcher import smart_sync
from engine.create_stock_data import recompute_indicators
from engine.news import build_news_cache

from engine.accuracy import (
    compute_per_ticker_accuracy, print_accuracy_report,
    ENTRY_THRESHOLD_LC, ENTRY_THRESHOLD_SC,
    EXIT_THRESHOLD_LC, EXIT_THRESHOLD_SC,
    HORIZONS, HOLD_DAYS, SL_FIXED,
)
from engine.tech_v8 import compute_tech_scores, compute_composites, fix_chart_markers, get_v8_latest_scores

STOP_LOSS_PCT = SL_FIXED

# ── Paths ─────────────────────────────────────────────────────────────────
DATA_DIR     = Path(".")
DATA_FILE    = DATA_DIR / "output/stock_data.csv"
TICKER_FILE  = DATA_DIR / "output/tickers.csv"
HISTORY_FILE = DATA_DIR / "output/history.csv"
OUTPUT_CSV   = DATA_DIR / "output/data.csv"
META_JSON    = DATA_DIR / "output/meta.json"
CHARTS_DIR   = DATA_DIR / "charts"

# ── Constants ─────────────────────────────────────────────────────────────
VERSION          = "7.4"
MCAP_THRESHOLD   = 10000          # in crores
NEWS_WINDOW_DAYS = 3
MAX_CATALYSTS    = 20
FINBERT_MODEL    = "ProsusAI/finbert"

TECH_WEIGHT  = 0.65
MACRO_WEIGHT = 0.16
FUND_WEIGHT  = 0.11
NEWS_WEIGHT  = 0.10

REPORTING_KW = re.compile(
    r"\b(quarter|q[1-4]|result|earning|profit|revenue|net income|ebitda|eps|"
    r"annual report|financial result|interim dividend|board meeting)\b", re.I
)
NSE_NOISE_KW = re.compile(
    r"\b(trading window|closure of|loss of share|duplicate share|"
    r"complian|annual general|postal ballot|record date|book closure|"
    r"change in address|change in name|alteration|amalgamation|"
    r"scheme of arrangement|preferential issue)\b", re.I
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _col(row, *names, default=0):
    """Get first non-NaN value from multiple possible column names."""
    for n in names:
        v = row.get(n)
        if v is not None:
            try:
                fv = float(v)
                if not math.isnan(fv):
                    return fv
            except (ValueError, TypeError):
                pass
    return default


def _col_df(df, *names):
    """Get first available column from a DataFrame."""
    for n in names:
        if n in df.columns:
            return df[n].astype(float).fillna(0)
    return pd.Series(0, index=df.index)


def classify_cap(mcap, threshold=MCAP_THRESHOLD):
    if mcap >= threshold * 10:
        return "MEGA"
    elif mcap >= threshold * 2:
        return "LARGE"
    elif mcap >= threshold * 0.5:
        return "MID"
    return "SMALL"


def is_hit(pred_dir, actual_dir):
    if pred_dir == 0:
        return None
    if actual_dir == 0:
        return True
    return pred_dir == actual_dir


# ── Ticker Loading ────────────────────────────────────────────────────────

def load_tickers():
    tdf = pd.read_csv(TICKER_FILE)
    tickers = [str(t).strip() for t in tdf["Ticker"].dropna().unique()]
    sector_map = {}
    if "Sector" in tdf.columns:
        for _, row in tdf.iterrows():
            tk = str(row["Ticker"]).strip()
            sec = str(row.get("Sector", "")).strip()
            if sec and sec not in ("", "nan", "0", "Other"):
                sector_map[tk] = sec
    print(f"Loaded {len(tickers)} tickers from tickers.csv (sector map: {len(sector_map)} entries)")
    return tickers, sector_map


# ── FinBERT ───────────────────────────────────────────────────────────────


def init_finbert():
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    print("Initializing FinBERT...")
    try:
        tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
        model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)
        model.eval()
        return tokenizer, model
    except Exception as e:
        print(f"  WARNING: FinBERT load failed: {e}")
        print(f"  -> News scoring will be skipped this run")
        return None, None




def score_headlines(headlines, tokenizer, model):
    import torch
    if not headlines: return 0.0, 0
    scores = []
    for h in headlines[:MAX_CATALYSTS]:
        inputs = tokenizer(h, return_tensors="pt", truncation=True, max_length=128, padding=True)
        with torch.no_grad():
            outputs = model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
        score = (probs[0].item() - probs[1].item()) * 100
        scores.append(score)
    if not scores: return 0.0, 0
    avg = np.mean(scores)
    direction = 1 if avg > 10 else (-1 if avg < -10 else 0)
    return round(avg, 1), direction



def run_finbert_phase(ticker_articles, tickers, stock_df, history_df):
    if not ticker_articles:
        return {}
    tokenizer, model = init_finbert()
    if tokenizer is None or model is None:
        print("  -> Skipping FinBERT phase (model unavailable)")
        return {}
    results = {}
    idx = 0
    for tk in tickers:
        if tk not in ticker_articles:
            continue
        articles = ticker_articles[tk]
        if not articles:
            continue
        idx += 1
        headlines = [a["title"] for a in articles]
        score, direction = score_headlines(headlines, tokenizer, model)
        ret_str = ""
        hit_str = ""
        if history_df is not None and len(history_df) > 0:
            hrows = history_df[history_df["Ticker"].astype(str).str.strip() == tk]
            if not hrows.empty:
                last = hrows.iloc[-1]
                act_ret = float(last.get("Actual_Return_Pct", 0) or 0)
                last_dir = int(last.get("Momentum_Direction", 0) or 0)
                ret_str = f" Ret: {act_ret:+.2f}%"
                if last_dir != 0:
                    was_hit = "HIT" if is_hit(last_dir, 1 if act_ret > 0 else (-1 if act_ret < 0 else 0)) else "MISS"
                    hit_str = f" {was_hit}"
        dir_label = "POSITIVE" if direction == 1 else ("NEGATIVE" if direction == -1 else "NEUTRAL")
        print(f"[{idx:>3d}] {tk:<18s} {dir_label} Score: {score:+.1f}{ret_str}{hit_str} [{len(headlines)}cat/{len(headlines)}h]")
        results[tk] = {
            "News_Score": score,
            "News_Sentiment": dir_label,
            "N_Catalysts": len(headlines),
            "headlines": headlines[:5],
        }
    n_scored = sum(1 for v in results.values() if v["N_Catalysts"] > 0)
    print(f"\n  Catalysts: {n_scored} scored")
    return results




# ── Technical Scoring ─────────────────────────────────────────────────────

def compute_tech_score(row, cat, prev_row=None):
    score = 0
    is_lc = cat in ("MEGA", "LARGE")
    close  = _col(row, "Close")
    rsi    = _col(row, "RSI_14", "RSI", default=50)
    sma9   = _col(row, "SMA_9")
    sma22  = _col(row, "SMA_22")
    sma200 = _col(row, "SMA_200")
    ema9   = _col(row, "EMA_9")
    ema21  = _col(row, "EMA_21")
    macd   = _col(row, "MACD_Line", "MACD")
    macd_s = _col(row, "MACD_Signal")
    adx    = _col(row, "ADX_14", "ADX")
    bb_u   = _col(row, "BB_Upper")
    bb_l   = _col(row, "BB_Lower")
    st     = _col(row, "ST_Value")
    sma9_prev = _col(prev_row, "SMA_9") if prev_row is not None else None
    if close == 0: return 0

    if is_lc:
        if sma9_prev is not None and sma9 > 0 and sma9_prev > 0:
            if sma9 > sma9_prev and close > sma9: score += 15
            elif sma9 < sma9_prev and close < sma9: score -= 15
        if close > sma22 > 0: score += 5
        elif close < sma22 > 0: score -= 5
        if close > sma200 > 0: score += 3
        elif close < sma200 > 0: score -= 3
        if rsi > 70: score -= 5
        elif rsi < 30: score += 5
        if macd > macd_s: score += 3
        elif macd < macd_s: score -= 3
        if adx > 25:
            if close > sma9 > 0: score += 4
            elif close < sma9 > 0: score -= 4
        if st > 0 and close > st: score += 3
        elif st > 0 and close < st: score -= 3
    else:
        if bb_l > 0 and bb_u > 0:
            bb_range = bb_u - bb_l
            if bb_range > 0:
                bb_pos = (close - bb_l) / bb_range
                if bb_pos < 0.1: score += 20
                elif bb_pos < 0.25: score += 12
                elif bb_pos > 0.9: score -= 20
                elif bb_pos > 0.75: score -= 12
        if rsi < 25: score += 10
        elif rsi < 35: score += 5
        elif rsi > 75: score -= 10
        elif rsi > 65: score -= 5
        if ema9 > ema21 > 0: score += 5
        elif ema9 < ema21 > 0: score -= 5
        if st > 0 and close > st: score += 4
        elif st > 0 and close < st: score -= 4
        if macd > macd_s: score += 3
        elif macd < macd_s: score -= 3
    return score


# ── Fundamental Scoring ───────────────────────────────────────────────────

def compute_fund_score(row):
    score = 0
    pe  = _col(row, "PE_Ratio", "PE")
    pb  = _col(row, "PB_Ratio", "PB")
    roe = _col(row, "ROE")
    dy  = _col(row, "Dividend_Yield")
    de  = _col(row, "Debt_to_Equity", "Debt_Equity")
    if 0 < pe < 15: score += 5
    elif 15 <= pe < 25: score += 2
    elif pe > 50: score -= 3
    if 0 < pb < 2: score += 3
    elif pb > 5: score -= 2
    if roe > 20: score += 5
    elif roe > 12: score += 2
    elif 0 < roe < 5: score -= 2
    if dy > 3: score += 3
    elif dy > 1: score += 1
    if 0 < de < 0.5: score += 2
    elif de > 2: score -= 3
    return score


# ── Market Regime ─────────────────────────────────────────────────────────

def compute_market_regime(stock_df):
    latest = stock_df.groupby("Ticker").tail(1)
    if latest.empty: return "CHOPPY", 50, 0
    above = 0; total = 0
    for _, row in latest.iterrows():
        c = _col(row, "Close"); s = _col(row, "SMA_22")
        if c > 0 and s > 0: total += 1; above += (1 if c > s else 0)
    breadth = int(above / total * 100) if total else 50
    nifty_5d = 0; mega_count = 0
    for _, row in latest.iterrows():
        mcap = _col(row, "Market_Cap")
        if mcap >= MCAP_THRESHOLD * 10:
            c = _col(row, "Close"); s9 = _col(row, "SMA_9")
            if c > 0 and s9 > 0:
                nifty_5d += (c - s9) / s9 * 100
                mega_count += 1
    if mega_count > 0:
        nifty_5d = nifty_5d / mega_count
    if breadth >= 65 and nifty_5d > 1: regime = "POSITIVE"
    elif breadth <= 35 and nifty_5d < -1: regime = "NEGATIVE"
    else: regime = "CHOPPY"
    print(f"  -> Nifty 5d: {nifty_5d:+.1f}% ({mega_count} mega-caps)\n  -> Breadth: {breadth}%\n  -> REGIME: {regime}")
    return regime, breadth, round(nifty_5d, 1)


# ── Sector Strength ───────────────────────────────────────────────────────

def compute_sector_strength(stock_df, sector_map):
    sector_scores = {}
    latest = stock_df.groupby("Ticker").tail(1)
    sec_tickers = defaultdict(list)
    for _, row in latest.iterrows():
        tk = str(row.get("Ticker", "")).strip()
        sec = sector_map.get(tk, "Other")
        sec_tickers[sec].append(row)
    for sec, rows in sec_tickers.items():
        rets = []
        for row in rows:
            c = _col(row, "Close"); s = _col(row, "SMA_22")
            if c > 0 and s > 0: rets.append((c - s) / s * 100)
        avg = np.mean(rets) if rets else 0
        sector_scores[sec] = round(avg, 1)
        print(f"    {sec} ({len(rows)}): {avg:+.0f}")
    return sector_scores


# ── Composite ─────────────────────────────────────────────────────────────

def compute_composite(tech, macro, fund, news, regime):
    base = tech * TECH_WEIGHT + macro * MACRO_WEIGHT + fund * FUND_WEIGHT + news * NEWS_WEIGHT
    if news != 0: base += news * 0.3
    bull_damp = 0.7 if regime == "NEGATIVE" else 1.0
    bear_damp = 0.7 if regime == "POSITIVE" else 1.0
    if base > 0: base *= bull_damp
    elif base < 0: base *= bear_damp
    return round(base, 1)


# ── Add Composite_Score to stock_df for backtest ──────────────────────────

def add_composite_scores(stock_df):
    """Vectorized composite score for ALL rows so accuracy.py backtest works."""
    close  = _col_df(stock_df, "Close")
    sma9   = _col_df(stock_df, "SMA_9")
    sma22  = _col_df(stock_df, "SMA_22")
    sma200 = _col_df(stock_df, "SMA_200")
    rsi    = _col_df(stock_df, "RSI_14", "RSI")
    bb_u   = _col_df(stock_df, "BB_Upper")
    bb_l   = _col_df(stock_df, "BB_Lower")
    macd   = _col_df(stock_df, "MACD_Line", "MACD")
    macd_s = _col_df(stock_df, "MACD_Signal")
    st     = _col_df(stock_df, "ST_Value")
    ema9   = _col_df(stock_df, "EMA_9")
    ema21  = _col_df(stock_df, "EMA_21")
    adx    = _col_df(stock_df, "ADX_14", "ADX")

    sc = pd.Series(0.0, index=stock_df.index)
    sc += np.where((close > sma22) & (sma22 > 0), 10, 0)
    sc += np.where((close < sma22) & (sma22 > 0), -10, 0)
    sc += np.where((close > sma200) & (sma200 > 0), 5, 0)
    sc += np.where((close < sma200) & (sma200 > 0), -5, 0)
    sc += np.where(rsi < 30, 10, 0)
    sc += np.where(rsi > 70, -10, 0)
    sc += np.where(macd > macd_s, 5, 0)
    sc += np.where(macd < macd_s, -5, 0)
    sc += np.where((st > 0) & (close > st), 5, 0)
    sc += np.where((st > 0) & (close < st), -5, 0)
    sc += np.where((ema9 > ema21) & (ema21 > 0), 3, 0)
    sc += np.where((ema9 < ema21) & (ema21 > 0), -3, 0)
    sc += np.where((adx > 25) & (close > sma9) & (sma9 > 0), 4, 0)
    sc += np.where((adx > 25) & (close < sma9) & (sma9 > 0), -4, 0)

    sma9_prev = stock_df.groupby("Ticker")["SMA_9"].shift(1).fillna(0) if "SMA_9" in stock_df.columns else pd.Series(0, index=stock_df.index)
    sc += np.where((sma9 > sma9_prev) & (sma9_prev > 0) & (close > sma9), 8, 0)
    sc += np.where((sma9 < sma9_prev) & (sma9_prev > 0) & (close < sma9), -8, 0)

    stock_df["Composite_Score"] = sc
    return stock_df


# ── Chart JSON ────────────────────────────────────────────────────────────

def generate_chart_data(ticker, stock_df, history_df, output_dir):
    tdf = stock_df[stock_df["Ticker"].astype(str).str.strip() == ticker].copy()
    if tdf.empty: return
    tdf = tdf.sort_values("Date").tail(365)
    tdf["Date"] = tdf["Date"].astype(str).str[:10]
    data = {"ohlc": [], "volume": [], "markers": [],
            "sma9": [], "sma22": [], "sma200": [],
            "ema9": [], "ema21": [], "vwap": [],
            "bb_upper": [], "bb_lower": [],
            "st_bull": [], "st_bear": [],
            "ichi_tenkan": [], "ichi_kijun": [], "ichi_spanA": [], "ichi_spanB": [],
            "rsi": [], "macd_line": [], "macd_signal": [], "macd_hist": [], "adx": []}

    for _, row in tdf.iterrows():
        d = str(row["Date"])[:10]
        o = _col(row, "Open"); h = _col(row, "High"); l = _col(row, "Low")
        c = _col(row, "Close"); v = _col(row, "Volume")
        if c == 0: continue
        data["ohlc"].append({"time": d, "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2)})
        color = "#22c55e88" if c >= o else "#ef444488"
        data["volume"].append({"time": d, "value": int(v), "color": color})
        for cols, key in [
            (("SMA_9",), "sma9"), (("SMA_22",), "sma22"), (("SMA_200",), "sma200"),
            (("EMA_9",), "ema9"), (("EMA_21",), "ema21"), (("VWAP",), "vwap"),
            (("BB_Upper",), "bb_upper"), (("BB_Lower",), "bb_lower"),
        ]:
            val = _col(row, *cols)
            if val > 0: data[key].append({"time": d, "value": round(val, 2)})

        st = _col(row, "ST_Value")
        if st > 0:
            if c > st: data["st_bull"].append({"time": d, "value": round(st, 2)})
            else: data["st_bear"].append({"time": d, "value": round(st, 2)})
        for cols, key in [
            (("Ichi_Tenkan", "Ichimoku_Tenkan"), "ichi_tenkan"),
            (("Ichi_Kijun", "Ichimoku_Kijun"), "ichi_kijun"),
            (("Ichi_SpanA", "Ichimoku_SpanA"), "ichi_spanA"),
            (("Ichi_SpanB", "Ichimoku_SpanB"), "ichi_spanB"),
        ]:
            val = _col(row, *cols)
            if val > 0: data[key].append({"time": d, "value": round(val, 2)})
        rsi_v = _col(row, "RSI_14", "RSI")
        if rsi_v > 0: data["rsi"].append({"time": d, "value": round(rsi_v, 2)})
        ml = _col(row, "MACD_Line", "MACD"); ms = _col(row, "MACD_Signal"); mh = ml - ms
        data["macd_line"].append({"time": d, "value": round(ml, 4)})
        data["macd_signal"].append({"time": d, "value": round(ms, 4)})
        mc = "#22c55e" if mh >= 0 else "#ef4444"
        data["macd_hist"].append({"time": d, "value": round(mh, 4), "color": mc})
        adx_v = _col(row, "ADX_14", "ADX")
        if adx_v > 0: data["adx"].append({"time": d, "value": round(adx_v, 2)})

    if history_df is not None and len(history_df) > 0:
        hdf_tk = history_df[history_df["Ticker"].astype(str).str.strip() == ticker]
        date_set = set(str(r["Date"])[:10] for _, r in tdf.iterrows())
        for _, hr in hdf_tk.iterrows():
            raw_dir = hr.get("Momentum_Direction", 0)
            if pd.isna(raw_dir): continue
            hdir = int(raw_dir)
            if hdir == 0: continue
            hdate = str(hr.get("Date", ""))[:10]
            if hdate not in date_set: continue
            if hdir == 1:
                data["markers"].append({"time": hdate, "position": "belowBar",
                    "color": "#22c55e", "shape": "arrowUp", "text": "POSITIVE"})
            else:
                data["markers"].append({"time": hdate, "position": "aboveBar",
                    "color": "#ef4444", "shape": "arrowDown", "text": "NEGATIVE"})
    data["markers"].sort(key=lambda m: m["time"])
    out_path = os.path.join(output_dir, ticker + ".json")
    with open(out_path, "w") as f:
        json.dump(data, f, separators=(",", ":"))


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")

    # ── Data sync ──
    smart_sync()

    # ── Recompute indicators ──
    recompute_indicators()

    # ── Load data ──
    tickers, sector_map = load_tickers()
    stock_df = pd.read_csv(DATA_FILE, low_memory=False)
    stock_df["Ticker"] = stock_df["Ticker"].astype(str).str.strip()

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  FIX 1: Forward-fill Market_Cap & Sector per ticker               ║
    # ║  create_stock_data.py may set these on only one row per ticker.   ║
    # ║  Without ffill, the LATEST row often has NaN → mcap=0 → SMALL.   ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    for col in ["Market_Cap", "Sector", "Sub_Industry"]:
        if col in stock_df.columns:
            stock_df[col] = stock_df.groupby("Ticker")[col].transform(
                lambda x: x.ffill().bfill()
            )

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  FIX 2: Auto-detect MCap scale & normalize to crores              ║
    # ║  yfinance stores Market_Cap in raw INR (e.g. 1.3e13 for TCS).    ║
    # ║  classify_cap expects crores (TCS ≈ 1,300,000 Cr).               ║
    # ║  If median > 1e10 → values are raw INR → divide by 1e7.          ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    if "Market_Cap" in stock_df.columns:
        mcap_latest = stock_df.groupby("Ticker")["Market_Cap"].last().dropna()
        if not mcap_latest.empty:
            med = mcap_latest.median()
            if med > 1e10:
                stock_df["Market_Cap"] = stock_df["Market_Cap"] / 1e7
                mcap_latest = mcap_latest / 1e7
                print(f"  -> MCap: raw INR detected (median={med:.2e}), normalized to Cr")
            elif med > 0:
                print(f"  -> MCap: already in Cr (median={med:,.0f})")
            else:
                print(f"  -> MCap: ⚠️ median is {med} — check data")
            cats = mcap_latest.apply(lambda x: classify_cap(x, MCAP_THRESHOLD))
            vc = cats.value_counts()
            preview = " | ".join(f"{c}:{vc.get(c,0)}" for c in ["MEGA","LARGE","MID","SMALL"])
            print(f"  -> MCap split: {preview}")
            top3 = mcap_latest.nlargest(3)
            bot3 = mcap_latest.nsmallest(3)
            print(f"  -> Top3: {', '.join(f'{t}={v:,.0f}Cr' for t,v in top3.items())}")
            print(f"  -> Bot3: {', '.join(f'{t}={v:,.0f}Cr' for t,v in bot3.items())}")
    else:
        print("  -> ⚠️ No Market_Cap column found!")

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  FIX 3: Rebuild sector_map from stock_data.csv if tickers.csv     ║
    # ║  doesn't have Sector column.                                      ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    if not sector_map and "Sector" in stock_df.columns:
        latest_rows = stock_df.groupby("Ticker").tail(1)
        for _, row in latest_rows.iterrows():
            tk = str(row["Ticker"]).strip()
            sec = str(row.get("Sector", "")).strip()
            if sec and sec not in ("", "nan", "0", "Other", "None"):
                sector_map[tk] = sec
        if sector_map:
            print(f"  -> Sector map rebuilt from stock_data.csv: {len(sector_map)} tickers mapped to {len(set(sector_map.values()))} sectors")

    n_tickers = stock_df["Ticker"].nunique()
    avg_days = len(stock_df) // n_tickers if n_tickers else 0
    print(f"  -> Loaded stock_data.csv: {n_tickers} tickers, {len(stock_df):,} rows (~{avg_days} days/ticker)")

    found = [c for c in ["Ticker","Date","Close","RSI","RSI_14","MACD","MACD_Line","MACD_Signal",
                          "SMA_9","SMA_22","SMA_200","EMA_9","EMA_21","BB_Upper","BB_Lower",
                          "ADX","ADX_14","SuperTrend","ST_Value","ATR_Pct","Market_Cap"] if c in stock_df.columns]
    print(f"  -> Found: {len(found)} key columns")
    print(f"  -> MCap threshold: {MCAP_THRESHOLD}")

    # ── Load history ──
    hdf = pd.DataFrame()
    if HISTORY_FILE.exists():
        hdf = pd.read_csv(HISTORY_FILE)
        hdf["Ticker"] = hdf["Ticker"].astype(str).str.strip()

    now_str = datetime.now().strftime("%I:%M %p")
    print(f"\nANALYTICAL Engine v{VERSION} - {len(tickers)} tickers | {today_str}")
    print(f"News: {(today - timedelta(days=NEWS_WINDOW_DAYS)).strftime('%Y-%m-%d')} to {now_str} | CATALYST-ONLY FinBERT")
    print(f"Tech: MEGA/LARGE=SMA9-reversal(strict) | MID/SMALL=BB-centric")
    print(f"Horizons: MEGA={HORIZONS['MEGA']}d LARGE={HORIZONS['LARGE']}d MID={HORIZONS['MID']}d SMALL={HORIZONS['SMALL']}d")
    print(f"MinHold: MEGA={HOLD_DAYS['MEGA']}d LARGE={HOLD_DAYS['LARGE']}d MID={HOLD_DAYS['MID']}d SMALL={HOLD_DAYS['SMALL']}d")
    print(f"SL: ATR-based LC | -{STOP_LOSS_PCT*100:.1f}% fixed SC | Neutral band: sigma-based")
    print(f"Entry: +/-{ENTRY_THRESHOLD_LC} | Exit: +/-{EXIT_THRESHOLD_LC}")
    print("=" * 110)

    # ── PHASE 1: News (with cache) ──
    print(f"\nPHASE 1: Fetching predictive news...")
    print("-" * 110)
    news_cache = build_news_cache(tickers)
    # Convert news_cache dict → ticker_articles format for FinBERT
    ticker_articles = defaultdict(list)
    for tk in tickers:
        entries = news_cache.get(tk, [])
        for e in entries:
            ticker_articles[tk].append({
                "title": e["headline"],
                "source": e["source"],
                "date": e.get("pub_time", ""),
                "tickers": [tk],
                "url": e.get("news_url", ""),
            })
    print("-" * 110)

    # ── PHASE 2: FinBERT ──
    print(f"\nPHASE 2: FinBERT scoring (CATALYST-ONLY)...")
    print("-" * 110)
    news_results = run_finbert_phase(ticker_articles, tickers, stock_df, hdf)

    # ── PHASE 3: Multi-layer analysis ──
    print(f"\nPHASE 3: Multi-layer analysis ({len(tickers)} tickers)...")
    print("-" * 110)

    print(f"Computing technical scores (v{VERSION} cap-aware)...")
    scored_rows = []
    for tk in tickers:
        tdf = stock_df[stock_df["Ticker"].astype(str).str.strip() == tk].sort_values("Date")
        if tdf.empty: continue
        last = tdf.iloc[-1]
        prev = tdf.iloc[-2] if len(tdf) >= 2 else None
        mcap = _col(last, "Market_Cap")
        cat = classify_cap(mcap, MCAP_THRESHOLD)
        tech = compute_tech_score(last, cat, prev)
        if len(scored_rows) < 3:
            sma9p = f"{_col(prev, 'SMA_9'):.1f}" if prev is not None else "N/A"
            print(f"    DEBUG {tk}({cat}): RSI={_col(last, 'RSI_14', 'RSI', default=50):.1f}, "
                  f"Close={_col(last, 'Close')}, SMA9={_col(last, 'SMA_9'):.1f}, "
                  f"SMA22={_col(last, 'SMA_22'):.1f}, SMA200={_col(last, 'SMA_200'):.1f}, "
                  f"SMA9prev={sma9p}, ATR={_col(last, 'ATR_Pct'):.1f}%  MCap={mcap:,.0f}Cr  Score={tech}")
        scored_rows.append({"Ticker": tk, "Category": cat, "Tech_Score": tech,
                           "row": last, "prev": prev, "mcap": mcap})

    lc_count = sum(1 for r in scored_rows if r["Category"] in ("MEGA", "LARGE"))
    sc_count = sum(1 for r in scored_rows if r["Category"] in ("MID", "SMALL"))
    print(f"  -> {len(scored_rows)}/{len(tickers)} scored | LC:{lc_count} SMC:{sc_count}")

    print("Computing fundamentals...")
    for sr in scored_rows:
        sr["Fund_Score"] = compute_fund_score(sr["row"])
    nz_fund = sum(1 for r in scored_rows if r["Fund_Score"] != 0)
    print(f"  -> {nz_fund}/{len(scored_rows)} with non-zero fund score")
    print(f"  -> {len(sector_map)}/{len(scored_rows)} mapped to {len(set(sector_map.values()))} sectors")

    print(f"\nComputing market regime...")
    regime, breadth, nifty_5d = compute_market_regime(stock_df)

    print(f"\nComputing sector strength...")
    sector_scores = compute_sector_strength(stock_df, sector_map)

    # ── v8 Tech Scoring Override ──
    print("  [v8] Applying corrected tech scoring...")
    stock_df = compute_tech_scores(stock_df)
    # ─────────────────────────────

    # ── PHASE 3b: Backtest ──
    print(f"\nPHASE 3b: Backtest (ATR SL for LC, {STOP_LOSS_PCT*100:.1f}% SL for SC)...")

    print("  Adding Composite_Score to stock_df (vectorized)...")
    stock_df = add_composite_scores(stock_df)
    nz = (stock_df["Composite_Score"] != 0).sum()
    print(f"  -> {nz}/{len(stock_df)} rows with non-zero Composite_Score")

    # ── v8 Composite Override ──
    print("  [v8] Applying corrected composite scoring...")
    stock_df = compute_composites(stock_df)
    # ─────────────────────────────

    bt_results = []
    for tk in tickers:
        r = compute_per_ticker_accuracy(stock_df, tk)
        if r:
            bt_results.append(r)

    if bt_results:
        btdf = pd.DataFrame(bt_results)
        print(f"\n  Per-category accuracy (DIRECTIONAL ONLY):")
        print(f"  {'Cat':<10s} {'N':>3s}  {'DirAcc':>6s}  {'SigRate':>7s}  {'Fwd':>3s}")
        print("  " + "-" * 40)
        for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
            cr = btdf[(btdf["Category"] == cat) & (btdf["dir_preds"] > 0)]
            if cr.empty: continue
            w_acc = cr["dir_hits"].sum() / cr["dir_preds"].sum() * 100 if cr["dir_preds"].sum() > 0 else 0
            avg_sig = cr["signal_rate"].mean()
            fwd = HORIZONS[cat]
            print(f"  {cat:<10s} {len(cr):>3d}  {w_acc:>5.1f}%  {avg_sig:>6.1f}%  {fwd:>2d}d")

    print(f"\nComputing composite + regime adjustment...")
    bull_damp = 0.7 if regime == "NEGATIVE" else 1.0
    bear_damp = 0.7 if regime == "POSITIVE" else 1.0
    print(f"  Regime: {regime} -> bull_damp={bull_damp} bear_damp={bear_damp}")

    # ── v8 Override: Feed corrected tech scores into output ──
    v8_scores = get_v8_latest_scores(stock_df, tickers)
    v8_applied = 0
    for sr in scored_rows:
        tk = sr["Ticker"]
        if tk in v8_scores:
            sr["Tech_Score"] = v8_scores[tk]["Tech_Score"]
            sr["Category"] = v8_scores[tk]["Category"]
            v8_applied += 1
    print(f"  [v8] Overrode {v8_applied}/{len(scored_rows)} ticker scores with v8 logic")
    # ─────────────────────────────────────────────────────────
    print("-" * 110)

    all_rows = []
    tech_bull = 0; tech_bear = 0; tech_neut = 0
    same_day_hit = 0; same_day_total = 0; flips = 0

    for sr in scored_rows:
        tk = sr["Ticker"]; cat = sr["Category"]
        tech = sr["Tech_Score"]; fund = sr["Fund_Score"]
        row = sr["row"]
        sec = sector_map.get(tk, "Other")
        macro = sector_scores.get(sec, 0)
        nr = news_results.get(tk, {})
        news_score = nr.get("News_Score", 0)
        news_dir = nr.get("News_Sentiment", "NEUTRAL")
        n_cat = nr.get("N_Catalysts", 0)
        comp = compute_composite(tech, macro, fund, news_score, regime)
        is_lc = cat in ("MEGA", "LARGE")
        entry = ENTRY_THRESHOLD_LC if is_lc else ENTRY_THRESHOLD_SC

        # v8 hard gate: if tech=0 for MEGA/LARGE, force NEUTRAL
        if cat in ("MEGA", "LARGE") and tech == 0:
            direction = 0; dir_label = "NEUTRAL"; tech_neut += 1
            comp = 0.0
        elif comp >= entry: direction = 1; dir_label = "POSITIVE"; tech_bull += 1
        elif comp <= -entry: direction = -1; dir_label = "NEGATIVE"; tech_bear += 1
        else: direction = 0; dir_label = "NEUTRAL"; tech_neut += 1

        tdf_tk = stock_df[stock_df["Ticker"].astype(str).str.strip() == tk].sort_values("Date")
        act_ret = 0
        if len(tdf_tk) >= 2:
            c_today = _col(tdf_tk.iloc[-1], "Close")
            c_prev = _col(tdf_tk.iloc[-2], "Close")
            if c_prev > 0: act_ret = (c_today - c_prev) / c_prev * 100

        if direction != 0:
            same_day_total += 1
            actual_dir = 1 if act_ret > 0 else (-1 if act_ret < 0 else 0)
            if is_hit(direction, actual_dir): same_day_hit += 1

        severity = "NEUTRAL"
        if direction != 0 and not hdf.empty:
            prev_rows = hdf[hdf["Ticker"].astype(str).str.strip() == tk]
            if not prev_rows.empty:
                last_h = prev_rows.iloc[-1]
                last_dir = int(last_h.get("Momentum_Direction", 0) or 0)
                if last_dir != 0:
                    actual_dir_h = 1 if act_ret > 0 else (-1 if act_ret < 0 else 0)
                    severity = "HIT" if is_hit(last_dir, actual_dir_h) else "MISS"

        bt = next((r for r in bt_results if r["Ticker"] == tk), {})
        bt_acc = bt.get("dir_accuracy", 0)
        bt_pf = bt.get("TR_profit_factor", 0)

        if direction != 0 or n_cat > 0:
            fwd = HORIZONS.get(cat, 14)
            print(f"  [{scored_rows.index(sr)+1:>3d}] {tk:<18s} Tech: {tech:>+3.0f} Macro: {macro:>+3.0f} Fund: {fund:>+3.0f} -> "
                  f"Comp: {comp:>+5.1f} {dir_label} {severity}  BT:{bt_acc:.0f}%/{cat} H:{fwd}d")

        out = {
            "Ticker": tk, "Category": cat, "BT_Category": cat, "Sector": sec,
            "Market_Cap": sr["mcap"], "Close": _col(row, "Close"),
            "Tech_Score": tech, "Technical_Score": tech,
            "Macro_Score": round(macro, 1), "Fund_Score": fund, "Fundamental_Score": fund,
            "News_Score": news_score, "Forecast_Score": news_score,
            "N_Catalysts": n_cat, "News_Sentiment": news_dir,
            "Composite_Score": comp, "Momentum_Direction": direction,
            "Forecast_Direction": direction, "Direction_Label": dir_label,
            "Composite_Severity": severity, "Actual_Return_Pct": round(act_ret, 2),
            "Regime": regime,
            "BT_6M": round(bt_acc, 1), "BT_Accuracy": round(bt_acc, 1),
            "BT_Forward_Days": HORIZONS.get(cat, 14), "Horizon": HORIZONS.get(cat, 14),
            "BT_PF": round(bt_pf, 2), "BT_Trades": int(bt.get("TR_total_trades", 0)),
            "TR_total_trades": int(bt.get("TR_total_trades", 0)),
            "TR_win_rate": round(bt.get("TR_win_rate", 0), 1),
            "TR_avg_win_pct": round(bt.get("TR_avg_win_pct", 0), 2),
            "TR_avg_loss_pct": round(bt.get("TR_avg_loss_pct", 0), 2),
            "TR_profit_factor": round(bt_pf, 2),
            "TR_total_return_pct": round(bt.get("TR_total_return_pct", 0), 1),
            "TR_avg_holding_days": round(bt.get("TR_avg_holding_days", 0), 1),
            "TR_sl_exits": int(bt.get("TR_sl_exits", 0)),
            "TR_flips": int(bt.get("TR_flips", 0)),
        }
        all_rows.append(out)

    sd_acc = same_day_hit / same_day_total * 100 if same_day_total else 0
    print(f"\n  Tech-only: Positive:{tech_bull} Negative:{tech_bear} Neutral:{tech_neut} | Hit:{same_day_hit}/{same_day_total} = {sd_acc:.1f}%")

    # ── PHASE 4: Save ──
    print(f"\nPHASE 4: Save...")
    print("-" * 110)

    out_df = pd.DataFrame(all_rows)
    out_df.to_csv(OUTPUT_CSV, index=False)

    today_rows = out_df[["Ticker", "Category", "Composite_Score", "Momentum_Direction",
                          "Direction_Label", "Actual_Return_Pct", "Tech_Score", "Fund_Score",
                          "News_Score", "Macro_Score"]].copy()
    today_rows["Date"] = today_str

    if not hdf.empty:
        hdf2 = pd.concat([hdf, today_rows], ignore_index=True)
    else:
        hdf2 = today_rows.copy()

    if "Date" in hdf2.columns:
        hdf2["Date"] = hdf2["Date"].astype(str).str[:10]
        cutoff = (today - timedelta(days=90)).strftime("%Y-%m-%d")
        hdf2 = hdf2[hdf2["Date"] >= cutoff]

    hdf2.to_csv(HISTORY_FILE, index=False)
    print(f"History: {len(hdf2)} rows / {hdf2['Date'].nunique() if 'Date' in hdf2.columns else 0} days")

    # ── PHASE 5: Charts + Meta ──
    print(f"\nPHASE 5: Generating chart JSON + meta...")
    print("-" * 110)

    os.makedirs(CHARTS_DIR, exist_ok=True)
    if "Date" in hdf2.columns:
        hdf2["Date"] = hdf2["Date"].astype(str).str[:10]

    for t in tickers:
        generate_chart_data(t, stock_df, hdf2, CHARTS_DIR)
    print(f"  -> Chart JSON: {len(tickers)} tickers in charts/")

    avg_acc = np.mean([r.get("BT_6M", 0) for r in all_rows if r.get("BT_6M", 0) > 0]) if all_rows else 0
    avg_pf = np.mean([r.get("TR_profit_factor", 0) for r in all_rows if r.get("TR_profit_factor", 0) > 0]) if all_rows else 0

    meta = {
        "date": today_str, "version": VERSION, "tickers": len(tickers),
        "total_tickers": len(tickers), "regime": regime, "breadth": breadth,
        "nifty_5d": nifty_5d, "avg_accuracy": round(avg_acc, 1),
        "direction_accuracy": round(avg_acc, 1), "avg_profit_factor": round(avg_pf, 2),
        "avg_pf": round(avg_pf, 2), "bulls": tech_bull, "bears": tech_bear,
        "neutral momentums": tech_neut, "same_day_accuracy": round(sd_acc, 1),
    }
    with open(META_JSON, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  -> meta.json saved (PF:{avg_pf:.2f} Acc:{avg_acc:.1f}%)")

    print(f"\n{'='*110}")
    print(f"data.csv | {today_str} | ENGINE v{VERSION} ATR SL + strict SMA9")
    print(f"READINGS: {tech_bull + tech_bear} directional momentum | {tech_neut} neutral momentum")
    print(f"REGIME: {regime} (breadth={breadth}% nifty={nifty_5d}%)")
    print(f"STRATEGY: LC({lc_count}) SMC({sc_count}) | MEGA/LARGE=SMA9-rev(strict) | MID/SMALL=BB")
    print(f"SAME-DAY ALIGNMENT: {same_day_hit}/{same_day_total} = {sd_acc:.1f}%")
    print("=" * 110)

    print_accuracy_report(stock_df, tickers, history_df=hdf2)


if __name__ == "__main__":
    main()
