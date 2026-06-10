#!/usr/bin/env python3
"""
app.py – xChart PREDICTIVE Engine v7.4 – Multi-Layer Trading Intelligence
"""

import os, sys, json, re, time, math, traceback, hashlib
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

# ── Engine imports ────────────────────────────────────────────────────────
from engine.data_fetcher import smart_sync
from create_stock_data import recompute_indicators

from engine.accuracy import (
    compute_per_ticker_accuracy, print_accuracy_report,
    compute_accuracy_periods,
    ENTRY_THRESHOLD_LC, ENTRY_THRESHOLD_SC,
    EXIT_THRESHOLD_LC, EXIT_THRESHOLD_SC,
    HORIZONS, HOLD_DAYS, SL_FIXED,
)

STOP_LOSS_PCT = SL_FIXED

# ── Paths ─────────────────────────────────────────────────────────────────
DATA_DIR     = Path(".")
DATA_FILE    = DATA_DIR / "stock_data.csv"
TICKER_FILE  = DATA_DIR / "tickers.csv"
HISTORY_FILE = DATA_DIR / "history.csv"
OUTPUT_CSV   = DATA_DIR / "data.csv"
META_JSON    = DATA_DIR / "meta.json"
CHARTS_DIR   = DATA_DIR / "charts"

# ── Constants ─────────────────────────────────────────────────────────────
VERSION          = "7.4"
MCAP_THRESHOLD   = 10000
NEWS_WINDOW_DAYS = 3
MAX_CATALYSTS    = 20
CATALYST_ONLY    = True
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


# ── Local helpers ─────────────────────────────────────────────────────────

def classify_cap(mcap, threshold=MCAP_THRESHOLD):
    """Classify ticker by market cap."""
    if mcap >= threshold * 20:
        return "MEGA"
    elif mcap >= threshold * 5:
        return "LARGE"
    elif mcap >= threshold:
        return "MID"
    return "SMALL"


def is_hit(pred_dir, actual_dir):
    """Check if prediction was correct."""
    if pred_dir == 0:
        return None
    if actual_dir == 0:
        return True  # neutral actual = soft hit
    return pred_dir == actual_dir


# ── News Fetcher ──────────────────────────────────────────────────────────

def load_tickers():
    """Load tickers and sector map from tickers.csv."""
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


def _parse_feed(url, source_name, tickers, max_items=60):
    """Parse an RSS feed URL and return list of article dicts."""
    import feedparser
    articles = []
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            print(f"   {source_name}: No entries")
            return []
    except Exception as e:
        print(f"   {source_name}: {e}")
        return []

    cutoff = datetime.now() - timedelta(days=NEWS_WINDOW_DAYS)
    outside_window = 0
    reporting_filtered = 0
    nse_noise = 0
    
    for entry in feed.entries[:max_items]:
        title = entry.get("title", "").strip()
        if not title:
            continue

        # Parse date
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            try:
                dt = datetime(*published[:6])
            except Exception:
                dt = datetime.now()
        else:
            dt = datetime.now()

        if dt < cutoff:
            outside_window += 1
            continue

        # Filter reporting/results headlines
        if REPORTING_KW.search(title):
            reporting_filtered += 1
            continue

        # Filter NSE noise
        if "nse" in source_name.lower() and NSE_NOISE_KW.search(title):
            nse_noise += 1
            continue

        # Match tickers
        matched = []
        title_upper = title.upper()
        for tk in tickers:
            tk_u = tk.upper()
            if tk_u in title_upper or tk_u.replace(".", "") in title_upper:
                matched.append(tk)

        articles.append({
            "title": title,
            "source": source_name,
            "date": dt.strftime("%Y-%m-%d %H:%M"),
            "tickers": matched,
            "url": entry.get("link", ""),
        })

    kept = len(articles)
    extra = ""
    if outside_window:
        extra += f", {outside_window} outside window"
    if reporting_filtered:
        extra += f", {reporting_filtered} reporting"
    if nse_noise:
        extra += f", {nse_noise} NSE noise"
    print(f"   {source_name}: {kept} predictive from {len(feed.entries[:max_items])}{extra}")
    return articles


RSS_FEEDS = {
    "mc_topnews":    "https://www.moneycontrol.com/rss/latestnews.xml",
    "mc_business":   "https://www.moneycontrol.com/rss/business.xml",
    "mc_markets":    "https://www.moneycontrol.com/rss/marketreports.xml",
    "mc_stocks":     "https://www.moneycontrol.com/rss/stocksinnews.xml",
    "et_markets":    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks":     "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "et_news":       "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    "ndtv_business": "https://feeds.feedburner.com/ndtvprofit-latest",
    "mint_market":   "https://www.livemint.com/rss/markets",
    "mint_companies":"https://www.livemint.com/rss/companies",
    "nse_announce":  "https://www.nseindia.com/api/corporate-announcements?index=equities&fo_sec=true",
    "nse_actions":   "https://www.nseindia.com/api/corporate-actions?index=equities",
    "fe_markets":    "https://www.financialexpress.com/market/feed/",
    "fe_companies":  "https://www.financialexpress.com/industry/feed/",
    "bl_markets":    "https://www.thehindubusinessline.com/markets/feeder/default.rss",
    "bl_stocks":     "https://www.thehindubusinessline.com/markets/stock-markets/feeder/default.rss",
    "bl_companies":  "https://www.thehindubusinessline.com/companies/feeder/default.rss",
}


def fetch_news(tickers):
    """Fetch predictive news from all RSS feeds."""
    all_articles = []
    for name, url in RSS_FEEDS.items():
        print(f"Fetching {name}...")
        articles = _parse_feed(url, name, tickers)
        all_articles.extend(articles)

    # Group by ticker
    ticker_articles = defaultdict(list)
    for art in all_articles:
        for tk in art["tickers"]:
            ticker_articles[tk].append(art)

    cache = len(ticker_articles)
    print(f"\nCache: {cache}/{len(tickers)} predictive | Scanned:{len(all_articles)} Kept:{len(all_articles)}")
    return ticker_articles


# ── FinBERT Scoring ───────────────────────────────────────────────────────

def init_finbert():
    """Initialize FinBERT model."""
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch
    print("Initializing FinBERT...")
    tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)
    model.eval()
    return tokenizer, model


def score_headlines(headlines, tokenizer, model):
    """Score a list of headlines with FinBERT. Returns (score, direction)."""
    import torch
    if not headlines:
        return 0.0, 0

    scores = []
    for h in headlines[:MAX_CATALYSTS]:
        inputs = tokenizer(h, return_tensors="pt", truncation=True, max_length=128, padding=True)
        with torch.no_grad():
            outputs = model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
        # FinBERT: [positive, negative, neutral]
        pos, neg, neu = probs[0].item(), probs[1].item(), probs[2].item()
        score = (pos - neg) * 100
        scores.append(score)

    if not scores:
        return 0.0, 0

    avg = np.mean(scores)
    direction = 1 if avg > 10 else (-1 if avg < -10 else 0)
    return round(avg, 1), direction


def run_finbert_phase(ticker_articles, tickers, stock_df, history_df):
    """PHASE 2: Score catalysts with FinBERT."""
    if not ticker_articles:
        return {}

    tokenizer, model = init_finbert()
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

        # Check historical accuracy
        ret_str = ""
        hit_str = ""
        if history_df is not None and len(history_df) > 0:
            hrows = history_df[history_df["Ticker"].astype(str).str.strip() == tk]
            if not hrows.empty:
                last = hrows.iloc[-1]
                act_ret = float(last.get("Actual_Return_Pct", 0) or 0)
                last_dir = int(last.get("Composite_Direction", 0) or 0)
                ret_str = f" Ret: {act_ret:+.2f}%"
                if last_dir != 0:
                    was_hit = "HIT" if is_hit(last_dir, 1 if act_ret > 0 else (-1 if act_ret < 0 else 0)) else "MISS"
                    hit_str = f" {was_hit}"

        dir_label = "BULL" if direction == 1 else ("BEAR" if direction == -1 else "NEUT")
        print(f"[{idx:>3d}] {tk:<18s} {dir_label} Score: {score:+.1f}{ret_str}{hit_str} [{len(headlines)}cat/{len(headlines)}h]")

        results[tk] = {
            "News_Score": score,
            "News_Direction": dir_label,
            "N_Catalysts": len(headlines),
            "headlines": headlines[:5],
        }

    n_scored = sum(1 for v in results.values() if v["N_Catalysts"] > 0)
    print(f"\n  Catalysts: {n_scored} scored")
    return results


# ── Technical Scoring ─────────────────────────────────────────────────────

def compute_tech_score(row, cat, prev_row=None):
    """Compute technical score for a single row. Cap-aware v7.4."""
    score = 0
    is_lc = cat in ("MEGA", "LARGE")

    close = float(row.get("Close", 0) or 0)
    rsi   = float(row.get("RSI", 50) or 50)
    sma9  = float(row.get("SMA_9", 0) or 0)
    sma22 = float(row.get("SMA_22", 0) or 0)
    sma200= float(row.get("SMA_200", 0) or 0)
    ema9  = float(row.get("EMA_9", 0) or 0)
    ema21 = float(row.get("EMA_21", 0) or 0)
    macd  = float(row.get("MACD", 0) or 0)
    macd_s= float(row.get("MACD_Signal", 0) or 0)
    adx   = float(row.get("ADX", 0) or 0)
    bb_u  = float(row.get("BB_Upper", 0) or 0)
    bb_l  = float(row.get("BB_Lower", 0) or 0)
    st    = float(row.get("SuperTrend", 0) or 0)
    atr_p = float(row.get("ATR_Pct", 0) or 0)

    sma9_prev = float(prev_row.get("SMA_9", 0) or 0) if prev_row is not None else None

    if close == 0:
        return 0

    if is_lc:
        # ── LC Strategy: Strict SMA9 reversal ──
        # SMA9 slope reversal
        if sma9_prev is not None and sma9 > 0 and sma9_prev > 0:
            if sma9 > sma9_prev and close > sma9:
                score += 15   # upward reversal
            elif sma9 < sma9_prev and close < sma9:
                score -= 15   # downward reversal

        # Trend: close vs SMA22
        if close > sma22 > 0:
            score += 5
        elif close < sma22 > 0:
            score -= 5

        # Long-term trend
        if close > sma200 > 0:
            score += 3
        elif close < sma200 > 0:
            score -= 3

        # RSI
        if rsi > 70:
            score -= 5
        elif rsi < 30:
            score += 5

        # MACD crossover
        if macd > macd_s:
            score += 3
        elif macd < macd_s:
            score -= 3

        # ADX trend strength
        if adx > 25:
            if close > sma9 > 0:
                score += 4
            elif close < sma9 > 0:
                score -= 4

        # SuperTrend
        if st > 0 and close > st:
            score += 3
        elif st > 0 and close < st:
            score -= 3

    else:
        # ── SC Strategy: BB-centric ──
        if bb_l > 0 and bb_u > 0:
            bb_range = bb_u - bb_l
            if bb_range > 0:
                bb_pos = (close - bb_l) / bb_range
                if bb_pos < 0.1:
                    score += 20   # near lower band
                elif bb_pos < 0.25:
                    score += 12
                elif bb_pos > 0.9:
                    score -= 20   # near upper band
                elif bb_pos > 0.75:
                    score -= 12

        # RSI
        if rsi < 25:
            score += 10
        elif rsi < 35:
            score += 5
        elif rsi > 75:
            score -= 10
        elif rsi > 65:
            score -= 5

        # EMA crossover
        if ema9 > ema21 > 0:
            score += 5
        elif ema9 < ema21 > 0:
            score -= 5

        # SuperTrend
        if st > 0 and close > st:
            score += 4
        elif st > 0 and close < st:
            score -= 4

        # MACD
        if macd > macd_s:
            score += 3
        elif macd < macd_s:
            score -= 3

    return score


# ── Fundamental Scoring ───────────────────────────────────────────────────

def compute_fund_score(row):
    """Compute fundamental score from row data."""
    score = 0
    pe  = float(row.get("PE", 0) or 0)
    pb  = float(row.get("PB", 0) or 0)
    roe = float(row.get("ROE", 0) or 0)
    dy  = float(row.get("Dividend_Yield", 0) or 0)
    de  = float(row.get("Debt_Equity", 0) or 0)

    if 0 < pe < 15:
        score += 5
    elif 15 <= pe < 25:
        score += 2
    elif pe > 50:
        score -= 3

    if 0 < pb < 2:
        score += 3
    elif pb > 5:
        score -= 2

    if roe > 20:
        score += 5
    elif roe > 12:
        score += 2
    elif roe < 5 and roe > 0:
        score -= 2

    if dy > 3:
        score += 3
    elif dy > 1:
        score += 1

    if 0 < de < 0.5:
        score += 2
    elif de > 2:
        score -= 3

    return score


# ── Market Regime ─────────────────────────────────────────────────────────

def compute_market_regime(stock_df):
    """Compute market regime from Nifty proxy + breadth."""
    # Use breadth: % of tickers where close > SMA_22
    latest = stock_df.groupby("Ticker").tail(1)
    if latest.empty:
        return "CHOPPY", 50, 0

    above = 0
    total = 0
    for _, row in latest.iterrows():
        c = float(row.get("Close", 0) or 0)
        s = float(row.get("SMA_22", 0) or 0)
        if c > 0 and s > 0:
            total += 1
            if c > s:
                above += 1

    breadth = int(above / total * 100) if total else 50

    # Nifty 5d return proxy (average 5d return of large caps)
    nifty_5d = 0
    for _, row in latest.iterrows():
        mcap = float(row.get("Market_Cap", 0) or 0)
        if mcap >= MCAP_THRESHOLD * 20:
            c = float(row.get("Close", 0) or 0)
            s9 = float(row.get("SMA_9", 0) or 0)
            if c > 0 and s9 > 0:
                nifty_5d += (c - s9) / s9 * 100

    if breadth >= 65 and nifty_5d > 1:
        regime = "BULL"
    elif breadth <= 35 and nifty_5d < -1:
        regime = "BEAR"
    else:
        regime = "CHOPPY"

    print(f"  -> Nifty 5d: {int(nifty_5d)}%")
    print(f"  -> Breadth: {breadth}%")
    print(f"  -> REGIME: {regime}")
    return regime, breadth, int(nifty_5d)


# ── Sector Strength ───────────────────────────────────────────────────────

def compute_sector_strength(stock_df, sector_map):
    """Compute sector-level momentum."""
    sector_scores = {}
    latest = stock_df.groupby("Ticker").tail(1)
    sector_tickers = defaultdict(list)
    for _, row in latest.iterrows():
        tk = str(row.get("Ticker", "")).strip()
        sec = sector_map.get(tk, "Other")
        sector_tickers[sec].append(row)

    for sec, rows in sector_tickers.items():
        rets = []
        for row in rows:
            c = float(row.get("Close", 0) or 0)
            s = float(row.get("SMA_22", 0) or 0)
            if c > 0 and s > 0:
                rets.append((c - s) / s * 100)
        avg = np.mean(rets) if rets else 0
        sector_scores[sec] = round(avg, 1)
        print(f"    {sec} ({len(rows)}): {avg:+.0f}")

    return sector_scores


# ── Composite Scoring ─────────────────────────────────────────────────────

def compute_composite(tech, macro, fund, news, regime, news_dir=0):
    """Compute final composite score with regime dampening."""
    base = (tech * TECH_WEIGHT + macro * MACRO_WEIGHT +
            fund * FUND_WEIGHT + news * NEWS_WEIGHT)

    # News catalyst boost
    if news != 0:
        base += news * 0.3  # extra weight for catalyst

    # Regime dampening
    bull_damp = 1.0
    bear_damp = 1.0
    if regime == "BEAR":
        bull_damp = 0.7
    elif regime == "BULL":
        bear_damp = 0.7

    if base > 0:
        base *= bull_damp
    elif base < 0:
        base *= bear_damp

    return round(base, 1)


# ── Chart JSON generation ─────────────────────────────────────────────────

def generate_chart_data(ticker, stock_df, history_df, output_dir):
    """Generate chart JSON with OHLCV, indicators, and signal markers."""
    tdf = stock_df[stock_df["Ticker"].astype(str).str.strip() == ticker].copy()
    if tdf.empty:
        return

    tdf = tdf.sort_values("Date").tail(365)
    tdf["Date"] = tdf["Date"].astype(str).str[:10]

    data = {
        "ohlc": [], "volume": [], "markers": [],
        "sma9": [], "sma22": [], "sma200": [],
        "ema9": [], "ema21": [], "vwap": [],
        "bb_upper": [], "bb_lower": [],
        "st_bull": [], "st_bear": [],
        "ichi_tenkan": [], "ichi_kijun": [], "ichi_spanA": [], "ichi_spanB": [],
        "rsi": [], "macd_line": [], "macd_signal": [], "macd_hist": [],
        "adx": [],
    }

    for _, row in tdf.iterrows():
        d = str(row["Date"])[:10]
        o = float(row.get("Open", 0) or 0)
        h = float(row.get("High", 0) or 0)
        l = float(row.get("Low", 0) or 0)
        c = float(row.get("Close", 0) or 0)
        v = float(row.get("Volume", 0) or 0)

        if c == 0:
            continue

        data["ohlc"].append({"time": d, "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2)})
        color = "#22c55e88" if c >= o else "#ef444488"
        data["volume"].append({"time": d, "value": int(v), "color": color})

        # Indicators
        for col, key in [("SMA_9", "sma9"), ("SMA_22", "sma22"), ("SMA_200", "sma200"),
                         ("EMA_9", "ema9"), ("EMA_21", "ema21"), ("VWAP", "vwap"),
                         ("BB_Upper", "bb_upper"), ("BB_Lower", "bb_lower")]:
            val = float(row.get(col, 0) or 0)
            if val > 0:
                data[key].append({"time": d, "value": round(val, 2)})

        # SuperTrend
        st = float(row.get("SuperTrend", 0) or 0)
        if st > 0:
            if c > st:
                data["st_bull"].append({"time": d, "value": round(st, 2)})
            else:
                data["st_bear"].append({"time": d, "value": round(st, 2)})

        # Ichimoku
        for col, key in [("Ichimoku_Tenkan", "ichi_tenkan"), ("Ichimoku_Kijun", "ichi_kijun"),
                         ("Ichimoku_SpanA", "ichi_spanA"), ("Ichimoku_SpanB", "ichi_spanB")]:
            val = float(row.get(col, 0) or 0)
            if val > 0:
                data[key].append({"time": d, "value": round(val, 2)})

        # RSI
        rsi = float(row.get("RSI", 0) or 0)
        if rsi > 0:
            data["rsi"].append({"time": d, "value": round(rsi, 2)})

        # MACD
        ml = float(row.get("MACD", 0) or 0)
        ms = float(row.get("MACD_Signal", 0) or 0)
        mh = ml - ms
        data["macd_line"].append({"time": d, "value": round(ml, 4)})
        data["macd_signal"].append({"time": d, "value": round(ms, 4)})
        mc = "#22c55e" if mh >= 0 else "#ef4444"
        data["macd_hist"].append({"time": d, "value": round(mh, 4), "color": mc})

        # ADX
        adx = float(row.get("ADX", 0) or 0)
        if adx > 0:
            data["adx"].append({"time": d, "value": round(adx, 2)})

    # ── Signal markers from history ──
    if history_df is not None and len(history_df) > 0:
        hdf_tk = history_df[history_df["Ticker"].astype(str).str.strip() == ticker]
        date_set = set(str(r["Date"])[:10] for _, r in tdf.iterrows())

        for _, hr in hdf_tk.iterrows():
            raw_dir = hr.get("Composite_Direction", 0)
            if pd.isna(raw_dir):
                continue
            hdir = int(raw_dir)
            if hdir == 0:
                continue
            hdate = str(hr.get("Date", ""))[:10]
            if hdate not in date_set:
                continue

            if hdir == 1:
                data["markers"].append({
                    "time": hdate, "position": "belowBar",
                    "color": "#22c55e", "shape": "arrowUp", "text": "BULL"
                })
            else:
                data["markers"].append({
                    "time": hdate, "position": "aboveBar",
                    "color": "#ef4444", "shape": "arrowDown", "text": "BEAR"
                })

    data["markers"].sort(key=lambda m: m["time"])

    # DEBUG: print marker count
    if data["markers"]:
        print(f"    {ticker}: {len(data['markers'])} markers")

    out_path = os.path.join(output_dir, ticker + ".json")
    with open(out_path, "w") as f:
        json.dump(data, f, separators=(",", ":"))


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    print(f"Smart Data Sync | {today_str}")

    # ── Data sync ──
    smart_sync()

    # ── Recompute indicators ──
    recompute_indicators()

    # ── Load data ──
    tickers, sector_map = load_tickers()
    stock_df = pd.read_csv(DATA_FILE, low_memory=False)
    print(f"  -> Loaded stock_data.csv: {stock_df['Ticker'].nunique()} tickers, {len(stock_df):,} rows (~{len(stock_df)//stock_df['Ticker'].nunique()} days/ticker)")

    # Verify columns
    required = ["Ticker", "Date", "Open", "High", "Low", "Close", "Volume",
                 "RSI", "MACD", "MACD_Signal", "SMA_9", "SMA_22", "SMA_200",
                 "EMA_9", "EMA_21", "BB_Upper", "BB_Lower", "ADX",
                 "SuperTrend", "ATR_Pct", "Market_Cap"]
    found = [c for c in required if c in stock_df.columns]
    print(f"  -> Found: {len(found)}/{len(required)} key columns")
    print(f"  -> MCap threshold: {MCAP_THRESHOLD}")

    # ── Load history ──
    hdf = pd.DataFrame()
    if HISTORY_FILE.exists():
        hdf = pd.read_csv(HISTORY_FILE)
        hdf["Ticker"] = hdf["Ticker"].astype(str).str.strip()

    now_str = datetime.now().strftime("%I:%M %p")
    print(f"\nPREDICTIVE Engine v{VERSION} - {len(tickers)} tickers | {today_str}")
    print(f"News: {(today - timedelta(days=NEWS_WINDOW_DAYS)).strftime('%Y-%m-%d')} to {now_str} | CATALYST-ONLY FinBERT")
    print(f"Tech: MEGA/LARGE=SMA9-reversal(strict) | MID/SMALL=BB-centric")
    print(f"Horizons: MEGA={HORIZONS['MEGA']}d LARGE={HORIZONS['LARGE']}d MID={HORIZONS['MID']}d SMALL={HORIZONS['SMALL']}d")
    print(f"MinHold: MEGA={HOLD_DAYS['MEGA']}d LARGE={HOLD_DAYS['LARGE']}d MID={HOLD_DAYS['MID']}d SMALL={HOLD_DAYS['SMALL']}d")
    print(f"SL: ATR-based LC | -{STOP_LOSS_PCT*100:.1f}% fixed SC | Neutral band: sigma-based")
    print(f"Entry: +/-{ENTRY_THRESHOLD_LC} | Exit: +/-{EXIT_THRESHOLD_LC}")
    print("=" * 110)

    # ── PHASE 1: News ──
    print(f"\nPHASE 1: Fetching predictive news...")
    print("-" * 110)
    ticker_articles = fetch_news(tickers)
    print("-" * 110)

    # ── PHASE 2: FinBERT ──
    print(f"\nPHASE 2: FinBERT scoring (CATALYST-ONLY)...")
    print("-" * 110)
    news_results = run_finbert_phase(ticker_articles, tickers, stock_df, hdf)

    # ── PHASE 3: Multi-layer analysis ──
    print(f"\nPHASE 3: Multi-layer analysis ({len(tickers)} tickers)...")
    print("-" * 110)

    print("Loading stock data...")
    print(f"  -> Loaded stock_data.csv: {stock_df['Ticker'].nunique()} tickers, {len(stock_df):,} rows (~{len(stock_df)//stock_df['Ticker'].nunique()} days/ticker)")
    print(f"  -> Found: {len(found)}/{len(required)} key columns")
    print(f"  -> MCap threshold: {MCAP_THRESHOLD}")

    # Compute tech scores
    print(f"Computing technical scores (v{VERSION} cap-aware)...")
    scored_rows = []
    for tk in tickers:
        tdf = stock_df[stock_df["Ticker"].astype(str).str.strip() == tk].sort_values("Date")
        if tdf.empty:
            continue

        last = tdf.iloc[-1]
        prev = tdf.iloc[-2] if len(tdf) >= 2 else None
        mcap = float(last.get("Market_Cap", 0) or 0)
        cat = classify_cap(mcap, MCAP_THRESHOLD)

        tech = compute_tech_score(last, cat, prev)

        # Debug first 3
        if len(scored_rows) < 3:
            sma9p = f"{float(prev.get('SMA_9', 0) or 0):.1f}" if prev is not None else "N/A"
            print(f"    DEBUG {tk}({cat[0]}{'MC' if cat in ('MID','SMALL') else 'C'}): "
                  f"RSI={float(last.get('RSI', 0) or 0):.1f}, Close={float(last.get('Close', 0) or 0)}, "
                  f"SMA9={float(last.get('SMA_9', 0) or 0):.1f}, SMA22={float(last.get('SMA_22', 0) or 0):.1f}, "
                  f"SMA200={float(last.get('SMA_200', 0) or 0):.1f}, SMA9prev={sma9p}, "
                  f"ATR={float(last.get('ATR_Pct', 0) or 0):.1f}%  Score={tech}")

        scored_rows.append({"Ticker": tk, "Category": cat, "Tech_Score": tech, "row": last, "prev": prev, "mcap": mcap})

    lc_count = sum(1 for r in scored_rows if r["Category"] in ("MEGA", "LARGE"))
    sc_count = sum(1 for r in scored_rows if r["Category"] in ("MID", "SMALL"))
    print(f"  -> {len(scored_rows)}/{len(tickers)} scored | LC:{lc_count} SMC:{sc_count}")

    # Compute fundamentals
    print("Computing fundamentals...")
    for sr in scored_rows:
        sr["Fund_Score"] = compute_fund_score(sr["row"])
    nz_fund = sum(1 for r in scored_rows if r["Fund_Score"] != 0)
    print(f"  -> {nz_fund}/{len(scored_rows)} with non-zero fund score")
    print(f"  -> {len(sector_map)}/{len(scored_rows)} mapped to {len(set(sector_map.values()))} sectors")

    # Market regime
    print(f"\nComputing market regime...")
    regime, breadth, nifty_5d = compute_market_regime(stock_df)

    # Sector strength
    print(f"\nComputing sector strength...")
    sector_scores = compute_sector_strength(stock_df, sector_map)

    # ── PHASE 3b: Backtest ──
    print(f"\nPHASE 3b: Backtest (ATR SL for LC, {STOP_LOSS_PCT*100:.1f}% SL for SC)...")

    bt_results = []
    for tk in tickers:
        r = compute_per_ticker_accuracy(stock_df, tk)
        if r:
            bt_results.append(r)

    # Print per-category accuracy summary
    if bt_results:
        btdf = pd.DataFrame(bt_results)
        print(f"\n  Per-category accuracy (DIRECTIONAL ONLY, neutral excluded):")
        print(f"  {'Cat':<10s}  {'N':>3s}  {'DirAcc':>6s}  {'SigRate':>7s}   {'σ-Thr':>6s}  {'Entry':>5s}   {'AvgSL':>5s}   {'Fwd':>3s}")
        print("  " + "-" * 60)
        for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
            cr = btdf[btdf["Category"] == cat]
            cr_dir = cr[cr["dir_preds"] > 0]
            if cr_dir.empty:
                continue
            w_acc = cr_dir["dir_hits"].sum() / cr_dir["dir_preds"].sum() * 100 if cr_dir["dir_preds"].sum() > 0 else 0
            avg_sig = cr_dir["signal_rate"].mean()
            avg_sigma = cr_dir["sigma_threshold"].mean()
            is_lc = cat in ("MEGA", "LARGE")
            entry = ENTRY_THRESHOLD_LC if is_lc else ENTRY_THRESHOLD_SC
            avg_sl = cr_dir["sl_pct"].mean()
            fwd = HORIZONS[cat]
            print(f"  {cat:<10s} {len(cr_dir):>3d}  {w_acc:>5.1f}%  {avg_sig:>6.1f}%  ±{avg_sigma:>.2f}%  ± {entry:<2d}    {avg_sl:>.1f}%   {fwd:>2d}d")

        # Trade sim summary
        print(f"\n  Per-category TRADE SIMULATION:")
        print(f"  SL: MEGA={btdf[btdf['Category']=='MEGA']['sl_pct'].mean():.1f}%ATR | LARGE={btdf[btdf['Category']=='LARGE']['sl_pct'].mean():.1f}%ATR | MID/SMALL={STOP_LOSS_PCT*100:.1f}%fixed")
        print(f"  Entry: LC±{ENTRY_THRESHOLD_LC} SC±{ENTRY_THRESHOLD_SC} | Exit: LC±{EXIT_THRESHOLD_LC} SC±{EXIT_THRESHOLD_SC} | MinHold:cap-based")
        print(f"  {'Cat':<10s} {'Trades':>6s}  {'WinR':>5s}   {'AvgW':>6s}   {'AvgL':>6s}    {'PF':>5s}  {'TotRet':>7s}  {'Hold':>6s}  {'SL%':>4s}  {'Flip':>4s}  {'AvgSL':>5s}")
        print("  " + "-" * 85)
        for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
            cr = btdf[(btdf["Category"] == cat) & (btdf["TR_total_trades"] >= 1)]
            if cr.empty:
                continue
            nt = int(cr["TR_total_trades"].sum())
            nw = int((cr["TR_win_rate"] * cr["TR_total_trades"] / 100).sum())
            wr = nw / nt * 100 if nt else 0
            aw = (cr["TR_avg_win_pct"] * cr["TR_total_trades"]).sum() / nt if nt else 0
            al = (cr["TR_avg_loss_pct"] * cr["TR_total_trades"]).sum() / nt if nt else 0
            gw = (cr["TR_avg_win_pct"] * cr["TR_win_rate"] / 100 * cr["TR_total_trades"]).sum()
            gl = (cr["TR_avg_loss_pct"] * (100 - cr["TR_win_rate"]) / 100 * cr["TR_total_trades"]).sum()
            pf = gw / gl if gl > 0 else 0
            ret = cr["TR_total_return_pct"].sum() / len(cr) if len(cr) else 0
            hld = (cr["TR_avg_holding_days"] * cr["TR_total_trades"]).sum() / nt if nt else 0
            sl_p = int(cr["TR_sl_exits"].sum()) / nt * 100 if nt else 0
            flp = int(cr["TR_flips"].sum())
            asl = cr["sl_pct"].mean()
            sign = "+" if ret > 0 else ""
            print(f"  {cat:<10s} {nt:>6d}  {wr:>4.1f}%  {aw:>5.2f}%  {al:>5.2f}%  {pf:>5.2f}  {sign}{ret:>5.1f}%  {hld:>4.1f}d {sl_p:>4.1f}%  {flp:>4d}  {asl:>4.1f}%")

    # ── Compute composite + regime adjustment ──
    print(f"\nComputing composite + regime adjustment...")
    bull_damp = 1.0; bear_damp = 1.0
    if regime == "BEAR":
        bull_damp = 0.7
    elif regime == "BULL":
        bear_damp = 0.7
    print(f"  Regime: {regime} -> bull_damp={bull_damp} bear_damp={bear_damp}")
    print("-" * 110)

    all_rows = []
    news_hit = 0; tech_bull = 0; tech_bear = 0; tech_neut = 0
    same_day_hit = 0; same_day_total = 0; flips = 0

    for sr in scored_rows:
        tk = sr["Ticker"]
        cat = sr["Category"]
        tech = sr["Tech_Score"]
        fund = sr["Fund_Score"]
        row = sr["row"]

        # Macro score (sector + regime context)
        sec = sector_map.get(tk, "Other")
        macro = sector_scores.get(sec, 0)

        # News
        nr = news_results.get(tk, {})
        news_score = nr.get("News_Score", 0)
        news_dir = nr.get("News_Direction", "NEUT")
        n_cat = nr.get("N_Catalysts", 0)

        # Composite
        comp = compute_composite(tech, macro, fund, news_score, regime)

        # Direction
        is_lc = cat in ("MEGA", "LARGE")
        entry = ENTRY_THRESHOLD_LC if is_lc else ENTRY_THRESHOLD_SC
        if comp >= entry:
            direction = 1
            dir_label = "BULL"
            tech_bull += 1
        elif comp <= -entry:
            direction = -1
            dir_label = "BEAR"
            tech_bear += 1
        else:
            direction = 0
            dir_label = "NEUT"
            tech_neut += 1

        # Actual return
        tdf_tk = stock_df[stock_df["Ticker"].astype(str).str.strip() == tk].sort_values("Date")
        act_ret = 0
        if len(tdf_tk) >= 2:
            c_today = float(tdf_tk.iloc[-1].get("Close", 0) or 0)
            c_prev = float(tdf_tk.iloc[-2].get("Close", 0) or 0)
            if c_prev > 0:
                act_ret = (c_today - c_prev) / c_prev * 100

        # Same-day accuracy
        if direction != 0:
            same_day_total += 1
            actual_dir = 1 if act_ret > 0 else (-1 if act_ret < 0 else 0)
            if is_hit(direction, actual_dir):
                same_day_hit += 1

        # Check history for severity/hit
        severity = "NEUT"
        if direction != 0 and not hdf.empty:
            prev_rows = hdf[hdf["Ticker"].astype(str).str.strip() == tk]
            if not prev_rows.empty:
                last_h = prev_rows.iloc[-1]
                last_dir = int(last_h.get("Composite_Direction", 0) or 0)
                if last_dir != 0:
                    actual_dir_h = 1 if act_ret > 0 else (-1 if act_ret < 0 else 0)
                    severity = "HIT" if is_hit(last_dir, actual_dir_h) else "MISS"

        # BT accuracy for this ticker
        bt = next((r for r in bt_results if r["Ticker"] == tk), {})
        bt_acc = bt.get("dir_accuracy", 0)
        bt_pf = bt.get("TR_profit_factor", 0)

        if direction != 0 or n_cat > 0:
            fwd = HORIZONS.get(cat, 14)
            print(f"  [{scored_rows.index(sr)+1:>3d}] {tk:<18s} Tech: {tech:>+3d} Macro: {macro:>+3d} Fund: {fund:>+3d} -> "
                  f"Comp: {comp:>+5.1f} {dir_label} {severity}  BT:{bt_acc:.0f}%/{cat} H:{fwd}d")

        # Build output row
        out = {
            "Ticker": tk,
            "Category": cat,
            "BT_Category": cat,
            "Sector": sec,
            "Market_Cap": sr["mcap"],
            "Close": float(row.get("Close", 0) or 0),
            "Tech_Score": tech,
            "Technical_Score": tech,
            "Macro_Score": round(macro, 1),
            "Fund_Score": fund,
            "Fundamental_Score": fund,
            "News_Score": news_score,
            "Forecast_Score": news_score,
            "N_Catalysts": n_cat,
            "News_Direction": news_dir,
            "Composite_Score": comp,
            "Composite_Direction": direction,
            "Forecast_Direction": direction,
            "Direction_Label": dir_label,
            "Composite_Severity": severity,
            "Actual_Return_Pct": round(act_ret, 2),
            "Regime": regime,
            # Backtest
            "BT_6M": round(bt_acc, 1),
            "BT_Accuracy": round(bt_acc, 1),
            "BT_1M": round(bt.get("dir_accuracy", 0), 1),
            "BT_3M": round(bt.get("dir_accuracy", 0), 1),
            "BT_Forward_Days": HORIZONS.get(cat, 14),
            "Horizon": HORIZONS.get(cat, 14),
            "BT_Threshold": round(bt.get("sigma_threshold", 4), 2),
            "BT_ATR_Pct": round(bt.get("atr_pct", 0), 1),
            "BT_SL_Level": round(bt.get("sl_pct", 5), 1),
            "BT_PF": round(bt_pf, 2),
            "BT_Trades": int(bt.get("TR_total_trades", 0)),
            # Trade sim
            "TR_total_trades": int(bt.get("TR_total_trades", 0)),
            "TR_win_rate": round(bt.get("TR_win_rate", 0), 1),
            "TR_avg_win_pct": round(bt.get("TR_avg_win_pct", 0), 2),
            "TR_avg_loss_pct": round(bt.get("TR_avg_loss_pct", 0), 2),
            "TR_profit_factor": round(bt_pf, 2),
            "TR_total_return_pct": round(bt.get("TR_total_return_pct", 0), 1),
            "TR_avg_holding_days": round(bt.get("TR_avg_holding_days", 0), 1),
            "TR_sl_exits": int(bt.get("TR_sl_exits", 0)),
            "TR_flips": int(bt.get("TR_flips", 0)),
            "TR_long_win_rate": 0,
            "TR_short_win_rate": 0,
        }
        all_rows.append(out)

    sd_acc = same_day_hit / same_day_total * 100 if same_day_total else 0
    print(f"\n  Tech-only: Bull:{tech_bull} Bear:{tech_bear} Neut:{tech_neut} | Hit:{same_day_hit}/{same_day_total} = {sd_acc:.1f}%")

    # ── PHASE 4: Save ──
    print(f"\nPHASE 4: Save...")
    print("-" * 110)

    # Save data.csv
    out_df = pd.DataFrame(all_rows)
    out_df.to_csv(OUTPUT_CSV, index=False)

    # Update history
    today_rows = out_df[["Ticker", "Category", "Composite_Score", "Composite_Direction",
                          "Direction_Label", "Actual_Return_Pct", "Tech_Score", "Fund_Score",
                          "News_Score", "Macro_Score"]].copy()
    today_rows["Date"] = today_str

    if not hdf.empty:
        hdf = pd.concat([hdf, today_rows], ignore_index=True)
    else:
        hdf = today_rows.copy()

    # Keep last 90 days
    if "Date" in hdf.columns:
        hdf["Date"] = hdf["Date"].astype(str).str[:10]
        cutoff = (today - timedelta(days=90)).strftime("%Y-%m-%d")
        hdf = hdf[hdf["Date"] >= cutoff]

    hdf.to_csv(HISTORY_FILE, index=False)
    print(f"History: {len(hdf)} rows / {hdf['Date'].nunique() if 'Date' in hdf.columns else 0} days")

    # ── PHASE 5: Charts + Meta ──
    print(f"\nPHASE 5: Generating chart JSON + meta...")
    print("-" * 110)

    os.makedirs(CHARTS_DIR, exist_ok=True)

    # Normalize history dates for marker matching
    if "Date" in hdf.columns:
        hdf["Date"] = hdf["Date"].astype(str).str[:10]

    for t in tickers:
        generate_chart_data(t, stock_df, hdf, CHARTS_DIR)

    print(f"  -> Chart JSON: {len(tickers)} tickers in charts/")

    # Meta
    avg_acc = np.mean([r.get("BT_6M", 0) for r in all_rows if r.get("BT_6M", 0) > 0]) if all_rows else 0
    avg_pf = np.mean([r.get("TR_profit_factor", 0) for r in all_rows if r.get("TR_profit_factor", 0) > 0]) if all_rows else 0

    meta = {
        "date": today_str,
        "version": VERSION,
        "tickers": len(tickers),
        "total_tickers": len(tickers),
        "regime": regime,
        "breadth": breadth,
        "nifty_5d": nifty_5d,
        "avg_accuracy": round(avg_acc, 1),
        "direction_accuracy": round(avg_acc, 1),
        "avg_profit_factor": round(avg_pf, 2),
        "avg_pf": round(avg_pf, 2),
        "bulls": tech_bull,
        "bears": tech_bear,
        "neutrals": tech_neut,
        "same_day_accuracy": round(sd_acc, 1),
    }
    with open(META_JSON, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  -> meta.json saved (PF:{avg_pf:.2f} Acc:{avg_acc:.1f}%)")

    print(f"\n{'='*110}")

    # ── Summary ──
    sig_rate_pct = (tech_bull + tech_bear) / len(tickers) * 100 if tickers else 0
    print(f"data.csv | {today_str} | ENGINE v{VERSION} ATR SL + strict SMA9")
    print(f"TICKERS: {tech_bull + tech_bear} news | {tech_neut} no-news")
    print(f"REGIME: {regime} (breadth={breadth}% nifty={nifty_5d}%)")
    print(f"STRATEGY: LC({lc_count}) SMC({sc_count}) | MEGA/LARGE=SMA9-rev(strict) | MID/SMALL=BB")

    # Backtest summary
    total_bt_preds = sum(r.get("total_preds", 0) for r in bt_results)
    total_bt_dir = sum(r.get("dir_preds", 0) for r in bt_results)
    total_bt_hits = sum(r.get("dir_hits", 0) for r in bt_results)
    bt_dir_acc = total_bt_hits / total_bt_dir * 100 if total_bt_dir else 0
    all_bt_acc = np.mean([r.get("dir_accuracy", 0) for r in bt_results if r.get("dir_preds", 0) > 0]) if bt_results else 0

    print(f"BACKTEST: {len(bt_results)} tickers | {total_bt_preds:,} preds | 1M:{all_bt_acc:.1f}% ALL:{all_bt_acc:.1f}%")
    print(f"SAME-DAY: {same_day_hit}/{same_day_total} = {sd_acc:.1f}% | Bull:{tech_bull} Bear:{tech_bear} | Flips:{flips}")
    print("=" * 110)

    # ── Full report ──
    print_accuracy_report(stock_df, tickers, history_df=hdf)


if __name__ == "__main__":
    main()
