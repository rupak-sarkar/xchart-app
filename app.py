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
TODAY_IST = datetime.now(IST).strftime("%Y-%m-%d")

TICKERS_FILE = "tickers.csv"
HISTORY_FILE = "history.csv"
DATA_FILE = "data.csv"


# ============================================================
# LOAD TICKERS FROM CSV (source of truth)
# ============================================================
def load_tickers():
    """
    Reads ticker list from tickers.csv.
    Expected format: Ticker,Sector
    Falls back to a minimal default if file is missing.
    """
    if os.path.exists(TICKERS_FILE):
        try:
            df = pd.read_csv(TICKERS_FILE)
            df.columns = df.columns.str.strip()
            if 'Ticker' not in df.columns:
                print(f"⚠️ tickers.csv missing 'Ticker' column. Found: {list(df.columns)}")
                print("   Attempting to use first column as ticker...")
                df.rename(columns={df.columns[0]: 'Ticker'}, inplace=True)

            tickers = df['Ticker'].dropna().str.strip().str.upper().tolist()
            # Remove .NS suffix if present
            tickers = [t.replace('.NS', '') for t in tickers if t]
            # Deduplicate while preserving order
            seen = set()
            unique = []
            for t in tickers:
                if t not in seen:
                    seen.add(t)
                    unique.append(t)

            # Build sector map
            sector_map = {}
            if 'Sector' in df.columns:
                for _, row in df.iterrows():
                    ticker = str(row['Ticker']).strip().upper().replace('.NS', '')
                    sector = str(row.get('Sector', '')).strip()
                    if ticker and sector:
                        sector_map[ticker] = sector

            print(f"📋 Loaded {len(unique)} tickers from {TICKERS_FILE}")
            return unique, sector_map
        except Exception as e:
            print(f"⚠️ Error reading {TICKERS_FILE}: {e}")

    print(f"⚠️ {TICKERS_FILE} not found — using minimal default list")
    defaults = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ICICIBANK", "ITC"]
    return defaults, {}


# ============================================================
# ALL RSS FEEDS
# ============================================================
ALL_FEEDS = {
    "mc_topnews":       "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "mc_business":      "https://www.moneycontrol.com/rss/business.xml",
    "mc_markets":       "https://www.moneycontrol.com/rss/marketreports.xml",
    "mc_stocks":        "https://www.moneycontrol.com/rss/latestnews.xml",
    "et_markets":       "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks":        "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "et_news":          "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146843.cms",
    "ndtv_business":    "https://feeds.feedburner.com/ndtvprofit-latest",
    "mint_market":      "https://www.livemint.com/rss/market",
    "mint_companies":   "https://www.livemint.com/rss/companies",
    "nse_announce":     "https://archives.nseindia.com/content/RSS/Online_announcements.xml",
    "nse_actions":      "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
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
# RSS FETCH
# ============================================================
def fetch_rss_with_headers(url, source_label, timeout=15):
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        response.raise_for_status()
        return feedparser.parse(response.content)
    except requests.exceptions.RequestException as e:
        print(f"   ⚠️ {source_label} requests failed: {e}")
        try:
            return feedparser.parse(url)
        except Exception:
            return None


# ============================================================
# TICKER MATCHING (uses dynamically loaded ticker list)
# ============================================================
def match_ticker_in_text(text_upper, tickers_list):
    for ticker in sorted(tickers_list, key=len, reverse=True):
        if re.search(r'\b' + re.escape(ticker.upper()) + r'\b', text_upper):
            return ticker
    for alias, ticker in COMPANY_ALIASES.items():
        if alias in text_upper and ticker in tickers_list:
            return ticker
    return None


# ============================================================
# PHASE 1: BULK RSS CACHE
# ============================================================
def build_exchange_news_cache(tickers_list):
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
            matched_ticker = match_ticker_in_text(full_text, tickers_list)
            if matched_ticker and title.strip() and matched_ticker not in cache:
                headline = title.strip().replace(",", ";")
                cache[matched_ticker] = {"headline": headline, "source": source_key}
                match_count += 1
        print(f"   ✅ {source_key}: {match_count} new matches from {len(feed.entries)} entries")
        time.sleep(0.3)
    print(f"\n📦 News cache built: {len(cache)}/{len(tickers_list)} tickers")
    return cache


# ============================================================
# FINBERT
# ============================================================
def compute_finbert_score(headline):
    if not headline or "Stable trade volatility" in headline:
        return 0.0, 0
    try:
        inputs = tokenizer([headline], padding=True, truncation=True,
                           max_length=512, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
        predictions = torch.nn.functional.softmax(outputs.logits, dim=-1)
        pos_prob = predictions[0][0].item()
        neg_prob = predictions[0][1].item()
        compound_score = (pos_prob - neg_prob) * 100.0
        if compound_score > 5.0: direction = 1
        elif compound_score < -5.0: direction = -1
        else: direction = 0
        return round(compound_score, 1), direction
    except Exception as e:
        print(f"  ⚠️ NLP crash: {e}")
        return 0.0, 0


# ============================================================
# PER-TICKER NEWS FALLBACKS
# ============================================================
def get_news_from_yfinance(ticker):
    try:
        yf_ticker = yf.Ticker(f"{ticker}.NS")
        news = getattr(yf_ticker, 'news', None)
        if news and isinstance(news, list) and len(news) > 0:
            first = news[0]
            if isinstance(first, dict):
                headline = first.get("title", first.get("headline", ""))
                if headline: return headline.replace(",", ";")
    except Exception: pass
    return None


def get_news_from_google_rss(ticker):
    try:
        encoded_ticker = urllib.parse.quote(ticker)
        rss_url = (f"https://news.google.com/rss/search?"
                   f"q={encoded_ticker}+NSE+stock+india&hl=en-IN&gl=IN&ceid=IN:en")
        feed = fetch_rss_with_headers(rss_url, f"google_{ticker}", timeout=8)
        if feed and feed.entries:
            headline = feed.entries[0].title
            clean = re.sub(r'\s+-\s+[^:\-]+$', '', headline)
            return clean.replace(",", ";")
    except Exception: pass
    return None


def get_live_news_headline(ticker, exchange_cache):
    if ticker in exchange_cache:
        return exchange_cache[ticker]["headline"], exchange_cache[ticker]["source"]
    headline = get_news_from_yfinance(ticker)
    if headline: return headline, "yfinance"
    headline = get_news_from_google_rss(ticker)
    if headline: return headline, "google"
    return f"Stable trade volatility tracked on exchange indices for {ticker}.", "fallback"


# ============================================================
# PRICE DATA
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
# STREAK CALCULATOR
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
            ticker_hist = history_df[
                (history_df['Ticker'] == ticker) & (history_df['Date'] != TODAY_IST)
            ].sort_values('Date', ascending=False)
        else:
            ticker_hist = pd.DataFrame()

        streak_days = 1
        streak_return = today_return
        if not ticker_hist.empty:
            for _, hr in ticker_hist.iterrows():
                if int(hr.get('Forecast_Direction', 0)) == today_dir and today_dir != 0:
                    streak_days += 1
                    streak_return += float(hr.get('Actual_Return_Pct', 0))
                else:
                    break

        prev_score = float(ticker_hist.iloc[0].get('Forecast_Score', 0)) if not ticker_hist.empty else None

        if today_dir == 0:
            momentum = "Neutral"
        elif streak_days == 1:
            momentum = "New"
        elif prev_score is not None:
            if today_dir == 1:
                momentum = ("Strong" if streak_days >= 3 else "Building") if today_score >= prev_score else "Fading"
            elif today_dir == -1:
                momentum = ("Strong" if streak_days >= 3 else "Building") if today_score <= prev_score else "Fading"
            else:
                momentum = "Neutral"
        else:
            momentum = "New"

        streaks[ticker] = {
            "Streak_Days": streak_days if today_dir != 0 else 0,
            "Streak_Return": round(streak_return, 2),
            "Momentum": momentum,
        }
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
    unique_dates = combined['Date'].nunique() if 'Date' in combined.columns else 1
    print(f"📜 History: {len(combined)} rows across {unique_dates} days")


# ============================================================
# MAIN ENGINE
# ============================================================
def execute_sentiment_engine():
    # Load tickers from CSV
    tickers_list, sector_map = load_tickers()
    total = len(tickers_list)

    print(f"🚀 Running AI Swing Trading Engine — {total} tickers")
    print(f"📅 Date: {TODAY_IST}")
    print("=" * 80)

    # PHASE 1
    print("\n📡 PHASE 1: Pre-fetching news from RSS feeds...")
    print("-" * 80)
    exchange_cache = build_exchange_news_cache(tickers_list)
    print("-" * 80)

    # PHASE 2
    print(f"\n📊 PHASE 2: Processing {total} tickers...")
    print("-" * 80)

    processed_rows = []
    source_stats = {}
    hits_all = 0

    for idx, ticker in enumerate(tickers_list, 1):
        print(f"[{idx:3d}/{total}] {ticker:<15s}", end=" ")

        headline, source = get_live_news_headline(ticker, exchange_cache)
        source_stats[source] = source_stats.get(source, 0) + 1
        if source in ("yfinance", "google"): time.sleep(0.3)

        realized_return = get_live_price_return(ticker)
        forecast_score, forecast_dir = compute_finbert_score(headline)

        if realized_return > 0.25: actual_dir = 1
        elif realized_return < -0.25: actual_dir = -1
        else: actual_dir = 0

        is_hit = forecast_dir == actual_dir
        if is_hit: hits_all += 1

        src_labels = {
            "mc_topnews": "💰MC", "mc_business": "💼MC", "mc_markets": "📈MC",
            "mc_stocks": "📰MC", "et_markets": "📊ET", "et_stocks": "📊ET",
            "et_news": "📊ET", "ndtv_business": "📺NDTV",
            "mint_market": "🌿Mint", "mint_companies": "🌿Mint",
            "nse_announce": "🏛️NSE", "nse_actions": "📋NSE",
            "yfinance": "📰YF", "google": "🔗GG", "fallback": "⚪FB"
        }
        dir_map = {1: "🟢", -1: "🔴", 0: "⚪"}
        print(f"{src_labels.get(source,'❓'):8s} {dir_map.get(forecast_dir,'⚪')} Score:{forecast_score:+6.1f} | Ret:{realized_return:+6.2f}% | {'✅' if is_hit else '❌'}")

        processed_rows.append({
            "Ticker": ticker,
            "Sector": sector_map.get(ticker, ""),
            "Latest_Headline": headline,
            "Forecast_Score": forecast_score,
            "Forecast_Direction": forecast_dir,
            "Actual_Direction": actual_dir,
            "Actual_Return_Pct": realized_return,
        })

    # PHASE 3: Streaks
    print(f"\n📜 PHASE 3: Calculating signal streaks...")
    print("-" * 80)
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

    print("\n" + "=" * 80)
    print(f"✅ data.csv written — {total} tickers | Date: {TODAY_IST}")
    print(f"📊 ACCURACY: {hits_all}/{total} = {hr:.1f}%")
    print(f"📈 SIGNALS:  🟢 {bull}  |  🔴 {bear}  |  ⚪ {neut}")
    print(f"📰 COVERAGE: {total - fb}/{total} ({(total-fb)/total*100:.0f}%)")
    print("=" * 80)


if __name__ == "__main__":
    execute_sentiment_engine()
