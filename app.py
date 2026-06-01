import pandas as pd
import yfinance as yf
import feedparser
import requests
import re
import time
import urllib.parse

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

# ============================================================
# CRITICAL: Browser headers for all RSS fetches
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


# ============================================================
# 171 swing trading tickers
# ============================================================
TICKERS = [
    "EICHERMOT", "HEROMOTOCO", "MARUTI", "ESCORTS",
    "BANCOINDIA", "BOSCHLTD", "ENDURANCE", "FMGOETZE", "FIEMIND",
    "GABRIEL", "LGBBROSLTD", "PRICOLLTD", "SANSERA", "SHARDAMOTR",
    "SHRIPISTON", "UNOMINDA", "ZFCVINDIA",
    "BEL", "DATAPATTNS", "GRSE", "HAL", "MAZDOCK",
    "ZENTEC", "ECLERX", "NEWGEN", "PERSISTENT", "RATEGAIN",
    "SAKSOFT", "ZENSARTECH", "CONTROLPR", "DLINKINDIA", "AFFLE",
    "COFORGE", "MPSLTD", "OFSS", "KFINTECH",
    "NATIONALUM", "HINDCOPPER", "COALINDIA", "GMDCLTD", "NAVA",
    "GRAVITA", "TEGA",
    "HDFCAMC", "NAM-INDIA", "360ONE", "ANGELONE", "MOTILALOFS",
    "NUVAMA", "IIFLCAPS", "PRUDENT", "CRISIL", "CARERATING", "ICRA",
    "GMBREW", "PICCADIL", "SDBL", "ITC", "JYOTHYLAB",
    "BIKAJI", "BECTORFOOD", "DODLA", "LTFOODS",
    "KEI", "POLYCAB",
    "HSCL", "AIAENG", "GODFRYPHLP", "AHLUCONT", "CEMPRO",
    "INTERARCH", "MANINFRA", "NBCC", "NCC", "POWERMECH", "TECHNOE",
    "ACE", "APLAPOLLO", "MAHSEAMLES", "WELCORP",
    "CUMMINSIND", "INGERRAND", "KIRLOSBROS", "KIRLPNU", "SHAKTIPUMP",
    "GRAUWEIL",
    "ABB", "ATLANTAELE", "ELECON", "TDPOWERSYS",
    "TRANSRAILL", "TRITURBINE", "VOLTAMP", "PFC", "RECLTD",
    "DPABHUSHAN", "GOLDIAM", "POKARNA",
    "MEDANTA", "INDRAMEDCO", "KOVAI",
    "TAJGVK", "TRAVELFOOD",
    "BLUESTARCO", "LGEINDIA",
    "LINDEINDIA", "EPIGRAL", "VISHNU",
    "SBILIFE",
    "TCI", "GESHIP",
    "CASTROLIND", "GULFOILLUB",
    "TIPSMUSIC", "DBCORP",
    "POLYMED",
    "AIIL", "KSCL", "SHILCTECH", "WAAREERTL", "NESCO",
    "VESUVIUS", "MCX", "COROMANDEL", "ORKLAINDIA", "HBLENGINE",
    "RAILTEL", "AGI",
    "ABBOTINDIA", "ACUTAAS", "ALIVUS", "ALKEM", "CAPLIPOINT",
    "CIPLA", "INNOVACAP", "JBCHEPHARM", "MARKSANS", "SUPRIYA",
    "TORNTPHARM",
    "SAFARI", "TRENT", "DOMS", "HYUNDAI",
    "GRWRHITECH", "KINGFA", "TIMETECHNO", "STYLAMIND",
    "JWL",
    "ARVSMART", "GANESHHOU", "LODHA", "MARATHON", "INDIASHLTR",
    "NUCLEUS",
    "BLS", "EIEL",
    "ARSSBL", "AUBANK", "BAJFINANCE", "GROWW", "CANFINHOME",
    "CHOLAHLDNG", "CHOLAFIN", "HUDCO", "HOMEFIRST",
    "MUTHOOTFIN", "SHRIRAMFIN", "SUNDARMFIN",
    "BAJAJHLDNG", "SYSTMTXC", "TVSHLTD",
]


# ============================================================
# ALL RSS FEEDS — 18 feeds across 8 sources
# ============================================================
ALL_FEEDS = {
    # Moneycontrol (4 feeds)
    "mc_topnews":       "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "mc_business":      "https://www.moneycontrol.com/rss/business.xml",
    "mc_markets":       "https://www.moneycontrol.com/rss/marketreports.xml",
    "mc_stocks":        "https://www.moneycontrol.com/rss/latestnews.xml",

    # Economic Times (3 feeds)
    "et_markets":       "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks":        "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "et_news":          "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146843.cms",

    # NDTV Profit (2 feeds) — NEW
    "ndtv_business":    "https://feeds.feedburner.com/ndtvprofit-latest",
    "ndtv_markets":     "https://feeds.feedburner.com/ndtvprofit-markets",

    # Business Standard (2 feeds) — NEW
    "bs_markets":       "https://www.business-standard.com/rss/markets-106.rss",
    "bs_companies":     "https://www.business-standard.com/rss/companies-101.rss",

    # LiveMint (2 feeds)
    "mint_market":      "https://www.livemint.com/rss/market",
    "mint_companies":   "https://www.livemint.com/rss/companies",

    # NSE Official (2 feeds)
    "nse_announce":     "https://archives.nseindia.com/content/RSS/Online_announcements.xml",
    "nse_actions":      "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",

    # BSE Official (3 feeds) — FIXED URLs from beta.bseindia.com
    "bse_announce":     "https://beta.bseindia.com/Msource/data/xml/RSSFeed.xml",
    "bse_board":        "https://beta.bseindia.com/Msource/data/xml/BoardMeetings.xml",
    "bse_results":      "https://beta.bseindia.com/Msource/data/xml/FinancialResults.xml",
}


# ============================================================
# COMPANY ALIAS MAP (100+ mappings)
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
    "TRANSPORT CORPORATION": "TCI",
    "CASTROL": "CASTROLIND", "CASTROL INDIA": "CASTROLIND",
    "TIPS MUSIC": "TIPSMUSIC", "TIPS INDUSTRIES": "TIPSMUSIC",
    "COROMANDEL": "COROMANDEL", "COROMANDEL INTERNATIONAL": "COROMANDEL",
    "ABBOTT INDIA": "ABBOTINDIA", "ABBOTT": "ABBOTINDIA",
    "ALKEM": "ALKEM", "ALKEM LAB": "ALKEM",
    "CIPLA": "CIPLA",
    "TORRENT PHARMA": "TORNTPHARM", "TORRENT PHARMACEUTICALS": "TORNTPHARM",
    "SAFARI INDUSTRIES": "SAFARI",
    "TRENT": "TRENT", "TRENT LTD": "TRENT",
    "LODHA": "LODHA", "MACROTECH": "LODHA", "MACROTECH DEVELOPERS": "LODHA",
    "BAJAJ FINANCE": "BAJFINANCE", "BAJAJ FIN": "BAJFINANCE",
    "AU SMALL FINANCE": "AUBANK", "AU BANK": "AUBANK",
    "CHOLAMANDALAM": "CHOLAFIN", "CHOLA": "CHOLAFIN",
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
    "ORACLE FINANCIAL": "OFSS",
    "BAJAJ HOLDINGS": "BAJAJHLDNG",
    "RAILTEL": "RAILTEL", "RAILTEL CORP": "RAILTEL",
    "DOMS": "DOMS", "DOMS INDUSTRIES": "DOMS",
    "DODLA DAIRY": "DODLA",
    "LT FOODS": "LTFOODS",
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
    "MARKSANS": "MARKSANS", "MARKSANS PHARMA": "MARKSANS",
    "SUPRIYA": "SUPRIYA", "SUPRIYA LIFESCIENCE": "SUPRIYA",
    "TEGA": "TEGA", "TEGA INDUSTRIES": "TEGA",
    "DATA PATTERNS": "DATAPATTNS",
    "NATIONAL ALUMINIUM": "NATIONALUM",
    "ENDURANCE": "ENDURANCE", "ENDURANCE TECH": "ENDURANCE",
    "HINDCOPPER": "HINDCOPPER",
    "TATA INVESTMENT": "SYSTMTXC",
    "TVS HOLDINGS": "TVSHLTD",
    "INDIAN HOTELS": "TAJGVK",
    "ANAND RATHI": "360ONE",
}


# ============================================================
# RSS FETCH WITH BROWSER HEADERS
# ============================================================
def fetch_rss_with_headers(url, source_label, timeout=15):
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        return feed
    except requests.exceptions.RequestException as e:
        print(f"   ⚠️ {source_label} requests failed: {e}")
        try:
            feed = feedparser.parse(url)
            return feed
        except Exception:
            return None


# ============================================================
# TICKER MATCHING
# ============================================================
def match_ticker_in_text(text_upper):
    for ticker in sorted(TICKERS, key=len, reverse=True):
        if re.search(r'\b' + re.escape(ticker.upper()) + r'\b', text_upper):
            return ticker
    for alias, ticker in COMPANY_ALIASES.items():
        if alias in text_upper:
            return ticker
    return None


# ============================================================
# PHASE 1: BUILD NEWS CACHE FROM ALL BULK RSS FEEDS
# ============================================================
def build_exchange_news_cache():
    cache = {}

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

            matched_ticker = match_ticker_in_text(full_text)
            if matched_ticker and title.strip() and matched_ticker not in cache:
                headline = title.strip().replace(",", ";")
                cache[matched_ticker] = {"headline": headline, "source": source_key}
                match_count += 1

        print(f"   ✅ {source_key}: {match_count} new matches from {len(feed.entries)} entries")
        time.sleep(0.3)

    print(f"\n📦 News cache built: {len(cache)}/{len(TICKERS)} tickers pre-loaded")
    source_breakdown = {}
    for v in cache.values():
        s = v["source"]
        source_breakdown[s] = source_breakdown.get(s, 0) + 1
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
# PER-TICKER FALLBACKS: yfinance + Google News
# ============================================================
def get_news_from_yfinance(ticker):
    try:
        yf_ticker = yf.Ticker(f"{ticker}.NS")
        news = getattr(yf_ticker, 'news', None)
        if news and isinstance(news, list) and len(news) > 0:
            first = news[0]
            if isinstance(first, dict):
                headline = first.get("title", first.get("headline", ""))
                if headline:
                    return headline.replace(",", ";")
    except Exception:
        pass
    return None


def get_news_from_google_rss(ticker):
    """Google News RSS — last resort before fallback placeholder."""
    try:
        encoded_ticker = urllib.parse.quote(ticker)
        rss_url = (
            f"https://news.google.com/rss/search?"
            f"q={encoded_ticker}+NSE+stock+india&hl=en-IN&gl=IN&ceid=IN:en"
        )
        feed = fetch_rss_with_headers(rss_url, f"google_{ticker}", timeout=8)
        if feed and feed.entries:
            headline = feed.entries[0].title
            clean_headline = re.sub(r'\s+-\s+[^:\-]+$', '', headline)
            return clean_headline.replace(",", ";")
    except Exception:
        pass
    return None


def get_live_news_headline(ticker, exchange_cache):
    """
    7-source waterfall:
      1-6. Bulk cache (MC → ET → NDTV → BS → Mint → NSE → BSE)
      7.   yfinance per-ticker
      8.   Google News RSS per-ticker (last resort)
      9.   Fallback placeholder
    """
    if ticker in exchange_cache:
        return exchange_cache[ticker]["headline"], exchange_cache[ticker]["source"]

    headline = get_news_from_yfinance(ticker)
    if headline:
        return headline, "yfinance"

    headline = get_news_from_google_rss(ticker)
    if headline:
        return headline, "google"

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
    print("=" * 76)

    # PHASE 1: Bulk pre-fetch
    print("\n📡 PHASE 1: Pre-fetching news from 18 RSS feeds...")
    print("-" * 76)
    exchange_cache = build_exchange_news_cache()
    print("-" * 76)

    # PHASE 2: Process each ticker
    print(f"\n📊 PHASE 2: Processing {total} tickers...")
    print("-" * 76)

    processed_rows = []
    source_stats = {}
    hits_with_news = 0
    total_with_news = 0
    hits_all = 0

    for idx, ticker in enumerate(TICKERS, 1):
        print(f"[{idx:3d}/{total}] {ticker:<15s}", end=" ")

        headline, source = get_live_news_headline(ticker, exchange_cache)
        source_stats[source] = source_stats.get(source, 0) + 1

        if source in ("yfinance", "google"):
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
            hits_all += 1

        has_real_news = source != "fallback"
        if has_real_news:
            total_with_news += 1
            if is_hit:
                hits_with_news += 1

        # Console output
        src_labels = {
            "mc_topnews": "💰MC-Top", "mc_business": "💼MC-Biz",
            "mc_markets": "📈MC-Mkt", "mc_stocks": "📰MC-Stk",
            "et_markets": "📊ET-Mkt", "et_stocks": "📊ET-Stk",
            "et_news": "📊ET-News",
            "ndtv_business": "📺NDTV-B", "ndtv_markets": "📺NDTV-M",
            "bs_markets": "📰BS-Mkt", "bs_companies": "📰BS-Co",
            "mint_market": "🌿Mint-M", "mint_companies": "🌿Mint-C",
            "nse_announce": "🏛️NSE", "nse_actions": "📋NSE-CA",
            "bse_announce": "🏦BSE-A", "bse_board": "🏦BSE-BM",
            "bse_results": "🏦BSE-FR",
            "yfinance": "📰YF", "google": "🔗GG", "fallback": "⚪FB"
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
    fb_count = source_stats.get("fallback", 0)
    bullish_c = sum(1 for r in processed_rows if r["Forecast_Direction"] == 1)
    bearish_c = sum(1 for r in processed_rows if r["Forecast_Direction"] == -1)
    neutral_c = sum(1 for r in processed_rows if r["Forecast_Direction"] == 0)

    # Hit rates
    hit_rate_all = (hits_all / total) * 100 if total > 0 else 0
    hit_rate_news = (hits_with_news / total_with_news) * 100 if total_with_news > 0 else 0

    # Group sources
    mc_total = sum(v for k, v in source_stats.items() if k.startswith("mc_"))
    et_total = sum(v for k, v in source_stats.items() if k.startswith("et_"))
    ndtv_total = sum(v for k, v in source_stats.items() if k.startswith("ndtv_"))
    bs_total = sum(v for k, v in source_stats.items() if k.startswith("bs_"))
    mint_total = sum(v for k, v in source_stats.items() if k.startswith("mint_"))
    nse_total = sum(v for k, v in source_stats.items() if k.startswith("nse_"))
    bse_total = sum(v for k, v in source_stats.items() if k.startswith("bse_"))
    yf_total = source_stats.get("yfinance", 0)
    gg_total = source_stats.get("google", 0)
    news_total = total - fb_count

    print("\n" + "=" * 76)
    print(f"✅ data.csv written — {total} tickers")
    print(f"")
    print(f"📊 ACCURACY (all tickers):         {hits_all}/{total} = {hit_rate_all:.1f}%")
    print(f"📊 ACCURACY (with real news only):  {hits_with_news}/{total_with_news} = {hit_rate_news:.1f}%  ← TRUE MODEL ACCURACY")
    print(f"")
    print(f"📈 SIGNALS:  🟢 Bullish: {bullish_c}  |  🔴 Bearish: {bearish_c}  |  ⚪ Neutral: {neutral_c}")
    print(f"📰 COVERAGE: {news_total}/{total} tickers had real news ({news_total/total*100:.0f}%)")
    print(f"")
    print(f"📰 NEWS SOURCES:")
    print(f"   💰 Moneycontrol:        {mc_total}")
    print(f"   📊 Economic Times:      {et_total}")
    print(f"   📺 NDTV Profit:         {ndtv_total}")
    print(f"   📰 Business Standard:   {bs_total}")
    print(f"   🌿 LiveMint:            {mint_total}")
    print(f"   🏛️  NSE Official:        {nse_total}")
    print(f"   🏦 BSE Official:         {bse_total}")
    print(f"   📰 yfinance:            {yf_total}")
    print(f"   🔗 Google News:          {gg_total}")
    print(f"   ⚪ Fallback:             {fb_count}")
    print(f"   ─────────────────────────────────────")
    print(f"   📰 Total with news:      {news_total}/{total} ({news_total/total*100:.0f}%)")
    print(f"   ⚪ No Coverage:           {fb_count}/{total} ({fb_count/total*100:.0f}%)")
    print("=" * 76)


if __name__ == "__main__":
    execute_sentiment_engine()
