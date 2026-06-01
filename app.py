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
# CONFIG
# ============================================================
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
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
TODAY_DATE = NOW_IST.date()
YESTERDAY_DATE = TODAY_DATE - timedelta(days=1)

TICKERS_FILE = "tickers.csv"
HISTORY_FILE = "history.csv"
DATA_FILE = "data.csv"

SOURCE_LABELS = {
    "mc_topnews": "Moneycontrol", "mc_business": "Moneycontrol",
    "mc_markets": "Moneycontrol", "mc_stocks": "Moneycontrol",
    "et_markets": "Economic Times", "et_stocks": "Economic Times",
    "et_news": "Economic Times", "ndtv_business": "NDTV Profit",
    "mint_market": "LiveMint", "mint_companies": "LiveMint",
    "nse_announce": "NSE Official", "nse_actions": "NSE Official",
    "yfinance": "Yahoo Finance", "google": "Google News",
}

SOURCE_WEIGHTS = {
    "mc_topnews": 1.5, "mc_business": 1.3, "mc_markets": 1.2, "mc_stocks": 1.2,
    "et_markets": 1.4, "et_stocks": 1.3, "et_news": 1.3,
    "ndtv_business": 1.2, "mint_market": 1.2, "mint_companies": 1.1,
    "nse_announce": 0.6, "nse_actions": 0.5,
    "yfinance": 1.0, "google": 1.0,
}

# ============================================================
# IMPACT CLASSIFICATION KEYWORDS
# ============================================================
SHORT_TERM_KEYWORDS = [
    "quarterly", "q1", "q2", "q3", "q4", "results", "earnings", "profit",
    "loss", "revenue", "ebitda", "net income", "beat", "miss", "estimate",
    "rally", "crash", "surge", "plunge", "jump", "tumble", "fall", "rise",
    "buyback", "dividend", "bonus", "split", "record date", "ex-date",
    "upgrade", "downgrade", "target price", "rating", "outlook",
    "block deal", "bulk deal", "insider", "promoter", "stake",
    "order win", "order book", "contract", "awarded",
    "trading halt", "circuit", "upper circuit", "lower circuit",
]

LONG_TERM_KEYWORDS = [
    "expansion", "capacity", "capex", "capital expenditure", "plant",
    "acquisition", "acquire", "merger", "amalgamation", "takeover",
    "partnership", "joint venture", "collaboration", "mou", "agreement",
    "regulation", "policy", "government", "sebi", "rbi", "ministry",
    "restructuring", "demerger", "spin-off", "reorganization",
    "ipo", "listing", "qip", "fpo", "rights issue", "fundraise",
    "technology", "ai", "digital", "automation", "innovation",
    "market entry", "new segment", "diversification", "subsidiary",
    "debt", "credit rating", "refinancing", "npa", "provisioning",
    "esg", "sustainability", "carbon", "green energy", "renewable",
]

# ============================================================
# SEVERITY SCALE (based on aggregated FinBERT score)
# ============================================================
def classify_severity(score):
    """
    Maps compound score (-100 to +100) to severity label.
    """
    if score >= 60:    return "Very Bullish"
    elif score >= 25:  return "Bullish"
    elif score >= 5:   return "Mildly Bullish"
    elif score >= -5:  return "Neutral"
    elif score >= -25: return "Mildly Bearish"
    elif score >= -60: return "Bearish"
    else:              return "Very Bearish"


def classify_impact(headline_entries):
    """
    Classifies impact as Short-term, Long-term, or Both
    by scanning all headlines for keyword matches.
    """
    combined_text = " ".join(e["headline"] for e in headline_entries).lower()

    short_hits = sum(1 for kw in SHORT_TERM_KEYWORDS if kw in combined_text)
    long_hits = sum(1 for kw in LONG_TERM_KEYWORDS if kw in combined_text)

    if short_hits > 0 and long_hits > 0:
        return "Both"
    elif long_hits > 0:
        return "Long-term"
    elif short_hits > 0:
        return "Short-term"
    else:
        # Default: single-day news without clear keywords → short-term
        return "Short-term"


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
            seen = set(); unique = []
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

COMPANY_ALIASES = {
    "EICHER MOTORS":"EICHERMOT","EICHER":"EICHERMOT","HERO MOTOCORP":"HEROMOTOCO",
    "HERO MOTO":"HEROMOTOCO","MARUTI SUZUKI":"MARUTI","ESCORTS KUBOTA":"ESCORTS",
    "BOSCH":"BOSCHLTD","BHARAT ELECTRONICS":"BEL","DATA PATTERNS":"DATAPATTNS",
    "GARDEN REACH":"GRSE","HINDUSTAN AERONAUTICS":"HAL","MAZAGON DOCK":"MAZDOCK",
    "PERSISTENT SYSTEMS":"PERSISTENT","ZENSAR":"ZENSARTECH","COFORGE":"COFORGE",
    "NATIONAL ALUMINIUM":"NATIONALUM","NALCO":"NATIONALUM","HINDUSTAN COPPER":"HINDCOPPER",
    "COAL INDIA":"COALINDIA","HDFC AMC":"HDFCAMC","ANGEL ONE":"ANGELONE",
    "MOTILAL OSWAL":"MOTILALOFS","CRISIL":"CRISIL","CARE RATINGS":"CARERATING",
    "ICRA":"ICRA","ITC":"ITC","JYOTHY LABS":"JYOTHYLAB","KEI INDUSTRIES":"KEI",
    "POLYCAB":"POLYCAB","NBCC":"NBCC","NCC":"NCC","CUMMINS INDIA":"CUMMINSIND",
    "ABB":"ABB","ABB INDIA":"ABB","POWER FINANCE":"PFC","REC LTD":"RECLTD",
    "GLOBAL HEALTH":"MEDANTA","BLUE STAR":"BLUESTARCO","LINDE INDIA":"LINDEINDIA",
    "SBI LIFE":"SBILIFE","CASTROL":"CASTROLIND","COROMANDEL":"COROMANDEL",
    "ABBOTT INDIA":"ABBOTINDIA","ALKEM":"ALKEM","CIPLA":"CIPLA",
    "TORRENT PHARMA":"TORNTPHARM","SAFARI INDUSTRIES":"SAFARI","TRENT":"TRENT",
    "LODHA":"LODHA","MACROTECH":"LODHA","BAJAJ FINANCE":"BAJFINANCE",
    "AU SMALL FINANCE":"AUBANK","CHOLAMANDALAM":"CHOLAFIN","MUTHOOT FINANCE":"MUTHOOTFIN",
    "SHRIRAM FINANCE":"SHRIRAMFIN","SUNDARAM FINANCE":"SUNDARMFIN","HUDCO":"HUDCO",
    "MCX":"MCX","GRAVITA":"GRAVITA","APL APOLLO":"APLAPOLLO","AFFLE":"AFFLE",
    "HYUNDAI":"HYUNDAI","BIKAJI":"BIKAJI","ORACLE FINANCIAL":"OFSS",
    "BAJAJ HOLDINGS":"BAJAJHLDNG","RAILTEL":"RAILTEL","DOMS":"DOMS",
    "DODLA DAIRY":"DODLA","LT FOODS":"LTFOODS","WELSPUN CORP":"WELCORP",
    "INGERSOLL RAND":"INGERRAND","KIRLOSKAR":"KIRLOSBROS","SHAKTI PUMPS":"SHAKTIPUMP",
    "TD POWER SYSTEMS":"TDPOWERSYS","UNO MINDA":"UNOMINDA","HOME FIRST":"HOMEFIRST",
    "CAN FIN HOMES":"CANFINHOME","NUVAMA":"NUVAMA","GROWW":"GROWW","TEGA":"TEGA",
    "ENDURANCE":"ENDURANCE","SANSERA":"SANSERA","TIPS MUSIC":"TIPSMUSIC",
    "GOLDIAM":"GOLDIAM","NEWGEN":"NEWGEN","RATEGAIN":"RATEGAIN","ECLERX":"ECLERX",
    "VOLTAMP":"VOLTAMP","ELECON":"ELECON","PRUDENT":"PRUDENT","MARKSANS":"MARKSANS",
    "SUPRIYA":"SUPRIYA","MARATHON":"MARATHON",
}


# ============================================================
# DATE HELPERS
# ============================================================
def extract_pub_date_and_time(entry):
    """
    Returns (date_obj, formatted_time_str) from RSS entry.
    date_obj = date in IST for freshness check.
    formatted_time_str = display string like "01 Jun 2026 03:15 PM"
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            dt_utc = datetime(*parsed[:6], tzinfo=timezone.utc)
            dt_ist = dt_utc.astimezone(IST)
            return dt_ist.date(), dt_ist.strftime("%d %b %Y %I:%M %p")
        except Exception:
            pass
    # If no parseable date, return None (will be treated as "today" since it's in today's RSS)
    return None, ""


def is_fresh(pub_date):
    """Returns True if pub_date is today or yesterday (or unparseable → benefit of doubt)."""
    if pub_date is None:
        return True  # No date available → assume fresh (it's in today's RSS feed)
    return pub_date >= YESTERDAY_DATE


# ============================================================
# RSS FETCH + MATCHING
# ============================================================
def fetch_rss_with_headers(url, label, timeout=15):
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except requests.exceptions.RequestException as e:
        print(f"   ⚠️ {label}: {e}")
        try: return feedparser.parse(url)
        except: return None


def match_ticker_in_text(text_upper, tickers_list):
    for t in sorted(tickers_list, key=len, reverse=True):
        if re.search(r'\b' + re.escape(t.upper()) + r'\b', text_upper):
            return t
    for alias, t in COMPANY_ALIASES.items():
        if alias in text_upper and t in tickers_list:
            return t
    return None


# ============================================================
# PHASE 1: BUILD CACHE (only today + yesterday news)
# ============================================================
def build_news_cache(tickers_list):
    """
    Fetches ALL RSS feeds. Stores ALL matching headlines per ticker.
    ONLY keeps news from today or yesterday.
    """
    cache = {}
    total_scanned = 0
    total_fresh = 0
    total_stale = 0

    for source_key, url in ALL_FEEDS.items():
        print(f"📡 Fetching {source_key}...")
        feed = fetch_rss_with_headers(url, source_key)
        if not feed or not feed.entries:
            print(f"   ⚠️ {source_key}: No entries")
            continue

        match_count = 0
        stale_count = 0
        for entry in feed.entries:
            title = entry.get("title", "")
            desc = entry.get("description", entry.get("summary", ""))
            full_text = f"{title} {desc}".upper()

            matched_ticker = match_ticker_in_text(full_text, tickers_list)
            if not matched_ticker or not title.strip():
                continue

            total_scanned += 1

            # Date freshness check
            pub_date, pub_time_str = extract_pub_date_and_time(entry)
            if not is_fresh(pub_date):
                stale_count += 1
                total_stale += 1
                continue

            total_fresh += 1
            headline = title.strip().replace(",", ";")
            weight = SOURCE_WEIGHTS.get(source_key, 1.0)

            # Deduplicate
            existing = cache.get(matched_ticker, [])
            if not any(e["headline"].lower() == headline.lower() for e in existing):
                if matched_ticker not in cache:
                    cache[matched_ticker] = []
                cache[matched_ticker].append({
                    "headline": headline,
                    "source": source_key,
                    "pub_time": pub_time_str,
                    "weight": weight,
                })
                match_count += 1

        stale_note = f" ({stale_count} stale filtered)" if stale_count else ""
        print(f"   ✅ {source_key}: {match_count} fresh matches from {len(feed.entries)} entries{stale_note}")
        time.sleep(0.3)

    total_tickers = len(cache)
    total_headlines = sum(len(v) for v in cache.values())
    multi = sum(1 for v in cache.values() if len(v) >= 2)

    print(f"\n📦 Fresh news cache (today + yesterday only):")
    print(f"   Tickers with news:    {total_tickers}/{len(tickers_list)}")
    print(f"   Total headlines:      {total_headlines}")
    print(f"   Multi-headline:       {multi}")
    print(f"   Stale news filtered:  {total_stale}")

    return cache


# ============================================================
# FINBERT SCORING
# ============================================================
def score_single_headline(headline):
    if not headline:
        return 0.0
    try:
        inputs = tokenizer([headline], padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
        return (probs[0][0].item() - probs[0][1].item()) * 100.0
    except Exception as e:
        print(f"  ⚠️ NLP crash: {e}")
        return 0.0


def compute_aggregated_score(entries):
    if not entries:
        return 0.0, 0
    total_w = 0.0
    weighted_sum = 0.0
    for e in entries:
        raw = score_single_headline(e["headline"])
        w = e.get("weight", 1.0)
        weighted_sum += raw * w
        total_w += w
    if total_w == 0:
        return 0.0, 0
    score = weighted_sum / total_w
    if score > 5.0: d = 1
    elif score < -5.0: d = -1
    else: d = 0
    return round(score, 1), d


# ============================================================
# PER-TICKER FALLBACKS (with freshness filtering)
# ============================================================
def get_yfinance_news(ticker):
    try:
        yf_t = yf.Ticker(f"{ticker}.NS")
        news = getattr(yf_t, 'news', None)
        if news and isinstance(news, list):
            for item in news:
                if not isinstance(item, dict): continue
                headline = item.get("title", item.get("headline", ""))
                if not headline: continue
                pub_ts = item.get("providerPublishTime") or item.get("publish_time")
                pub_time_str = ""
                pub_date = None
                if pub_ts:
                    try:
                        dt = datetime.fromtimestamp(int(pub_ts), tz=IST)
                        pub_date = dt.date()
                        pub_time_str = dt.strftime("%d %b %Y %I:%M %p")
                    except: pass
                if is_fresh(pub_date):
                    return headline.replace(",", ";"), pub_time_str
    except: pass
    return None, ""


def get_google_news(ticker):
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(ticker)}+NSE+stock+india&hl=en-IN&gl=IN&ceid=IN:en"
        feed = fetch_rss_with_headers(url, f"gg_{ticker}", timeout=8)
        if feed and feed.entries:
            for entry in feed.entries[:3]:  # Check top 3 results
                pub_date, pub_time_str = extract_pub_date_and_time(entry)
                if is_fresh(pub_date):
                    headline = re.sub(r'\s+-\s+[^:\-]+$', '', entry.title)
                    return headline.replace(",", ";"), pub_time_str
    except: pass
    return None, ""


def get_all_fresh_news(ticker, cache):
    """
    Collects all FRESH (today/yesterday) headlines from all sources.
    Returns (entries_list, primary_source, primary_pub_time) or None if no news.
    """
    entries = []

    # 1. Bulk cache (already freshness-filtered)
    if ticker in cache:
        entries.extend(cache[ticker])

    # 2. yfinance
    hl, pt = get_yfinance_news(ticker)
    if hl and not any(e["headline"].lower() == hl.lower() for e in entries):
        entries.append({"headline": hl, "source": "yfinance", "pub_time": pt, "weight": 1.0})

    # 3. Google (only if < 3 headlines so far)
    if len(entries) < 3:
        hl, pt = get_google_news(ticker)
        if hl and not any(e["headline"].lower() == hl.lower() for e in entries):
            entries.append({"headline": hl, "source": "google", "pub_time": pt, "weight": 1.0})

    if not entries:
        return None  # NO fresh news — ticker will be skipped

    primary = max(entries, key=lambda e: e["weight"])
    return {
        "entries": entries,
        "primary_source": primary["source"],
        "primary_pub_time": primary["pub_time"],
    }


# ============================================================
# PRICE
# ============================================================
def get_live_price_return(ticker):
    try:
        h = yf.Ticker(f"{ticker}.NS").history(period="5d")
        if len(h) >= 2:
            return round(((h['Close'].iloc[-1] - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100, 2)
    except: pass
    return 0.0


# ============================================================
# STREAKS
# ============================================================
def load_history():
    try:
        df = pd.read_csv(HISTORY_FILE)
        if 'Date' in df.columns:
            dates = sorted(df['Date'].unique(), reverse=True)[:30]
            df = df[df['Date'].isin(dates)]
        return df
    except FileNotFoundError:
        return pd.DataFrame()


def calculate_streaks(history_df, today_rows):
    streaks = {}
    for row in today_rows:
        tk = row["Ticker"]; td = row["Forecast_Direction"]
        ts = row["Forecast_Score"]; tr = row["Actual_Return_Pct"]
        th = pd.DataFrame()
        if not history_df.empty and 'Ticker' in history_df.columns:
            th = history_df[(history_df['Ticker']==tk)&(history_df['Date']!=TODAY_IST)].sort_values('Date',ascending=False)
        sd=1; sr=tr
        if not th.empty:
            for _,hr in th.iterrows():
                if int(hr.get('Forecast_Direction',0))==td and td!=0: sd+=1; sr+=float(hr.get('Actual_Return_Pct',0))
                else: break
        ps = float(th.iloc[0].get('Forecast_Score',0)) if not th.empty else None
        if td==0: m="Neutral"
        elif sd==1: m="New"
        elif ps is not None:
            if td==1: m=("Strong" if sd>=3 else "Building") if ts>=ps else "Fading"
            elif td==-1: m=("Strong" if sd>=3 else "Building") if ts<=ps else "Fading"
            else: m="Neutral"
        else: m="New"
        streaks[tk]={"Streak_Days":sd if td!=0 else 0,"Streak_Return":round(sr,2),"Momentum":m}
    return streaks


def save_to_history(rows):
    hdf = load_history()
    tdf = pd.DataFrame(rows); tdf['Date'] = TODAY_IST
    if not hdf.empty and 'Date' in hdf.columns:
        hdf = hdf[hdf['Date']!=TODAY_IST]
    c = pd.concat([hdf,tdf],ignore_index=True)
    if 'Date' in c.columns:
        dates = sorted(c['Date'].unique(),reverse=True)[:30]
        c = c[c['Date'].isin(dates)]
    c.to_csv(HISTORY_FILE,index=False)
    print(f"📜 History: {len(c)} rows / {c['Date'].nunique() if 'Date' in c.columns else 1} days")


# ============================================================
# MAIN ENGINE
# ============================================================
def execute_sentiment_engine():
    tickers_list, sector_map = load_tickers()
    total = len(tickers_list)

    print(f"🚀 Running AI Swing Trading Engine — {total} tickers")
    print(f"📅 Date: {TODAY_IST} | Fresh window: {YESTERDAY_DATE} → {TODAY_DATE}")
    print("=" * 95)

    # PHASE 1: Bulk fetch (only fresh news)
    print("\n📡 PHASE 1: Pre-fetching news (today + yesterday only)...")
    print("-" * 95)
    news_cache = build_news_cache(tickers_list)
    print("-" * 95)

    # PHASE 2: Process ONLY tickers with fresh news
    print(f"\n📊 PHASE 2: Scoring tickers with fresh news...")
    print("-" * 95)

    scored_rows = []
    skipped_rows = []
    source_stats = {}
    hits = 0

    for idx, ticker in enumerate(tickers_list, 1):
        result = get_all_fresh_news(ticker, news_cache)

        if result is None:
            # NO fresh news → skip scoring, add to skipped
            skipped_rows.append({
                "Ticker": ticker,
                "Sector": sector_map.get(ticker, ""),
                "Latest_Headline": "",
                "News_Source": "",
                "News_Time": "",
                "Headline_Count": 0,
                "Forecast_Score": 0.0,
                "Forecast_Direction": 0,
                "Actual_Direction": 0,
                "Actual_Return_Pct": get_live_price_return(ticker),
                "Severity": "No News",
                "Impact": "",
                "Streak_Days": 0,
                "Streak_Return": 0.0,
                "Momentum": "",
            })
            continue

        entries = result["entries"]
        primary_src = result["primary_source"]
        primary_time = result["primary_pub_time"]
        source_stats[primary_src] = source_stats.get(primary_src, 0) + 1

        if primary_src in ("yfinance", "google"):
            time.sleep(0.3)

        # Aggregated FinBERT scoring
        score, direction = compute_aggregated_score(entries)
        ret = get_live_price_return(ticker)

        if ret > 0.25: actual = 1
        elif ret < -0.25: actual = -1
        else: actual = 0

        is_hit = direction == actual
        if is_hit: hits += 1

        # Severity & Impact
        severity = classify_severity(score)
        impact = classify_impact(entries)

        # Sources display
        unique_src = list(dict.fromkeys(SOURCE_LABELS.get(e["source"], e["source"]) for e in entries))
        src_display = " | ".join(unique_src)

        # Primary headline
        primary = max(entries, key=lambda e: e["weight"])

        # Console
        hc = len(entries)
        src_short = {"mc_topnews":"💰MC","mc_business":"💼MC","mc_markets":"📈MC","mc_stocks":"📰MC",
                     "et_markets":"📊ET","et_stocks":"📊ET","et_news":"📊ET","ndtv_business":"📺ND",
                     "mint_market":"🌿Mi","mint_companies":"🌿Mi","nse_announce":"🏛️NS","nse_actions":"📋NS",
                     "yfinance":"📰YF","google":"🔗GG"}
        dir_map = {1:"🟢",-1:"🔴",0:"⚪"}
        htag = f"[{hc}h]" if hc>=2 else "    "
        sev_short = severity[:8]

        print(f"[{len(scored_rows)+1:3d}] {ticker:<14s} {src_short.get(primary_src,'❓'):6s} {htag} {dir_map.get(direction,'⚪')} {sev_short:10s} | Score:{score:+6.1f} | Ret:{ret:+6.2f}% | {impact:10s} | {'✅' if is_hit else '❌'}")

        scored_rows.append({
            "Ticker": ticker,
            "Sector": sector_map.get(ticker, ""),
            "Latest_Headline": primary["headline"],
            "News_Source": src_display,
            "News_Time": primary_time.replace(",", "") if primary_time else "",
            "Headline_Count": hc,
            "Forecast_Score": score,
            "Forecast_Direction": direction,
            "Actual_Direction": actual,
            "Actual_Return_Pct": ret,
            "Severity": severity,
            "Impact": impact,
        })

    # PHASE 3: Streaks (only for scored tickers)
    print(f"\n📜 PHASE 3: Calculating streaks for {len(scored_rows)} scored tickers...")
    print("-" * 95)
    history_df = load_history()
    streaks = calculate_streaks(history_df, scored_rows)

    final_rows = []
    for row in scored_rows:
        s = streaks.get(row["Ticker"], {})
        row["Streak_Days"] = s.get("Streak_Days", 0)
        row["Streak_Return"] = s.get("Streak_Return", 0.0)
        row["Momentum"] = s.get("Momentum", "Neutral")
        final_rows.append(row)

    # Combine: scored first, then skipped (no news) at the bottom
    all_rows = final_rows + skipped_rows
    df = pd.DataFrame(all_rows)
    df.to_csv(DATA_FILE, index=False)

    # Save only scored tickers to history (skipped have no signal)
    save_to_history(scored_rows)

    # ============================================================
    # SUMMARY
    # ============================================================
    scored_count = len(scored_rows)
    skipped_count = len(skipped_rows)
    bull = sum(1 for r in scored_rows if r["Forecast_Direction"]==1)
    bear = sum(1 for r in scored_rows if r["Forecast_Direction"]==-1)
    neut = sum(1 for r in scored_rows if r["Forecast_Direction"]==0)
    hr = (hits/scored_count)*100 if scored_count>0 else 0

    # Severity breakdown
    sev_counts = {}
    for r in scored_rows:
        s = r["Severity"]
        sev_counts[s] = sev_counts.get(s, 0) + 1

    # Impact breakdown
    imp_counts = {}
    for r in scored_rows:
        i = r["Impact"]
        imp_counts[i] = imp_counts.get(i, 0) + 1

    print("\n" + "=" * 95)
    print(f"✅ data.csv written | Date: {TODAY_IST}")
    print(f"")
    print(f"📊 SCORING:     {scored_count} tickers scored | {skipped_count} skipped (no fresh news)")
    print(f"📊 ACCURACY:    {hits}/{scored_count} = {hr:.1f}%  (measured only on tickers with news)")
    print(f"📈 SIGNALS:     🟢 Bullish: {bull}  |  🔴 Bearish: {bear}  |  ⚪ Neutral: {neut}")
    print(f"")
    print(f"🎯 SEVERITY BREAKDOWN:")
    for s in ["Very Bullish","Bullish","Mildly Bullish","Neutral","Mildly Bearish","Bearish","Very Bearish"]:
        c = sev_counts.get(s, 0)
        if c > 0:
            bar = "█" * c
            print(f"   {s:18s} {c:3d}  {bar}")
    print(f"")
    print(f"⏱️  IMPACT BREAKDOWN:")
    for i in ["Short-term","Long-term","Both"]:
        c = imp_counts.get(i, 0)
        if c > 0: print(f"   {i:18s} {c:3d}")
    print("=" * 95)


if __name__ == "__main__":
    execute_sentiment_engine()
