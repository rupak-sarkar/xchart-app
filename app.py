import pandas as pd
import yfinance as yf
import feedparser
import re

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

print("🤖 Initializing FinBERT Neural Network Pipeline...")
FINBERT_MODEL = "ProsusAI/finbert"
tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)


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

        # FinBERT label order: [0 -> Positive, 1 -> Negative, 2 -> Neutral]
        pos_prob = predictions[0][0].item()
        neg_prob = predictions[0][1].item()

        # Normalized compound score from -100 to +100
        compound_score = (pos_prob - neg_prob) * 100.0

        # Direction thresholds
        if compound_score > 15.0:
            direction = 1
        elif compound_score < -15.0:
            direction = -1
        else:
            direction = 0

        return round(compound_score, 1), direction
    except Exception as e:
        print(f"⚠️ NLP Processing Crash: {e}")
        return 0.0, 0


def get_live_news_headline(ticker):
    """
    Fetches the latest news headline from Google News RSS for a given NSE ticker.
    Returns sanitized headline string (commas replaced with semicolons for CSV safety).
    """
    try:
        # FIX: Corrected Google News RSS URL
        # Original bug: was "https://google.com{ticker}+stock+india&..."
        # Missing domain (news.google.com), missing path (/rss/search?q=)
        rss_url = (
            f"https://news.google.com/rss/search?"
            f"q={ticker}+stock+india&hl=en-IN&gl=IN&ceid=IN:en"
        )
        feed = feedparser.parse(rss_url)
        if feed.entries:
            headline = feed.entries[0].title
            # Strip publisher suffix like " - Economic Times"
            clean_headline = re.sub(r'\s+-\s+[^:\-]+$', '', headline)
            # Replace commas with semicolons to protect CSV formatting
            return clean_headline.replace(",", ";")
    except Exception as e:
        print(f"⚠️ RSS failure for {ticker}: {e}")
    return f"Stable trade volatility tracked on exchange indices for {ticker}."


def get_live_price_return(ticker_symbol):
    """
    Fetches last 2 trading-day closing prices from Yahoo Finance and computes daily return %.
    """
    try:
        yf_ticker = yf.Ticker(f"{ticker_symbol}.NS")
        # FIX: Changed from period="2d" to period="5d"
        # Original bug: "2d" returns <2 rows on Mondays, holidays, and after market closures
        # "5d" guarantees at least 2 trading days even over long weekends
        history = yf_ticker.history(period="5d")
        if len(history) >= 2:
            prev_close = history['Close'].iloc[-2]
            current_close = history['Close'].iloc[-1]
            pct_return = ((current_close - prev_close) / prev_close) * 100
            return round(pct_return, 2)
        else:
            print(f"⚠️ Insufficient price history for {ticker_symbol} ({len(history)} rows)")
    except Exception as e:
        print(f"⚠️ YFinance block for {ticker_symbol}: {e}")
    return 0.0


def execute_sentiment_engine():
    """
    Main pipeline: fetches news + prices for each ticker,
    runs FinBERT sentiment scoring, and writes data.csv.
    """
    print("🚀 Running AI Live Extraction Engine Pipeline...")
    tickers = [
        "RELIANCE", "TCS", "INFY", "HDFCBANK",
        "TATAMOTORS", "SBIN", "ICICIBANK"
    ]
    processed_rows = []

    for ticker in tickers:
        print(f"📡 Processing tracking node: {ticker}...")
        headline = get_live_news_headline(ticker)
        realized_return = get_live_price_return(ticker)

        # Compute AI sentiment metrics
        forecast_score, forecast_dir = compute_finbert_score(headline)

        # FIX: Actual direction now uses symmetric 3-state system (-1, 0, 1)
        # Original bug: was only 2-state (1 if >= 0 else -1)
        # This made neutral forecast (0) NEVER match actual, crushing hit rate
        # Threshold: +/-0.25% to filter market noise from genuine moves
        if realized_return > 0.25:
            actual_dir = 1       # Bullish
        elif realized_return < -0.25:
            actual_dir = -1      # Bearish
        else:
            actual_dir = 0       # Neutral / flat

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
    print(f"\n✅ data.csv written successfully! ({len(df)} rows)")
    print("-" * 80)
    print(df.to_string(index=False))
    print("-" * 80)


if __name__ == "__main__":
    execute_sentiment_engine()
