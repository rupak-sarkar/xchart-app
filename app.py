import pandas as pd
import yfinance as yf
import feedparser
import requests
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

# ============================================================
# CRITICAL FIX: Set browser User-Agent GLOBALLY
# Without this, NSE/BSE/Moneycontrol all block requests from GitHub Actions
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
# Also set feedparser's built-in user-agent as backup
feedparser.USER_AGENT = BROWSER_HEADERS["User-Agent"]


print("🤖 Initializing FinBERT Neural Network Pipeline...")
FINBERT_MODEL = "ProsusAI/finbert"
tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)


# ============================================================
# 172 swing trading tickers (fixed broken symbols)
# ============================================================
TICKERS = [
    # Auto & Auto Ancillary
    "EICHERMOT", "HEROMOTOCO", "MARUTI", "ESCORTS",
    "BANCOINDIA", "BOSCHLTD", "ENDURANCE", "FMGOETZE", "FIEMIND",
    "GABRIEL", "LGBBROSLTD", "PRICOLLTD", "SANSERA", "SHARDAMOTR",
    "SHRIPISTON", "UNOMINDA", "ZFCVINDIA",
    # Defence & Aerospace
    "BEL", "DATAPATTNS", "GRSE", "HAL", "MAZDOCK",
    # IT / Tech / Software
    "ZENTEC", "ECLERX", "NEWGEN", "PERSISTENT", "RATEGAIN",
    "SAKSOFT", "ZENSARTECH", "CONTROLPR", "DLINKINDIA", "AFFLE",
    "COFORGE", "MPSLTD", "OFSS", "KFINTECH",
    # Metals & Mining
    "NATIONALUM", "HINDCOPPER", "COALINDIA", "GMDCLTD", "NAVA",
    "GRAVITA", "TEGA",
    # Asset Management & Financial Services
    "HDFCAMC", "NAM-INDIA", "360ONE", "ANGELONE", "MOTILALOFS",
    "NUVAMA", "IIFLCAPS", "PRUDENT", "CRISIL", "CARERATING", "ICRA",
    # Breweries & FMCG
    "GMBREW", "PICCADIL", "SDBL", "ITC", "JYOTHYLAB",
    "BIKAJI", "BECTORFOOD", "DODLA", "LTFOODS",
    # Electricals & Cables
    "KEI", "POLYCAB",
    # Capital Goods / Engineering / EPC
    "HSCL", "AIAENG", "GODFRYPHLP", "AHLUCONT", "CEMPRO",
    "INTERARCH", "MANINFRA", "NBCC", "NCC", "POWERMECH", "TECHNOE",
    "ACE", "APLAPOLLO", "MAHSEAMLES", "WELCORP",
    # Industrial / Pumps / Compressors
    "CUMMINSIND", "INGERRAND", "KIRLOSBROS", "KIRLPNU", "SHAKTIPUMP",
    "GRAUWEIL",
    # Power / T&D / Electrical Equipment
    "ABB", "ATLANTAELE", "ELECON", "TDPOWERSYS",
    "TRANSRAILL", "TRITURBINE", "VOLTAMP", "PFC", "RECLTD",
    # Jewellery & Gems
    "DPABHUSHAN", "GOLDIAM", "POKARNA",
    # Healthcare / Hospitals
    "MEDANTA", "INDRAMEDCO", "KOVAI",
    # Hotels & Travel
    "TAJGVK", "TRAVELFOOD",
    # Consumer Durables
    "BLUESTARCO", "LGEINDIA",
    # Chemicals & Gas
    "LINDEINDIA", "EPIGRAL", "VISHNU",
    # Insurance
    "SBILIFE",
    # Logistics
    "TCI", "GESHIP",
    # Lubricants / Oil
    "CASTROLIND", "GULFOILLUB",
    # Media & Entertainment
    "TIPSMUSIC", "DBCORP",
    # Medical Devices
    "POLYMED",
    # Miscellaneous / Diversified
    "AIIL", "KSCL", "SHILCTECH", "WAAREERTL", "NESCO",
    "VESUVIUS", "MCX", "COROMANDEL", "ORKLAINDIA", "HBLENGINE",
    "RAILTEL", "AGI",
    # Pharma & Healthcare Products
    "ABBOTINDIA", "ACUTAAS", "ALIVUS", "ALKEM", "CAPLIPOINT",
    "CIPLA", "INNOVACAP", "JBCHEPHARM", "MARKSANS", "SUPRIYA",
    "TORNTPHARM",
    # Consumer / Retail / Lifestyle
    "SAFARI", "TRENT", "DOMS", "HYUNDAI",
    # Plastics & Building Materials
    "GRWRHITECH", "KINGFA", "TIMETECHNO", "STYLAMIND",
    # Jewellery (JWL)
    "JWL",
    # Real Estate
    "ARVSMART", "GANESHHOU", "LODHA", "MARATHON", "INDIASHLTR",
    # Software Products
    "NUCLEUS",
    # Industrial Misc
    "BLS", "EIEL",
    # NBFC / Banking / Finance
    "ARSSBL", "AUBANK", "BAJFINANCE", "GROWW", "CANFINHOME",
    "CHOLAHLDNG", "CHOLAFIN", "HUDCO", "HOMEFIRST",
    "MUTHOOTFIN", "SHRIRAMFIN", "SUNDARMFIN",
    # Holdings
    "BAJAJHLDNG", "SYSTMTXC", "TVSHLTD",
]

TICKERS_UPPER = {t.upper() for t in TICKERS}


# ============================================================
# ALL RSS FEED URLS
# ============================================================

# Official Exchange Feeds
NSE_FEEDS = {
    "nse_announce": "https://archives.nseindia.com/content/RSS/Online_announcements.xml",
    "nse_actions":  "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
}

# BSE Feed
BSE_FEEDS = {
    "bse_announce": "https://www.bseindia.com/data/xml/RSSFeed.xml",
}

# Moneycontrol Feeds
MC_FEEDS = {
    "mc_topnews":  "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "mc_business": "https://www.moneycontrol.com/rss/business.xml",
    "mc_markets":  "https://www.moneycontrol.com/rss/marketreports.xml",
    "mc_stocks":   "https://www.moneycontrol.com/rss/latestnews.xml",
}

# Economic Times & LiveMint (additional Indian financial news)
ET_FEEDS = {
    "et_markets":  "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks":   "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "et_news":     "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146843.cms",
}

LIVEMINT_FEEDS = {
    "mint_market":  "https://www.livemint.com/rss/market",
    "mint_companies": "https://www.livemint.com/rss/companies",
}


# ============================================================
# COMPANY ALIAS MAP (Company name → Ticker)
# Moneycontrol/ET use full names like "Bajaj Finance", not "BAJFINANCE"
# ============================================================
COMPANY_ALIASES = {
    "EICHER MOTORS": "EICHERMOT", "EICHER": "EICHERMOT",
    "HERO MOTOCORP": "HEROMOTOCO", "HERO MOTO": "HEROMOTOCO",
    "MARUTI SUZUKI": "MARUTI",
    "ESCORTS KUBOTA": "ESCORTS",
    "BOSCH": "BOSCHLTD", "BOSCH LTD": "BOSCHLTD",
    "BHARAT ELECTRONICS": "BEL",
    "DATA PATTERNS": "DATAPATTNS",
    "GARDEN REACH": "GRSE",
    "HINDUSTAN AERONAUTICS": "HAL",
    "MAZAGON DOCK": "MAZDOCK",
    "PERSISTENT SYSTEMS": "PERSISTENT",
    "ZENSAR": "ZENSARTECH", "ZENSAR TECH": "ZENSARTECH",
    "COFORGE": "COFORGE",
    "NATIONAL ALUMINIUM": "NATIONALUM", "NALCO": "NATIONALUM",
    "HINDUSTAN COPPER": "HINDCOPPER",
    "COAL INDIA": "COALINDIA",
    "HDFC AMC": "HDFCAMC", "HDFC ASSET": "HDFCAMC",
    "ANGEL ONE": "ANGELONE",
    "MOTILAL OSWAL": "MOTILALOFS",
    "CRISIL": "CRISIL",
    "CARE RATINGS": "CARERATING",
    "ICRA": "ICRA",
    "ITC": "ITC", "ITC LTD": "ITC",
    "JYOTHY LABS": "JYOTHYLAB", "JYOTHY": "JYOTHYLAB",
    "KEI INDUSTRIES": "KEI",
    "POLYCAB": "POLYCAB", "POLYCAB INDIA": "POLYCAB",
    "NBCC": "NBCC", "NBCC INDIA": "NBCC",
    "NCC": "NCC", "NCC LTD": "NCC",
    "CUMMINS INDIA": "CUMMINSIND", "CUMMINS": "CUMMINSIND",
    "ABB": "ABB", "ABB INDIA": "ABB",
    "POWER FINANCE": "PFC", "PFC": "PFC",
    "REC LTD": "RECLTD", "REC": "RECLTD",
    "GLOBAL HEALTH": "MEDANTA", "MEDANTA": "MEDANTA",
    "BLUE STAR": "BLUESTARCO", "BLUESTAR": "BLUESTARCO",
    "LINDE INDIA": "LINDEINDIA", "LINDE": "LINDEINDIA",
    "SBI LIFE": "SBILIFE", "SBI LIFE INSURANCE": "SBILIFE",
    "TRANSPORT CORPORATION": "TCI", "TCI": "TCI",
    "CASTROL": "CASTROLIND", "CASTROL INDIA": "CASTROLIND",
    "TIPS MUSIC": "TIPSMUSIC", "TIPS INDUSTRIES": "TIPSMUSIC",
    "COROMANDEL": "COROMANDEL", "COROMANDEL INTERNATIONAL": "COROMANDEL",
    "ABBOTT INDIA": "ABBOTINDIA", "ABBOTT": "ABBOTINDIA",
    "ALKEM": "ALKEM", "ALKEM LAB": "ALKEM",
    "CIPLA": "CIPLA",
    "TORRENT PHARMA": "TORNTPHARM", "TORRENT PHARMACEUTICALS": "TORNTPHARM",
    "SAFARI INDUSTRIES": "SAFARI", "SAFARI": "SAFARI",
    "TRENT": "TRENT", "TRENT LTD": "TRENT",
    "LODHA": "LODHA", "MACROTECH": "LODHA", "MACROTECH DEVELOPERS": "LODHA",
    "BAJAJ FINANCE": "BAJFINANCE", "BAJAJ FIN": "BAJFINANCE",
    "AU SMALL FINANCE": "AUBANK", "AU BANK": "AUBANK",
    "CHOLAMANDALAM": "CHOLAFIN", "CHOLA FINANCE": "CHOLAFIN", "CHOLA": "CHOLAFIN",
    "MUTHOOT FINANCE": "MUTHOOTFIN", "MUTHOOT": "MUTHOOTFIN",
    "SHRIRAM FINANCE": "SHRIRAMFIN", "SHRIRAM": "SHRIRAMFIN",
    "SUNDARAM FINANCE": "SUNDARMFIN", "SUNDARAM": "SUNDARMFIN",
    "HUDCO": "HUDCO",
    "MCX": "MCX", "MULTI COMMODITY": "MCX",
    "GRAVITA": "GRAVITA", "GRAVITA INDIA": "GRAVITA",
    "APL APOLLO": "APLAPOLLO", "APL APOLLO TUBES": "APLAPOLLO",
    "AFFLE": "AFFLE", "AFFLE INDIA": "AFFLE",
    "HYUNDAI": "HYUNDAI", "HYUNDAI MOTOR": "HYUNDAI",
    "BIKAJI": "BIKAJI", "BIKAJI FOODS": "BIKAJI",
    "ORACLE FINANCIAL": "OFSS", "OFSS": "OFSS",
    "BAJAJ HOLDINGS": "BAJAJHLDNG",
    "RAILTEL": "RAILTEL", "RAILTEL CORP": "RAILTEL",
    "DOMS": "DOMS", "DOMS INDUSTRIES": "DOMS",
    "DODLA DAIRY": "DODLA", "DODLA": "DODLA",
    "LT FOODS": "LTFOODS",
    "HINDCOPPER": "HINDCOPPER",
    "NEWGEN": "NEWGEN", "NEWGEN SOFTWARE": "NEWGEN",
    "RATEGAIN": "RATEGAIN", "RATEGAIN TRAVEL": "RATEGAIN",
    "ECLERX": "ECLERX", "ECLERX SERVICES": "ECLERX",
    "VOLTAMP": "VOLTAMP", "VOLTAMP TRANSFORMERS": "VOLTAMP",
    "ELECON": "ELECON", "ELECON ENGINEERING": "ELECON",
    "GOLDIAM": "GOLDIAM", "GOLDIAM INTERNATIONAL": "GOLDIAM",
    "WELCORP": "WELCORP", "WELSPUN CORP": "WELCORP",
    "INGERSOLL": "INGERRAND", "INGERSOLL RAND": "INGERRAND",
    "KIRLOSKAR": "KIRLOSBROS", "KIRLOSKAR BROTHERS": "KIRLOSBROS",
    "SHAKTI PUMPS": "SHAKTIPUMP",
    "TD POWER": "TDPOWERSYS", "TD POWER SYSTEMS": "TDPOWERSYS",
    "SANSERA": "SANSERA", "SANSERA ENGINEERING": "SANSERA",
    "UNO MINDA": "UNOMINDA",
    "PRUDENT": "PRUDENT", "PRUDENT CORPORATE": "PRUDENT",
    "HOME FIRST": "HOMEFIRST", "HOME FIRST FINANCE": "HOMEFIRST",
    "CAN FIN HOMES": "CANFINHOME", "CANFIN": "CANFINHOME",
    "NUVAMA": "NUVAMA", "NUVAMA WEALTH": "NUVAMA",
    "MARATHON": "MARATHON", "MARATHON NEXTGEN": "MARATHON",
    "GROWW": "GROWW",
    "HDFCAMC": "HDFCAMC",
    "MARKSANS": "MARKSANS", "MARKSANS PHARMA": "MARKSANS",
    "SUPRIYA": "SUPRIYA", "SUPRIYA LIFESCIENCE": "SUPRIYA",
}


# ============================================================
# FETCH RSS WITH PROPER HEADERS (the key fix)
# ============================================================
def fetch_rss_with_headers(url, source_label, timeout=15):
    """
    Fetches RSS using requests library with browser headers.
    Falls back to feedparser direct if requests fails.
    This is THE critical fix — NSE/BSE block bare Python user-agents.
    """
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        return feed
    except requests.exceptions.RequestException as e:
        print(f"   ⚠️ {source_label} requests failed: {e}")
        # Fallback: try feedparser directly (has USER_AGENT set)
        try:
            feed = feedparser.parse(url)
            return feed
        except Exception as e2:
            print(f"   ⚠️ {source_label} feedparser fallback also failed: {e2}")
            return None


# ============================================================
# TICKER MATCHING ENGINE
# ============================================================
def match_ticker_in_text(text_upper):
    """
    Matches a ticker from our watchlist in the given text.
    Tries direct ticker match first, then company alias mapping.
    """
    # Direct ticker symbol match (longest first to avoid partial matches)
    for ticker in sorted(TICKERS, key=len, reverse=True):
        # Use word boundary check to avoid false matches
        # e.g. "ACE" shouldn't match "PALACE"
        if re.search(r'\b' + re.escape(ticker.upper()) + r'\b', text_upper):
            return ticker

    # Company alias match
    for alias, ticker in COMPANY_ALIASES.items():
        if alias in text_upper:
            return ticker

    return None


# ============================================================
# PHASE 1: BUILD NEWS CACHE FROM ALL BULK FEEDS
# ============================================================
def build_exchange_news_cache():
    """
    Pre-fetches ALL RSS feeds using proper browser headers.
    Builds {TICKER: {"headline": str, "source": str}} cache.
    """
    cache = {}
    all_feeds = {}
    all_feeds.update(MC_FEEDS)         # Moneycontrol (priority 1)
    all_feeds.update(ET_FEEDS)         # Economic Times (priority 2)
    all_feeds.update(LIVEMINT_FEEDS)   # LiveMint (priority 3)
    all_feeds.update(NSE_FEEDS)        # NSE (priority 4)
    all_feeds.update(BSE_FEEDS)        # BSE (priority 5)

    for source_key, url in all_feeds.items():
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

            matched_ticker = match_ticker_in_text(full_text)
            if matched_ticker and title.strip() and matched_ticker not in cache:
                headline = title.strip().replace(",", ";")
                cache[matched_ticker] = {"headline": headline, "source": source_key}
                match_count += 1

        print(f"   ✅ {source_key}: {match_count} new matches from {len(feed.entries)} entries")
        time.sleep(0.5)  # Small delay between feeds to be polite

    # Source breakdown
    source_breakdown = {}
    for v in cache.values():
        s = v["source"]
        source_breakdown[s] = source_breakdown.get(s, 0) + 1

    print(f"\n📦 News cache built: {len(cache)}/{len(TICKERS)} tickers pre-loaded")
    for s, count in sorted(source_breakdown.items(), key=lambda x: -x[1]):
        print(f"   {s}: {count}")

    return cache


# ============================================================
# FINBERT SCORING
# ============================================================
def compute_finbert_score(headline):
    if not headline or "Stable trade volatility" in headline:
        return 0.0, 0
    try:
        inputs = tokenizer(
            [headline], padding=True, truncation=True,
            max_length=512, return_tensors="pt"
        )
        with torch.no_grad():
            outputs = model(**inputs)
        predictions = torch.nn.functional.softmax(outputs.logits, dim=-1)

        pos_prob = predictions[0][0].item()
        neg_prob = predictions[0][1].item()
        compound_score = (pos_prob - neg_prob) * 100.0

        if compound_score > 5.0:
            direction = 1
        elif compound_score < -5.0:
            direction = -1
        else:
            direction = 0

        return round(compound_score, 1), direction
    except Exception as e:
        print(f"  ⚠️ NLP crash: {e}")
        return 0.0, 0


# ============================================================
# PER-TICKER NEWS FALLBACK: yfinance (with error handling)
# ============================================================
def get_news_from_yfinance(ticker):
    """
    yfinance built-in news — per ticker.
    Note: May fail on GitHub Actions due to cookie/auth requirements.
    """
    try:
        yf_ticker = yf.Ticker(f"{ticker}.NS")
        news = getattr(yf_ticker, 'news', None)
        if news and isinstance(news, list) and len(news) > 0:
            # Handle different yfinance response formats
            first = news[0]
            headline = ""
            if isinstance(first, dict):
                headline = first.get("title", first.get("headline", ""))
            if headline:
                return headline.replace(",", ";")
    except Exception:
        pass  # Silent fail — yfinance news is unreliable on cloud
    return None


def get_live_news_headline(ticker, exchange_cache):
    """
    News waterfall:
      1-5. Bulk cache (MC → ET → Mint → NSE → BSE)
      6.   yfinance per-ticker
      7.   Fallback placeholder
    """
    if ticker in exchange_cache:
        return exchange_cache[ticker]["headline"], exchange_cache[ticker]["source"]

    headline = get_news_from_yfinance(ticker)
    if headline:
        return headline, "yfinance"

    return f"Stable trade volatility tracked on exchange indices for {ticker}.", "fallback"


# ============================================================
# PRICE DATA
# ============================================================
def get_live_price_return(ticker_symbol):
    try:
        yf_ticker = yf.Ticker(f"{ticker_symbol}.NS")
        history = yf_ticker.history(period="5d")
        if len(history) >= 2:
            prev_close = history['Close'].iloc[-2]
            current_close = history['Close'].iloc[-1]
            pct_return = ((current_close - prev_close) / prev_close) * 100
            return round(pct_return, 2)
    except Exception:
        pass
    return 0.0


# ============================================================
# MAIN ENGINE
# ============================================================
def execute_sentiment_engine():
    total = len(TICKERS)
    print(f"🚀 Running AI Swing Trading Engine — {total} tickers")
    print("=" * 74)

    # PHASE 1: Bulk pre-fetch
    print("\n📡 PHASE 1: Pre-fetching news from all RSS feeds (with browser headers)...")
    print("-" * 74)
    exchange_cache = build_exchange_news_cache()
    print("-" * 74)

    # PHASE 2: Process each ticker
    print(f"\n📊 PHASE 2: Processing {total} tickers...")
    print("-" * 74)

    processed_rows = []
    source_stats = {}
    hits = 0

    for idx, ticker in enumerate(TICKERS, 1):
        print(f"[{idx:3d}/{total}] {ticker:<15s}", end=" ")

        headline, source = get_live_news_headline(ticker, exchange_cache)
        source_stats[source] = source_stats.get(source, 0) + 1

        if source in ("yfinance",):
            time.sleep(0.3)

        realized_return = get_live_price_return(ticker)
        forecast_score, forecast_dir = compute_finbert_score(headline)

        if realized_return > 0.25:
            actual_dir = 1
        elif realized_return < -0.25:
            actual_dir = -1
        else:
            actual_dir = 0

        is_hit = forecast_dir == actual_dir
        if is_hit:
            hits += 1

        # Console labels
        src_labels = {
            "mc_topnews": "💰MC-Top", "mc_business": "💼MC-Biz",
            "mc_markets": "📈MC-Mkt", "mc_stocks": "📰MC-Stk",
            "et_markets": "📊ET-Mkt", "et_stocks": "📊ET-Stk",
            "et_news": "📊ET-News",
            "mint_market": "🌿Mint-M", "mint_companies": "🌿Mint-C",
            "nse_announce": "🏛️NSE", "nse_actions": "📋NSE-CA",
            "bse_announce": "🏦BSE",
            "yfinance": "📰YF", "fallback": "⚪FB"
        }
        src_label = src_labels.get(source, f"❓{source}")
        dir_map = {1: "🟢", -1: "🔴", 0: "⚪"}
        dir_emoji = dir_map.get(forecast_dir, "⚪")
        hit_emoji = "✅" if is_hit else "❌"

        print(f"{src_label:10s} {dir_emoji} Score:{forecast_score:+6.1f} | Ret:{realized_return:+6.2f}% | {hit_emoji}")

        processed_rows.append({
            "Ticker": ticker,
            "Latest_Headline": headline,
            "Repeat_Count": 1,
            "Forecast_Score": forecast_score,
            "Forecast_Direction": forecast_dir,
            "Actual_Direction": actual_dir,
            "Actual_Return_Pct": realized_return
        })

    df = pd.DataFrame(processed_rows)
    df.to_csv("data.csv", index=False)

    # ============================================================
    # SUMMARY
    # ============================================================
    hit_rate = (hits / total) * 100 if total > 0 else 0
    bullish_c = sum(1 for r in processed_rows if r["Forecast_Direction"] == 1)
    bearish_c = sum(1 for r in processed_rows if r["Forecast_Direction"] == -1)
    neutral_c = sum(1 for r in processed_rows if r["Forecast_Direction"] == 0)
    fb_count = source_stats.get("fallback", 0)

    # Group sources
    mc_total = sum(v for k, v in source_stats.items() if k.startswith("mc_"))
    et_total = sum(v for k, v in source_stats.items() if k.startswith("et_"))
    mint_total = sum(v for k, v in source_stats.items() if k.startswith("mint_"))
    nse_total = sum(v for k, v in source_stats.items() if k.startswith("nse_"))
    bse_total = sum(v for k, v in source_stats.items() if k.startswith("bse_"))
    yf_total = source_stats.get("yfinance", 0)

    print("\n" + "=" * 74)
    print(f"✅ data.csv written — {total} tickers")
    print(f"")
    print(f"📊 ACCURACY:       {hits}/{total} = {hit_rate:.1f}%")
    print(f"")
    print(f"📈 SIGNALS:        🟢 Bullish: {bullish_c}  |  🔴 Bearish: {bearish_c}  |  ⚪ Neutral: {neutral_c}")
    print(f"")
    print(f"📰 NEWS SOURCES:")
    for s in sorted(source_stats.keys()):
        label = src_labels.get(s, s)
        print(f"   {label:20s} {source_stats[s]}")
    print(f"   ─────────────────────────────────────")
    print(f"   💰 Moneycontrol:        {mc_total}/{total}")
    print(f"   📊 Economic Times:      {et_total}/{total}")
    print(f"   🌿 LiveMint:            {mint_total}/{total}")
    print(f"   🏛️  NSE Official:        {nse_total}/{total}")
    print(f"   🏦 BSE Official:         {bse_total}/{total}")
    print(f"   📰 yfinance:            {yf_total}/{total}")
    print(f"   ⚪ No Coverage:          {fb_count}/{total} ({fb_count/total*100:.0f}%)")
    print(f"")
    if fb_count > total * 0.4:
        print(f"⚠️  WARNING: {fb_count}/{total} tickers had NO news")
    print("=" * 74)


if __name__ == "__main__":
    execute_sentiment_engine()
