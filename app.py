import pandas as pd
import yfinance as yf
import feedparser
import requests
import re
import time
import json
import urllib.parse
import os
import numpy as np
from datetime import datetime, timezone, timedelta
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

print("Initializing FinBERT...")
FINBERT_MODEL = "ProsusAI/finbert"
tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_IST = NOW_IST.strftime("%Y-%m-%d")
TODAY_DATE = NOW_IST.date()
NEWS_START_DATE = TODAY_DATE - timedelta(days=3)
NEWS_CUTOFF_TIME = NOW_IST - timedelta(hours=2)

print(f"News window: {NEWS_START_DATE} to {NEWS_CUTOFF_TIME.strftime('%Y-%m-%d %I:%M %p')} IST")

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-IN,en;q=0.9"
}
feedparser.USER_AGENT = BROWSER_HEADERS["User-Agent"]

TICKERS_FILE = "tickers.csv"
HISTORY_FILE = "history.csv"
DATA_FILE = "data.csv"
STOCK_DATA_FILE = "stock_data.csv"

WEIGHTS_NEWS = {"technical": 0.65, "sentiment": 0.10, "macro": 0.15, "fundamental": 0.10}
WEIGHTS_NO_NEWS = {"technical": 0.75, "macro": 0.15, "fundamental": 0.10}

print(f"Weights (news):    Tech={WEIGHTS_NEWS['technical']:.0%} Sent={WEIGHTS_NEWS['sentiment']:.0%} Macro={WEIGHTS_NEWS['macro']:.0%} Fund={WEIGHTS_NEWS['fundamental']:.0%}")
print(f"Weights (no-news): Tech={WEIGHTS_NO_NEWS['technical']:.0%} Macro={WEIGHTS_NO_NEWS['macro']:.0%} Fund={WEIGHTS_NO_NEWS['fundamental']:.0%}")

SECTOR_MAP = {
    "Technology": ["Software - Application", "Software - Infrastructure", "Information Technology Services", "Communication Equipment", "Consumer Electronics"],
    "Healthcare": ["Drug Manufacturers - Specialty & Generic", "Drug Manufacturers - General", "Biotechnology", "Medical Care Facilities"],
    "Financial Services": ["Capital Markets", "Asset Management", "Financial Data & Stock Exchanges", "Insurance - Life", "Insurance - Diversified"],
    "Industrials": ["Specialty Industrial Machinery", "Aerospace & Defense", "Engineering & Construction", "Farm & Heavy Construction Machinery", "Electrical Equipment & Parts", "Conglomerates", "Integrated Freight & Logistics", "Marine Shipping", "Staffing & Employment Services"],
    "Consumer Discretionary": ["Auto Manufacturers", "Auto Parts", "Apparel Retail", "Apparel Manufacturing", "Footwear & Accessories", "Luxury Goods", "Furnishings, Fixtures & Appliances", "Lodging", "Entertainment", "Publishing"],
    "Consumer Staples": ["Packaged Foods", "Beverages - Non-Alcoholic", "Beverages - Wineries & Distilleries", "Household & Personal Products", "Agricultural Inputs"],
    "Materials": ["Steel", "Copper", "Chemicals", "Specialty Chemicals", "Building Materials", "Building Products & Equipment", "Packaging & Containers", "Textile Manufacturing"],
    "Real Estate": ["Real Estate - Development"],
    "Energy": ["Oil & Gas Integrated", "Oil & Gas Refining & Marketing"],
    "Specialty": ["Specialty Business Services", "Tools & Accessories"],
}

SOURCE_LABELS = {
    "mc_topnews": "Moneycontrol", "mc_business": "Moneycontrol", "mc_markets": "Moneycontrol", "mc_stocks": "Moneycontrol",
    "et_markets": "Economic Times", "et_stocks": "Economic Times", "et_news": "Economic Times",
    "ndtv_business": "NDTV Profit", "mint_market": "LiveMint", "mint_companies": "LiveMint",
    "nse_announce": "NSE Official", "nse_actions": "NSE Official",
    "fe_markets": "Financial Express", "fe_companies": "Financial Express",
    "bl_markets": "BusinessLine", "bl_stocks": "BusinessLine", "bl_companies": "BusinessLine",
    "yfinance": "Yahoo Finance", "google": "Google News"
}

SOURCE_SEARCH_URLS = {
    "Moneycontrol": "https://www.moneycontrol.com/news/tags/{ticker}.html",
    "Economic Times": "https://economictimes.indiatimes.com/topic/{ticker}",
    "NDTV Profit": "https://www.ndtvprofit.com/search?q={ticker}",
    "LiveMint": "https://www.livemint.com/Search/Link/Keyword/{ticker}",
    "NSE Official": "https://www.nseindia.com/get-quotes/equity?symbol={ticker}",
    "Yahoo Finance": "https://finance.yahoo.com/quote/{ticker}.NS/news/",
    "Google News": "https://news.google.com/search?q={ticker}+NSE+stock+india&hl=en-IN",
    "Financial Express": "https://www.financialexpress.com/about/{ticker}/",
    "BusinessLine": "https://www.thehindubusinessline.com/topic/{ticker}/"
}

SOURCE_WEIGHTS = {
    "mc_topnews": 1.5, "mc_business": 1.3, "mc_markets": 1.2, "mc_stocks": 1.2,
    "et_markets": 1.4, "et_stocks": 1.3, "et_news": 1.3,
    "ndtv_business": 1.2, "mint_market": 1.2, "mint_companies": 1.1,
    "nse_announce": 0.8, "nse_actions": 0.7,
    "fe_markets": 1.3, "fe_companies": 1.2,
    "bl_markets": 1.3, "bl_stocks": 1.3, "bl_companies": 1.2,
    "yfinance": 1.0, "google": 1.0
}

NSE_SOURCES = {"nse_announce", "nse_actions"}

ALL_FEEDS = {
    "mc_topnews": "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "mc_business": "https://www.moneycontrol.com/rss/business.xml",
    "mc_markets": "https://www.moneycontrol.com/rss/marketreports.xml",
    "mc_stocks": "https://www.moneycontrol.com/rss/latestnews.xml",
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "et_news": "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146843.cms",
    "ndtv_business": "https://feeds.feedburner.com/ndtvprofit-latest",
    "mint_market": "https://www.livemint.com/rss/market",
    "mint_companies": "https://www.livemint.com/rss/companies",
    "nse_announce": "https://archives.nseindia.com/content/RSS/Online_announcements.xml",
    "nse_actions": "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
    "fe_markets": "https://www.financialexpress.com/market/feed/",
    "fe_companies": "https://www.financialexpress.com/industry/companies/feed/",
    "bl_markets": "https://www.thehindubusinessline.com/markets/feeder/default.rss",
    "bl_stocks": "https://www.thehindubusinessline.com/markets/stock-markets/feeder/default.rss",
    "bl_companies": "https://www.thehindubusinessline.com/companies/feeder/default.rss"
}

NSE_NOISE_KEYWORDS = [
    "board meeting intimation", "intimation of board meeting", "outcome of board meeting",
    "disclosure under regulation", "regulation 30", "regulation 29", "regulation 31", "regulation 32",
    "compliance certificate", "corporate governance", "annual report", "annual return",
    "change of address", "change in registered office", "newspaper publication",
    "notice of agm", "notice of egm", "proceedings of agm", "proceedings of egm",
    "general meeting", "book closure", "cessation of", "appointment of company secretary",
    "secretarial compliance", "reconciliation of share capital", "statement of investor complaints",
    "certificate under regulation", "disclosure of related party", "prior intimation",
    "loss of share certificate", "duplicate share certificate", "investor grievance",
    "shareholder meeting", "postal ballot", "e-voting", "investor presentation",
    "analyst meet", "credit facility"
]

NSE_ACTIONABLE_KEYWORDS = [
    "financial results", "quarterly results", "annual results", "profit", "revenue", "turnover",
    "ebitda", "net income", "earnings", "results for the quarter", "results for the year",
    "audited results", "unaudited results", "standalone results", "consolidated results",
    "order", "contract", "awarded", "received order", "order win", "letter of intent", "loi", "work order",
    "dividend", "interim dividend", "final dividend", "special dividend",
    "buyback", "buy back", "share repurchase", "bonus", "bonus issue", "bonus shares",
    "stock split", "sub-division", "acquisition", "acquire", "merger", "amalgamation", "takeover",
    "joint venture", "partnership", "subsidiary", "disinvestment", "stake sale",
    "mou", "memorandum of understanding", "qip", "qualified institutional",
    "rights issue", "preferential allotment", "warrants", "fpo", "fundraise", "fund raise", "capital raise",
    "credit rating", "rating upgrade", "rating downgrade", "crisil", "icra", "care rating",
    "india ratings", "outlook revised", "rating assigned",
    "promoter", "insider trading", "acquisition of shares", "disposal of shares",
    "pledge", "encumbrance", "substantial acquisition",
    "expansion", "capacity", "capex", "capital expenditure", "new plant", "commissioning",
    "production commenced", "commercial production",
    "managing director", "chief executive", "ceo", "cfo", "cto", "whole time director",
    "resignation of", "appointment of managing", "appointment of chief",
    "sebi order", "penalty", "fine", "adjudication", "suspension", "debarment",
    "default", "npa", "restructuring", "insolvency", "nclt", "resolution plan",
    "fire", "accident", "force majeure", "shutdown", "export order", "import duty", "anti-dumping"
]

SHORT_TERM_KEYWORDS = [
    "quarterly", "q1", "q2", "q3", "q4", "results", "earnings", "profit", "loss", "revenue",
    "ebitda", "net income", "beat", "miss", "estimate", "buyback", "dividend", "bonus", "split",
    "record date", "ex-date", "upgrade", "downgrade", "target price", "rating", "outlook",
    "block deal", "bulk deal", "insider", "promoter", "stake", "order win", "order book", "contract", "awarded"
]

LONG_TERM_KEYWORDS = [
    "expansion", "capacity", "capex", "capital expenditure", "plant", "acquisition", "acquire",
    "merger", "amalgamation", "takeover", "partnership", "joint venture", "collaboration", "mou",
    "agreement", "regulation", "policy", "government", "sebi", "rbi", "ministry",
    "restructuring", "demerger", "spin-off", "reorganization", "ipo", "listing", "qip", "fpo",
    "rights issue", "fundraise", "technology", "ai", "digital", "automation", "innovation",
    "market entry", "new segment", "diversification", "subsidiary", "debt", "credit rating",
    "refinancing", "npa", "provisioning", "esg", "sustainability", "carbon", "green energy", "renewable"
]

COMPANY_ALIASES = {
    "EICHER MOTORS": "EICHERMOT", "EICHER": "EICHERMOT", "HERO MOTOCORP": "HEROMOTOCO",
    "HERO MOTO": "HEROMOTOCO", "MARUTI SUZUKI": "MARUTI", "ESCORTS KUBOTA": "ESCORTS",
    "BOSCH": "BOSCHLTD", "BHARAT ELECTRONICS": "BEL", "DATA PATTERNS": "DATAPATTNS",
    "GARDEN REACH": "GRSE", "HINDUSTAN AERONAUTICS": "HAL", "MAZAGON DOCK": "MAZDOCK",
    "PERSISTENT SYSTEMS": "PERSISTENT", "ZENSAR": "ZENSARTECH", "COFORGE": "COFORGE",
    "NATIONAL ALUMINIUM": "NATIONALUM", "NALCO": "NATIONALUM", "HINDUSTAN COPPER": "HINDCOPPER",
    "COAL INDIA": "COALINDIA", "HDFC AMC": "HDFCAMC", "ANGEL ONE": "ANGELONE",
    "MOTILAL OSWAL": "MOTILALOFS", "CRISIL": "CRISIL", "CARE RATINGS": "CARERATING",
    "ICRA": "ICRA", "ITC": "ITC", "JYOTHY LABS": "JYOTHYLAB", "KEI INDUSTRIES": "KEI",
    "POLYCAB": "POLYCAB", "NBCC": "NBCC", "NCC": "NCC", "CUMMINS INDIA": "CUMMINSIND",
    "ABB": "ABB", "ABB INDIA": "ABB", "POWER FINANCE": "PFC", "REC LTD": "RECLTD",
    "GLOBAL HEALTH": "MEDANTA", "BLUE STAR": "BLUESTARCO", "LINDE INDIA": "LINDEINDIA",
    "SBI LIFE": "SBILIFE", "CASTROL": "CASTROLIND", "COROMANDEL": "COROMANDEL",
    "ABBOTT INDIA": "ABBOTINDIA", "ALKEM": "ALKEM", "CIPLA": "CIPLA",
    "TORRENT PHARMA": "TORNTPHARM", "SAFARI INDUSTRIES": "SAFARI", "TRENT": "TRENT",
    "LODHA": "LODHA", "MACROTECH": "LODHA", "BAJAJ FINANCE": "BAJFINANCE",
    "AU SMALL FINANCE": "AUBANK", "CHOLAMANDALAM": "CHOLAFIN", "MUTHOOT FINANCE": "MUTHOOTFIN",
    "SHRIRAM FINANCE": "SHRIRAMFIN", "SUNDARAM FINANCE": "SUNDARMFIN", "HUDCO": "HUDCO",
    "MCX": "MCX", "GRAVITA": "GRAVITA", "APL APOLLO": "APLAPOLLO", "AFFLE": "AFFLE",
    "HYUNDAI": "HYUNDAI", "BIKAJI": "BIKAJI", "ORACLE FINANCIAL": "OFSS",
    "BAJAJ HOLDINGS": "BAJAJHLDNG", "RAILTEL": "RAILTEL", "DOMS": "DOMS",
    "DODLA DAIRY": "DODLA", "LT FOODS": "LTFOODS", "WELSPUN CORP": "WELCORP",
    "INGERSOLL RAND": "INGERRAND", "KIRLOSKAR": "KIRLOSBROS", "SHAKTI PUMPS": "SHAKTIPUMP",
    "TD POWER SYSTEMS": "TDPOWERSYS", "UNO MINDA": "UNOMINDA", "HOME FIRST": "HOMEFIRST",
    "CAN FIN HOMES": "CANFINHOME", "NUVAMA": "NUVAMA", "GROWW": "GROWW", "TEGA": "TEGA",
    "ENDURANCE": "ENDURANCE", "SANSERA": "SANSERA", "TIPS MUSIC": "TIPSMUSIC",
    "GOLDIAM": "GOLDIAM", "NEWGEN": "NEWGEN", "RATEGAIN": "RATEGAIN", "ECLERX": "ECLERX",
    "VOLTAMP": "VOLTAMP", "ELECON": "ELECON", "PRUDENT": "PRUDENT", "MARKSANS": "MARKSANS",
    "SUPRIYA": "SUPRIYA", "MARATHON": "MARATHON"
}

REPORTING_VERBS = {
    "surged", "surges", "surge", "jumped", "jumps", "jump", "rallied", "rallies", "rally",
    "soared", "soars", "soar", "rose", "rises", "crashed", "crashes", "crash",
    "fell", "falls", "fall", "dropped", "drops", "drop", "tumbled", "tumbles", "tumble",
    "plunged", "plunges", "plunge", "sank", "sinks", "sink", "declined", "declines", "decline",
    "slipped", "slips", "slip", "gained", "gains", "gain", "lost", "loses", "lose",
    "climbed", "climbs", "climb", "advanced", "advances", "advance", "retreated", "retreats",
    "tanked", "tanks", "zoomed", "zooms", "skyrocketed", "nosedived"
}

PRICE_CONTEXT = {
    "share", "shares", "stock", "stocks", "scrip", "counter", "sensex", "nifty", "market",
    "index", "indices", "bse", "nse", "trading", "trade", "session", "intraday", "today",
    "morning", "afternoon", "week", "high", "low", "close", "closed", "closing", "open", "opened"
}

CATALYST_VERBS = {
    "wins", "win", "won", "awarded", "receives", "received", "secures", "secured",
    "acquires", "acquired", "acquire", "merges", "merged", "merge", "approves", "approved", "approve",
    "clears", "cleared", "clear", "launches", "launched", "launch", "plans", "planned", "plan",
    "expands", "expanded", "expand", "invests", "invested", "invest", "raises", "raised", "raise",
    "signs", "signed", "sign", "partners", "partnered", "partner", "enters", "entered", "enter",
    "files", "filed", "file", "announces", "announced", "announce", "declares", "declared", "declare",
    "recommends", "recommended", "upgrades", "upgraded", "upgrade", "downgrades", "downgraded", "downgrade",
    "appoints", "appointed", "appoint", "resigns", "resigned", "resign",
    "penalizes", "penalized", "fines", "fined", "suspends", "suspended", "bans", "banned",
    "restructures", "restructured", "defaults", "defaulted", "commissions", "commissioned",
    "inaugurates", "inaugurated", "divests", "divested", "demerges", "demerged"
}

SECTOR_IMPACT_WORDS = {
    "industry", "sector", "segment", "policy", "regulation", "government", "ministry", "budget",
    "gst", "tariff", "duty", "subsidy", "pli", "rbi", "sebi", "ban", "mandate", "compliance",
    "guideline", "monsoon", "crude", "oil", "commodity", "inflation", "rate cut", "rate hike",
    "forex", "rupee", "dollar", "export", "import", "demand", "supply"
}

MATERIAL_CATALYST_KEYWORDS = [
    "quarterly results", "annual results", "q1 results", "q2 results", "q3 results", "q4 results",
    "net profit", "net loss", "revenue growth", "revenue decline", "ebitda",
    "beat estimates", "missed estimates", "above estimates", "below estimates",
    "profit after tax", "pat", "topline", "bottomline",
    "dividend", "interim dividend", "final dividend", "special dividend",
    "buyback", "buy back", "share repurchase", "bonus issue", "bonus shares", "stock split", "sub-division",
    "rights issue", "preferential allotment", "qip", "fpo", "ipo",
    "order win", "order worth", "received order", "bags order", "wins order",
    "contract awarded", "contract worth", "secured contract", "deal worth", "deal value", "letter of intent", "work order",
    "acquisition", "acquires", "acquired", "acquire", "merger", "amalgamation", "takeover", "takeover bid",
    "joint venture", "stake sale", "stake acquisition", "disinvestment", "divestiture", "demerger",
    "sebi order", "sebi penalty", "sebi ban", "penalty imposed", "fine imposed",
    "suspension", "debarment", "show cause", "default", "npa", "insolvency", "nclt",
    "new ceo", "new cfo", "new md", "appoints ceo", "appoints md",
    "ceo resigns", "md resigns", "cfo resigns", "managing director", "chief executive officer",
    "rating upgrade", "rating downgrade", "target price raised", "target price cut", "target price reduced",
    "initiates coverage", "maintains buy", "maintains sell",
    "new plant", "plant commissioning", "capacity expansion", "commercial production", "production commenced",
    "capex plan", "capex of", "investment of",
    "crore order", "crore deal", "crore contract", "million order", "million deal", "billion",
    "usfda approval", "fda approval", "anda approval", "drug approval", "product launch", "patent",
]

NOISE_HEADLINE_PATTERNS = [
    "markets likely", "market likely", "expected to open", "global cues", "global markets",
    "asian markets", "european markets", "wall street", "dow jones", "nasdaq", "s&p 500",
    "fii sold", "fii bought", "fii selling", "fii buying", "dii sold", "dii bought",
    "dii selling", "dii buying", "foreign institutional", "domestic institutional",
    "analyst expects", "analysts expect", "may outperform", "could benefit",
    "likely to", "expected to outperform", "poised to",
    "looks attractive", "appears overvalued", "sentiment positive", "sentiment negative",
    "support level", "resistance level", "breakout", "breakdown",
    "technical analysis", "chart pattern", "moving average",
    "nifty may", "sensex may", "nifty likely", "sensex likely",
    "sector outlook", "sector rotation", "sector performance",
    "growth prospects", "long-term story", "structural growth",
    "headwinds", "tailwinds", "challenges ahead", "opportunities ahead",
]

BAD_STRINGS = ('nan', 'none', 'n/a', 'null', '')

def is_bad_str(s):
    if not s: return True
    return str(s).strip().lower() in BAD_STRINGS

def safe_int(val, default=0):
    try:
        if val is None: return default
        if isinstance(val, float) and pd.isna(val): return default
        return int(float(val))
    except (ValueError, TypeError): return default

def safe_float(val, default=None):
    try:
        if val is None: return default
        if isinstance(val, float) and pd.isna(val): return default
        return float(val)
    except (ValueError, TypeError): return default

def is_material_catalyst(headline):
    if not headline: return False
    text = headline.lower()
    for noise in NOISE_HEADLINE_PATTERNS:
        if noise in text: return False
    for catalyst in MATERIAL_CATALYST_KEYWORDS:
        if catalyst in text: return True
    if bool(re.search(r'(?:rs\.?|inr|₹)\s*[\d,]+\s*(?:crore|cr|million|mn|billion|bn|lakh)', text)): return True
    words = set(re.findall(r'[a-z]+', text))
    if bool(words & CATALYST_VERBS) and bool(re.search(r'\d+', text)): return True
    return False


# ═══════════════════════════════════════════════════════════════
# HEADLINE CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

def classify_headline(headline, actual_return=None):
    text = headline.lower(); words = set(re.findall(r'[a-z]+', text))
    pct_matches = re.findall(r'(\d+\.?\d*)\s*%', text)
    if pct_matches and actual_return is not None:
        for ps in pct_matches:
            try:
                if abs(float(ps) - abs(actual_return)) < 3.0: return "reporting", "% match"
            except: pass
    has_rv = bool(words & REPORTING_VERBS); has_pc = bool(words & PRICE_CONTEXT)
    has_pct = bool(re.search(r'\d+\.?\d*\s*%', text))
    if has_rv and has_pc and has_pct: return "reporting", "verb+context+%"
    if has_rv and has_pc: return "reporting", "verb+context"
    if bool(words & CATALYST_VERBS): return "predictive", "catalyst"
    if bool(words & SECTOR_IMPACT_WORDS): return "predictive", "sector"
    if has_rv and has_pct: return "reporting", "verb+%"
    for kw in NSE_ACTIONABLE_KEYWORDS:
        if kw in text: return "predictive", "actionable"
    return "predictive", "default"

def classify_nse_headline(hl):
    t = hl.lower()
    for kw in NSE_ACTIONABLE_KEYWORDS:
        if kw in t: return "actionable"
    for kw in NSE_NOISE_KEYWORDS:
        if kw in t: return "noise"
    return "noise"

def classify_severity(s):
    if s >= 60: return "Very Bullish"
    elif s >= 25: return "Bullish"
    elif s >= 5: return "Mildly Bullish"
    elif s >= -5: return "Neutral"
    elif s >= -25: return "Mildly Bearish"
    elif s >= -60: return "Bearish"
    else: return "Very Bearish"

def classify_impact(entries):
    c = " ".join(e["headline"] for e in entries).lower()
    s = sum(1 for kw in SHORT_TERM_KEYWORDS if kw in c)
    l = sum(1 for kw in LONG_TERM_KEYWORDS if kw in c)
    if s > 0 and l > 0: return "Both"
    elif l > 0: return "Long-term"
    elif s > 0: return "Short-term"
    return "Short-term"

def classify_composite_severity(s):
    if s >= 40: return "Strong Buy"
    elif s >= 20: return "Buy"
    elif s >= 8: return "Mild Buy"
    elif s >= -8: return "Neutral"
    elif s >= -20: return "Mild Sell"
    elif s >= -40: return "Sell"
    else: return "Strong Sell"


# ═══════════════════════════════════════════════════════════════
# NEWS UTILITY
# ═══════════════════════════════════════════════════════════════

def extract_pub_datetime_full(entry):
    p = entry.get("published_parsed") or entry.get("updated_parsed")
    if p:
        try:
            d = datetime(*p[:6], tzinfo=timezone.utc).astimezone(IST)
            return d, d.strftime("%d %b %Y %I:%M %p")
        except: pass
    return None, ""

def extract_news_url(e): return e.get("link", e.get("id", ""))

def is_in_news_window(d):
    if d is None: return True
    return datetime.combine(NEWS_START_DATE, datetime.min.time()).replace(tzinfo=IST) <= d <= NEWS_CUTOFF_TIME

def get_source_search_url(sl, tk):
    t = SOURCE_SEARCH_URLS.get(sl, "")
    return t.replace("{ticker}", tk) if t else ""

def fetch_rss_with_headers(url, label, timeout=15):
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout); r.raise_for_status()
        return feedparser.parse(r.content)
    except requests.exceptions.RequestException as e:
        print(f"   {label}: {e}")
        try: return feedparser.parse(url)
        except: return None

def match_ticker_in_text(tu, tl):
    for t in sorted(tl, key=len, reverse=True):
        if re.search(r'\b' + re.escape(t.upper()) + r'\b', tu): return t
    for a, t in COMPANY_ALIASES.items():
        if a in tu and t in tl: return t
    return None


# ═══════════════════════════════════════════════════════════════
# TICKER LOADING
# ═══════════════════════════════════════════════════════════════

def load_tickers():
    if os.path.exists(TICKERS_FILE):
        try:
            df = pd.read_csv(TICKERS_FILE); df.columns = df.columns.str.strip()
            if 'Ticker' not in df.columns:
                first_col = df.columns[0]
                df.rename(columns={first_col: 'Ticker'}, inplace=True)
            tks = [t.replace('.NS', '') for t in df['Ticker'].dropna().str.strip().str.upper().tolist() if t]
            s = set(); u = []
            for t in tks:
                if t not in s: s.add(t); u.append(t)
            sm = {}
            if 'Sector' in df.columns:
                for _, r in df.iterrows():
                    tk = str(r['Ticker']).strip().upper().replace('.NS', '')
                    sc = str(r.get('Sector', '')).strip()
                    if tk and sc and not is_bad_str(sc): sm[tk] = sc
            print(f"Loaded {len(u)} tickers from {TICKERS_FILE} (sector map: {len(sm)} entries)")
            return u, sm
        except Exception as e: print(f"Error: {e}")
    return ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ICICIBANK", "ITC"], {}


# ═══════════════════════════════════════════════════════════════
# FINBERT (Catalyst-Only)
# ═══════════════════════════════════════════════════════════════

def score_single_headline(hl):
    if not hl: return 0.0
    try:
        i = tokenizer([hl], padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad(): o = model(**i)
        p = torch.nn.functional.softmax(o.logits, dim=-1)
        return (p[0][0].item() - p[0][1].item()) * 100.0
    except: return 0.0

def compute_aggregated_score(entries):
    if not entries: return 0.0, 0, 0, 0
    catalyst_entries = [e for e in entries if is_material_catalyst(e["headline"])]
    noise_count = len(entries) - len(catalyst_entries); catalyst_count = len(catalyst_entries)
    if not catalyst_entries: return 0.0, 0, catalyst_count, noise_count
    tw = 0.0; ws = 0.0
    for e in catalyst_entries:
        r = score_single_headline(e["headline"]); w = e.get("weight", 1.0); ws += r * w; tw += w
    if tw == 0: return 0.0, 0, catalyst_count, noise_count
    s = ws / tw; direction = 1 if s > 5 else (-1 if s < -5 else 0)
    return round(s, 1), direction, catalyst_count, noise_count

def get_live_price_return(tk):
    clean = tk.replace('.NS', '').replace('.BO', '').strip()
    symbols = [f"{clean}.BO", f"{clean}.NS"] if clean.isdigit() else [f"{clean}.NS", f"{clean}.BO"]
    for symbol in symbols:
        try:
            h = yf.Ticker(symbol).history(period="5d")
            if len(h) >= 2: return round(((h['Close'].iloc[-1] - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100, 2)
        except: continue
    return 0.0


# ═══════════════════════════════════════════════════════════════
# NEWS CACHE
# ═══════════════════════════════════════════════════════════════

def build_news_cache(tl):
    cache = {}; st = {"sc": 0, "rp": 0, "nn": 0, "kp": 0}
    for sk, url in ALL_FEEDS.items():
        print(f"Fetching {sk}...")
        feed = fetch_rss_with_headers(url, sk)
        if not feed or not feed.entries: print(f"   {sk}: No entries"); continue
        mc = 0; rp = 0; stc = 0; nc = 0
        for entry in feed.entries:
            title = entry.get("title", ""); desc = entry.get("description", entry.get("summary", ""))
            ft = f"{title} {desc}".upper(); mt = match_ticker_in_text(ft, tl)
            if not mt or not title.strip(): continue
            st["sc"] += 1; di, pt = extract_pub_datetime_full(entry)
            if not is_in_news_window(di): stc += 1; continue
            hl = title.strip().replace(",", ";"); nu = extract_news_url(entry)
            hc, _ = classify_headline(hl)
            if hc == "reporting": rp += 1; st["rp"] += 1; continue
            if sk in NSE_SOURCES:
                if classify_nse_headline(hl) == "noise":
                    nc += 1; st["nn"] += 1; fk = f"_filing_{mt}"
                    if fk not in cache: cache[fk] = []
                    cache[fk].append({"headline": hl, "source": sk, "pub_time": pt, "weight": 0.0, "nse_class": "noise", "news_url": nu}); continue
            w = SOURCE_WEIGHTS.get(sk, 1.0); ex = cache.get(mt, [])
            if not any(e["headline"].lower() == hl.lower() for e in ex):
                if mt not in cache: cache[mt] = []
                cache[mt].append({"headline": hl, "source": sk, "pub_time": pt, "weight": w, "nse_class": "actionable" if sk in NSE_SOURCES else "news", "news_url": nu}); mc += 1; st["kp"] += 1
        notes = []
        if stc: notes.append(f"{stc} outside window")
        if rp: notes.append(f"{rp} reporting")
        if nc: notes.append(f"{nc} NSE noise")
        print(f"   {sk}: {mc} predictive from {len(feed.entries)}" + (f" ({', '.join(notes)})" if notes else ""))
        time.sleep(0.3)
    rl = {k for k in cache if not k.startswith("_filing_")}
    print(f"\nCache: {len(rl)}/{len(tl)} predictive | Scanned:{st['sc']} Reporting:{st['rp']} NSEnoise:{st['nn']} Kept:{st['kp']}")
    return cache

def get_yfinance_news(tk, ar=None):
    try:
        news = getattr(yf.Ticker(f"{tk}.NS"), 'news', None)
        if news and isinstance(news, list):
            for item in news:
                if not isinstance(item, dict): continue
                hl = item.get("title", item.get("headline", ""))
                if not hl: continue
                hc, _ = classify_headline(hl, ar)
                if hc == "reporting": continue
                nu = item.get("link", item.get("url", ""))
                pts = item.get("providerPublishTime") or item.get("publish_time")
                pt = ""; di = None
                if pts:
                    try: di = datetime.fromtimestamp(int(pts), tz=IST); pt = di.strftime("%d %b %Y %I:%M %p")
                    except: pass
                if is_in_news_window(di): return hl.replace(",", ";"), pt, nu
    except: pass
    return None, "", ""

def get_google_news(tk, ar=None):
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(tk)}+NSE+stock+india&hl=en-IN&gl=IN&ceid=IN:en"
        feed = fetch_rss_with_headers(url, f"gg_{tk}", timeout=8)
        if feed and feed.entries:
            for entry in feed.entries[:5]:
                di, pt = extract_pub_datetime_full(entry)
                if not is_in_news_window(di): continue
                hl = re.sub(r'\s+-\s+[^:\-]+$', '', entry.title)
                hc, _ = classify_headline(hl, ar)
                if hc == "reporting": continue
                return hl.replace(",", ";"), pt, extract_news_url(entry)
    except: pass
    return None, "", ""

def get_all_fresh_news(tk, cache, ar=None):
    entries = list(cache.get(tk, []))
    hl, pt, nu = get_yfinance_news(tk, ar)
    if hl and not any(e["headline"].lower() == hl.lower() for e in entries):
        entries.append({"headline": hl, "source": "yfinance", "pub_time": pt, "weight": 1.0, "nse_class": "news", "news_url": nu})
    if len(entries) < 3:
        hl, pt, nu = get_google_news(tk, ar)
        if hl and not any(e["headline"].lower() == hl.lower() for e in entries):
            entries.append({"headline": hl, "source": "google", "pub_time": pt, "weight": 1.0, "nse_class": "news", "news_url": nu})
    if ar is not None and entries:
        entries = [e for e in entries if classify_headline(e["headline"], ar)[0] != "reporting"]
    fe = cache.get(f"_filing_{tk}", [])
    if entries: return entries, "actionable", fe
    elif fe: return fe, "filing_only", fe
    else: return [], "no_news", []


# ═══════════════════════════════════════════════════════════════
# HISTORY + STREAKS
# ═══════════════════════════════════════════════════════════════

def load_history():
    try:
        df = pd.read_csv(HISTORY_FILE)
        if 'Date' in df.columns:
            dates = sorted(df['Date'].unique(), reverse=True)[:30]; df = df[df['Date'].isin(dates)]
        return df
    except FileNotFoundError: return pd.DataFrame()

def calculate_streaks(hdf, tr):
    streaks = {}
    for row in tr:
        tk = row["Ticker"]; td = row["Forecast_Direction"]; ts = row["Forecast_Score"]; trr = row["Actual_Return_Pct"]
        th = pd.DataFrame()
        if not hdf.empty and 'Ticker' in hdf.columns:
            th = hdf[(hdf['Ticker'] == tk) & (hdf['Date'] != TODAY_IST)].sort_values('Date', ascending=False)
        sd = 1; sr = trr
        if not th.empty:
            for _, hr in th.iterrows():
                if safe_int(hr.get('Forecast_Direction', 0)) == td and td != 0: sd += 1; sr += float(hr.get('Actual_Return_Pct', 0))
                else: break
        ps = float(th.iloc[0].get('Forecast_Score', 0)) if not th.empty else None
        if td == 0: m = "Neutral"
        elif sd == 1: m = "New"
        elif ps is not None:
            if td == 1: m = ("Strong" if sd >= 3 else "Building") if ts >= ps else "Fading"
            elif td == -1: m = ("Strong" if sd >= 3 else "Building") if ts <= ps else "Fading"
            else: m = "Neutral"
        else: m = "New"
        streaks[tk] = {"Streak_Days": sd if td != 0 else 0, "Streak_Return": round(sr, 2), "Momentum": m}
    return streaks

def save_to_history(rows):
    hdf = load_history(); tdf = pd.DataFrame(rows); tdf['Date'] = TODAY_IST
    if not hdf.empty and 'Date' in hdf.columns: hdf = hdf[hdf['Date'] != TODAY_IST]
    c = pd.concat([hdf, tdf], ignore_index=True)
    if 'Date' in c.columns:
        dates = sorted(c['Date'].unique(), reverse=True)[:30]; c = c[c['Date'].isin(dates)]
    c.to_csv(HISTORY_FILE, index=False)
    print(f"History: {len(c)} rows / {c['Date'].nunique() if 'Date' in c.columns else 1} days")


# ═══════════════════════════════════════════════════════════════
# STOCK DATA
# ═══════════════════════════════════════════════════════════════

def load_stock_data_for_scoring():
    try:
        if os.path.exists(STOCK_DATA_FILE):
            df = pd.read_csv(STOCK_DATA_FILE)
            if 'Ticker' in df.columns:
                df['Ticker'] = df['Ticker'].astype(str).str.replace('.NS', '', regex=False).str.strip().str.upper()
                if 'Date' in df.columns: df = df.sort_values(['Ticker', 'Date'])
                print(f"  -> Loaded stock_data.csv: {df['Ticker'].nunique()} tickers, {len(df)} rows")
                key_cols = ['RSI_14', 'BB_Flag', 'SMA_9', 'SMA_22', 'SMA_50', 'SMA_52', 'SMA_200', 'Knoxville_Divergence', 'up_true', 'Close', 'High', 'Low', 'Market_Cap', 'Industry', 'MACD_Line', 'MACD_Signal', 'ADX_14', 'ST_Direction', 'EMA_9', 'EMA_21', 'OBV']
                found = [c for c in key_cols if c in df.columns]
                print(f"  -> Found: {len(found)}/{len(key_cols)} key columns")
                return df
    except Exception as e: print(f"  -> Error: {e}")
    print("  -> stock_data.csv not found"); return pd.DataFrame()

def get_sector_from_stock_data(ticker, stock_df):
    if stock_df is None or stock_df.empty: return ""
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty: return ""
    for cn in ['Industry', 'Sector']:
        if cn not in tk_data.columns: continue
        vals = tk_data[cn].dropna().astype(str).str.strip()
        vals = vals[vals.apply(lambda x: not is_bad_str(x))]
        if len(vals) > 0: return vals.iloc[-1]
    return ""

def detect_mcap_scale(stock_df):
    if stock_df is None or stock_df.empty or 'Market_Cap' not in stock_df.columns: return 10000
    mcap_max = stock_df['Market_Cap'].dropna().max()
    if pd.isna(mcap_max): return 10000
    if mcap_max > 1e9: return 1e11
    return 10000

def get_latest_valid_rows(stock_df):
    """Get latest row per ticker where Close AND SMA_22 are both valid"""
    if stock_df is None or stock_df.empty: return pd.DataFrame()
    sdf = stock_df.sort_values(['Ticker', 'Date']) if 'Date' in stock_df.columns else stock_df
    results = []
    for ticker in sdf['Ticker'].unique():
        tk = sdf[sdf['Ticker'] == ticker]
        valid = tk[tk['Close'].notna()]
        if 'SMA_22' in tk.columns:
            v2 = valid[valid['SMA_22'].notna()]
            if not v2.empty: results.append(v2.iloc[-1]); continue
        if not valid.empty: results.append(valid.iloc[-1])
    if results: return pd.DataFrame(results).reset_index(drop=True)
    return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════
# v5.0.1: STRATEGY-BASED TECHNICAL SCORING (ADX-aware)
# ═══════════════════════════════════════════════════════════════

def compute_tech_score_v5(valid_df, mcap_threshold):
    if len(valid_df) < 2: return 0, []
    score = 0; signals = []
    last = valid_df.iloc[-1]

    def fv(names):
        if isinstance(names, str): names = [names]
        for n in names:
            v = last.get(n)
            if v is not None:
                try:
                    if pd.notna(v): return float(v)
                except: pass
        return None

    def sv(names):
        if isinstance(names, str): names = [names]
        for n in names:
            v = last.get(n)
            if v is not None:
                try:
                    if pd.notna(v) and str(v).strip(): return str(v)
                except: pass
        return None

    close = fv(['Close'])
    if close is None: return 0, []
    sma9 = fv(['SMA_9']); sma22 = fv(['SMA_22']); sma52 = fv(['SMA_52', 'SMA_50']); sma200 = fv(['SMA_200'])
    rsi = fv(['RSI_14', 'RSI']); adx = fv(['ADX_14']); st_dir = fv(['ST_Direction'])
    macd_line = fv(['MACD_Line']); macd_signal = fv(['MACD_Signal']); macd_hist = fv(['MACD_Hist'])
    ema9 = fv(['EMA_9']); ema21 = fv(['EMA_21']); mcap = fv(['Market_Cap'])
    is_large = mcap is not None and mcap > mcap_threshold
    tag = "LC" if is_large else "SMC"
    is_trending = adx is not None and adx > 25

    # ── SUPPORT / RESISTANCE (20-day) ──
    support = None; resistance = None
    if 'Low' in valid_df.columns and 'High' in valid_df.columns:
        recent = valid_df.tail(20)
        lows = recent['Low'].dropna(); highs = recent['High'].dropna()
        if len(lows) > 0: support = lows.min()
        if len(highs) > 0: resistance = highs.max()
    near_support = support is not None and close <= support * 1.02
    near_resistance = resistance is not None and close >= resistance * 0.98
    at_breakout = resistance is not None and close > resistance
    at_breakdown = support is not None and close < support

    # ═══ TIER 1: SMA HIERARCHY ═══
    has_all = all(v is not None for v in [sma9, sma22, sma52, sma200])
    has_short = all(v is not None for v in [sma9, sma22])

    if is_large and has_all:
        # LARGE CAP
        if close < sma9 < sma22 < sma52 < sma200:
            if is_trending:
                score += 25; signals.append(f"{tag} FULL oversold (trending down, cautious)")
            else:
                score += 40; signals.append(f"{tag} FULL oversold (mean reversion BUY)")
        elif close < sma9 < sma22 < sma52:
            score += 20; signals.append(f"{tag} 4-level oversold")
        elif close < sma9 < sma22:
            score += 12; signals.append(f"{tag} short-term oversold")
        elif close > sma9 > sma22 > sma52 > sma200:
            if is_trending:
                score += 15; signals.append(f"{tag} FULL uptrend (ADX={adx:.0f})")
            else:
                score -= 25; signals.append(f"{tag} overextended (weak ADX)")
        elif close > sma9 > sma22 > sma52:
            if is_trending: score += 10; signals.append(f"{tag} 4-level uptrend")
            else: score -= 15; signals.append(f"{tag} 4-level stretched")
        elif close > sma9 > sma22:
            score += 8; signals.append(f"{tag} short uptrend")
        else:
            if close < sma22: score -= 8; signals.append("Below SMA22")
            else: score += 5
            if close < sma200: score -= 15; signals.append("Below SMA200")
            elif close > sma200: score += 8

    elif not is_large and has_short:
        # SMALL/MID CAP
        if close > sma9 > sma22:
            score += 15; signals.append(f"{tag} uptrend")
            if sma52 is not None and sma22 > sma52: score += 10; signals.append("Medium trend confirmed")
        elif close < sma9 < sma22:
            score -= 15; signals.append(f"{tag} downtrend")
            if sma52 is not None and sma22 < sma52: score -= 10; signals.append("Medium trend confirms down")
        elif close > sma22 and sma9 is not None and sma9 <= sma22:
            score += 20; signals.append(f"{tag} breakout above SMA22")
        elif close < sma22 and sma9 is not None and sma9 >= sma22:
            score -= 20; signals.append(f"{tag} breakdown below SMA22")
        else:
            if close < sma22: score -= 8
            else: score += 5

        if at_breakout: score += 20; signals.append(f"Breakout R={resistance:.0f}")
        elif at_breakdown: score -= 20; signals.append(f"Breakdown S={support:.0f}")
        elif near_support: score += 12; signals.append(f"Near support S={support:.0f}")
        elif near_resistance: score -= 8; signals.append(f"Near resistance R={resistance:.0f}")
    else:
        if sma22 is not None:
            if close < sma22: score -= 10
            else: score += 5
        if sma200 is not None:
            if close < sma200: score -= 12
            else: score += 5

    # ═══ TIER 2: CONFIRMATION ═══
    bb = sv(['BB_Flag'])
    if bb is not None:
        bbs = bb.strip().upper()
        if bbs == 'BBL':
            if near_support and rsi is not None and rsi < 35:
                score += 35; signals.append(f"BBL+support+RSI({rsi:.0f}) STRONG")
            elif rsi is not None and rsi < 35:
                score += 30; signals.append(f"BBL+RSI({rsi:.0f}) reversal")
            elif near_support:
                score += 25; signals.append("BBL at support")
            else:
                score += 20; signals.append("BBL bullish reversal")
        elif bbs == 'BBH':
            if near_resistance and rsi is not None and rsi > 65:
                score -= 35; signals.append(f"BBH+resistance+RSI({rsi:.0f}) STRONG")
            elif rsi is not None and rsi > 65:
                score -= 30; signals.append(f"BBH+RSI({rsi:.0f}) reversal")
            elif near_resistance:
                score -= 25; signals.append("BBH at resistance")
            else:
                score -= 20; signals.append("BBH bearish reversal")

    knox = sv(['Knoxville_Divergence'])
    if knox is not None:
        ks = knox.lower()
        if 'bullish' in ks:
            if near_support: score += 35; signals.append("Knox bullish at support STRONG")
            elif rsi is not None and rsi < 40: score += 25; signals.append(f"Knox bullish+RSI({rsi:.0f})")
            else: score += 15; signals.append("Knox bullish divergence")
        elif 'bearish' in ks:
            if near_resistance: score -= 35; signals.append("Knox bearish at resistance STRONG")
            elif rsi is not None and rsi > 60: score -= 25; signals.append(f"Knox bearish+RSI({rsi:.0f})")
            else: score -= 15; signals.append("Knox bearish divergence")

    # UP20 Reconsolidation
    if 'up_true' in valid_df.columns and len(valid_df) >= 7:
        recent_7 = valid_df.tail(7)
        try: up_mask = recent_7['up_true'].apply(lambda x: safe_int(x) == 1); up_rows = recent_7[up_mask]
        except: up_rows = pd.DataFrame()
        latest_up = safe_int(last.get('up_true', 0)) == 1
        if len(up_rows) > 0 and not latest_up and 'Low' in up_rows.columns:
            up_low = up_rows['Low'].dropna().min()
            if up_low is not None and pd.notna(up_low):
                if close <= up_low * 1.02: score += 30; signals.append(f"UP20 reconsolidation at {up_low:.0f}")
                elif close <= up_low * 1.05: score += 15; signals.append("UP20 pullback near accumulation")

    # ═══ TIER 3: SUPPORTING ═══
    if macd_line is not None and macd_signal is not None:
        if macd_line > macd_signal: score += 12; signals.append("MACD bullish")
        else: score -= 12; signals.append("MACD bearish")
    if macd_hist is not None: score += 3 if macd_hist > 0 else -3

    if ema9 is not None and ema21 is not None:
        if ema9 > ema21: score += 10; signals.append("EMA golden")
        else: score -= 10; signals.append("EMA death")

    if st_dir is not None:
        try:
            st = int(float(st_dir))
            if st == 1: score += 8; signals.append("ST up")
            elif st == -1: score -= 8; signals.append("ST down")
        except: pass

    if len(valid_df) >= 6:
        try:
            pc = valid_df.iloc[-6].get('Close')
            if pc and close and pd.notna(pc) and pc > 0:
                mom = ((close - pc) / pc) * 100
                if mom > 5: score += 15; signals.append(f"Mom5d +{mom:.1f}%")
                elif mom > 2: score += 8; signals.append(f"Mom5d +{mom:.1f}%")
                elif mom < -5: score -= 15; signals.append(f"Mom5d {mom:.1f}%")
                elif mom < -2: score -= 8; signals.append(f"Mom5d {mom:.1f}%")
        except: pass

    rsi_used = any('RSI' in s for s in signals)
    if rsi is not None and not rsi_used:
        if rsi > 80: score -= 12; signals.append(f"RSI extreme OB({rsi:.0f})")
        elif rsi > 70: score -= 6; signals.append(f"RSI OB({rsi:.0f})")
        elif rsi < 20: score += 12; signals.append(f"RSI extreme OS({rsi:.0f})")
        elif rsi < 30: score += 6; signals.append(f"RSI OS({rsi:.0f})")

    # ═══ TIER 4: ADX MODIFIER ═══
    if adx is not None and adx > 25 and st_dir is not None:
        try:
            st = int(float(st_dir))
            if st == 1 and score < 0:
                adj = min(15, int(abs(score) * 0.25)); score += adj; signals.append(f"ADX({adx:.0f}) trend +{adj}")
            elif st == -1 and score > 0:
                adj = min(15, int(abs(score) * 0.25)); score -= adj; signals.append(f"ADX({adx:.0f}) trend -{adj}")
        except: pass

    return max(-100, min(100, score)), signals


def get_technical_score(ticker, stock_df, mcap_threshold, debug=False):
    if stock_df is None or stock_df.empty: return {"score": 0, "signals": []}
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty: return {"score": 0, "signals": []}
    valid = tk_data[tk_data['Close'].notna()]
    if 'Date' in valid.columns: valid = valid.sort_values('Date')
    if valid.empty: return {"score": 0, "signals": []}
    score, signals = compute_tech_score_v5(valid, mcap_threshold)
    if debug:
        last = valid.iloc[-1]; mc = safe_float(last.get('Market_Cap', 0), 0)
        ct = "LC" if mc > mcap_threshold else "SMC"
        print(f"    DEBUG {ticker}({ct}): RSI={last.get('RSI_14')}, Close={last.get('Close')}, SMA9={last.get('SMA_9')}, SMA22={last.get('SMA_22')}, SMA52={last.get('SMA_52')}, SMA200={last.get('SMA_200')}, BB={last.get('BB_Flag')}, Knox={last.get('Knoxville_Divergence')}, ADX={last.get('ADX_14')}, MCap={mc:.0f}")
    return {"score": score, "signals": signals}


def score_fundamentals_rules(ticker, stock_df):
    if stock_df is None or stock_df.empty: return {"score": 0, "concern": ""}
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty: return {"score": 0, "concern": ""}
    valid = tk_data[tk_data['Close'].notna()]
    if 'Date' in valid.columns: valid = valid.sort_values('Date')
    if valid.empty: return {"score": 0, "concern": ""}
    last = valid.iloc[-1]; score = 0; concerns = []
    de = safe_float(last.get('Debt_Eq'))
    if de is not None:
        if de > 200: score -= 20; concerns.append("Very high debt")
        elif de > 100: score -= 10; concerns.append("High debt")
        elif de < 30: score += 5
    up = safe_int(last.get('up_true', 0))
    if up == 1: score += 30; concerns.append("FII/DII accumulation")
    obv = safe_float(last.get('OBV'))
    if obv is not None and len(valid) >= 6 and 'OBV' in valid.columns:
        obv_prev = safe_float(valid.iloc[-6].get('OBV'))
        if obv_prev is not None and obv_prev != 0:
            oc = ((obv - obv_prev) / abs(obv_prev)) * 100
            if oc > 10: score += 15; concerns.append(f"OBV accum +{oc:.0f}%")
            elif oc < -10: score -= 15; concerns.append(f"OBV dist {oc:.0f}%")
    return {"score": max(-100, min(100, score)), "concern": "; ".join(concerns) if concerns else ""}

def get_nifty_change():
    try:
        h = yf.Ticker("^NSEI").history(period="5d")
        if len(h) >= 2: return round(((h['Close'].iloc[-1] - h['Close'].iloc[0]) / h['Close'].iloc[0]) * 100, 2)
    except: pass
    return 0.0

def get_broad_sector(sub):
    if not sub: return ""
    for broad, subs in SECTOR_MAP.items():
        if sub in subs: return broad
    return sub


# ═══════════════════════════════════════════════════════════════
# MARKET REGIME + SECTOR STRENGTH (Fixed v5.0.1)
# ═══════════════════════════════════════════════════════════════

def compute_market_regime(stock_df, nifty_change):
    regime_data = {"regime": "CHOPPY", "score": 0, "breadth": 0.5, "nifty": nifty_change, "avg_rsi": 50.0, "lt_breadth": 0.5, "detail": ""}
    if stock_df is None or stock_df.empty: return regime_data
    valid = get_latest_valid_rows(stock_df)
    if valid.empty: return regime_data

    breadth = 0.5
    if 'SMA_22' in valid.columns:
        sv2 = valid[valid['SMA_22'].notna() & valid['Close'].notna()]
        if len(sv2) > 0:
            above = (sv2['Close'] > sv2['SMA_22']).sum(); breadth = above / len(sv2)
            print(f"  -> SMA22 breadth: {above}/{len(sv2)} = {breadth:.0%}")

    avg_rsi = 50.0
    if 'RSI_14' in valid.columns:
        rv = valid['RSI_14'].dropna()
        if len(rv) > 0: avg_rsi = rv.mean(); print(f"  -> Avg RSI: {avg_rsi:.1f} ({len(rv)} tickers)")

    lt_breadth = 0.5
    if 'SMA_200' in valid.columns:
        sv3 = valid[valid['SMA_200'].notna() & valid['Close'].notna()]
        if len(sv3) > 0: lt_breadth = (sv3['Close'] > sv3['SMA_200']).sum() / len(sv3); print(f"  -> SMA200 breadth: {lt_breadth:.0%}")

    bull = 0; bear = 0
    if breadth > 0.60: bull += 2
    elif breadth > 0.50: bull += 1
    elif breadth < 0.35: bear += 2
    elif breadth < 0.45: bear += 1
    if nifty_change > 1.0: bull += 2
    elif nifty_change > 0.3: bull += 1
    elif nifty_change < -1.0: bear += 2
    elif nifty_change < -0.3: bear += 1
    if avg_rsi > 60: bull += 1
    elif avg_rsi < 40: bear += 1
    if lt_breadth > 0.65: bull += 1
    elif lt_breadth < 0.40: bear += 1
    net = bull - bear
    if net >= 4: regime, sc = "BULL", 15
    elif net >= 2: regime, sc = "MILD_BULL", 8
    elif net <= -4: regime, sc = "BEAR", -15
    elif net <= -2: regime, sc = "MILD_BEAR", -8
    else: regime, sc = "CHOPPY", 0
    detail = f"breadth={breadth:.0%} nifty={nifty_change:+.2f}% rsi={avg_rsi:.0f} lt={lt_breadth:.0%}"
    return {"regime": regime, "score": sc, "breadth": breadth, "nifty": nifty_change, "avg_rsi": avg_rsi, "lt_breadth": lt_breadth, "detail": detail}


def compute_sector_strength(stock_df):
    if stock_df is None or stock_df.empty: return {}, 0.5
    valid = get_latest_valid_rows(stock_df)
    if valid.empty or 'Industry' not in valid.columns or 'SMA_22' not in valid.columns: return {}, 0.5
    sv2 = valid[valid['SMA_22'].notna() & valid['Close'].notna()]
    if len(sv2) == 0: return {}, 0.5
    market_breadth = (sv2['Close'] > sv2['SMA_22']).sum() / len(sv2)
    sub_scores = {}; sub_to_broad = {}
    for sector in sv2['Industry'].dropna().unique():
        if is_bad_str(sector): continue
        sd = sv2[sv2['Industry'] == sector]
        if len(sd) < 1: continue
        s_above = (sd['Close'] > sd['SMA_22']).sum(); s_breadth = s_above / len(sd)
        relative = s_breadth - market_breadth
        s_rsi = sd['RSI_14'].dropna().mean() if 'RSI_14' in sd.columns and len(sd['RSI_14'].dropna()) > 0 else 50.0
        sc = round(relative * 40)
        if s_rsi > 65: sc -= 5
        elif s_rsi < 35: sc += 5
        sc = max(-20, min(20, sc))
        sub_scores[sector] = {"score": sc, "breadth": s_breadth, "rsi": s_rsi, "count": len(sd), "context": f"b={s_breadth:.0%} rsi={s_rsi:.0f} n={len(sd)}"}
        sub_to_broad[sector] = get_broad_sector(sector)
    broad_scores = {}
    for broad in set(sub_to_broad.values()):
        if not broad: continue
        members = [s for s, b in sub_to_broad.items() if b == broad]
        if members: broad_scores[broad] = round(sum(sub_scores[m]["score"] for m in members) / len(members))
    for sub in sub_scores:
        if sub_scores[sub]["count"] < 2:
            broad = sub_to_broad.get(sub, "")
            if broad in broad_scores: sub_scores[sub]["score"] = round((sub_scores[sub]["score"] + broad_scores[broad]) / 2)
    return sub_scores, market_breadth


def get_macro_scores(sectors, stock_df, regime):
    macro_cache = {}
    sector_strength, market_breadth = compute_sector_strength(stock_df)
    unique_sectors = list(set(s for s in sectors if s and not is_bad_str(s)))
    if not unique_sectors: return macro_cache
    sub_to_broad = {sub: get_broad_sector(sub) for sub in unique_sectors}
    broad_set = set(sub_to_broad.values()) - {""}
    print(f"  -> {len(unique_sectors)} sub-industries -> {len(broad_set)} broad sectors")
    print(f"  -> Market breadth: {market_breadth:.0%} above SMA22")
    broad_agg = {}
    for sub in unique_sectors:
        ss = sector_strength.get(sub, {"score": 0, "context": "no data"})
        combined = max(-30, min(30, regime["score"] + ss["score"]))
        macro_cache[sub] = {"score": combined, "context": f"{regime['regime']}|{ss.get('context', 'no data')}"}
        broad = sub_to_broad.get(sub, sub)
        if broad not in broad_agg: broad_agg[broad] = []
        broad_agg[broad].append(combined)
    for broad in sorted(broad_agg.keys(), key=lambda b: sum(broad_agg[b]) / len(broad_agg[b])):
        avg = sum(broad_agg[broad]) / len(broad_agg[broad]); count = len(broad_agg[broad])
        print(f"    {broad} ({count}): {avg:+.0f} [data-driven]")
    return macro_cache


# ═══════════════════════════════════════════════════════════════
# COMPOSITE + REGIME ADJUSTMENT
# ═══════════════════════════════════════════════════════════════

def compute_composite_news(sentiment, technical, macro, fundamental):
    w = dict(WEIGHTS_NEWS)
    if technical != 0 and sentiment != 0:
        td = 1 if technical > 0 else -1; sd = 1 if sentiment > 0 else -1
        if td == sd and abs(sentiment) > 50:
            w["technical"] += 0.05; w["sentiment"] += 0.05; w["macro"] -= 0.05; w["fundamental"] -= 0.05
    comp = round(technical * w["technical"] + sentiment * w["sentiment"] + macro * w["macro"] + fundamental * w["fundamental"], 1)
    direction = 1 if comp > 15 else (-1 if comp < -15 else 0)
    return {"score": comp, "direction": direction}

def compute_composite_no_news(technical, macro, fundamental=0):
    w = WEIGHTS_NO_NEWS; cm = max(-25, min(25, macro))
    comp = round(technical * w["technical"] + cm * w["macro"] + fundamental * w["fundamental"], 1)
    direction = 1 if comp > 15 else (-1 if comp < -15 else 0)
    return {"score": comp, "direction": direction}

def apply_regime_adjustment(comp_score, regime):
    r = regime["regime"]
    if comp_score > 0:
        if r == "BEAR": comp_score = round(comp_score * 0.60, 1)
        elif r == "MILD_BEAR": comp_score = round(comp_score * 0.80, 1)
        elif r == "BULL": comp_score = round(comp_score * 1.10, 1)
    elif comp_score < 0:
        if r == "BULL": comp_score = round(comp_score * 0.60, 1)
        elif r == "MILD_BULL": comp_score = round(comp_score * 0.80, 1)
        elif r == "BEAR": comp_score = round(comp_score * 1.10, 1)
    direction = 1 if comp_score > 15 else (-1 if comp_score < -15 else 0)
    return comp_score, direction


# ═══════════════════════════════════════════════════════════════
# PREDICTION ACCURACY (3-Day Rolling)
# ═══════════════════════════════════════════════════════════════

def compute_prediction_accuracy(hdf, today_rows, stock_df):
    print(f"\n{'='*110}"); print(f"PREDICTION ACCURACY REPORT (v5.0.1)"); print(f"{'='*110}")
    backtest_technical(stock_df); compute_composite_multiday(hdf, today_rows); compute_news_impact(hdf, today_rows)
    print(f"{'='*110}")

def backtest_technical(stock_df, forward_days=3, test_days=60):
    print(f"\n  -- TECHNICAL BACKTEST ({test_days}-day, {forward_days}-day forward, +-0.5%) --")
    if stock_df is None or stock_df.empty: print("  No stock data"); return
    mcap_threshold = detect_mcap_scale(stock_df)
    total_hit = 0; total_dir = 0; total_tests = 0; total_neutral = 0; ticker_results = {}
    tickers = stock_df['Ticker'].unique()
    for tk in tickers:
        tk_data = stock_df[stock_df['Ticker'] == tk].sort_values('Date').reset_index(drop=True)
        valid = tk_data[tk_data['Close'].notna()].reset_index(drop=True)
        if len(valid) < test_days + forward_days + 20: continue
        tk_hits = 0; tk_dir = 0; tk_tests = 0
        start_idx = max(20, len(valid) - test_days - forward_days)
        for i in range(start_idx, len(valid) - forward_days):
            cc = valid.iloc[i].get('Close'); fc = valid.iloc[i + forward_days].get('Close')
            if pd.isna(cc) or pd.isna(fc): continue
            cum_ret = 0.0
            for d in range(1, forward_days + 1):
                dc = valid.iloc[i + d].get('Close'); dp = valid.iloc[i + d - 1].get('Close')
                if pd.notna(dc) and pd.notna(dp) and dp > 0: cum_ret += ((dc - dp) / dp) * 100
            adir = 1 if cum_ret > 0.5 else (-1 if cum_ret < -0.5 else 0)
            slice_df = valid.iloc[max(0, i - 10):i + 1]
            ts, _ = compute_tech_score_v5(slice_df, mcap_threshold)
            pdir = 1 if ts > 15 else (-1 if ts < -15 else 0)
            tk_tests += 1; total_tests += 1
            if pdir == 0: total_neutral += 1; (tk_hits := tk_hits + 1) if adir == 0 else None; (total_hit := total_hit + 1) if adir == 0 else None; continue
            tk_dir += 1; total_dir += 1
            if pdir == adir: tk_hits += 1; total_hit += 1
        if tk_dir > 0: ticker_results[tk] = {"tests": tk_tests, "dir": tk_dir, "hits": tk_hits, "pct": (tk_hits / tk_tests) * 100}
    if total_tests == 0: print("  No backtest data"); return
    dir_pct = (total_hit / total_dir * 100) if total_dir > 0 else 0
    print(f"  Tickers tested: {len(ticker_results)}/{len(tickers)}")
    print(f"  Total predictions: {total_tests} | Directional: {total_dir} | Neutral: {total_neutral}")
    print(f"\n  DIRECTIONAL ACCURACY: {total_hit}/{total_dir} = {dir_pct:.1f}%")
    print(f"  OVERALL (incl neutral): {total_hit}/{total_tests} = {total_hit/total_tests*100:.1f}%")
    if ticker_results:
        stk = sorted(ticker_results.items(), key=lambda x: x[1]["pct"], reverse=True)
        print(f"\n  Top 5:")
        for tk, r in stk[:5]: print(f"    {tk:<14s} {r['hits']}/{r['tests']} = {r['pct']:.0f}% ({r['dir']} dir)")
        print(f"  Bottom 5:")
        for tk, r in stk[-5:]: print(f"    {tk:<14s} {r['hits']}/{r['tests']} = {r['pct']:.0f}% ({r['dir']} dir)")

def compute_composite_multiday(hdf, today_rows):
    print(f"\n  -- COMPOSITE MULTI-DAY ACCURACY (3-day rolling) --")
    today_df = pd.DataFrame(today_rows); today_df['Date'] = TODAY_IST
    if hdf.empty or 'Date' not in hdf.columns: all_data = today_df
    else:
        past = hdf[hdf['Date'] != TODAY_IST]; all_data = pd.concat([past, today_df], ignore_index=True)
    dates = sorted(all_data['Date'].unique())
    if len(dates) < 2: print(f"  Need 2+ trading days"); return

    print(f"\n  Next-Day (D -> D+1):")
    nd_hit = 0; nd_dir = 0
    for i in range(len(dates) - 1):
        sr = all_data[all_data['Date'] == dates[i]]; ar = all_data[all_data['Date'] == dates[i + 1]]
        if sr.empty or ar.empty: continue
        am = {}
        for _, a in ar.iterrows():
            tk = a.get('Ticker', '')
            if tk: am[tk] = safe_int(a.get('Actual_Direction', 0))
        dh = 0; dd = 0
        for _, s in sr.iterrows():
            tk = s.get('Ticker', '')
            if tk not in am: continue
            pc = safe_int(s.get('Composite_Direction', s.get('Forecast_Direction', 0)))
            if pc != 0:
                dd += 1; nd_dir += 1
                actual = am[tk]
                if pc == actual: dh += 1; nd_hit += 1
        if dd > 0: print(f"    {dates[i]} -> {dates[i+1]}: {dh}/{dd}={dh*100//dd}%")
        else: print(f"    {dates[i]} -> {dates[i+1]}: no dir")
    if nd_dir > 0: print(f"    AGGREGATE: {nd_hit}/{nd_dir} = {nd_hit/nd_dir*100:.1f}%")

    if len(dates) >= 4:
        print(f"\n  3-Day Cumulative (PRIMARY):")
        th = 0; td = 0
        for i in range(len(dates) - 3):
            for _, s in all_data[all_data['Date'] == dates[i]].iterrows():
                tk = s.get('Ticker', ''); pc = safe_int(s.get('Composite_Direction', s.get('Forecast_Direction', 0)))
                if pc == 0: continue
                cr = 0.0; f = False
                for j in range(i + 1, min(i + 4, len(dates))):
                    dr = all_data[(all_data['Date'] == dates[j]) & (all_data['Ticker'] == tk)]
                    if not dr.empty:
                        try: cr += float(dr.iloc[0].get('Actual_Return_Pct', 0.0))
                        except: pass
                        f = True
                if not f: continue
                ad = 1 if cr > 0.5 else (-1 if cr < -0.5 else 0)
                td += 1
                if pc == ad: th += 1
        if td > 0: print(f"    3-day: {th}/{td} = {th/td*100:.1f}%")
        else: print(f"    Not enough data yet")

def compute_news_impact(hdf, today_rows):
    print(f"\n  -- NEWS SENTIMENT IMPACT (1-3 day) --")
    today_df = pd.DataFrame(today_rows); today_df['Date'] = TODAY_IST
    if hdf.empty or 'Date' not in hdf.columns: all_data = today_df
    else:
        past = hdf[hdf['Date'] != TODAY_IST]; all_data = pd.concat([past, today_df], ignore_index=True)
    dates = sorted(all_data['Date'].unique())
    if len(dates) < 2: print("  Need 2+ days"); return
    for window in [1, 2, 3]:
        if len(dates) < window + 1: continue
        wh = 0; wd = 0
        for i in range(len(dates) - window):
            for _, s in all_data[all_data['Date'] == dates[i]].iterrows():
                pf = safe_int(s.get('Forecast_Direction', 0))
                if pf == 0: continue
                tk = s.get('Ticker', ''); cr = 0.0; f = False
                for j in range(i + 1, min(i + window + 1, len(dates))):
                    dr = all_data[(all_data['Date'] == dates[j]) & (all_data['Ticker'] == tk)]
                    if not dr.empty:
                        try: cr += float(dr.iloc[0].get('Actual_Return_Pct', 0.0))
                        except: pass
                        f = True
                if not f: continue
                ad = 1 if cr > 0.5 else (-1 if cr < -0.5 else 0); wd += 1
                if pf == ad: wh += 1
        if wd > 0: print(f"  {window}-day: {wh}/{wd} = {wh/wd*100:.1f}%")


# ═══════════════════════════════════════════════════════════════
# MAIN ENGINE v5.0.1
# ═══════════════════════════════════════════════════════════════

def execute_sentiment_engine():
    tl, sm = load_tickers(); total = len(tl)
    print(f"PREDICTIVE Engine v5.0.1 - {total} tickers | {TODAY_IST}")
    print(f"News: {NEWS_START_DATE} to {NEWS_CUTOFF_TIME.strftime('%I:%M %p')} | CATALYST-ONLY FinBERT")
    print(f"Tech: STRATEGY-BASED (LC=mean reversion ADX-aware, SMC=momentum+breakout)")
    print(f"  Tier1: SMA Hierarchy | Tier2: BB+Knox(S/R)+UP20 | Tier3: MACD+EMA+ST+Mom | Tier4: ADX")
    print(f"Fund: Debt + FII/DII + OBV | Macro: DATA-DRIVEN regime + sector strength")
    print(f"Validation: 3-day rolling cumulative direction")
    print("=" * 110)

    print("\nPHASE 1: Fetching predictive news...")
    print("-" * 110)
    nc = build_news_cache(tl)
    print("-" * 110)

    print(f"\nPHASE 2: FinBERT scoring (CATALYST-ONLY)...")
    print("-" * 110)
    scored = []; filing = []; nonews = []
    ha = 0; hd = 0; td2 = 0; total_catalyst = 0; total_noise_filtered = 0

    for idx, tk in enumerate(tl, 1):
        ret = get_live_price_return(tk)
        ad = 1 if ret > 0.25 else (-1 if ret < -0.25 else 0)
        entries, cls, fe = get_all_fresh_news(tk, nc, ret)
        base_row = {"Ticker": tk, "Sector": sm.get(tk, ""), "Actual_Direction": ad, "Actual_Return_Pct": ret}
        if cls == "no_news":
            nonews.append({**base_row, "Latest_Headline": "", "News_Source": "", "News_Time": "", "News_URL": "", "Headline_Count": 0, "Forecast_Score": 0.0, "Forecast_Direction": 0, "Severity": "No News", "Impact": "", "Streak_Days": 0, "Streak_Return": 0.0, "Momentum": "", "Signal_Quality": "Tech-Scored"}); continue
        if cls == "filing_only":
            p = fe[0] if fe else {}; nu = p.get("news_url", "") or get_source_search_url("NSE Official", tk)
            filing.append({**base_row, "Latest_Headline": p.get("headline", ""), "News_Source": "NSE Official", "News_Time": p.get("pub_time", "").replace(",", ""), "News_URL": nu, "Headline_Count": len(fe), "Forecast_Score": 0.0, "Forecast_Direction": 0, "Severity": "Filing Only", "Impact": "", "Streak_Days": 0, "Streak_Return": 0.0, "Momentum": "", "Signal_Quality": "Tech-Scored"}); continue
        pe = max(entries, key=lambda e: e["weight"]); ps = pe["source"]; pt = pe["pub_time"]
        pu = pe.get("news_url", "") or get_source_search_url(SOURCE_LABELS.get(ps, ""), tk)
        if ps in ("yfinance", "google"): time.sleep(0.3)
        score, direction, cat_count, noise_count = compute_aggregated_score(entries)
        total_catalyst += cat_count; total_noise_filtered += noise_count
        sev = classify_severity(score); imp = classify_impact(entries)
        hit = direction == ad
        if hit: ha += 1
        if direction != 0:
            td2 += 1
            if hit: hd += 1
        ab = abs(score); q = "High Conviction" if ab >= 60 else ("Moderate" if ab >= 25 else ("Weak" if ab >= 5 else "Neutral"))
        usrc = list(dict.fromkeys(SOURCE_LABELS.get(e["source"], e["source"]) for e in entries))
        dm = {1: "BULL", -1: "BEAR", 0: "NEUT"}; cat_tag = f"[{cat_count}cat/{len(entries)}h]"
        print(f"[{len(scored)+1:3d}] {tk:<14s} {dm.get(direction, '?'):4s} {sev[:12]:14s} Score:{score:+6.1f} Ret:{ret:+6.2f}% {imp:10s} {'HIT' if hit else 'MISS'} {cat_tag}")
        scored.append({**base_row, "Latest_Headline": pe["headline"], "News_Source": " | ".join(usrc), "News_Time": pt.replace(",", "") if pt else "", "News_URL": pu, "Headline_Count": len(entries), "Forecast_Score": score, "Forecast_Direction": direction, "Severity": sev, "Impact": imp, "Signal_Quality": q})
    print(f"\n  Catalyst filter: {total_catalyst} catalysts / {total_noise_filtered} noise filtered")

    # PHASE 3
    all_rows = scored + filing + nonews
    print(f"\nPHASE 3: Multi-layer STRATEGY-BASED analysis ({len(all_rows)} tickers)...")
    print("-" * 110)

    print("Loading stock data...")
    stock_df = load_stock_data_for_scoring()
    mcap_threshold = detect_mcap_scale(stock_df)
    print(f"  -> MCap threshold: {mcap_threshold:.0f}")

    print("Computing STRATEGY-BASED technical scores (v5.0.1)...")
    tech_count = 0; lc_count = 0; smc_count = 0
    for i, row in enumerate(all_rows):
        tech = get_technical_score(row["Ticker"], stock_df, mcap_threshold, debug=(i < 3))
        row["Technical_Score"] = tech["score"]
        row["Tech_Signals"] = " | ".join(tech["signals"]) if tech["signals"] else ""
        if tech["score"] != 0: tech_count += 1
        if stock_df is not None and not stock_df.empty:
            tk_data = stock_df[stock_df['Ticker'] == row["Ticker"]]
            tk_valid = tk_data[tk_data['Close'].notna()]
            if not tk_valid.empty:
                mc = safe_float(tk_valid.iloc[-1].get('Market_Cap', 0), 0)
                if mc > mcap_threshold: lc_count += 1
                else: smc_count += 1
            else: smc_count += 1
        else: smc_count += 1
    print(f"  -> {tech_count}/{len(all_rows)} with non-zero tech score | LC:{lc_count} SMC:{smc_count}")

    print("Computing fundamental scores...")
    for row in all_rows:
        fund = score_fundamentals_rules(row["Ticker"], stock_df)
        row["Fundamental_Score"] = fund["score"]; row["Fund_Concern"] = fund.get("concern", "")
    fund_nonzero = sum(1 for r in all_rows if r["Fundamental_Score"] != 0)
    print(f"  -> {fund_nonzero}/{len(all_rows)} with non-zero fundamental score")

    print("Building sector map...")
    all_sectors = set(); sector_count = 0
    for row in all_rows:
        sector = sm.get(row["Ticker"], "")
        if not sector or is_bad_str(sector): sector = get_sector_from_stock_data(row["Ticker"], stock_df)
        if is_bad_str(sector): sector = ""
        row["_sector"] = sector
        if sector: all_sectors.add(sector); sector_count += 1
    print(f"  -> {sector_count}/{len(all_rows)} mapped to {len(all_sectors)} sectors")

    print("\nComputing market regime (data-driven)...")
    nifty_chg = get_nifty_change()
    print(f"  -> Nifty 5d change: {nifty_chg:+.2f}%")
    regime = compute_market_regime(stock_df, nifty_chg)
    print(f"  -> REGIME: {regime['regime']} (score: {regime['score']:+d})")
    print(f"  -> {regime['detail']}")

    print(f"\nComputing sector strength ({len(all_sectors)} sectors)...")
    macro_scores = get_macro_scores(all_sectors, stock_df, regime)
    for row in all_rows:
        macro = macro_scores.get(row.get("_sector", ""), {"score": 0, "context": ""})
        row["Macro_Score"] = macro["score"]; row["Macro_Context"] = macro.get("context", "")

    print(f"\nComputing composite + regime adjustment...")
    rdesc = f"BULL dampened {'60%' if regime['regime']=='BEAR' else '80%'}" if "BEAR" in regime["regime"] else (f"BEAR dampened {'60%' if regime['regime']=='BULL' else '80%'}" if "BULL" in regime["regime"] else "no adjustment")
    print(f"  Regime: {regime['regime']} -> {rdesc}")
    print("-" * 110)

    cha = 0; chd = 0; ctd = 0; regime_flips = 0
    for row in scored:
        comp = compute_composite_news(row["Forecast_Score"], row["Technical_Score"], row["Macro_Score"], row["Fundamental_Score"])
        raw_score = comp["score"]; raw_dir = comp["direction"]
        adj_score, adj_dir = apply_regime_adjustment(raw_score, regime)
        row["Composite_Score"] = adj_score; row["Composite_Direction"] = adj_dir
        row["Composite_Severity"] = classify_composite_severity(adj_score)
        if raw_dir != adj_dir: regime_flips += 1
        c_hit = adj_dir == row["Actual_Direction"]
        if c_hit: cha += 1
        if adj_dir != 0:
            ctd += 1
            if c_hit: chd += 1
        dm2 = {1: "BULL", -1: "BEAR", 0: "NEUT"}
        corrected = " <- CORRECTED" if row["Forecast_Direction"] != adj_dir else ""
        rtag = f" [R:{raw_score:+.1f}->{adj_score:+.1f}]" if abs(raw_score - adj_score) > 0.5 else ""
        print(f"  [{scored.index(row)+1:3d}] {row['Ticker']:<14s} Tech:{row['Technical_Score']:+4d} Sent:{row['Forecast_Score']:+6.1f}({dm2[row['Forecast_Direction']]}) Macro:{row['Macro_Score']:+4d} Fund:{row['Fundamental_Score']:+4d} -> Comp:{adj_score:+6.1f} {dm2[adj_dir]} {'HIT' if c_hit else 'MISS'}{corrected}{rtag}")

    t_bull = 0; t_bear = 0; t_neut = 0; t_hit = 0; t_total = 0
    for row in filing + nonews:
        comp = compute_composite_no_news(row["Technical_Score"], row["Macro_Score"], row["Fundamental_Score"])
        raw_score = comp["score"]
        adj_score, adj_dir = apply_regime_adjustment(raw_score, regime)
        row["Composite_Score"] = adj_score; row["Composite_Direction"] = adj_dir
        row["Composite_Severity"] = classify_composite_severity(adj_score) if adj_score != 0 else ""
        row["Forecast_Direction"] = 0
        if adj_dir == 1: t_bull += 1
        elif adj_dir == -1: t_bear += 1
        else: t_neut += 1
        if adj_dir == row["Actual_Direction"]: t_hit += 1
        t_total += 1

    for row in all_rows: row.pop("_sector", None)
    scored_with_tech = [r for r in filing + nonews if r["Composite_Score"] != 0]
    print(f"\n  Tech-only scored: {len(scored_with_tech)}/{len(filing) + len(nonews)} | Bull:{t_bull} Bear:{t_bear} Neut:{t_neut}")
    if t_total > 0: print(f"  Tech-only hit rate: {t_hit}/{t_total} = {(t_hit / t_total) * 100:.1f}%")
    print(f"  Regime flips: {regime_flips}")

    # PHASE 4
    print(f"\nPHASE 4: Streaks for {len(scored)} tickers...")
    print("-" * 110)
    hdf = load_history()
    streaks = calculate_streaks(hdf, scored)
    for row in scored:
        s = streaks.get(row["Ticker"], {})
        row["Streak_Days"] = s.get("Streak_Days", 0); row["Streak_Return"] = s.get("Streak_Return", 0.0); row["Momentum"] = s.get("Momentum", "Neutral")

    pd.DataFrame(all_rows).to_csv(DATA_FILE, index=False)
    save_to_history(scored)

    sc = len(scored); fc = len(filing); nc2 = len(nonews)
    hrd = (hd / td2) * 100 if td2 > 0 else 0
    chrd = (chd / ctd) * 100 if ctd > 0 else 0
    corrected_count = sum(1 for r in scored if r["Forecast_Direction"] != r.get("Composite_Direction", r["Forecast_Direction"]))
    comp_bull = sum(1 for r in scored if r.get("Composite_Direction", 0) == 1)
    comp_bear = sum(1 for r in scored if r.get("Composite_Direction", 0) == -1)
    total_scored = sc + len(scored_with_tech)

    print("\n" + "=" * 110)
    print(f"data.csv | {TODAY_IST} | ENGINE v5.0.1 STRATEGY-BASED + REGIME")
    print(f"TICKERS: {sc} news | {fc} filing | {nc2} no-news | {total_scored} total signals")
    print(f"CATALYST FILTER: {total_catalyst} catalysts / {total_noise_filtered} noise filtered")
    print(f"REGIME: {regime['regime']} ({regime['detail']})")
    print(f"STRATEGY: LC({lc_count})=mean-reversion(ADX-aware) | SMC({smc_count})=momentum+breakout")
    print(f"TECH: Tier1:SMA-hierarchy | Tier2:BB+Knox(S/R)+UP20 | Tier3:MACD+EMA+ST+Mom | Tier4:ADX")
    print(f"FUND: Debt + FII/DII + OBV ({fund_nonzero} scored)")
    print(f"MACRO: Data-driven regime + sector strength (NO API)")
    print(f"WEIGHTS: News-> Tech={WEIGHTS_NEWS['technical']:.0%} Sent={WEIGHTS_NEWS['sentiment']:.0%} Macro={WEIGHTS_NEWS['macro']:.0%} Fund={WEIGHTS_NEWS['fundamental']:.0%}")
    print(f"         No-News-> Tech={WEIGHTS_NO_NEWS['technical']:.0%} Macro={WEIGHTS_NO_NEWS['macro']:.0%} Fund={WEIGHTS_NO_NEWS['fundamental']:.0%}")
    print(f"VALIDATION: 3-day rolling cumulative direction")
    print()
    print(f"SAME-DAY ACCURACY:")
    print(f"  SENTIMENT (catalyst-only):  Directional {hd}/{td2} = {hrd:.1f}%")
    print(f"  COMPOSITE + REGIME:         Directional {chd}/{ctd} = {chrd:.1f}%")
    print(f"  Corrected: {corrected_count} | Comp Bull:{comp_bull} Bear:{comp_bear} | Regime flips: {regime_flips}")
    print()
    print(f"TECH-ONLY ({t_total} without news):")
    if t_total > 0: print(f"  Hit rate: {t_hit}/{t_total} = {(t_hit / t_total) * 100:.1f}%")
    print(f"  Signals: Bull:{t_bull} Bear:{t_bear} Neutral:{t_neut}")
    delta_d = chrd - hrd
    print(f"\nIMPROVEMENT: {delta_d:+.1f}% ({hrd:.1f}% -> {chrd:.1f}%)")
    print("=" * 110)
    compute_prediction_accuracy(hdf, all_rows, stock_df)


if __name__ == "__main__":
    execute_sentiment_engine()
