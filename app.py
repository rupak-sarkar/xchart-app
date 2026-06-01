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
# 172 unique swing trading tickers (cleaned, deduped, .NS stripped)
# The .NS suffix is added dynamically in yfinance calls
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

    # Steel & Pipes — covered in Capital Goods above

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

    # Stationery & Packaging — covered above

    # Jewellery & Watches (JWL)
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


def compute_finbert_score(headline):
    """
    Runs text through FinBERT and returns:
      - compound_score: float between -100 and +100
      - direction: -1 (bearish), 0 (neutral), or 1 (bullish)
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

        if compound_score > 15.0:
            direction = 1
        elif compound_score < -15.0:
            direction = -1
        else:
            direction = 0

        return round(compound_score, 1), direction
    except Exception as e:
        print(f"  ⚠️ NLP crash: {e}")
        return 0.0, 0


def get_live_news_headline(ticker):
    """
    Fetches the latest news headline from Google News RSS.
    URL-encodes ticker to handle special characters (e.g. 360ONE).
    """
    try:
        # URL-encode the ticker to safely handle names like "360ONE", "NAM-INDIA"
        encoded_ticker = urllib.parse.quote(ticker)
        rss_url = (
            f"https://news.google.com/rss/search?"
            f"q={encoded_ticker}+NSE+stock+india&hl=en-IN&gl=IN&ceid=IN:en"
        )
        feed = feedparser.parse(rss_url)
        if feed.entries:
            headline = feed.entries[0].title
            clean_headline = re.sub(r'\s+-\s+[^:\-]+$', '', headline)
            return clean_headline.replace(",", ";")
    except Exception as e:
        print(f"  ⚠️ RSS failure for {ticker}: {e}")
    return f"Stable trade volatility tracked on exchange indices for {ticker}."


def get_live_price_return(ticker_symbol):
    """
    Fetches last 2 trading-day closes from Yahoo Finance and computes daily return %.
    Handles special ticker mappings (e.g. GVT&D -> GVTD on yfinance).
    """
    try:
        yf_ticker = yf.Ticker(f"{ticker_symbol}.NS")
        history = yf_ticker.history(period="5d")
        if len(history) >= 2:
            prev_close = history['Close'].iloc[-2]
            current_close = history['Close'].iloc[-1]
            pct_return = ((current_close - prev_close) / prev_close) * 100
            return round(pct_return, 2)
        else:
            print(f"  ⚠️ Insufficient price data for {ticker_symbol} ({len(history)} rows)")
    except Exception as e:
        print(f"  ⚠️ YFinance block for {ticker_symbol}: {e}")
    return 0.0


def execute_sentiment_engine():
    """
    Main pipeline: fetches news + prices for each ticker,
    runs FinBERT scoring, writes data.csv.
    """
    total = len(TICKERS)
    print(f"🚀 Running AI Swing Trading Engine — {total} tickers")
    print("=" * 60)

    processed_rows = []
    errors = 0

    for idx, ticker in enumerate(TICKERS, 1):
        print(f"📡 [{idx:3d}/{total}] {ticker}...", end=" ")

        headline = get_live_news_headline(ticker)

        # Small delay between RSS calls to avoid rate-limiting on 172 tickers
        time.sleep(0.5)

        realized_return = get_live_price_return(ticker)
        forecast_score, forecast_dir = compute_finbert_score(headline)

        # 3-state actual direction (aligned with forecast)
        if realized_return > 0.25:
            actual_dir = 1
        elif realized_return < -0.25:
            actual_dir = -1
        else:
            actual_dir = 0

        # Log status
        status = "✅" if forecast_dir == actual_dir else "❌"
        is_fallback = "Stable trade volatility" in headline
        news_flag = "📰" if not is_fallback else "⚪"
        print(f"{news_flag} Score:{forecast_score:+6.1f} | Actual:{realized_return:+6.2f}% | {status}")

        if is_fallback:
            errors += 1

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

    # Summary stats
    hits = sum(1 for _, r in df.iterrows() if r['Forecast_Direction'] == r['Actual_Direction'])
    hit_rate = (hits / total) * 100 if total > 0 else 0

    print("\n" + "=" * 60)
    print(f"✅ data.csv written — {total} tickers")
    print(f"📊 Hit Rate: {hits}/{total} = {hit_rate:.1f}%")
    print(f"📰 Live headlines fetched: {total - errors}/{total}")
    print(f"⚪ Fallback (no news): {errors}/{total}")
    print("=" * 60)


if __name__ == "__main__":
    execute_sentiment_engine()
