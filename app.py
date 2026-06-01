import pandas as pd
import yfinance as yf
import feedparser
import re
import os

# Import the core Hugging Face Transformers pipeline for sentiment analysis
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

print("🤖 Initializing FinBERT Neural Network Pipeline...")
FINBERT_MODEL = "ProsusAI/finbert"
tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)

def compute_finbert_score(headline):
    """
    Runs text token arrays through FinBERT.
    Converts Pos/Neg/Neu probabilities into a single score bounded between -100 and +100.
    """
    if not headline or "Stable trade volatility" in headline:
        return 0.0, 0
        
    try:
        inputs = tokenizer([headline], padding=True, truncation=True, return_tensors="pt")
        outputs = model(**inputs)
        predictions = torch.nn.functional.softmax(outputs.logits, dim=-1)
        
        # FinBERT labels map: [0 -> Positive, 1 -> Negative, 2 -> Neutral]
        pos_prob = predictions[0][0].item()
        neg_prob = predictions[0][1].item()
        neu_prob = predictions[0][2].item()
        
        # Calculate a normalized compound score from -100 to +100
        compound_score = (pos_prob - neg_prob) * 100.0
        
        # Determine strict direction indicators
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
    try:
        rss_url = f"https://google.com{ticker}+stock+india&hl=en-IN&gl=IN&ceid=IN:en"
        feed = feedparser.parse(rss_url)
        if feed.entries:
            headline = feed.entries[0].title
            clean_headline = re.sub(r'\s+-\s+[^:-]+$', '', headline) # Strip publisher suffix
            # Clean comma characters to protect raw csv formatting strings
            return clean_headline.replace(",", ";")
    except Exception as e:
        print(f"⚠️ RSS failure for {ticker}: {e}")
    return f"Stable trade volatility tracked on exchange indices for {ticker}."

def get_live_price_return(ticker_symbol):
    try:
        yf_ticker = yf.Ticker(f"{ticker_symbol}.NS")
        history = yf_ticker.history(period="2d")
        if len(history) >= 2:
            prev_close = history['Close'].iloc[-2]
            current_close = history['Close'].iloc[-1]
            pct_return = ((current_close - prev_close) / prev_close) * 100
            return round(pct_return, 2)
    except Exception as e:
        print(f"⚠️ YFinance block for {ticker_symbol}: {e}")
    return 0.0

def execute_sentiment_engine():
    print("🚀 Running AI Live Extraction Engine Pipeline...")
    tickers = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "TATAMOTORS", "SBIN", "ICICIBANK"]
    processed_rows = []
    
    for ticker in tickers:
        print(f"📡 Processing tracking node: {ticker}...")
        headline = get_live_news_headline(ticker)
        realized_return = get_live_price_return(ticker)
        
        # Compute AI metrics
        forecast_score, forecast_dir = compute_finbert_score(headline)
        actual_dir = 1 if realized_return >= 0 else -1
        
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
    print("✅ data.csv dynamically written via FinBERT models!")

if __name__ == "__main__":
    execute_sentiment_engine()
