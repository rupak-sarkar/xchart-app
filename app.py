import pandas as pd
import yfinance as yf
import feedparser
import requests
import re
import time
import json
import urllib.parse
import os
from datetime import datetime, timezone, timedelta
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

BROWSER_HEADERS = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36","Accept":"application/rss+xml, application/xml, text/xml, */*","Accept-Language":"en-IN,en;q=0.9"}
feedparser.USER_AGENT = BROWSER_HEADERS["User-Agent"]
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
TICKERS_FILE = "tickers.csv"
HISTORY_FILE = "history.csv"
DATA_FILE = "data.csv"
STOCK_DATA_FILE = "stock_data.csv"

# ── GEMINI API (multi-layer scoring) ──
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_NAME}:generateContent"
GEMINI_DELAY = 4  # seconds between calls (free tier = 15 RPM)
COMPOSITE_WEIGHTS = {"sentiment": 0.25, "fundamental": 0.35, "technical": 0.20, "macro": 0.20}
if GEMINI_API_KEY:
    print(f"Gemini API: enabled ({GEMINI_MODEL_NAME})")
else:
    print("Gemini API: not configured → rule-based fallback for fundamental/macro")

SOURCE_LABELS = {"mc_topnews":"Moneycontrol","mc_business":"Moneycontrol","mc_markets":"Moneycontrol","mc_stocks":"Moneycontrol","et_markets":"Economic Times","et_stocks":"Economic Times","et_news":"Economic Times","ndtv_business":"NDTV Profit","mint_market":"LiveMint","mint_companies":"LiveMint","nse_announce":"NSE Official","nse_actions":"NSE Official","fe_markets":"Financial Express","fe_companies":"Financial Express","bl_markets":"BusinessLine","bl_stocks":"BusinessLine","bl_companies":"BusinessLine","yfinance":"Yahoo Finance","google":"Google News"}
SOURCE_SEARCH_URLS = {"Moneycontrol":"https://www.moneycontrol.com/news/tags/{ticker}.html","Economic Times":"https://economictimes.indiatimes.com/topic/{ticker}","NDTV Profit":"https://www.ndtvprofit.com/search?q={ticker}","LiveMint":"https://www.livemint.com/Search/Link/Keyword/{ticker}","NSE Official":"https://www.nseindia.com/get-quotes/equity?symbol={ticker}","Yahoo Finance":"https://finance.yahoo.com/quote/{ticker}.NS/news/","Google News":"https://news.google.com/search?q={ticker}+NSE+stock+india&hl=en-IN","Financial Express":"https://www.financialexpress.com/about/{ticker}/","BusinessLine":"https://www.thehindubusinessline.com/topic/{ticker}/"}
SOURCE_WEIGHTS = {"mc_topnews":1.5,"mc_business":1.3,"mc_markets":1.2,"mc_stocks":1.2,"et_markets":1.4,"et_stocks":1.3,"et_news":1.3,"ndtv_business":1.2,"mint_market":1.2,"mint_companies":1.1,"nse_announce":0.8,"nse_actions":0.7,"fe_markets":1.3,"fe_companies":1.2,"bl_markets":1.3,"bl_stocks":1.3,"bl_companies":1.2,"yfinance":1.0,"google":1.0}
NSE_SOURCES = {"nse_announce","nse_actions"}
ALL_FEEDS = {"mc_topnews":"https://www.moneycontrol.com/rss/MCtopnews.xml","mc_business":"https://www.moneycontrol.com/rss/business.xml","mc_markets":"https://www.moneycontrol.com/rss/marketreports.xml","mc_stocks":"https://www.moneycontrol.com/rss/latestnews.xml","et_markets":"https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms","et_stocks":"https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms","et_news":"https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146843.cms","ndtv_business":"https://feeds.feedburner.com/ndtvprofit-latest","mint_market":"https://www.livemint.com/rss/market","mint_companies":"https://www.livemint.com/rss/companies","nse_announce":"https://archives.nseindia.com/content/RSS/Online_announcements.xml","nse_actions":"https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml","fe_markets":"https://www.financialexpress.com/market/feed/","fe_companies":"https://www.financialexpress.com/industry/companies/feed/","bl_markets":"https://www.thehindubusinessline.com/markets/feeder/default.rss","bl_stocks":"https://www.thehindubusinessline.com/markets/stock-markets/feeder/default.rss","bl_companies":"https://www.thehindubusinessline.com/companies/feeder/default.rss"}
NSE_NOISE_KEYWORDS = ["board meeting intimation","intimation of board meeting","outcome of board meeting","disclosure under regulation","regulation 30","regulation 29","regulation 31","regulation 32","compliance certificate","corporate governance","annual report","annual return","change of address","change in registered office","newspaper publication","notice of agm","notice of egm","proceedings of agm","proceedings of egm","general meeting","book closure","cessation of","appointment of company secretary","secretarial compliance","reconciliation of share capital","statement of investor complaints","certificate under regulation","disclosure of related party","prior intimation","loss of share certificate","duplicate share certificate","investor grievance","shareholder meeting","postal ballot","e-voting","investor presentation","analyst meet","credit facility"]
NSE_ACTIONABLE_KEYWORDS = ["financial results","quarterly results","annual results","profit","revenue","turnover","ebitda","net income","earnings","results for the quarter","results for the year","audited results","unaudited results","standalone results","consolidated results","order","contract","awarded","received order","order win","letter of intent","loi","work order","dividend","interim dividend","final dividend","special dividend","buyback","buy back","share repurchase","bonus","bonus issue","bonus shares","stock split","sub-division","acquisition","acquire","merger","amalgamation","takeover","joint venture","partnership","subsidiary","disinvestment","stake sale","mou","memorandum of understanding","qip","qualified institutional","rights issue","preferential allotment","warrants","fpo","fundraise","fund raise","capital raise","credit rating","rating upgrade","rating downgrade","crisil","icra","care rating","india ratings","outlook revised","rating assigned","promoter","insider trading","acquisition of shares","disposal of shares","pledge","encumbrance","substantial acquisition","expansion","capacity","capex","capital expenditure","new plant","commissioning","production commenced","commercial production","managing director","chief executive","ceo","cfo","cto","whole time director","resignation of","appointment of managing","appointment of chief","sebi order","penalty","fine","adjudication","suspension","debarment","default","npa","restructuring","insolvency","nclt","resolution plan","fire","accident","force majeure","shutdown","export order","import duty","anti-dumping"]
SHORT_TERM_KEYWORDS = ["quarterly","q1","q2","q3","q4","results","earnings","profit","loss","revenue","ebitda","net income","beat","miss","estimate","buyback","dividend","bonus","split","record date","ex-date","upgrade","downgrade","target price","rating","outlook","block deal","bulk deal","insider","promoter","stake","order win","order book","contract","awarded"]
LONG_TERM_KEYWORDS = ["expansion","capacity","capex","capital expenditure","plant","acquisition","acquire","merger","amalgamation","takeover","partnership","joint venture","collaboration","mou","agreement","regulation","policy","government","sebi","rbi","ministry","restructuring","demerger","spin-off","reorganization","ipo","listing","qip","fpo","rights issue","fundraise","technology","ai","digital","automation","innovation","market entry","new segment","diversification","subsidiary","debt","credit rating","refinancing","npa","provisioning","esg","sustainability","carbon","green energy","renewable"]
COMPANY_ALIASES = {"EICHER MOTORS":"EICHERMOT","EICHER":"EICHERMOT","HERO MOTOCORP":"HEROMOTOCO","HERO MOTO":"HEROMOTOCO","MARUTI SUZUKI":"MARUTI","ESCORTS KUBOTA":"ESCORTS","BOSCH":"BOSCHLTD","BHARAT ELECTRONICS":"BEL","DATA PATTERNS":"DATAPATTNS","GARDEN REACH":"GRSE","HINDUSTAN AERONAUTICS":"HAL","MAZAGON DOCK":"MAZDOCK","PERSISTENT SYSTEMS":"PERSISTENT","ZENSAR":"ZENSARTECH","COFORGE":"COFORGE","NATIONAL ALUMINIUM":"NATIONALUM","NALCO":"NATIONALUM","HINDUSTAN COPPER":"HINDCOPPER","COAL INDIA":"COALINDIA","HDFC AMC":"HDFCAMC","ANGEL ONE":"ANGELONE","MOTILAL OSWAL":"MOTILALOFS","CRISIL":"CRISIL","CARE RATINGS":"CARERATING","ICRA":"ICRA","ITC":"ITC","JYOTHY LABS":"JYOTHYLAB","KEI INDUSTRIES":"KEI","POLYCAB":"POLYCAB","NBCC":"NBCC","NCC":"NCC","CUMMINS INDIA":"CUMMINSIND","ABB":"ABB","ABB INDIA":"ABB","POWER FINANCE":"PFC","REC LTD":"RECLTD","GLOBAL HEALTH":"MEDANTA","BLUE STAR":"BLUESTARCO","LINDE INDIA":"LINDEINDIA","SBI LIFE":"SBILIFE","CASTROL":"CASTROLIND","COROMANDEL":"COROMANDEL","ABBOTT INDIA":"ABBOTINDIA","ALKEM":"ALKEM","CIPLA":"CIPLA","TORRENT PHARMA":"TORNTPHARM","SAFARI INDUSTRIES":"SAFARI","TRENT":"TRENT","LODHA":"LODHA","MACROTECH":"LODHA","BAJAJ FINANCE":"BAJFINANCE","AU SMALL FINANCE":"AUBANK","CHOLAMANDALAM":"CHOLAFIN","MUTHOOT FINANCE":"MUTHOOTFIN","SHRIRAM FINANCE":"SHRIRAMFIN","SUNDARAM FINANCE":"SUNDARMFIN","HUDCO":"HUDCO","MCX":"MCX","GRAVITA":"GRAVITA","APL APOLLO":"APLAPOLLO","AFFLE":"AFFLE","HYUNDAI":"HYUNDAI","BIKAJI":"BIKAJI","ORACLE FINANCIAL":"OFSS","BAJAJ HOLDINGS":"BAJAJHLDNG","RAILTEL":"RAILTEL","DOMS":"DOMS","DODLA DAIRY":"DODLA","LT FOODS":"LTFOODS","WELSPUN CORP":"WELCORP","INGERSOLL RAND":"INGERRAND","KIRLOSKAR":"KIRLOSBROS","SHAKTI PUMPS":"SHAKTIPUMP","TD POWER SYSTEMS":"TDPOWERSYS","UNO MINDA":"UNOMINDA","HOME FIRST":"HOMEFIRST","CAN FIN HOMES":"CANFINHOME","NUVAMA":"NUVAMA","GROWW":"GROWW","TEGA":"TEGA","ENDURANCE":"ENDURANCE","SANSERA":"SANSERA","TIPS MUSIC":"TIPSMUSIC","GOLDIAM":"GOLDIAM","NEWGEN":"NEWGEN","RATEGAIN":"RATEGAIN","ECLERX":"ECLERX","VOLTAMP":"VOLTAMP","ELECON":"ELECON","PRUDENT":"PRUDENT","MARKSANS":"MARKSANS","SUPRIYA":"SUPRIYA","MARATHON":"MARATHON"}
REPORTING_VERBS = {"surged","surges","surge","jumped","jumps","jump","rallied","rallies","rally","soared","soars","soar","rose","rises","crashed","crashes","crash","fell","falls","fall","dropped","drops","drop","tumbled","tumbles","tumble","plunged","plunges","plunge","sank","sinks","sink","declined","declines","decline","slipped","slips","slip","gained","gains","gain","lost","loses","lose","climbed","climbs","climb","advanced","advances","advance","retreated","retreats","tanked","tanks","zoomed","zooms","skyrocketed","nosedived"}
PRICE_CONTEXT = {"share","shares","stock","stocks","scrip","counter","sensex","nifty","market","index","indices","bse","nse","trading","trade","session","intraday","today","morning","afternoon","week","high","low","close","closed","closing","open","opened"}
CATALYST_VERBS = {"wins","win","won","awarded","receives","received","secures","secured","acquires","acquired","acquire","merges","merged","merge","approves","approved","approve","clears","cleared","clear","launches","launched","launch","plans","planned","plan","expands","expanded","expand","invests","invested","invest","raises","raised","raise","signs","signed","sign","partners","partnered","partner","enters","entered","enter","files","filed","file","announces","announced","announce","declares","declared","declare","recommends","recommended","upgrades","upgraded","upgrade","downgrades","downgraded","downgrade","appoints","appointed","appoint","resigns","resigned","resign","penalizes","penalized","fines","fined","suspends","suspended","bans","banned","restructures","restructured","defaults","defaulted","commissions","commissioned","inaugurates","inaugurated","divests","divested","demerges","demerged"}
SECTOR_IMPACT_WORDS = {"industry","sector","segment","policy","regulation","government","ministry","budget","gst","tariff","duty","subsidy","pli","rbi","sebi","ban","mandate","compliance","guideline","monsoon","crude","oil","commodity","inflation","rate cut","rate hike","forex","rupee","dollar","export","import","demand","supply"}

# ═══════════════════════════════════════════════════════════════
# EXISTING FUNCTIONS (unchanged)
# ═══════════════════════════════════════════════════════════════

def classify_headline(headline, actual_return=None):
    text = headline.lower()
    words = set(re.findall(r'[a-z]+', text))
    pct_matches = re.findall(r'(\d+\.?\d*)\s*%', text)
    if pct_matches and actual_return is not None:
        for ps in pct_matches:
            try:
                if abs(float(ps) - abs(actual_return)) < 3.0: return "reporting", "% match"
            except: pass
    has_rv = bool(words & REPORTING_VERBS); has_pc = bool(words & PRICE_CONTEXT); has_pct = bool(re.search(r'\d+\.?\d*\s*%', text))
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
    if s>=60: return "Very Bullish"
    elif s>=25: return "Bullish"
    elif s>=5: return "Mildly Bullish"
    elif s>=-5: return "Neutral"
    elif s>=-25: return "Mildly Bearish"
    elif s>=-60: return "Bearish"
    else: return "Very Bearish"

def classify_impact(entries):
    c = " ".join(e["headline"] for e in entries).lower()
    s = sum(1 for kw in SHORT_TERM_KEYWORDS if kw in c); l = sum(1 for kw in LONG_TERM_KEYWORDS if kw in c)
    if s>0 and l>0: return "Both"
    elif l>0: return "Long-term"
    elif s>0: return "Short-term"
    return "Short-term"

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
    t = SOURCE_SEARCH_URLS.get(sl, ""); return t.replace("{ticker}", tk) if t else ""

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

def load_tickers():
    if os.path.exists(TICKERS_FILE):
        try:
            df = pd.read_csv(TICKERS_FILE); df.columns = df.columns.str.strip()
            if 'Ticker' not in df.columns: df.rename(columns={df.columns[0]:'Ticker'}, inplace=True)
            tks = [t.replace('.NS','') for t in df['Ticker'].dropna().str.strip().str.upper().tolist() if t]
            s = set(); u = []
            for t in tks:
                if t not in s: s.add(t); u.append(t)
            sm = {}
            if 'Sector' in df.columns:
                for _, r in df.iterrows():
                    tk = str(r['Ticker']).strip().upper().replace('.NS',''); sc = str(r.get('Sector','')).strip()
                    if tk and sc: sm[tk] = sc
            print(f"Loaded {len(u)} tickers from {TICKERS_FILE}"); return u, sm
        except Exception as e: print(f"Error: {e}")
    return ["RELIANCE","TCS","INFY","HDFCBANK","SBIN","ICICIBANK","ITC"], {}

def score_single_headline(hl):
    if not hl: return 0.0
    try:
        i = tokenizer([hl], padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad(): o = model(**i)
        p = torch.nn.functional.softmax(o.logits, dim=-1)
        return (p[0][0].item() - p[0][1].item()) * 100.0
    except: return 0.0

def compute_aggregated_score(entries):
    if not entries: return 0.0, 0
    tw=0.0; ws=0.0
    for e in entries: r=score_single_headline(e["headline"]); w=e.get("weight",1.0); ws+=r*w; tw+=w
    if tw==0: return 0.0, 0
    s = ws/tw
    return round(s,1), 1 if s>5 else (-1 if s<-5 else 0)

def get_live_price_return(tk):
    try:
        h = yf.Ticker(f"{tk}.NS").history(period="5d")
        if len(h)>=2: return round(((h['Close'].iloc[-1]-h['Close'].iloc[-2])/h['Close'].iloc[-2])*100, 2)
    except: pass
    return 0.0

def build_news_cache(tl):
    cache={}; st={"sc":0,"iw":0,"rp":0,"nn":0,"kp":0,"sl":0}
    for sk, url in ALL_FEEDS.items():
        print(f"Fetching {sk}..."); feed=fetch_rss_with_headers(url,sk)
        if not feed or not feed.entries: print(f"   {sk}: No entries"); continue
        mc=0; rp=0; stc=0; nc=0
        for entry in feed.entries:
            title=entry.get("title",""); desc=entry.get("description",entry.get("summary",""))
            ft=f"{title} {desc}".upper(); mt=match_ticker_in_text(ft,tl)
            if not mt or not title.strip(): continue
            st["sc"]+=1; di,pt=extract_pub_datetime_full(entry)
            if not is_in_news_window(di): stc+=1; st["sl"]+=1; continue
            st["iw"]+=1; hl=title.strip().replace(",",";"); nu=extract_news_url(entry)
            hc,_=classify_headline(hl)
            if hc=="reporting": rp+=1; st["rp"]+=1; continue
            if sk in NSE_SOURCES:
                if classify_nse_headline(hl)=="noise":
                    nc+=1; st["nn"]+=1; fk=f"_filing_{mt}"
                    if fk not in cache: cache[fk]=[]
                    cache[fk].append({"headline":hl,"source":sk,"pub_time":pt,"weight":0.0,"nse_class":"noise","news_url":nu})
                    continue
            w=SOURCE_WEIGHTS.get(sk,1.0); ex=cache.get(mt,[])
            if not any(e["headline"].lower()==hl.lower() for e in ex):
                if mt not in cache: cache[mt]=[]
                cache[mt].append({"headline":hl,"source":sk,"pub_time":pt,"weight":w,"nse_class":"actionable" if sk in NSE_SOURCES else "news","news_url":nu}); mc+=1; st["kp"]+=1
        notes=[]
        if stc: notes.append(f"{stc} outside window")
        if rp: notes.append(f"{rp} reporting")
        if nc: notes.append(f"{nc} NSE noise")
        print(f"   {sk}: {mc} predictive from {len(feed.entries)}"+(f" ({', '.join(notes)})" if notes else ""))
        time.sleep(0.3)
    rl={k for k in cache if not k.startswith("_filing_")}
    print(f"\nCache: {len(rl)}/{len(tl)} predictive | Scanned:{st['sc']} Reporting:{st['rp']} NSEnoise:{st['nn']} Kept:{st['kp']}")
    return cache

def get_yfinance_news(tk, ar=None):
    try:
        news = getattr(yf.Ticker(f"{tk}.NS"), 'news', None)
        if news and isinstance(news, list):
            for item in news:
                if not isinstance(item, dict): continue
                hl = item.get("title",item.get("headline",""))
                if not hl: continue
                hc,_ = classify_headline(hl, ar)
                if hc=="reporting": continue
                nu = item.get("link",item.get("url",""))
                pts = item.get("providerPublishTime") or item.get("publish_time")
                pt=""; di=None
                if pts:
                    try: di=datetime.fromtimestamp(int(pts),tz=IST); pt=di.strftime("%d %b %Y %I:%M %p")
                    except: pass
                if is_in_news_window(di): return hl.replace(",",";"), pt, nu
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
                hc,_ = classify_headline(hl, ar)
                if hc=="reporting": continue
                return hl.replace(",",";"), pt, extract_news_url(entry)
    except: pass
    return None, "", ""

def get_all_fresh_news(tk, cache, ar=None):
    entries = []
    if tk in cache: entries.extend(cache[tk])
    hl,pt,nu = get_yfinance_news(tk, ar)
    if hl and not any(e["headline"].lower()==hl.lower() for e in entries):
        entries.append({"headline":hl,"source":"yfinance","pub_time":pt,"weight":1.0,"nse_class":"news","news_url":nu})
    if len(entries) < 3:
        hl,pt,nu = get_google_news(tk, ar)
        if hl and not any(e["headline"].lower()==hl.lower() for e in entries):
            entries.append({"headline":hl,"source":"google","pub_time":pt,"weight":1.0,"nse_class":"news","news_url":nu})
    if ar is not None and entries:
        entries = [e for e in entries if classify_headline(e["headline"], ar)[0]!="reporting"]
    fe = cache.get(f"_filing_{tk}", [])
    if entries: return entries, "actionable", fe
    elif fe: return fe, "filing_only", fe
    else: return [], "no_news", []

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
        tk=row["Ticker"]; td=row["Forecast_Direction"]; ts=row["Forecast_Score"]; trr=row["Actual_Return_Pct"]
        th = pd.DataFrame()
        if not hdf.empty and 'Ticker' in hdf.columns:
            th = hdf[(hdf['Ticker']==tk)&(hdf['Date']!=TODAY_IST)].sort_values('Date',ascending=False)
        sd=1; sr=trr
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


# ═══════════════════════════════════════════════════════════════
# NEW: MULTI-LAYER SCORING ENGINE
# ═══════════════════════════════════════════════════════════════

def call_gemini(prompt, retries=2):
    """Call Gemini Flash API with retry and rate-limit handling"""
    if not GEMINI_API_KEY:
        return None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200}
                },
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            if resp.status_code == 429:
                time.sleep(6)
                continue
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            jm = re.search(r'\{[^}]+\}', text)
            if jm:
                return json.loads(jm.group())
            return None
        except Exception:
            if attempt < retries:
                time.sleep(3)
            continue
    return None


def load_stock_data_for_scoring():
    """Load stock_data.csv for technical scoring"""
    try:
        if os.path.exists(STOCK_DATA_FILE):
            df = pd.read_csv(STOCK_DATA_FILE)
            if 'Ticker' in df.columns:
                print(f"  → Loaded stock_data.csv: {df['Ticker'].nunique()} tickers, {len(df)} rows")
                return df
    except Exception as e:
        print(f"  → Could not load stock_data.csv: {e}")
    print("  → stock_data.csv not found — technical scores will be 0")
    return pd.DataFrame()


def get_technical_score(ticker, stock_df):
    """Score technical position from stock_data.csv indicators"""
    if stock_df is None or stock_df.empty:
        return {"score": 0, "signals": []}

    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty:
        return {"score": 0, "signals": []}

    last = tk_data.iloc[-1]
    score = 0
    signals = []

    # RSI
    rsi = last.get('RSI_14')
    if pd.notna(rsi):
        rsi = float(rsi)
        if rsi > 75: score -= 30; signals.append(f"RSI overbought({rsi:.0f})")
        elif rsi > 65: score -= 15; signals.append(f"RSI elevated({rsi:.0f})")
        elif rsi < 25: score += 30; signals.append(f"RSI oversold({rsi:.0f})")
        elif rsi < 35: score += 15; signals.append(f"RSI depressed({rsi:.0f})")

    # Bollinger Band Flag
    bb = str(last.get('BB_Flag', '')).strip().upper()
    if bb == 'BBH': score -= 20; signals.append("BB upper band")
    elif bb == 'BBL': score += 20; signals.append("BB lower band")

    # Price vs SMAs
    close = last.get('Close')
    if pd.notna(close):
        close = float(close)
        sma22 = last.get('SMA_22')
        sma52 = last.get('SMA_52')
        sma200 = last.get('SMA_200')
        if pd.notna(sma22):
            if close < float(sma22): score -= 12; signals.append("Below SMA22")
            else: score += 8
        if pd.notna(sma52):
            if close < float(sma52): score -= 10; signals.append("Below SMA52")
        if pd.notna(sma200):
            if close < float(sma200): score -= 20; signals.append("Below SMA200")
            else: score += 10

    # Knoxville Divergence
    knox = str(last.get('Knoxville_Divergence', '')).strip().lower()
    if knox == 'bearish': score -= 15; signals.append("Knox bearish div")
    elif knox == 'bullish': score += 15; signals.append("Knox bullish div")

    # FII/DII momentum burst
    up_true = last.get('up_true')
    if pd.notna(up_true) and int(up_true) == 1:
        score += 15; signals.append("FII/DII momentum")

    return {"score": max(-100, min(100, score)), "signals": signals}


def get_fundamental_data(ticker):
    """Fetch fundamental metrics from yfinance .info"""
    try:
        info = yf.Ticker(f"{ticker}.NS").info
        if not info or not isinstance(info, dict):
            return {}
        return {
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "debt_equity": info.get("debtToEquity"),
            "roe": info.get("returnOnEquity"),
            "rev_growth": info.get("revenueGrowth"),
            "profit_margin": info.get("profitMargins"),
            "op_margin": info.get("operatingMargins"),
            "fcf": info.get("freeCashflow"),
            "current_ratio": info.get("currentRatio"),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", "")
        }
    except Exception:
        return {}


def score_fundamentals_rules(data):
    """Rule-based fundamental scoring (no API needed)"""
    score = 0
    concerns = []

    roe = data.get("roe")
    if isinstance(roe, (int, float)):
        if roe > 0.20: score += 25
        elif roe > 0.12: score += 10
        elif roe < 0.05: score -= 25; concerns.append("Low ROE")

    de = data.get("debt_equity")
    if isinstance(de, (int, float)):
        if de > 200: score -= 30; concerns.append("Very high debt")
        elif de > 100: score -= 15; concerns.append("High debt")
        elif de < 30: score += 15

    pm = data.get("profit_margin")
    if isinstance(pm, (int, float)):
        if pm > 0.20: score += 20
        elif pm > 0.10: score += 10
        elif pm < 0.03: score -= 25; concerns.append("Thin margins")
        elif pm < 0: score -= 35; concerns.append("Negative margins")

    om = data.get("op_margin")
    if isinstance(om, (int, float)):
        if om < 0.05 and om >= 0: score -= 10; concerns.append("Weak operating margin")

    rg = data.get("rev_growth")
    if isinstance(rg, (int, float)):
        if rg > 0.15: score += 20
        elif rg > 0.05: score += 10
        elif rg < -0.05: score -= 25; concerns.append("Revenue declining")
        elif rg < 0: score -= 10; concerns.append("Revenue flat/down")

    cr = data.get("current_ratio")
    if isinstance(cr, (int, float)):
        if cr < 0.8: score -= 15; concerns.append("Liquidity risk")

    pe = data.get("pe")
    fpe = data.get("forward_pe")
    if isinstance(pe, (int, float)) and isinstance(fpe, (int, float)):
        if fpe > pe * 1.2: score -= 10; concerns.append("Earnings expected to slow")
        elif fpe < pe * 0.8: score += 10

    return {"score": max(-100, min(100, score)), "concern": "; ".join(concerns) if concerns else "Fundamentals OK"}


def score_fundamentals_gemini(ticker, data):
    """AI fundamental scoring via Gemini Flash"""
    def fmt(v):
        if v is None: return "N/A"
        if isinstance(v, float): return f"{v:.4f}" if abs(v) < 1 else f"{v:.2f}"
        return str(v)

    prompt = f"""You are a strict fundamental equity analyst for Indian stocks.
Score this stock ONLY on business health. IGNORE news sentiment and stock price.

Ticker: {ticker} (NSE India)
Trailing PE: {fmt(data.get('pe'))}
Forward PE: {fmt(data.get('forward_pe'))}
Debt/Equity: {fmt(data.get('debt_equity'))}
ROE: {fmt(data.get('roe'))}
Revenue Growth: {fmt(data.get('rev_growth'))}
Profit Margins: {fmt(data.get('profit_margin'))}
Operating Margins: {fmt(data.get('op_margin'))}
Free Cash Flow: {fmt(data.get('fcf'))}
Current Ratio: {fmt(data.get('current_ratio'))}
Sector: {data.get('sector','N/A')}

Score -100 (very weak) to +100 (very strong).
Focus: margin quality, debt health, earnings growth, cash generation.
Return ONLY JSON: {{"score": <integer>, "concern": "<max 10 words>"}}"""

    result = call_gemini(prompt)
    if result and "score" in result:
        return {"score": max(-100, min(100, int(result["score"]))), "concern": str(result.get("concern", ""))}
    return None


def get_fundamental_score(ticker):
    """Get fundamental score — Gemini if available, else rule-based"""
    data = get_fundamental_data(ticker)
    if not data:
        return {"score": 0, "concern": "No data", "sector": "", "industry": ""}

    sector = data.get("sector", "")
    industry = data.get("industry", "")

    if GEMINI_API_KEY:
        result = score_fundamentals_gemini(ticker, data)
        if result:
            result["sector"] = sector
            result["industry"] = industry
            time.sleep(GEMINI_DELAY)
            return result

    result = score_fundamentals_rules(data)
    result["sector"] = sector
    result["industry"] = industry
    return result


def get_nifty_change():
    """Get Nifty 50 recent performance for macro context"""
    try:
        h = yf.Ticker("^NSEI").history(period="5d")
        if len(h) >= 2:
            chg = round(((h['Close'].iloc[-1] - h['Close'].iloc[0]) / h['Close'].iloc[0]) * 100, 2)
            print(f"  → Nifty 5d change: {chg:+.2f}%")
            return chg
    except Exception:
        pass
    print("  → Could not fetch Nifty data")
    return 0.0


def get_macro_scores(sectors, nifty_change):
    """Get macro/flow scores per sector — Gemini if available, else rule-based"""
    macro_cache = {}
    unique_sectors = list(set(s for s in sectors if s and s.strip()))

    if not unique_sectors:
        return macro_cache

    if not GEMINI_API_KEY:
        base = 15 if nifty_change > 1.0 else (5 if nifty_change > 0.3 else (-5 if nifty_change > -0.3 else (-15 if nifty_change > -1.0 else -25)))
        for sector in unique_sectors:
            macro_cache[sector] = {"score": base, "context": f"Nifty {nifty_change:+.1f}% (rule-based)"}
        print(f"  → {len(unique_sectors)} sectors scored (rule-based, Nifty {nifty_change:+.1f}%)")
        return macro_cache

    print(f"  → Scoring {len(unique_sectors)} sectors via Gemini...")
    for sector in unique_sectors:
        prompt = f"""You are a macro analyst for Indian equities.
Score the CURRENT market environment for the "{sector}" sector in India.

Nifty 50 recent 5-day change: {nifty_change:+.2f}%

Consider: FII/DII institutional flows, sector rotation trends, global cues,
RBI monetary policy, commodity/crude impact, rupee movement, government policy.

Score -100 (very hostile environment) to +100 (very supportive).
Return ONLY JSON: {{"score": <integer>, "context": "<max 10 words>"}}"""

        result = call_gemini(prompt)
        if result and "score" in result:
            macro_cache[sector] = {"score": max(-100, min(100, int(result["score"]))), "context": str(result.get("context", ""))}
        else:
            base = 10 if nifty_change > 0.5 else (-10 if nifty_change < -0.5 else 0)
            macro_cache[sector] = {"score": base, "context": f"Nifty {nifty_change:+.1f}%"}
        time.sleep(GEMINI_DELAY)

    return macro_cache


def compute_composite(sentiment, fundamental, technical, macro):
    """Compute weighted composite score from all 4 layers"""
    w = COMPOSITE_WEIGHTS
    comp = (sentiment * w["sentiment"]) + (fundamental * w["fundamental"]) + (technical * w["technical"]) + (macro * w["macro"])
    comp = round(comp, 1)
    if comp > 12: direction = 1
    elif comp < -12: direction = -1
    else: direction = 0
    return {"score": comp, "direction": direction}


def classify_composite_severity(s):
    """Severity label for composite score"""
    if s >= 40: return "Strong Buy"
    elif s >= 20: return "Buy"
    elif s >= 8: return "Mild Buy"
    elif s >= -8: return "Neutral"
    elif s >= -20: return "Mild Sell"
    elif s >= -40: return "Sell"
    else: return "Strong Sell"


# ═══════════════════════════════════════════════════════════════
# MAIN ENGINE
# ═══════════════════════════════════════════════════════════════

def execute_sentiment_engine():
    tl, sm = load_tickers(); total = len(tl)
    print(f"PREDICTIVE Engine - {total} tickers | {TODAY_IST}")
    print(f"News: {NEWS_START_DATE} to {NEWS_CUTOFF_TIME.strftime('%I:%M %p')} | {len(ALL_FEEDS)} feeds | Reporting filtered")
    print("=" * 110)

    # ── PHASE 1: Fetch predictive news ──
    print("\nPHASE 1: Fetching predictive news (D-3 to 2hr cutoff)...")
    print("-" * 110)
    nc = build_news_cache(tl)
    print("-" * 110)

    # ── PHASE 2: FinBERT scoring ──
    print(f"\nPHASE 2: FinBERT scoring (circular headlines filtered)...")
    print("-" * 110)
    scored=[]; filing=[]; nonews=[]; ha=0; hd=0; td2=0
    for idx, tk in enumerate(tl, 1):
        ret = get_live_price_return(tk)
        ad = 1 if ret>0.25 else (-1 if ret<-0.25 else 0)
        entries, cls, fe = get_all_fresh_news(tk, nc, ret)
        if cls=="no_news":
            nonews.append({"Ticker":tk,"Sector":sm.get(tk,""),"Latest_Headline":"","News_Source":"","News_Time":"","News_URL":"","Headline_Count":0,"Forecast_Score":0.0,"Forecast_Direction":0,"Actual_Direction":ad,"Actual_Return_Pct":ret,"Severity":"No News","Impact":"","Streak_Days":0,"Streak_Return":0.0,"Momentum":"","Signal_Quality":"No News"})
            continue
        if cls=="filing_only":
            p = fe[0] if fe else {}; nu = p.get("news_url","") or get_source_search_url("NSE Official",tk)
            filing.append({"Ticker":tk,"Sector":sm.get(tk,""),"Latest_Headline":p.get("headline",""),"News_Source":"NSE Official","News_Time":p.get("pub_time","").replace(",",""),"News_URL":nu,"Headline_Count":len(fe),"Forecast_Score":0.0,"Forecast_Direction":0,"Actual_Direction":ad,"Actual_Return_Pct":ret,"Severity":"Filing Only","Impact":"","Streak_Days":0,"Streak_Return":0.0,"Momentum":"","Signal_Quality":"Filing Only"})
            continue
        pe = max(entries, key=lambda e: e["weight"]); ps=pe["source"]; pt=pe["pub_time"]; pu=pe.get("news_url","")
        if not pu: pu = get_source_search_url(SOURCE_LABELS.get(ps,""), tk)
        if ps in ("yfinance","google"): time.sleep(0.3)
        score, direction = compute_aggregated_score(entries)
        sev = classify_severity(score); imp = classify_impact(entries)
        hit = direction==ad
        if hit: ha+=1
        if direction!=0: td2+=1; (hd:=hd+1) if hit else None
        ab = abs(score)
        q = "High Conviction" if ab>=60 else ("Moderate" if ab>=25 else ("Weak" if ab>=5 else "Neutral"))
        usrc = list(dict.fromkeys(SOURCE_LABELS.get(e["source"],e["source"]) for e in entries))
        dm={1:"BULL",-1:"BEAR",0:"NEUT"}; hc=len(entries); ht=f"[{hc}h]" if hc>=2 else ""
        print(f"[{len(scored)+1:3d}] {tk:<14s} {dm.get(direction,'?'):4s} {sev[:12]:14s} Score:{score:+6.1f} Ret:{ret:+6.2f}% {imp:10s} {'HIT' if hit else 'MISS'} {ht}")
        scored.append({"Ticker":tk,"Sector":sm.get(tk,""),"Latest_Headline":pe["headline"],"News_Source":" | ".join(usrc),"News_Time":pt.replace(",","") if pt else "","News_URL":pu,"Headline_Count":len(entries),"Forecast_Score":score,"Forecast_Direction":direction,"Actual_Direction":ad,"Actual_Return_Pct":ret,"Severity":sev,"Impact":imp,"Signal_Quality":q})

    # ── PHASE 3: Multi-layer analysis ──
    print(f"\nPHASE 3: Multi-layer analysis ({len(scored)} scored tickers)...")
    print("-" * 110)

    # 3a: Load stock data for technical scoring
    print("Loading stock data for technical scoring...")
    stock_df = load_stock_data_for_scoring()

    # 3b: Technical scores for ALL rows
    print("Computing technical scores...")
    tech_count = 0
    for row in scored + filing + nonews:
        tech = get_technical_score(row["Ticker"], stock_df)
        row["Technical_Score"] = tech["score"]
        row["Tech_Signals"] = " | ".join(tech["signals"]) if tech["signals"] else ""
        if tech["score"] != 0: tech_count += 1
    print(f"  → {tech_count} tickers with non-zero technical score")

    # 3c: Fundamental scores for SCORED tickers
    print(f"Computing fundamental scores ({'Gemini' if GEMINI_API_KEY else 'rule-based'})...")
    sectors_found = {}
    for i, row in enumerate(scored):
        tk = row["Ticker"]
        fund = get_fundamental_score(tk)
        row["Fundamental_Score"] = fund["score"]
        row["Fund_Concern"] = fund.get("concern", "")
        yf_sector = fund.get("sector", "") or fund.get("industry", "") or sm.get(tk, "")
        row["_sector_yf"] = yf_sector
        if yf_sector: sectors_found[tk] = yf_sector
        fc_tag = f"Fund:{fund['score']:+d}" + (f" ({fund.get('concern','')})" if fund.get("concern","") and fund["concern"] != "Fundamentals OK" else "")
        print(f"  [{i+1:3d}] {tk:<14s} {fc_tag}")
    # defaults for non-scored
    for row in filing + nonews:
        row["Fundamental_Score"] = 0
        row["Fund_Concern"] = ""
        row["_sector_yf"] = ""

    # 3d: Macro scores per sector
    print("Fetching Nifty 50 performance...")
    nifty_chg = get_nifty_change()
    all_sectors = set(sectors_found.values())
    print(f"Computing macro context ({len(all_sectors)} sectors)...")
    macro_cache = get_macro_scores(all_sectors, nifty_chg)
    for row in scored:
        sector = row.get("_sector_yf", "")
        macro = macro_cache.get(sector, {"score": 0, "context": ""})
        row["Macro_Score"] = macro["score"]
        row["Macro_Context"] = macro.get("context", "")
    for row in filing + nonews:
        row["Macro_Score"] = 0
        row["Macro_Context"] = ""

    # 3e: Composite scoring
    print("\nComputing composite signals...")
    print("-" * 110)
    cha = 0; chd = 0; ctd = 0
    for row in scored:
        comp = compute_composite(row["Forecast_Score"], row["Fundamental_Score"], row["Technical_Score"], row["Macro_Score"])
        row["Composite_Score"] = comp["score"]
        row["Composite_Direction"] = comp["direction"]
        row["Composite_Severity"] = classify_composite_severity(comp["score"])
        # composite accuracy
        c_hit = comp["direction"] == row["Actual_Direction"]
        if c_hit: cha += 1
        if comp["direction"] != 0: ctd += 1; (chd := chd + 1) if c_hit else None
        # log
        dm2 = {1: "BULL", -1: "BEAR", 0: "NEUT"}
        sent_dir = dm2.get(row["Forecast_Direction"], "?")
        comp_dir = dm2.get(comp["direction"], "?")
        corrected = " ← CORRECTED" if row["Forecast_Direction"] != comp["direction"] else ""
        print(f"  [{scored.index(row)+1:3d}] {row['Ticker']:<14s} Sent:{row['Forecast_Score']:+6.1f}({sent_dir}) Fund:{row['Fundamental_Score']:+4d} Tech:{row['Technical_Score']:+4d} Macro:{row['Macro_Score']:+4d} → Comp:{comp['score']:+6.1f} {comp_dir} {'HIT' if c_hit else 'MISS'}{corrected}")

    # defaults for non-scored
    for row in filing + nonews:
        row["Composite_Score"] = 0.0
        row["Composite_Direction"] = 0
        row["Composite_Severity"] = ""

    # cleanup temp field
    for row in scored + filing + nonews:
        row.pop("_sector_yf", None)

    # ── PHASE 4: Streaks ──
    print(f"\nPHASE 4: Streaks for {len(scored)} tickers...")
    print("-" * 110)
    hdf = load_history(); streaks = calculate_streaks(hdf, scored)
    for row in scored:
        s = streaks.get(row["Ticker"],{})
        row["Streak_Days"]=s.get("Streak_Days",0); row["Streak_Return"]=s.get("Streak_Return",0.0); row["Momentum"]=s.get("Momentum","Neutral")

    # ── OUTPUT ──
    all_rows = scored + filing + nonews
    pd.DataFrame(all_rows).to_csv(DATA_FILE, index=False)
    save_to_history(scored)

    sc=len(scored); fc=len(filing); nc2=len(nonews)
    bull=sum(1 for r in scored if r["Forecast_Direction"]==1)
    bear=sum(1 for r in scored if r["Forecast_Direction"]==-1)
    neut=sum(1 for r in scored if r["Forecast_Direction"]==0)
    hra=(ha/sc)*100 if sc>0 else 0; hrd=(hd/td2)*100 if td2>0 else 0
    hcr=[r for r in scored if r["Signal_Quality"]=="High Conviction"]
    hch=sum(1 for r in hcr if r["Forecast_Direction"]==r["Actual_Direction"])
    hcra=(hch/len(hcr))*100 if hcr else 0

    chra=(cha/sc)*100 if sc>0 else 0; chrd=(chd/ctd)*100 if ctd>0 else 0
    chcr=[r for r in scored if abs(r.get("Composite_Score",0))>=25]
    chchh=sum(1 for r in chcr if r.get("Composite_Direction",0)==r["Actual_Direction"])
    chchra=(chchh/len(chcr))*100 if chcr else 0

    corrected_count = sum(1 for r in scored if r["Forecast_Direction"] != r.get("Composite_Direction", r["Forecast_Direction"]))

    comp_bull = sum(1 for r in scored if r.get("Composite_Direction",0)==1)
    comp_bear = sum(1 for r in scored if r.get("Composite_Direction",0)==-1)
    comp_neut = sum(1 for r in scored if r.get("Composite_Direction",0)==0)

    print("\n" + "=" * 110)
    print(f"data.csv | {TODAY_IST} | MULTI-LAYER ENGINE | {len(ALL_FEEDS)} RSS feeds")
    print(f"TICKERS: {sc} scored | {fc} filing-only | {nc2} no news")
    print()
    print(f"SENTIMENT-ONLY ACCURACY (Layer 1: FinBERT):")
    print(f"  Overall:         {ha}/{sc} = {hra:.1f}%")
    print(f"  Directional:     {hd}/{td2} = {hrd:.1f}%")
    print(f"  High Conviction: {hch}/{len(hcr)} = {hcra:.1f}%")
    print(f"  Signals: Bull:{bull} Bear:{bear} Neutral:{neut}")
    print()
    print(f"COMPOSITE ACCURACY (Sentiment + Fundamental + Technical + Macro):")
    print(f"  Overall:         {cha}/{sc} = {chra:.1f}%")
    print(f"  Directional:     {chd}/{ctd} = {chrd:.1f}%")
    print(f"  High Conviction: {chchh}/{len(chcr)} = {chchra:.1f}%")
    print(f"  Signals: Bull:{comp_bull} Bear:{comp_bear} Neutral:{comp_neut}")
    print(f"  Corrected:       {corrected_count} signals flipped from sentiment-only")
    print()
    delta_o = chra - hra; delta_d = chrd - hrd
    print(f"IMPROVEMENT (Composite vs Sentiment-only):")
    print(f"  Overall:     {delta_o:+.1f}% ({hra:.1f}% → {chra:.1f}%)")
    print(f"  Directional: {delta_d:+.1f}% ({hrd:.1f}% → {chrd:.1f}%)")
    print("=" * 110)


if __name__ == "__main__":
    execute_sentiment_engine()
