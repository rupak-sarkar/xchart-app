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

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-IN,en;q=0.9",
}
feedparser.USER_AGENT = BROWSER_HEADERS["User-Agent"]

print("Initializing FinBERT...")
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
    "mc_topnews":"Moneycontrol","mc_business":"Moneycontrol",
    "mc_markets":"Moneycontrol","mc_stocks":"Moneycontrol",
    "et_markets":"Economic Times","et_stocks":"Economic Times",
    "et_news":"Economic Times","ndtv_business":"NDTV Profit",
    "mint_market":"LiveMint","mint_companies":"LiveMint",
    "nse_announce":"NSE Official","nse_actions":"NSE Official",
    "yfinance":"Yahoo Finance","google":"Google News",
}
SOURCE_SEARCH_URLS = {
    "Moneycontrol":"https://www.moneycontrol.com/news/tags/{ticker}.html",
    "Economic Times":"https://economictimes.indiatimes.com/topic/{ticker}",
    "NDTV Profit":"https://www.ndtvprofit.com/search?q={ticker}",
    "LiveMint":"https://www.livemint.com/Search/Link/Keyword/{ticker}",
    "NSE Official":"https://www.nseindia.com/get-quotes/equity?symbol={ticker}",
    "Yahoo Finance":"https://finance.yahoo.com/quote/{ticker}.NS/news/",
    "Google News":"https://news.google.com/search?q={ticker}+NSE+stock+india&hl=en-IN",
}
SOURCE_WEIGHTS = {
    "mc_topnews":1.5,"mc_business":1.3,"mc_markets":1.2,"mc_stocks":1.2,
    "et_markets":1.4,"et_stocks":1.3,"et_news":1.3,"ndtv_business":1.2,
    "mint_market":1.2,"mint_companies":1.1,
    "nse_announce":0.8,"nse_actions":0.7,
    "yfinance":1.0,"google":1.0,
}
NSE_SOURCES = {"nse_announce","nse_actions"}

ALL_FEEDS = {
    "mc_topnews":"https://www.moneycontrol.com/rss/MCtopnews.xml",
    "mc_business":"https://www.moneycontrol.com/rss/business.xml",
    "mc_markets":"https://www.moneycontrol.com/rss/marketreports.xml",
    "mc_stocks":"https://www.moneycontrol.com/rss/latestnews.xml",
    "et_markets":"https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks":"https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "et_news":"https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146843.cms",
    "ndtv_business":"https://feeds.feedburner.com/ndtvprofit-latest",
    "mint_market":"https://www.livemint.com/rss/market",
    "mint_companies":"https://www.livemint.com/rss/companies",
    "nse_announce":"https://archives.nseindia.com/content/RSS/Online_announcements.xml",
    "nse_actions":"https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
}

NSE_NOISE_KEYWORDS = [
    "board meeting intimation","intimation of board meeting","outcome of board meeting",
    "disclosure under regulation","regulation 30","regulation 29","regulation 31",
    "regulation 32","compliance certificate","corporate governance","annual report",
    "annual return","change of address","change in registered office",
    "newspaper publication","notice of agm","notice of egm","proceedings of agm",
    "proceedings of egm","general meeting","book closure","cessation of",
    "appointment of company secretary","secretarial compliance",
    "reconciliation of share capital","statement of investor complaints",
    "certificate under regulation","disclosure of related party","prior intimation",
    "loss of share certificate","duplicate share certificate","investor grievance",
    "shareholder meeting","postal ballot","e-voting","investor presentation",
    "analyst meet","credit facility",
]
NSE_ACTIONABLE_KEYWORDS = [
    "financial results","quarterly results","annual results","profit","revenue",
    "turnover","ebitda","net income","earnings","results for the quarter",
    "results for the year","audited results","unaudited results","standalone results",
    "consolidated results","order","contract","awarded","received order","order win",
    "letter of intent","loi","work order","dividend","interim dividend",
    "final dividend","special dividend","buyback","buy back","share repurchase",
    "bonus","bonus issue","bonus shares","stock split","sub-division",
    "acquisition","acquire","merger","amalgamation","takeover","joint venture",
    "partnership","subsidiary","disinvestment","stake sale","mou",
    "memorandum of understanding","qip","qualified institutional","rights issue",
    "preferential allotment","warrants","fpo","fundraise","fund raise",
    "capital raise","credit rating","rating upgrade","rating downgrade","crisil",
    "icra","care rating","india ratings","outlook revised","rating assigned",
    "promoter","insider trading","acquisition of shares","disposal of shares",
    "pledge","encumbrance","substantial acquisition","expansion","capacity","capex",
    "capital expenditure","new plant","commissioning","production commenced",
    "commercial production","managing director","chief executive","ceo","cfo","cto",
    "whole time director","resignation of","appointment of managing",
    "appointment of chief","sebi order","penalty","fine","adjudication",
    "suspension","debarment","default","npa","restructuring","insolvency","nclt",
    "resolution plan","fire","accident","force majeure","shutdown",
    "export order","import duty","anti-dumping",
]
SHORT_TERM_KEYWORDS = [
    "quarterly","q1","q2","q3","q4","results","earnings","profit","loss","revenue",
    "ebitda","net income","beat","miss","estimate","rally","crash","surge","plunge",
    "jump","tumble","fall","rise","buyback","dividend","bonus","split","record date",
    "ex-date","upgrade","downgrade","target price","rating","outlook","block deal",
    "bulk deal","insider","promoter","stake","order win","order book","contract",
    "awarded","trading halt","circuit","upper circuit","lower circuit",
]
LONG_TERM_KEYWORDS = [
    "expansion","capacity","capex","capital expenditure","plant","acquisition",
    "acquire","merger","amalgamation","takeover","partnership","joint venture",
    "collaboration","mou","agreement","regulation","policy","government","sebi",
    "rbi","ministry","restructuring","demerger","spin-off","reorganization","ipo",
    "listing","qip","fpo","rights issue","fundraise","technology","ai","digital",
    "automation","innovation","market entry","new segment","diversification",
    "subsidiary","debt","credit rating","refinancing","npa","provisioning","esg",
    "sustainability","carbon","green energy","renewable",
]
COMPANY_ALIASES = {
    "EICHER MOTORS":"EICHERMOT","EICHER":"EICHERMOT","HERO MOTOCORP":"HEROMOTOCO",
    "HERO MOTO":"HEROMOTOCO","MARUTI SUZUKI":"MARUTI","ESCORTS KUBOTA":"ESCORTS",
    "BOSCH":"BOSCHLTD","BHARAT ELECTRONICS":"BEL","DATA PATTERNS":"DATAPATTNS",
    "GARDEN REACH":"GRSE","HINDUSTAN AERONAUTICS":"HAL","MAZAGON DOCK":"MAZDOCK",
    "PERSISTENT SYSTEMS":"PERSISTENT","ZENSAR":"ZENSARTECH","COFORGE":"COFORGE",
    "NATIONAL ALUMINIUM":"NATIONALUM","NALCO":"NATIONALUM",
    "HINDUSTAN COPPER":"HINDCOPPER","COAL INDIA":"COALINDIA","HDFC AMC":"HDFCAMC",
    "ANGEL ONE":"ANGELONE","MOTILAL OSWAL":"MOTILALOFS","CRISIL":"CRISIL",
    "CARE RATINGS":"CARERATING","ICRA":"ICRA","ITC":"ITC",
    "JYOTHY LABS":"JYOTHYLAB","KEI INDUSTRIES":"KEI","POLYCAB":"POLYCAB",
    "NBCC":"NBCC","NCC":"NCC","CUMMINS INDIA":"CUMMINSIND","ABB":"ABB",
    "ABB INDIA":"ABB","POWER FINANCE":"PFC","REC LTD":"RECLTD",
    "GLOBAL HEALTH":"MEDANTA","BLUE STAR":"BLUESTARCO","LINDE INDIA":"LINDEINDIA",
    "SBI LIFE":"SBILIFE","CASTROL":"CASTROLIND","COROMANDEL":"COROMANDEL",
    "ABBOTT INDIA":"ABBOTINDIA","ALKEM":"ALKEM","CIPLA":"CIPLA",
    "TORRENT PHARMA":"TORNTPHARM","SAFARI INDUSTRIES":"SAFARI","TRENT":"TRENT",
    "LODHA":"LODHA","MACROTECH":"LODHA","BAJAJ FINANCE":"BAJFINANCE",
    "AU SMALL FINANCE":"AUBANK","CHOLAMANDALAM":"CHOLAFIN",
    "MUTHOOT FINANCE":"MUTHOOTFIN","SHRIRAM FINANCE":"SHRIRAMFIN",
    "SUNDARAM FINANCE":"SUNDARMFIN","HUDCO":"HUDCO","MCX":"MCX",
    "GRAVITA":"GRAVITA","APL APOLLO":"APLAPOLLO","AFFLE":"AFFLE",
    "HYUNDAI":"HYUNDAI","BIKAJI":"BIKAJI","ORACLE FINANCIAL":"OFSS",
    "BAJAJ HOLDINGS":"BAJAJHLDNG","RAILTEL":"RAILTEL","DOMS":"DOMS",
    "DODLA DAIRY":"DODLA","LT FOODS":"LTFOODS","WELSPUN CORP":"WELCORP",
    "INGERSOLL RAND":"INGERRAND","KIRLOSKAR":"KIRLOSBROS",
    "SHAKTI PUMPS":"SHAKTIPUMP","TD POWER SYSTEMS":"TDPOWERSYS",
    "UNO MINDA":"UNOMINDA","HOME FIRST":"HOMEFIRST","CAN FIN HOMES":"CANFINHOME",
    "NUVAMA":"NUVAMA","GROWW":"GROWW","TEGA":"TEGA","ENDURANCE":"ENDURANCE",
    "SANSERA":"SANSERA","TIPS MUSIC":"TIPSMUSIC","GOLDIAM":"GOLDIAM",
    "NEWGEN":"NEWGEN","RATEGAIN":"RATEGAIN","ECLERX":"ECLERX","VOLTAMP":"VOLTAMP",
    "ELECON":"ELECON","PRUDENT":"PRUDENT","MARKSANS":"MARKSANS",
    "SUPRIYA":"SUPRIYA","MARATHON":"MARATHON",
}

def classify_nse_headline(headline):
    text = headline.lower()
    for kw in NSE_ACTIONABLE_KEYWORDS:
        if kw in text: return "actionable"
    for kw in NSE_NOISE_KEYWORDS:
        if kw in text: return "noise"
    return "noise"

def classify_severity(score):
    if score >= 60: return "Very Bullish"
    elif score >= 25: return "Bullish"
    elif score >= 5: return "Mildly Bullish"
    elif score >= -5: return "Neutral"
    elif score >= -25: return "Mildly Bearish"
    elif score >= -60: return "Bearish"
    else: return "Very Bearish"

def classify_impact(entries):
    combined = " ".join(e["headline"] for e in entries).lower()
    short = sum(1 for kw in SHORT_TERM_KEYWORDS if kw in combined)
    long = sum(1 for kw in LONG_TERM_KEYWORDS if kw in combined)
    if short > 0 and long > 0: return "Both"
    elif long > 0: return "Long-term"
    elif short > 0: return "Short-term"
    else: return "Short-term"

def extract_pub_date_and_time(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            dt_utc = datetime(*parsed[:6], tzinfo=timezone.utc)
            dt_ist = dt_utc.astimezone(IST)
            return dt_ist.date(), dt_ist.strftime("%d %b %Y %I:%M %p")
        except: pass
    return None, ""

def extract_news_url(entry):
    return entry.get("link", entry.get("id", ""))

def is_fresh(pub_date):
    if pub_date is None: return True
    return pub_date >= YESTERDAY_DATE

def get_source_search_url(source_label, ticker):
    template = SOURCE_SEARCH_URLS.get(source_label, "")
    return template.replace("{ticker}", ticker) if template else ""

def fetch_rss_with_headers(url, label, timeout=15):
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except requests.exceptions.RequestException as e:
        print(f"   {label}: {e}")
        try: return feedparser.parse(url)
        except: return None

def match_ticker_in_text(text_upper, tickers_list):
    for t in sorted(tickers_list, key=len, reverse=True):
        if re.search(r'\b' + re.escape(t.upper()) + r'\b', text_upper): return t
    for alias, t in COMPANY_ALIASES.items():
        if alias in text_upper and t in tickers_list: return t
    return None

def load_tickers():
    if os.path.exists(TICKERS_FILE):
        try:
            df = pd.read_csv(TICKERS_FILE); df.columns = df.columns.str.strip()
            if 'Ticker' not in df.columns: df.rename(columns={df.columns[0]: 'Ticker'}, inplace=True)
            tickers = [t.replace('.NS','') for t in df['Ticker'].dropna().str.strip().str.upper().tolist() if t]
            seen = set(); unique = []
            for t in tickers:
                if t not in seen: seen.add(t); unique.append(t)
            sector_map = {}
            if 'Sector' in df.columns:
                for _, row in df.iterrows():
                    tk = str(row['Ticker']).strip().upper().replace('.NS','')
                    sec = str(row.get('Sector','')).strip()
                    if tk and sec: sector_map[tk] = sec
            print(f"Loaded {len(unique)} tickers from {TICKERS_FILE}")
            return unique, sector_map
        except Exception as e: print(f"Error: {e}")
    return ["RELIANCE","TCS","INFY","HDFCBANK","SBIN","ICICIBANK","ITC"], {}

def score_single_headline(headline):
    if not headline: return 0.0
    try:
        inputs = tokenizer([headline], padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad(): outputs = model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
        return (probs[0][0].item() - probs[0][1].item()) * 100.0
    except: return 0.0

def compute_aggregated_score(entries):
    if not entries: return 0.0, 0
    tw = 0.0; ws = 0.0
    for e in entries:
        raw = score_single_headline(e["headline"]); w = e.get("weight",1.0)
        ws += raw * w; tw += w
    if tw == 0: return 0.0, 0
    score = ws / tw
    if score > 5.0: d = 1
    elif score < -5.0: d = -1
    else: d = 0
    return round(score, 1), d

def get_live_price_return(ticker):
    try:
        h = yf.Ticker(f"{ticker}.NS").history(period="5d")
        if len(h) >= 2: return round(((h['Close'].iloc[-1] - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100, 2)
    except: pass
    return 0.0

def build_news_cache(tickers_list):
    cache = {}; total_stale = 0; nse_noise = 0; nse_action = 0
    for source_key, url in ALL_FEEDS.items():
        print(f"Fetching {source_key}...")
        feed = fetch_rss_with_headers(url, source_key)
        if not feed or not feed.entries: print(f"   {source_key}: No entries"); continue
        mc = 0; sc = 0; nc = 0
        for entry in feed.entries:
            title = entry.get("title",""); desc = entry.get("description",entry.get("summary",""))
            full_text = f"{title} {desc}".upper()
            mt = match_ticker_in_text(full_text, tickers_list)
            if not mt or not title.strip(): continue
            pub_date, pub_time = extract_pub_date_and_time(entry)
            if not is_fresh(pub_date): sc += 1; total_stale += 1; continue
            headline = title.strip().replace(",",";"); news_url = extract_news_url(entry)
            if source_key in NSE_SOURCES:
                nse_class = classify_nse_headline(headline)
                if nse_class == "noise":
                    nc += 1; nse_noise += 1
                    fk = f"_filing_{mt}"
                    if fk not in cache: cache[fk] = []
                    cache[fk].append({"headline":headline,"source":source_key,"pub_time":pub_time,"weight":0.0,"nse_class":"noise","news_url":news_url})
                    continue
                else: nse_action += 1
            weight = SOURCE_WEIGHTS.get(source_key, 1.0)
            existing = cache.get(mt, [])
            if not any(e["headline"].lower() == headline.lower() for e in existing):
                if mt not in cache: cache[mt] = []
                cache[mt].append({"headline":headline,"source":source_key,"pub_time":pub_time,"weight":weight,"nse_class":"actionable" if source_key in NSE_SOURCES else "news","news_url":news_url})
                mc += 1
        notes = []
        if sc: notes.append(f"{sc} stale")
        if nc: notes.append(f"{nc} NSE noise")
        print(f"   {source_key}: {mc} fresh from {len(feed.entries)}" + (f" ({', '.join(notes)})" if notes else ""))
        time.sleep(0.3)
    real = {k for k in cache if not k.startswith("_filing_")}
    print(f"\nCache: {len(real)}/{len(tickers_list)} tickers | NSE noise:{nse_noise} actionable:{nse_action} stale:{total_stale}")
    return cache

def get_yfinance_news(ticker):
    try:
        news = getattr(yf.Ticker(f"{ticker}.NS"), 'news', None)
        if news and isinstance(news, list):
            for item in news:
                if not isinstance(item, dict): continue
                hl = item.get("title",item.get("headline",""))
                if not hl: continue
                nu = item.get("link",item.get("url",""))
                pts = item.get("providerPublishTime") or item.get("publish_time")
                pt = ""; pd2 = None
                if pts:
                    try: dt = datetime.fromtimestamp(int(pts), tz=IST); pd2 = dt.date(); pt = dt.strftime("%d %b %Y %I:%M %p")
                    except: pass
                if is_fresh(pd2): return hl.replace(",",";"), pt, nu
    except: pass
    return None, "", ""

def get_google_news(ticker):
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(ticker)}+NSE+stock+india&hl=en-IN&gl=IN&ceid=IN:en"
        feed = fetch_rss_with_headers(url, f"gg_{ticker}", timeout=8)
        if feed and feed.entries:
            for entry in feed.entries[:3]:
                pd2, pt = extract_pub_date_and_time(entry)
                if is_fresh(pd2):
                    hl = re.sub(r'\s+-\s+[^:\-]+$', '', entry.title)
                    return hl.replace(",",";"), pt, extract_news_url(entry)
    except: pass
    return None, "", ""

def get_all_fresh_news(ticker, cache):
    entries = []
    if ticker in cache: entries.extend(cache[ticker])
    hl, pt, nu = get_yfinance_news(ticker)
    if hl and not any(e["headline"].lower()==hl.lower() for e in entries):
        entries.append({"headline":hl,"source":"yfinance","pub_time":pt,"weight":1.0,"nse_class":"news","news_url":nu})
    if len(entries) < 3:
        hl, pt, nu = get_google_news(ticker)
        if hl and not any(e["headline"].lower()==hl.lower() for e in entries):
            entries.append({"headline":hl,"source":"google","pub_time":pt,"weight":1.0,"nse_class":"news","news_url":nu})
    filing_entries = cache.get(f"_filing_{ticker}", [])
    if entries: return entries, "actionable", filing_entries
    elif filing_entries: return filing_entries, "filing_only", filing_entries
    else: return [], "no_news", []

def load_history():
    try:
        df = pd.read_csv(HISTORY_FILE)
        if 'Date' in df.columns:
            dates = sorted(df['Date'].unique(), reverse=True)[:30]
            df = df[df['Date'].isin(dates)]
        return df
    except FileNotFoundError: return pd.DataFrame()

def calculate_streaks(history_df, today_rows):
    streaks = {}
    for row in today_rows:
        tk=row["Ticker"]; td=row["Forecast_Direction"]; ts=row["Forecast_Score"]; tr=row["Actual_Return_Pct"]
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
    if not hdf.empty and 'Date' in hdf.columns: hdf = hdf[hdf['Date']!=TODAY_IST]
    c = pd.concat([hdf,tdf],ignore_index=True)
    if 'Date' in c.columns:
        dates = sorted(c['Date'].unique(),reverse=True)[:30]; c = c[c['Date'].isin(dates)]
    c.to_csv(HISTORY_FILE,index=False)
    print(f"History: {len(c)} rows / {c['Date'].nunique() if 'Date' in c.columns else 1} days")

def execute_sentiment_engine():
    tickers_list, sector_map = load_tickers()
    total = len(tickers_list)
    print(f"Running Engine - {total} tickers | Date: {TODAY_IST} | Window: {YESTERDAY_DATE} to {TODAY_DATE}")
    print("=" * 100)
    print("\nPHASE 1: Pre-fetching news...")
    print("-" * 100)
    news_cache = build_news_cache(tickers_list)
    print("-" * 100)
    print(f"\nPHASE 2: Scoring...")
    print("-" * 100)
    scored_rows=[]; filing_rows=[]; no_news_rows=[]; source_stats={}
    hits_all=0; hits_dir=0; total_dir=0
    for idx, ticker in enumerate(tickers_list, 1):
        entries, classification, filing_entries = get_all_fresh_news(ticker, news_cache)
        ret = get_live_price_return(ticker)
        if ret > 0.25: ad = 1
        elif ret < -0.25: ad = -1
        else: ad = 0
        if classification == "no_news":
            no_news_rows.append({"Ticker":ticker,"Sector":sector_map.get(ticker,""),"Latest_Headline":"","News_Source":"","News_Time":"","News_URL":"","Headline_Count":0,"Forecast_Score":0.0,"Forecast_Direction":0,"Actual_Direction":ad,"Actual_Return_Pct":ret,"Severity":"No News","Impact":"","Streak_Days":0,"Streak_Return":0.0,"Momentum":"","Signal_Quality":"No News"})
            continue
        if classification == "filing_only":
            p = filing_entries[0] if filing_entries else {}
            nu = p.get("news_url","") or get_source_search_url("NSE Official", ticker)
            filing_rows.append({"Ticker":ticker,"Sector":sector_map.get(ticker,""),"Latest_Headline":p.get("headline",""),"News_Source":"NSE Official","News_Time":p.get("pub_time","").replace(",",""),"News_URL":nu,"Headline_Count":len(filing_entries),"Forecast_Score":0.0,"Forecast_Direction":0,"Actual_Direction":ad,"Actual_Return_Pct":ret,"Severity":"Filing Only","Impact":"","Streak_Days":0,"Streak_Return":0.0,"Momentum":"","Signal_Quality":"Filing Only"})
            continue
        pe = max(entries, key=lambda e: e["weight"])
        ps = pe["source"]; pt = pe["pub_time"]; pu = pe.get("news_url","")
        source_stats[ps] = source_stats.get(ps,0)+1
        if not pu: pu = get_source_search_url(SOURCE_LABELS.get(ps,""), ticker)
        if ps in ("yfinance","google"): time.sleep(0.3)
        score, direction = compute_aggregated_score(entries)
        severity = classify_severity(score); impact = classify_impact(entries)
        is_hit = direction == ad
        if is_hit: hits_all += 1
        if direction != 0:
            total_dir += 1
            if is_hit: hits_dir += 1
        abss = abs(score)
        if abss >= 60: quality = "High Conviction"
        elif abss >= 25: quality = "Moderate"
        elif abss >= 5: quality = "Weak"
        else: quality = "Neutral"
        usrc = list(dict.fromkeys(SOURCE_LABELS.get(e["source"],e["source"]) for e in entries))
        dm = {1:"BULL",-1:"BEAR",0:"NEUT"}
        hc = len(entries); ht = f"[{hc}h]" if hc>=2 else ""
        print(f"[{len(scored_rows)+1:3d}] {ticker:<14s} {dm.get(direction,'?'):4s} {severity[:12]:14s} Score:{score:+6.1f} Ret:{ret:+6.2f}% {impact:10s} {'HIT' if is_hit else 'MISS'} {ht}")
        scored_rows.append({"Ticker":ticker,"Sector":sector_map.get(ticker,""),"Latest_Headline":pe["headline"],"News_Source":" | ".join(usrc),"News_Time":pt.replace(",","") if pt else "","News_URL":pu,"Headline_Count":len(entries),"Forecast_Score":score,"Forecast_Direction":direction,"Actual_Direction":ad,"Actual_Return_Pct":ret,"Severity":severity,"Impact":impact,"Signal_Quality":quality})
    print(f"\nPHASE 3: Streaks for {len(scored_rows)} tickers...")
    print("-" * 100)
    history_df = load_history(); streaks = calculate_streaks(history_df, scored_rows)
    for row in scored_rows:
        s = streaks.get(row["Ticker"],{})
        row["Streak_Days"]=s.get("Streak_Days",0); row["Streak_Return"]=s.get("Streak_Return",0.0); row["Momentum"]=s.get("Momentum","Neutral")
    all_rows = scored_rows + filing_rows + no_news_rows
    pd.DataFrame(all_rows).to_csv(DATA_FILE, index=False)
    save_to_history(scored_rows)
    sc=len(scored_rows); fc=len(filing_rows); nc=len(no_news_rows)
    bull=sum(1 for r in scored_rows if r["Forecast_Direction"]==1)
    bear=sum(1 for r in scored_rows if r["Forecast_Direction"]==-1)
    neut=sum(1 for r in scored_rows if r["Forecast_Direction"]==0)
    hra=(hits_all/sc)*100 if sc>0 else 0; hrd=(hits_dir/total_dir)*100 if total_dir>0 else 0
    hcr=[r for r in scored_rows if r["Signal_Quality"]=="High Conviction"]
    hch=sum(1 for r in hcr if r["Forecast_Direction"]==r["Actual_Direction"])
    hcra=(hch/len(hcr))*100 if hcr else 0
    print("\n"+"="*100)
    print(f"data.csv written | {TODAY_IST}")
    print(f"TICKERS: {sc} scored | {fc} filing-only | {nc} no news")
    print(f"ACCURACY: Overall:{hits_all}/{sc}={hra:.1f}% | Directional:{hits_dir}/{total_dir}={hrd:.1f}% | HighConv:{hch}/{len(hcr)}={hcra:.1f}%")
    print(f"SIGNALS: Bull:{bull} Bear:{bear} Neutral:{neut}")
    print("="*100)

if __name__ == "__main__":
    execute_sentiment_engine()
