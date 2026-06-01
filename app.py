import pandas as pd
import yfinance as yf
import feedparser
import re
import time
import urllib.parse

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

print("🤖 Initializing FinBERT Neural Network Pipeline...")
FINBERT_MODEL = "ProsusAI/finbert"
tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)


# ============================================================
# 172 unique swing trading tickers
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
    "CIGNITITEC", "MPSLTD", "OFSS", "KFINTECH",
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
    "ABB", "ATLANTAELE", "ELECON", "GVTD", "TDPOWERSYS",
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

# Build a set of uppercase tickers for fast matching
TICKERS_SET = {t.upper() for t in TICKERS}


# ============================================================
# RSS FEED URLS — Official Exchange + Moneycontrol
# ============================================================

# --- Official Exchange Feeds (bulk — one fetch covers all tickers) ---
NSE_ANNOUNCEMENTS_RSS = "https://archives.nseindia.com/content/RSS/Online_announcements.xml"
NSE_CORP_ACTIONS_RSS  = "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml"
BSE_ANNOUNCEMENTS_RSS = "https://www.bseindia.com/data/xml/RSSFeed.xml"

# --- Moneycontrol Feeds (bulk — company names mentioned in headlines) ---
MC_FEEDS = {
    "mc_topnews":   "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "mc_business":  "https://www.moneycontrol.com/rss/business.xml",
    "mc_markets":   "https://www.moneycontrol.com/rss/marketreports.xml",
}

# --- Common company name → ticker mapping ---
# Moneycontrol headlines use full company names, not NSE symbols
# This mapping helps match "Eicher Motors" → EICHERMOT, etc.
COMPANY_ALIASES = {
    "EICHER MOTORS": "EICHERMOT", "EICHER": "EICHERMOT",
    "HERO MOTOCORP": "HEROMOTOCO", "HERO MOTO": "HEROMOTOCO",
    "MARUTI SUZUKI": "MARUTI", "MARUTI": "MARUTI",
    "ESCORTS KUBOTA": "ESCORTS", "ESCORTS": "ESCORTS",
    "BOSCH": "BOSCHLTD", "BOSCH LTD": "BOSCHLTD",
    "BHARAT ELECTRONICS": "BEL", "BEL": "BEL",
    "DATA PATTERNS": "DATAPATTNS",
    "GARDEN REACH": "GRSE", "GRSE": "GRSE",
    "HINDUSTAN AERONAUTICS": "HAL", "HAL": "HAL",
    "MAZAGON DOCK": "MAZDOCK",
    "ECLERX": "ECLERX", "ECLERX SERVICES": "ECLERX",
    "PERSISTENT SYSTEMS": "PERSISTENT", "PERSISTENT": "PERSISTENT",
    "ZENSARTECH": "ZENSARTECH", "ZENSAR": "ZENSARTECH",
    "NATIONAL ALUMINIUM": "NATIONALUM", "NALCO": "NATIONALUM",
    "HINDUSTAN COPPER": "HINDCOPPER",
    "COAL INDIA": "COALINDIA",
    "HDFC AMC": "HDFCAMC", "HDFC ASSET": "HDFCAMC",
    "ANGEL ONE": "ANGELONE", "ANGELONE": "ANGELONE",
    "MOTILAL OSWAL": "MOTILALOFS",
    "CRISIL": "CRISIL",
    "CARE RATINGS": "CARERATING",
    "ICRA": "ICRA",
    "ITC": "ITC", "ITC LTD": "ITC",
    "JYOTHY LABS": "JYOTHYLAB", "JYOTHY": "JYOTHYLAB",
    "KEI INDUSTRIES": "KEI", "KEI": "KEI",
    "POLYCAB": "POLYCAB", "POLYCAB INDIA": "POLYCAB",
    "NBCC": "NBCC", "NBCC INDIA": "NBCC",
    "NCC": "NCC", "NCC LTD": "NCC",
    "CUMMINS INDIA": "CUMMINSIND", "CUMMINS": "CUMMINSIND",
    "ABB": "ABB", "ABB INDIA": "ABB",
    "PFC": "PFC", "POWER FINANCE": "PFC",
    "REC": "RECLTD", "REC LTD": "RECLTD",
    "MEDANTA": "MEDANTA", "GLOBAL HEALTH": "MEDANTA",
    "BLUE STAR": "BLUESTARCO", "BLUESTAR": "BLUESTARCO",
    "LINDE INDIA": "LINDEINDIA", "LINDE": "LINDEINDIA",
    "SBI LIFE": "SBILIFE", "SBI LIFE INSURANCE": "SBILIFE",
    "TRANSPORT CORPORATION": "TCI", "TCI": "TCI",
    "CASTROL": "CASTROLIND", "CASTROL INDIA": "CASTROLIND",
    "TIPS MUSIC": "TIPSMUSIC", "TIPS INDUSTRIES": "TIPSMUSIC",
    "COROMANDEL": "COROMANDEL", "COROMANDEL INTERNATIONAL": "COROMANDEL",
    "ABBOTT INDIA": "ABBOTINDIA", "ABBOTT": "ABBOTINDIA",
    "ALKEM": "ALKEM", "ALKEM LABORATORIES": "ALKEM",
    "CIPLA": "CIPLA",
    "TORRENT PHARMA": "TORNTPHARM", "TORRENT PHARMACEUTICALS": "TORNTPHARM",
    "SAFARI INDUSTRIES": "SAFARI", "SAFARI": "SAFARI",
    "TRENT": "TRENT", "TRENT LTD": "TRENT",
    "LODHA": "LODHA", "MACROTECH": "LODHA", "MACROTECH DEVELOPERS": "LODHA",
    "BAJAJ FINANCE": "BAJFINANCE",
    "AU SMALL FINANCE": "AUBANK", "AU BANK": "AUBANK",
    "CHOLAMANDALAM": "CHOLAFIN", "CHOLA FINANCE": "CHOLAFIN",
    "MUTHOOT FINANCE": "MUTHOOTFIN", "MUTHOOT": "MUTHOOTFIN",
    "SHRIRAM FINANCE": "SHRIRAMFIN", "SHRIRAM": "SHRIRAMFIN",
    "SUNDARAM FINANCE": "SUNDARMFIN",
    "HUDCO": "HUDCO",
    "MCX": "MCX",
    "GRAVITA": "GRAVITA", "GRAVITA INDIA": "GRAVITA",
    "APL APOLLO": "APLAPOLLO", "APL APOLLO TUBES": "APLAPOLLO",
    "AFFLE": "AFFLE", "AFFLE INDIA": "AFFLE",
    "HYUNDAI": "HYUNDAI", "HYUNDAI MOTOR INDIA": "HYUNDAI",
    "BIKAJI": "BIKAJI", "BIKAJI FOODS": "BIKAJI",
    "OFSS": "OFSS", "ORACLE FINANCIAL": "OFSS",
    "BAJAJ HOLDINGS": "BAJAJHLDNG",
    "RAILTEL": "RAILTEL",
    "DOMS": "DOMS", "DOMS INDUSTRIES": "DOMS",
}


# ============================================================
# PHASE 1: PRE-FETCH ALL BULK RSS FEEDS
# ============================================================
def _match_ticker_in_text(text_upper):
    """
    Tries to match a ticker from our watchlist in the given text.
    First tries direct ticker match, then tries company alias mapping.
    Returns ticker string or None.
    """
    # Direct ticker match (e.g., "COALINDIA" appears in headline)
    for ticker in TICKERS:
        if ticker.upper() in text_upper:
            return ticker

    # Alias match (e.g., "Coal India" in headline → COALINDIA)
    for alias, ticker in COMPANY_ALIASES.items():
        if alias in text_upper:
            return ticker

    return None


def _fetch_single_rss(url, source_label):
    """Fetches a single RSS feed and returns list of (ticker, headline, source)."""
    matches = []
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            print(f"   ⚠️ {source_label}: No entries returned")
            return matches

        for entry in feed.entries:
            title = entry.get("title", "")
            desc = entry.get("description", entry.get("summary", ""))
            full_text = f"{title} {desc}".upper()

            matched_ticker = _match_ticker_in_text(full_text)
            if matched_ticker and title.strip():
                headline = title.strip().replace(",", ";")
                matches.append((matched_ticker, headline, source_label))

        print(f"   ✅ {source_label}: {len(matches)} ticker matches from {len(feed.entries)} entries")
    except Exception as e:
        print(f"   ⚠️ {source_label} failed: {e}")
    return matches


def build_exchange_news_cache():
    """
    Pre-fetches all bulk RSS feeds (NSE + BSE + Moneycontrol).
    Returns dict: {TICKER: {"headline": str, "source": str}}
    First match wins — priority order determines which source takes precedence.
    """
    cache = {}

    # --- Priority 1: Moneycontrol (most relevant for sentiment analysis) ---
    print("📡 Fetching Moneycontrol RSS feeds...")
    for source_key, url in MC_FEEDS.items():
        matches = _fetch_single_rss(url, source_key)
        for ticker, headline, source in matches:
            if ticker not in cache:
                cache[ticker] = {"headline": headline, "source": source}

    # --- Priority 2: NSE Corporate Announcements ---
    print("📡 Fetching NSE Corporate Announcements RSS...")
    matches = _fetch_single_rss(NSE_ANNOUNCEMENTS_RSS, "nse_announce")
    for ticker, headline, source in matches:
        if ticker not in cache:
            cache[ticker] = {"headline": headline, "source": source}

    # --- Priority 3: NSE Corporate Actions ---
    print("📡 Fetching NSE Corporate Actions RSS...")
    matches = _fetch_single_rss(NSE_CORP_ACTIONS_RSS, "nse_actions")
    for ticker, headline, source in matches:
        if ticker not in cache:
            cache[ticker] = {"headline": headline, "source": source}

    # --- Priority 4: BSE Corporate Announcements ---
    print("📡 Fetching BSE Corporate Announcements RSS...")
    matches = _fetch_single_rss(BSE_ANNOUNCEMENTS_RSS, "bse_announce")
    for ticker, headline, source in matches:
        if ticker not in cache:
            cache[ticker] = {"headline": headline, "source": source}

    # Summary
    source_breakdown = {}
    for v in cache.values():
        s = v["source"]
        source_breakdown[s] = source_breakdown.get(s, 0) + 1

    print(f"\n📦 Exchange cache built: {len(cache)} tickers pre-loaded")
    for s, count in sorted(source_breakdown.items()):
        print(f"   {s}: {count}")

    return cache


# ============================================================
# FINBERT SCORING
# ============================================================
def compute_finbert_score(headline):
    """
    Runs headline through FinBERT.
    Returns compound_score (-100 to +100) and direction (-1, 0, 1).
    """
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

        # ±5 threshold for swing trading sensitivity
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
# PER-TICKER NEWS FALLBACK: yfinance only (Google dropped)
# ============================================================
def get_news_from_yfinance(ticker):
    """yfinance built-in news API — per-ticker, reliable."""
    try:
        yf_ticker = yf.Ticker(f"{ticker}.NS")
        news = yf_ticker.news
        if news and len(news) > 0:
            headline = news[0].get("title", "")
            if headline:
                return headline.replace(",", ";")
    except Exception as e:
        print(f"  ⚠️ yfinance news failed for {ticker}: {e}")
    return None


def get_live_news_headline(ticker, exchange_cache):
    """
    5-source waterfall (Google dropped):
      1. Moneycontrol RSS (from cache — top news, business, markets)
      2. NSE Corporate Announcements RSS (from cache)
      3. NSE Corporate Actions RSS (from cache)
      4. BSE Corporate Announcements RSS (from cache)
      5. yfinance news API (per-ticker)
      6. Fallback placeholder
    """
    # Sources 1-4: Check bulk cache (Moneycontrol → NSE → BSE)
    if ticker in exchange_cache:
        return exchange_cache[ticker]["headline"], exchange_cache[ticker]["source"]

    # Source 5: yfinance news
    headline = get_news_from_yfinance(ticker)
    if headline:
        return headline, "yfinance"

    # Source 6: Fallback
    return f"Stable trade volatility tracked on exchange indices for {ticker}.", "fallback"


# ============================================================
# PRICE DATA
# ============================================================
def get_live_price_return(ticker_symbol):
    """Fetches last 2 trading-day closes, computes daily return %."""
    try:
        yf_ticker = yf.Ticker(f"{ticker_symbol}.NS")
        history = yf_ticker.history(period="5d")
        if len(history) >= 2:
            prev_close = history['Close'].iloc[-2]
            current_close = history['Close'].iloc[-1]
            pct_return = ((current_close - prev_close) / prev_close) * 100
            return round(pct_return, 2)
        else:
            print(f"  ⚠️ Insufficient data for {ticker_symbol} ({len(history)} rows)")
    except Exception as e:
        print(f"  ⚠️ YFinance block for {ticker_symbol}: {e}")
    return 0.0


# ============================================================
# MAIN ENGINE
# ============================================================
def execute_sentiment_engine():
    total = len(TICKERS)
    print(f"🚀 Running AI Swing Trading Engine — {total} tickers")
    print("=" * 74)

    # ---- PHASE 1: Bulk pre-fetch (6 RSS calls cover all tickers) ----
    print("\n📡 PHASE 1: Pre-fetching official exchange + Moneycontrol feeds...")
    print("-" * 74)
    exchange_cache = build_exchange_news_cache()
    print("-" * 74)

    # ---- PHASE 2: Process each ticker ----
    print(f"\n📊 PHASE 2: Processing {total} tickers...")
    print("-" * 74)

    processed_rows = []
    source_stats = {
        "mc_topnews": 0, "mc_business": 0, "mc_markets": 0,
        "nse_announce": 0, "nse_actions": 0, "bse_announce": 0,
        "yfinance": 0, "fallback": 0
    }
    hits = 0

    for idx, ticker in enumerate(TICKERS, 1):
        print(f"[{idx:3d}/{total}] {ticker:<15s}", end=" ")

        # Fetch news (5-source waterfall, no Google)
        headline, source = get_live_news_headline(ticker, exchange_cache)
        source_stats[source] = source_stats.get(source, 0) + 1

        # Delay only for per-ticker API calls (yfinance)
        if source == "yfinance":
            time.sleep(0.3)

        # Fetch price
        realized_return = get_live_price_return(ticker)

        # FinBERT scoring
        forecast_score, forecast_dir = compute_finbert_score(headline)

        # 3-state actual direction
        if realized_return > 0.25:
            actual_dir = 1
        elif realized_return < -0.25:
            actual_dir = -1
        else:
            actual_dir = 0

        is_hit = forecast_dir == actual_dir
        if is_hit:
            hits += 1

        # Source labels for console
        src_labels = {
            "mc_topnews":   "💰MC-Top",
            "mc_business":  "💼MC-Biz",
            "mc_markets":   "📈MC-Mkt",
            "nse_announce": "🏛️NSE",
            "nse_actions":  "📋NSE-CA",
            "bse_announce": "🏦BSE",
            "yfinance":     "📰YF",
            "fallback":     "⚪FB"
        }
        src_label = src_labels.get(source, "❓")

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
    # SUMMARY REPORT
    # ============================================================
    hit_rate = (hits / total) * 100 if total > 0 else 0
    bullish_count = sum(1 for r in processed_rows if r["Forecast_Direction"] == 1)
    bearish_count = sum(1 for r in processed_rows if r["Forecast_Direction"] == -1)
    neutral_count = sum(1 for r in processed_rows if r["Forecast_Direction"] == 0)

    mc_count = source_stats.get("mc_topnews", 0) + source_stats.get("mc_business", 0) + source_stats.get("mc_markets", 0)
    exchange_count = source_stats.get("nse_announce", 0) + source_stats.get("nse_actions", 0) + source_stats.get("bse_announce", 0)
    yf_count = source_stats.get("yfinance", 0)
    fb_count = source_stats.get("fallback", 0)

    print("\n" + "=" * 74)
    print(f"✅ data.csv written — {total} tickers")
    print(f"")
    print(f"📊 ACCURACY:       {hits}/{total} = {hit_rate:.1f}%")
    print(f"")
    print(f"📈 SIGNALS:        🟢 Bullish: {bullish_count}  |  🔴 Bearish: {bearish_count}  |  ⚪ Neutral: {neutral_count}")
    print(f"")
    print(f"📰 NEWS SOURCES:")
    print(f"   💰  Moneycontrol Top News:   {source_stats.get('mc_topnews', 0)}")
    print(f"   💼  Moneycontrol Business:    {source_stats.get('mc_business', 0)}")
    print(f"   📈  Moneycontrol Markets:     {source_stats.get('mc_markets', 0)}")
    print(f"   🏛️  NSE Announcements:        {source_stats.get('nse_announce', 0)}")
    print(f"   📋  NSE Corp Actions:          {source_stats.get('nse_actions', 0)}")
    print(f"   🏦  BSE Announcements:         {source_stats.get('bse_announce', 0)}")
    print(f"   📰  yfinance News:             {yf_count}")
    print(f"   ⚪  Fallback (no news):        {fb_count}")
    print(f"   ─────────────────────────────────────")
    print(f"   💰  Moneycontrol:              {mc_count}/{total} ({mc_count/total*100:.0f}%)")
    print(f"   🏛️  Official Exchange:         {exchange_count}/{total} ({exchange_count/total*100:.0f}%)")
    print(f"   📰  yfinance:                  {yf_count}/{total} ({yf_count/total*100:.0f}%)")
    print(f"   ⚪  No Coverage:               {fb_count}/{total} ({fb_count/total*100:.0f}%)")
    print(f"")
    if fb_count > total * 0.4:
        print(f"⚠️  WARNING: {fb_count}/{total} tickers had NO news — review ticker names or add aliases")
    print("=" * 74)


if __name__ == "__main__":
    execute_sentiment_engine()
