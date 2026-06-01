import pandas as pd
import yfinance as yf
import feedparser
import requests
import re
import time
import urllib.parse
import os
from datetime import datetime, timezone, timedelta

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

# ============================================================
# BROWSER HEADERS
# ============================================================
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-IN,en;q=0.9",
}
feedparser.USER_AGENT = BROWSER_HEADERS["User-Agent"]

print("🤖 Initializing FinBERT Neural Network Pipeline...")
FINBERT_MODEL = "ProsusAI/finbert"
tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_IST = NOW_IST.strftime("%Y-%m-%d")

TICKERS_FILE = "tickers.csv"
HISTORY_FILE = "history.csv"
DATA_FILE = "data.csv"

SOURCE_LABELS = {
    "mc_topnews": "Moneycontrol", "mc_business": "Moneycontrol",
    "mc_markets": "Moneycontrol", "mc_stocks": "Moneycontrol",
    "et_markets": "Economic Times", "et_stocks": "Economic Times",
    "et_news": "Economic Times",
    "ndtv_business": "NDTV Profit",
    "mint_market": "LiveMint", "mint_companies": "LiveMint",
    "nse_announce": "NSE Official", "nse_actions": "NSE Official",
    "yfinance": "Yahoo Finance", "google": "Google News",
    "fallback": "—",
}

# Source credibility weights for aggregated scoring
# Higher weight = more influence on final score
SOURCE_WEIGHTS = {
    "mc_topnews": 1.5, "mc_business": 1.3, "mc_markets": 1.2, "mc_stocks": 1.2,
    "et_markets": 1.4, "et_stocks": 1.3, "et_news": 1.3,
    "ndtv_business": 1.2,
    "mint_market": 1.2, "mint_companies": 1.1,
    "nse_announce": 0.6, "nse_actions": 0.5,   # Low: regulatory filings are mostly neutral noise
    "yfinance": 1.0, "google": 1.0,
    "fallback": 0.0,
}


# ============================================================
# LOAD TICKERS
# ============================================================
def load_tickers():
    if os.path.exists(TICKERS_FILE):
        try:
            df = pd.read_csv(TICKERS_FILE)
            df.columns = df.columns.str.strip()
            if 'Ticker' not in df.columns:
                df.rename(columns={df.columns[0]: 'Ticker'}, inplace=True)
            tickers = df['Ticker'].dropna().str.strip().str.upper().tolist()
            tickers = [t.replace('.NS', '') for t in tickers if t]
            seen = set()
            unique = []
            for t in tickers:
                if t not in seen: seen.add(t); unique.append(t)
            sector_map = {}
            if 'Sector' in df.columns:
                for _, row in df.iterrows():
                    tk = str(row['Ticker']).strip().upper().replace('.NS', '')
                    sec = str(row.get('Sector', '')).strip()
                    if tk and sec: sector_map[tk] = sec
            print(f"📋 Loaded {len(unique)} tickers from {TICKERS_FILE}")
            return unique, sector_map
        except Exception as e:
            print(f"⚠️ Error reading {TICKERS_FILE}: {e}")
    print(f"⚠️ {TICKERS_FILE} not found — using defaults")
    return ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ICICIBANK", "ITC"], {}


# ============================================================
# RSS FEEDS
# ============================================================
ALL_FEEDS = {
    "mc_topnews":    "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "mc_business":   "https://www.moneycontrol.com/rss/business.xml",
    "mc_markets":    "https://www.moneycontrol.com/rss/marketreports.xml",
    "mc_stocks":     "https://www.moneycontrol.com/rss/latestnews.xml",
    "et_markets":    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks":     "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "et_news":       "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146843.cms",
    "ndtv_business": "https://feeds.feedburner.com/ndtvprofit-latest",
    "mint_market":   "https://www.livemint.com/rss/market",
    "mint_companies":"https://www.livemint.com/rss/companies",
    "nse_announce":  "https://archives.nseindia.com/content/RSS/Online_announcements.xml",
    "nse_actions":   "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
}


# ============================================================
# COMPANY ALIASES
# ============================================================
COMPANY_ALIASES = {
    "EICHER MOTORS": "EICHERMOT", "EICHER": "EICHERMOT",
    "HERO MOTOCORP": "HEROMOTOCO", "HERO MOTO": "HEROMOTOCO",
    "MARUTI SUZUKI": "MARUTI", "ESCORTS KUBOTA": "ESCORTS",
    "BOSCH": "BOSCHLTD", "BHARAT ELECTRONICS": "BEL",
    "DATA PATTERNS": "DATAPATTNS", "GARDEN REACH": "GRSE",
    "HINDUSTAN AERONAUTICS": "HAL", "MAZAGON DOCK": "MAZDOCK",
    "PERSISTENT SYSTEMS": "PERSISTENT", "ZENSAR": "ZENSARTECH",
    "COFORGE": "COFORGE", "NATIONAL ALUMINIUM": "NATIONALUM",
    "NALCO": "NATIONALUM", "HINDUSTAN COPPER": "HINDCOPPER",
    "COAL INDIA": "COALINDIA", "HDFC AMC": "HDFCAMC",
    "ANGEL ONE": "ANGELONE", "MOTILAL OSWAL": "MOTILALOFS",
    "CRISIL": "CRISIL", "CARE RATINGS": "CARERATING",
    "ICRA": "ICRA", "ITC": "ITC",
    "JYOTHY LABS": "JYOTHYLAB", "KEI INDUSTRIES": "KEI",
    "POLYCAB": "POLYCAB", "NBCC": "NBCC",
    "NCC": "NCC", "CUMMINS INDIA": "CUMMINSIND",
    "ABB": "ABB", "ABB INDIA": "ABB",
    "POWER FINANCE": "PFC", "REC LTD": "RECLTD",
    "GLOBAL HEALTH": "MEDANTA", "BLUE STAR": "BLUESTARCO",
    "LINDE INDIA": "LINDEINDIA", "SBI LIFE": "SBILIFE",
    "CASTROL": "CASTROLIND", "COROMANDEL": "COROMANDEL",
    "ABBOTT INDIA": "ABBOTINDIA", "ALKEM": "ALKEM",
    "CIPLA": "CIPLA", "TORRENT PHARMA": "TORNTPHARM",
    "SAFARI INDUSTRIES": "SAFARI", "TRENT": "TRENT",
    "LODHA": "LODHA", "MACROTECH": "LODHA",
    "BAJAJ FINANCE": "BAJFINANCE", "AU SMALL FINANCE": "AUBANK",
    "CHOLAMANDALAM": "CHOLAFIN", "MUTHOOT FINANCE": "MUTHOOTFIN",
    "SHRIRAM FINANCE": "SHRIRAMFIN", "SUNDARAM FINANCE": "SUNDARMFIN",
    "HUDCO": "HUDCO", "MCX": "MCX",
    "GRAVITA": "GRAVITA", "APL APOLLO": "APLAPOLLO",
    "AFFLE": "AFFLE", "HYUNDAI": "HYUNDAI",
    "BIKAJI": "BIKAJI", "ORACLE FINANCIAL": "OFSS",
    "BAJAJ HOLDINGS": "BAJAJHLDNG", "RAILTEL": "RAILTEL",
    "DOMS": "DOMS", "DODLA DAIRY": "DODLA",
    "LT FOODS": "LTFOODS", "WELSPUN CORP": "WELCORP",
    "INGERSOLL RAND": "INGERRAND", "KIRLOSKAR": "KIRLOSBROS",
    "SHAKTI PUMPS": "SHAKTIPUMP", "TD POWER SYSTEMS": "TDPOWERSYS",
    "UNO MINDA": "UNOMINDA", "HOME FIRST": "HOMEFIRST",
    "CAN FIN HOMES": "CANFINHOME", "NUVAMA": "NUVAMA",
    "GROWW": "GROWW", "TEGA": "TEGA",
    "ENDURANCE": "ENDURANCE", "SANSERA": "SANSERA",
    "TIPS MUSIC": "TIPSMUSIC", "GOLDIAM": "GOLDIAM",
    "NEWGEN": "NEWGEN", "RATEGAIN": "RATEGAIN",
    "ECLERX": "ECLERX", "VOLTAMP": "VOLTAMP",
    "ELECON": "ELECON", "PRUDENT": "PRUDENT",
    "MARKSANS": "MARKSANS", "SUPRIYA": "SUPRIYA",
    "MARATHON": "MARATHON",
}


# ============================================================
# HELPERS
# ============================================================
def extract_pub_datetime(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            dt_utc = datetime(*parsed[:6], tzinfo=timezone.utc)
            dt_ist = dt_utc.astimezone(IST)
            return dt_ist.strftime("%d %b %Y %I:%M %p")
        except Exception:
            pass
    raw = entry.get("published") or entry.get("updated") or ""
    return raw.strip()[:30] if raw else ""


def fetch_rss_with_headers(url, source_label, timeout=15):
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        response.raise_for_status()
        return feedparser.parse(response.content)
    except requests.exceptions.RequestException as e:
        print(f"   ⚠️ {source_label} requests failed: {e}")
        try: return feedparser.parse(url)
        except Exception: return None


def match_ticker_in_text(text_upper, tickers_list):
    for ticker in sorted(tickers_list, key=len, reverse=True):
        if re.search(r'\b' + re.escape(ticker.upper()) + r'\b', text_upper):
            return ticker
    for alias, ticker in COMPANY_ALIASES.items():
        if alias in text_upper and ticker in tickers_list:
            return ticker
    return None


# ============================================================
# FINBERT: Score a single headline
# ============================================================
def score_single_headline(headline):
    """Returns raw compound score (-100 to +100) for one headline."""
    if not headline or "Stable trade volatility" in headline:
        return 0.0
    try:
        inputs = tokenizer([headline], padding=True, truncation=True,
                           max_length=512, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
        return (probs[0][0].item() - probs[0][1].item()) * 100.0
    except Exception as e:
        print(f"  ⚠️ NLP crash: {e}")
        return 0.0


def compute_aggregated_score(headline_entries):
    """
    Takes a list of {headline, source, weight} dicts.
    Scores each headline individually via FinBERT.
    Returns weighted average score and direction.

    Example:
      MC:  "Coal India Q1 output drops 8%"     → -72.4  × weight 1.5
      ET:  "Coal India shares rally on dividend"→ +84.2  × weight 1.4
      NSE: "Board Meeting Outcome"              →  +1.0  × weight 0.6
      ────────────────────────────────────────────
      Weighted avg = (-72.4×1.5 + 84.2×1.4 + 1.0×0.6) / (1.5+1.4+0.6)
                   = (-108.6 + 117.88 + 0.6) / 3.5
                   = +2.8 → Neutral
    """
    if not headline_entries:
        return 0.0, 0

    total_weight = 0.0
    weighted_sum = 0.0
    individual_scores = []

    for entry in headline_entries:
        raw_score = score_single_headline(entry["headline"])
        weight = entry.get("weight", 1.0)
        weighted_sum += raw_score * weight
        total_weight += weight
        individual_scores.append({
            "source": entry["source"],
            "headline": entry["headline"][:60],
            "raw_score": round(raw_score, 1),
            "weight": weight,
        })

    if total_weight == 0:
        return 0.0, 0

    compound_score = weighted_sum / total_weight

    if compound_score > 5.0: direction = 1
    elif compound_score < -5.0: direction = -1
    else: direction = 0

    return round(compound_score, 1), direction


# ============================================================
# PHASE 1: BUILD MULTI-HEADLINE CACHE
# Now stores ALL headlines per ticker, not just the first
# ============================================================
def build_exchange_news_cache(tickers_list):
    """
    Returns: {
      TICKER: [
        {headline, source, pub_time, weight},
        {headline, source, pub_time, weight},
        ...
      ]
    }
    """
    cache = {}  # ticker -> list of headline entries

    for source_key, url in ALL_FEEDS.items():
        print(f"📡 Fetching {source_key}...")
        feed = fetch_rss_with_headers(url, source_key)
        if not feed or not feed.entries:
            print(f"   ⚠️ {source_key}: No entries returned")
            continue

        match_count = 0
        for entry in feed.entries:
            title = entry.get("title", "")
            desc = entry.get("description", entry.get("summary", ""))
            full_text = f"{title} {desc}".upper()
            matched_ticker = match_ticker_in_text(full_text, tickers_list)

            if matched_ticker and title.strip():
                headline = title.strip().replace(",", ";")
                pub_time = extract_pub_datetime(entry)
                weight = SOURCE_WEIGHTS.get(source_key, 1.0)

                # Check for duplicate headlines (same ticker, same text)
                existing = cache.get(matched_ticker, [])
                is_dupe = any(e["headline"].lower() == headline.lower() for e in existing)
                if not is_dupe:
                    if matched_ticker not in cache:
                        cache[matched_ticker] = []
                    cache[matched_ticker].append({
                        "headline": headline,
                        "source": source_key,
                        "pub_time": pub_time,
                        "weight": weight,
                    })
                    match_count += 1

        print(f"   ✅ {source_key}: {match_count} new matches from {len(feed.entries)} entries")
        time.sleep(0.3)

    # Summary
    total_tickers = len(cache)
    total_headlines = sum(len(v) for v in cache.values())
    multi_count = sum(1 for v in cache.values() if len(v) >= 2)
    print(f"\n📦 News cache built: {total_tickers}/{len(tickers_list)} tickers | {total_headlines} total headlines")
    print(f"   📰 Tickers with multiple headlines: {multi_count}")

    return cache


# ============================================================
# PER-TICKER FALLBACKS
# ============================================================
def get_news_from_yfinance(ticker):
    try:
        yf_ticker = yf.Ticker(f"{ticker}.NS")
        news = getattr(yf_ticker, 'news', None)
        if news and isinstance(news, list) and len(news) > 0:
            first = news[0]
            if isinstance(first, dict):
                headline = first.get("title", first.get("headline", ""))
                pub_ts = first.get("providerPublishTime") or first.get("publish_time")
                pub_time = ""
                if pub_ts:
                    try: pub_time = datetime.fromtimestamp(int(pub_ts), tz=IST).strftime("%d %b %Y %I:%M %p")
                    except Exception: pass
                if headline: return headline.replace(",", ";"), pub_time
    except Exception: pass
    return None, ""


def get_news_from_google_rss(ticker):
    try:
        encoded = urllib.parse.quote(ticker)
        url = f"https://news.google.com/rss/search?q={encoded}+NSE+stock+india&hl=en-IN&gl=IN&ceid=IN:en"
        feed = fetch_rss_with_headers(url, f"google_{ticker}", timeout=8)
        if feed and feed.entries:
            entry = feed.entries[0]
            headline = re.sub(r'\s+-\s+[^:\-]+$', '', entry.title)
            pub_time = extract_pub_datetime(entry)
            return headline.replace(",", ";"), pub_time
    except Exception: pass
    return None, ""


def get_live_news_for_ticker(ticker, exchange_cache):
    """
    Returns: (list_of_headline_entries, primary_source, primary_pub_time)
    Aggregates ALL available headlines from cache + per-ticker fallbacks.
    """
    entries = []

    # 1. All headlines from bulk RSS cache
    if ticker in exchange_cache:
        entries.extend(exchange_cache[ticker])

    # 2. yfinance (per-ticker)
    headline, pub_time = get_news_from_yfinance(ticker)
    if headline:
        # Check for duplicate
        is_dupe = any(e["headline"].lower() == headline.lower() for e in entries)
        if not is_dupe:
            entries.append({
                "headline": headline,
                "source": "yfinance",
                "pub_time": pub_time,
                "weight": SOURCE_WEIGHTS.get("yfinance", 1.0),
            })

    # 3. Google News (per-ticker, last resort)
    if len(entries) < 3:  # Only fetch Google if we have < 3 headlines
        headline, pub_time = get_news_from_google_rss(ticker)
        if headline:
            is_dupe = any(e["headline"].lower() == headline.lower() for e in entries)
            if not is_dupe:
                entries.append({
                    "headline": headline,
                    "source": "google",
                    "pub_time": pub_time,
                    "weight": SOURCE_WEIGHTS.get("google", 1.0),
                })

    if entries:
        # Primary = highest weight entry (shown as main headline)
        primary = max(entries, key=lambda e: e["weight"])
        return entries, primary["source"], primary["pub_time"]

    # Fallback
    return [{
        "headline": f"Stable trade volatility tracked on exchange indices for {ticker}.",
        "source": "fallback",
        "pub_time": "",
        "weight": 0.0,
    }], "fallback", ""


# ============================================================
# PRICE
# ============================================================
def get_live_price_return(ticker_symbol):
    try:
        yf_ticker = yf.Ticker(f"{ticker_symbol}.NS")
        history = yf_ticker.history(period="5d")
        if len(history) >= 2:
            prev = history['Close'].iloc[-2]
            curr = history['Close'].iloc[-1]
            return round(((curr - prev) / prev) * 100, 2)
    except Exception: pass
    return 0.0


# ============================================================
# STREAKS
# ============================================================
def load_history():
    try:
        df = pd.read_csv(HISTORY_FILE)
        if 'Date' in df.columns:
            all_dates = sorted(df['Date'].unique(), reverse=True)[:30]
            df = df[df['Date'].isin(all_dates)]
        return df
    except FileNotFoundError:
        return pd.DataFrame()


def calculate_streaks(history_df, today_rows):
    streaks = {}
    for row in today_rows:
        ticker = row["Ticker"]
        today_dir = row["Forecast_Direction"]
        today_score = row["Forecast_Score"]
        today_return = row["Actual_Return_Pct"]
        if not history_df.empty and 'Ticker' in history_df.columns:
            th = history_df[(history_df['Ticker'] == ticker) & (history_df['Date'] != TODAY_IST)].sort_values('Date', ascending=False)
        else:
            th = pd.DataFrame()
        streak_days = 1
        streak_return = today_return
        if not th.empty:
            for _, hr in th.iterrows():
                if int(hr.get('Forecast_Direction', 0)) == today_dir and today_dir != 0:
                    streak_days += 1
                    streak_return += float(hr.get('Actual_Return_Pct', 0))
                else: break
        prev_score = float(th.iloc[0].get('Forecast_Score', 0)) if not th.empty else None
        if today_dir == 0: momentum = "Neutral"
        elif streak_days == 1: momentum = "New"
        elif prev_score is not None:
            if today_dir == 1: momentum = ("Strong" if streak_days >= 3 else "Building") if today_score >= prev_score else "Fading"
            elif today_dir == -1: momentum = ("Strong" if streak_days >= 3 else "Building") if today_score <= prev_score else "Fading"
            else: momentum = "Neutral"
        else: momentum = "New"
        streaks[ticker] = {"Streak_Days": streak_days if today_dir != 0 else 0, "Streak_Return": round(streak_return, 2), "Momentum": momentum}
    return streaks


def save_to_history(today_rows):
    history_df = load_history()
    today_df = pd.DataFrame(today_rows)
    today_df['Date'] = TODAY_IST
    if not history_df.empty and 'Date' in history_df.columns:
        history_df = history_df[history_df['Date'] != TODAY_IST]
    combined = pd.concat([history_df, today_df], ignore_index=True)
    if 'Date' in combined.columns:
        all_dates = sorted(combined['Date'].unique(), reverse=True)[:30]
        combined = combined[combined['Date'].isin(all_dates)]
    combined.to_csv(HISTORY_FILE, index=False)
    print(f"📜 History: {len(combined)} rows across {combined['Date'].nunique() if 'Date' in combined.columns else 1} days")


# ============================================================
# MAIN ENGINE
# ============================================================
def execute_sentiment_engine():
    tickers_list, sector_map = load_tickers()
    total = len(tickers_list)

    print(f"🚀 Running AI Swing Trading Engine — {total} tickers")
    print(f"📅 Date: {TODAY_IST}")
    print("=" * 90)

    # PHASE 1: Bulk pre-fetch (stores ALL headlines per ticker)
    print("\n📡 PHASE 1: Pre-fetching news from RSS feeds...")
    print("-" * 90)
    exchange_cache = build_exchange_news_cache(tickers_list)
    print("-" * 90)

    # PHASE 2: Process each ticker with aggregated scoring
    print(f"\n📊 PHASE 2: Processing {total} tickers (multi-headline aggregation)...")
    print("-" * 90)

    processed_rows = []
    source_stats = {}
    hits_all = 0
    multi_headline_count = 0

    for idx, ticker in enumerate(tickers_list, 1):
        print(f"[{idx:3d}/{total}] {ticker:<15s}", end=" ")

        # Get ALL headlines for this ticker
        all_entries, primary_source, primary_pub_time = get_live_news_for_ticker(ticker, exchange_cache)
        source_stats[primary_source] = source_stats.get(primary_source, 0) + 1

        if primary_source in ("yfinance", "google"):
            time.sleep(0.3)

        # Aggregate score across all headlines
        headline_count = len(all_entries)
        forecast_score, forecast_dir = compute_aggregated_score(all_entries)

        # Track multi-headline tickers
        if headline_count >= 2:
            multi_headline_count += 1

        realized_return = get_live_price_return(ticker)

        if realized_return > 0.25: actual_dir = 1
        elif realized_return < -0.25: actual_dir = -1
        else: actual_dir = 0

        is_hit = forecast_dir == actual_dir
        if is_hit: hits_all += 1

        # Primary headline for display
        primary_entry = max(all_entries, key=lambda e: e["weight"])
        display_headline = primary_entry["headline"]

        # All sources for this ticker
        unique_sources = list(dict.fromkeys(SOURCE_LABELS.get(e["source"], e["source"]) for e in all_entries if e["source"] != "fallback"))
        display_sources = " | ".join(unique_sources) if unique_sources else "—"

        # Console
        src_short = {"mc_topnews":"💰MC","mc_business":"💼MC","mc_markets":"📈MC","mc_stocks":"📰MC",
                     "et_markets":"📊ET","et_stocks":"📊ET","et_news":"📊ET","ndtv_business":"📺NDTV",
                     "mint_market":"🌿Mi","mint_companies":"🌿Mi","nse_announce":"🏛️NSE","nse_actions":"📋NSE",
                     "yfinance":"📰YF","google":"🔗GG","fallback":"⚪FB"}
        dir_map = {1: "🟢", -1: "🔴", 0: "⚪"}
        news_tag = f"[{headline_count}h]" if headline_count >= 2 else "    "
        print(f"{src_short.get(primary_source,'❓'):6s} {news_tag} {dir_map.get(forecast_dir,'⚪')} Score:{forecast_score:+6.1f} | Ret:{realized_return:+6.2f}% | {'✅' if is_hit else '❌'}")

        processed_rows.append({
            "Ticker": ticker,
            "Sector": sector_map.get(ticker, ""),
            "Latest_Headline": display_headline,
            "News_Source": display_sources,
            "News_Time": primary_pub_time.replace(",", "") if primary_pub_time else "",
            "Headline_Count": headline_count,
            "Forecast_Score": forecast_score,
            "Forecast_Direction": forecast_dir,
            "Actual_Direction": actual_dir,
            "Actual_Return_Pct": realized_return,
        })

    # PHASE 3: Streaks
    print(f"\n📜 PHASE 3: Calculating signal streaks...")
    print("-" * 90)
    history_df = load_history()
    streaks = calculate_streaks(history_df, processed_rows)

    final_rows = []
    for row in processed_rows:
        streak = streaks.get(row["Ticker"], {})
        row["Streak_Days"] = streak.get("Streak_Days", 0)
        row["Streak_Return"] = streak.get("Streak_Return", 0.0)
        row["Momentum"] = streak.get("Momentum", "Neutral")
        final_rows.append(row)

    df = pd.DataFrame(final_rows)
    df.to_csv(DATA_FILE, index=False)
    save_to_history(processed_rows)

    # Summary
    fb = source_stats.get("fallback", 0)
    bull = sum(1 for r in final_rows if r["Forecast_Direction"] == 1)
    bear = sum(1 for r in final_rows if r["Forecast_Direction"] == -1)
    neut = sum(1 for r in final_rows if r["Forecast_Direction"] == 0)
    hr = (hits_all / total) * 100 if total > 0 else 0

    print("\n" + "=" * 90)
    print(f"✅ data.csv written — {total} tickers | Date: {TODAY_IST}")
    print(f"")
    print(f"📊 ACCURACY:  {hits_all}/{total} = {hr:.1f}%")
    print(f"📈 SIGNALS:   🟢 {bull}  |  🔴 {bear}  |  ⚪ {neut}")
    print(f"📰 COVERAGE:  {total - fb}/{total} ({(total-fb)/total*100:.0f}%)")
    print(f"📰 MULTI-HEADLINE TICKERS: {multi_headline_count} (scored with weighted aggregation)")
    print("=" * 90)


if __name__ == "__main__":
    execute_sentiment_engine()
