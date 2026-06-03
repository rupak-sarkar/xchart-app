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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_NAME}:generateContent"
GEMINI_DELAY = 4
if GEMINI_API_KEY:
    print(f"Gemini API: enabled for macro ({GEMINI_MODEL_NAME})")
else:
    print("Gemini API: not configured → rule-based macro")

WEIGHTS_NEWS = {"sentiment": 0.45, "technical": 0.35, "macro": 0.15, "fundamental": 0.05}
WEIGHTS_NO_NEWS = {"technical": 0.70, "macro": 0.30}
print(f"Weights (news):    Sent={WEIGHTS_NEWS['sentiment']:.0%} Tech={WEIGHTS_NEWS['technical']:.0%} Macro={WEIGHTS_NEWS['macro']:.0%} Fund={WEIGHTS_NEWS['fundamental']:.0%}")
print(f"Weights (no-news): Tech={WEIGHTS_NO_NEWS['technical']:.0%} Macro={WEIGHTS_NO_NEWS['macro']:.0%}")

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
# HEADLINE + NEWS FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def classify_headline(headline, actual_return=None):
    text = headline.lower(); words = set(re.findall(r'[a-z]+', text))
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
# MULTI-LAYER SCORING ENGINE (v3.1)
# ═══════════════════════════════════════════════════════════════

def call_gemini(prompt, retries=2):
    if not GEMINI_API_KEY: return None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.1,"maxOutputTokens":200}},
                headers={"Content-Type":"application/json"}, timeout=30)
            if resp.status_code == 429: time.sleep(6); continue
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            jm = re.search(r'\{[^}]+\}', text)
            if jm: return json.loads(jm.group())
            return None
        except Exception:
            if attempt < retries: time.sleep(3)
            continue
    return None


def load_stock_data_for_scoring():
    try:
        if os.path.exists(STOCK_DATA_FILE):
            df = pd.read_csv(STOCK_DATA_FILE)
            if 'Ticker' in df.columns:
                df['Ticker'] = df['Ticker'].astype(str).str.replace('.NS','',regex=False).str.strip().str.upper()
                print(f"  → Loaded stock_data.csv: {df['Ticker'].nunique()} tickers, {len(df)} rows")
                print(f"  → Columns: {', '.join(df.columns[:20])}...")
                key_cols = ['RSI_14','BB_Flag','SMA_22','SMA_50','SMA_52','SMA_200','Knoxville_Divergence','up_true','Close']
                found = [c for c in key_cols if c in df.columns]
                missing = [c for c in key_cols if c not in df.columns]
                print(f"  → Found: {found}")
                if missing: print(f"  → Missing: {missing}")
                return df
    except Exception as e:
        print(f"  → Could not load stock_data.csv: {e}")
    print("  → stock_data.csv not found")
    return pd.DataFrame()


# ── FIX 2: Scan ALL rows for sector ──
def get_sector_from_stock_data(ticker, stock_df):
    """Get Industry/sector — scan all rows for non-null value"""
    if stock_df is None or stock_df.empty: return ""
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty: return ""
    for cn in ['Industry', 'industry', 'Sector', 'sector']:
        if cn not in tk_data.columns: continue
        vals = tk_data[cn].dropna().astype(str).str.strip()
        vals = vals[vals != '']
        if len(vals) > 0:
            return vals.iloc[-1]
    return ""


# ── FIX 1: Technical with backward scan ──
def get_technical_score(ticker, stock_df, debug=False):
    """Score technical position — scans backward for BB_Flag, Knox, up_true"""
    if stock_df is None or stock_df.empty:
        return {"score": 0, "signals": []}
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty:
        if debug: print(f"    DEBUG {ticker}: not found in stock_data")
        return {"score": 0, "signals": []}
    valid = tk_data[tk_data['Close'].notna()]
    if valid.empty:
        if debug: print(f"    DEBUG {ticker}: no valid Close rows")
        return {"score": 0, "signals": []}

    last = valid.iloc[-1]
    score = 0; signals = []

    def val(col_names):
        if isinstance(col_names, str): col_names = [col_names]
        for cn in col_names:
            if cn in last.index:
                v = last[cn]
                try:
                    if pd.notna(v): return v
                except: pass
        return None

    def val_scan(col_names, rows=5):
        """Scan backward up to N rows for a non-null value"""
        if isinstance(col_names, str): col_names = [col_names]
        for cn in col_names:
            if cn not in valid.columns: continue
            for i in range(1, min(rows + 1, len(valid) + 1)):
                v = valid.iloc[-i].get(cn) if cn in valid.iloc[-i].index else None
                try:
                    if v is not None and pd.notna(v) and str(v).strip() != '': return v
                except: pass
        return None

    # RSI
    rsi = val(['RSI_14', 'RSI', 'rsi_14'])
    if debug:
        print(f"    DEBUG {ticker}: RSI={rsi}, Close={val('Close')}, SMA22={val('SMA_22')}, BB={val_scan('BB_Flag',3)}, Knox={val_scan('Knoxville_Divergence',5)}, up={val_scan('up_true',3)}")
    if rsi is not None:
        rsi = float(rsi)
        if rsi > 75: score -= 30; signals.append(f"RSI overbought({rsi:.0f})")
        elif rsi > 65: score -= 15; signals.append(f"RSI elevated({rsi:.0f})")
        elif rsi < 25: score += 30; signals.append(f"RSI oversold({rsi:.0f})")
        elif rsi < 35: score += 15; signals.append(f"RSI depressed({rsi:.0f})")

    # BB Flag — scan backward 3 rows
    bb = val_scan(['BB_Flag', 'bb_flag'], rows=3)
    if bb is not None:
        bb = str(bb).strip().upper()
        if bb == 'BBH': score -= 20; signals.append("BB upper band")
        elif bb == 'BBL': score += 20; signals.append("BB lower band")

    # Price vs SMAs
    close = val(['Close', 'close'])
    if close is not None:
        close = float(close)
        sma22 = val(['SMA_22', 'sma_22', 'SMA22'])
        sma50 = val(['SMA_50', 'SMA_52', 'sma_50', 'sma_52'])
        sma200 = val(['SMA_200', 'sma_200', 'SMA200'])
        if sma22 is not None:
            if close < float(sma22): score -= 12; signals.append("Below SMA22")
            else: score += 8
        if sma50 is not None:
            if close < float(sma50): score -= 10; signals.append("Below SMA50")
        if sma200 is not None:
            if close < float(sma200): score -= 20; signals.append("Below SMA200")
            else: score += 10

    # Knoxville — scan backward 5 rows
    knox = val_scan(['Knoxville_Divergence', 'Knoxville', 'knoxville_divergence'], rows=5)
    if knox is not None:
        knox = str(knox).strip().lower()
        if knox in ('bearish', 'bear'): score -= 15; signals.append("Knox bearish div")
        elif knox in ('bullish', 'bull'): score += 15; signals.append("Knox bullish div")

    # FII/DII — scan backward 3 rows
    up = val_scan(['up_true', 'Up_True', 'UP_TRUE'], rows=3)
    if up is not None:
        try:
            if int(float(up)) == 1: score += 15; signals.append("FII/DII momentum")
        except: pass

    return {"score": max(-100, min(100, score)), "signals": signals}


def score_fundamentals_rules(ticker, stock_df):
    """Lightweight valuation from stock_data.csv — no API call"""
    if stock_df is None or stock_df.empty:
        return {"score": 0, "concern": ""}
    tk_data = stock_df[stock_df['Ticker'] == ticker]
    if tk_data.empty:
        return {"score": 0, "concern": ""}
    last = tk_data.iloc[-1]
    score = 0; concerns = []
    def val(names):
        if isinstance(names, str): names = [names]
        for n in names:
            if n in last.index:
                v = last[n]
                try:
                    if pd.notna(v): return float(v)
                except: pass
        return None
    de = val(['Debt_Eq','debt_equity','Debt_Equity','DebtToEquity'])
    if de is not None:
        if de > 200: score -= 20; concerns.append("Very high debt")
        elif de > 100: score -= 10; concerns.append("High debt")
        elif de < 30: score += 5
    return {"score": max(-100, min(100, score)), "concern": "; ".join(concerns) if concerns else ""}


def get_nifty_change():
    try:
        h = yf.Ticker("^NSEI").history(period="5d")
        if len(h) >= 2:
            chg = round(((h['Close'].iloc[-1] - h['Close'].iloc[0]) / h['Close'].iloc[0]) * 100, 2)
            print(f"  → Nifty 5d change: {chg:+.2f}%")
            return chg
    except: pass
    print("  → Could not fetch Nifty data")
    return 0.0


def get_macro_scores(sectors, nifty_change):
    macro_cache = {}
    unique_sectors = list(set(s for s in sectors if s and s.strip()))
    if not unique_sectors: return macro_cache
    if not GEMINI_API_KEY:
        base = 15 if nifty_change > 1.0 else (5 if nifty_change > 0.3 else (-5 if nifty_change > -0.3 else (-15 if nifty_change > -1.0 else -25)))
        for sector in unique_sectors:
            macro_cache[sector] = {"score": base, "context": f"Nifty {nifty_change:+.1f}%"}
        print(f"  → {len(unique_sectors)} sectors scored (rule-based)")
        return macro_cache
    print(f"  → Scoring {len(unique_sectors)} sectors via Gemini...")
    for sector in unique_sectors:
        prompt = f"""You are a macro analyst for Indian equities.
Score the CURRENT short-term market environment for "{sector}" sector in India.
Nifty 50 5-day change: {nifty_change:+.2f}%
Consider: FII/DII flows, sector rotation, global cues, RBI policy, commodity/crude.
Score -100 (very hostile) to +100 (very supportive). Be realistic: most between -30 and +30.
Return ONLY JSON: {{"score": <integer>, "context": "<max 10 words>"}}"""
        result = call_gemini(prompt)
        if result and "score" in result:
            macro_cache[sector] = {"score": max(-100, min(100, int(result["score"]))), "context": str(result.get("context",""))}
        else:
            base = 10 if nifty_change > 0.5 else (-10 if nifty_change < -0.5 else 0)
            macro_cache[sector] = {"score": base, "context": f"Nifty {nifty_change:+.1f}%"}
        time.sleep(GEMINI_DELAY)
    return macro_cache


def compute_composite_news(sentiment, technical, macro, fundamental):
    """Composite for tickers WITH news"""
    w = WEIGHTS_NEWS
    if technical == 0:
        ew = {"sentiment": w["sentiment"] + w["technical"]*0.65, "technical": 0,
              "macro": w["macro"] + w["technical"]*0.2, "fundamental": w["fundamental"] + w["technical"]*0.15}
    else:
        ew = dict(w)
    comp = (sentiment*ew["sentiment"]) + (technical*ew["technical"]) + (macro*ew["macro"]) + (fundamental*ew["fundamental"])
    comp = round(comp, 1)
    d = 1 if comp > 15 else (-1 if comp < -15 else 0)
    return {"score": comp, "direction": d}


# ── FIX 3: Clamped macro for tech-only ──
def compute_composite_no_news(technical, macro):
    """Composite for tickers WITHOUT news — tech-dominant, clamped macro"""
    w = WEIGHTS_NO_NEWS
    clamped_macro = max(-15, min(15, macro))
    comp = (technical * w["technical"]) + (clamped_macro * w["macro"])
    comp = round(comp, 1)
    d = 1 if comp > 15 else (-1 if comp < -15 else 0)
    return {"score": comp, "direction": d}


def classify_composite_severity(s):
    if s >= 40: return "Strong Buy"
    elif s >= 20: return "Buy"
    elif s >= 8: return "Mild Buy"
    elif s >= -8: return "Neutral"
    elif s >= -20: return "Mild Sell"
    elif s >= -40: return "Sell"
    else: return "Strong Sell"


# ═══════════════════════════════════════════════════════════════
# MAIN ENGINE (v3.1)
# ═══════════════════════════════════════════════════════════════

def execute_sentiment_engine():
    tl, sm = load_tickers(); total = len(tl)
    print(f"PREDICTIVE Engine v3.1 - {total} tickers | {TODAY_IST}")
    print(f"News: {NEWS_START_DATE} to {NEWS_CUTOFF_TIME.strftime('%I:%M %p')} | {len(ALL_FEEDS)} feeds | ALL tickers scored")
    print("=" * 110)

    # ── PHASE 1 ──
    print("\nPHASE 1: Fetching predictive news (D-3 to 2hr cutoff)...")
    print("-" * 110)
    nc = build_news_cache(tl)
    print("-" * 110)

    # ── PHASE 2 ──
    print(f"\nPHASE 2: FinBERT scoring (circular headlines filtered)...")
    print("-" * 110)
    scored=[]; filing=[]; nonews=[]; ha=0; hd=0; td2=0
    for idx, tk in enumerate(tl, 1):
        ret = get_live_price_return(tk)
        ad = 1 if ret>0.25 else (-1 if ret<-0.25 else 0)
        entries, cls, fe = get_all_fresh_news(tk, nc, ret)
        base_row = {"Ticker":tk,"Sector":sm.get(tk,""),"Actual_Direction":ad,"Actual_Return_Pct":ret}
        if cls=="no_news":
            nonews.append({**base_row,"Latest_Headline":"","News_Source":"","News_Time":"","News_URL":"","Headline_Count":0,"Forecast_Score":0.0,"Forecast_Direction":0,"Severity":"No News","Impact":"","Streak_Days":0,"Streak_Return":0.0,"Momentum":"","Signal_Quality":"Tech-Scored"})
            continue
        if cls=="filing_only":
            p = fe[0] if fe else {}; nu = p.get("news_url","") or get_source_search_url("NSE Official",tk)
            filing.append({**base_row,"Latest_Headline":p.get("headline",""),"News_Source":"NSE Official","News_Time":p.get("pub_time","").replace(",",""),"News_URL":nu,"Headline_Count":len(fe),"Forecast_Score":0.0,"Forecast_Direction":0,"Severity":"Filing Only","Impact":"","Streak_Days":0,"Streak_Return":0.0,"Momentum":"","Signal_Quality":"Tech-Scored"})
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
        scored.append({**base_row,"Latest_Headline":pe["headline"],"News_Source":" | ".join(usrc),"News_Time":pt.replace(",","") if pt else "","News_URL":pu,"Headline_Count":len(entries),"Forecast_Score":score,"Forecast_Direction":direction,"Severity":sev,"Impact":imp,"Signal_Quality":q})

    # ── PHASE 3 ──
    all_rows = scored + filing + nonews
    print(f"\nPHASE 3: Multi-layer analysis (ALL {len(all_rows)} tickers)...")
    print("-" * 110)

    # 3a: Technical for ALL
    print("Loading stock data...")
    stock_df = load_stock_data_for_scoring()
    print("Computing technical scores for ALL tickers...")
    tech_count = 0
    for i, row in enumerate(all_rows):
        tech = get_technical_score(row["Ticker"], stock_df, debug=(i < 3))
        row["Technical_Score"] = tech["score"]
        row["Tech_Signals"] = " | ".join(tech["signals"]) if tech["signals"] else ""
        if tech["score"] != 0: tech_count += 1
    print(f"  → {tech_count}/{len(all_rows)} tickers with non-zero technical score")

    # 3b: Fundamental (lightweight, from stock_data)
    print("Computing fundamental scores (rule-based from stock_data)...")
    for row in all_rows:
        fund = score_fundamentals_rules(row["Ticker"], stock_df)
        row["Fundamental_Score"] = fund["score"]
        row["Fund_Concern"] = fund.get("concern", "")

    # 3c: Sector mapping + Macro — FIX 2
    print("Building sector map...")
    all_sectors = set()
    sector_count = 0
    for row in all_rows:
        sector = sm.get(row["Ticker"], "") or get_sector_from_stock_data(row["Ticker"], stock_df)
        row["_sector"] = sector
        if sector:
            all_sectors.add(sector)
            sector_count += 1
    print(f"  → {sector_count}/{len(all_rows)} tickers mapped to {len(all_sectors)} sectors")
    if len(all_sectors) <= 5:
        print(f"  → Sectors: {all_sectors}")

    print("Fetching Nifty 50 performance...")
    nifty_chg = get_nifty_change()
    print(f"Computing macro context ({len(all_sectors)} sectors)...")
    macro_cache = get_macro_scores(all_sectors, nifty_chg)
    for row in all_rows:
        macro = macro_cache.get(row.get("_sector",""), {"score": 0, "context": ""})
        row["Macro_Score"] = macro["score"]
        row["Macro_Context"] = macro.get("context", "")

    # 3d: Composite
    print(f"\nComputing composite signals (news: {len(scored)} | tech-only: {len(filing)+len(nonews)})...")
    print("-" * 110)

    cha=0; chd=0; ctd=0
    for row in scored:
        comp = compute_composite_news(row["Forecast_Score"], row["Technical_Score"], row["Macro_Score"], row["Fundamental_Score"])
        row["Composite_Score"] = comp["score"]
        row["Composite_Direction"] = comp["direction"]
        row["Composite_Severity"] = classify_composite_severity(comp["score"])
        c_hit = comp["direction"] == row["Actual_Direction"]
        if c_hit: cha += 1
        if comp["direction"] != 0: ctd += 1; (chd := chd + 1) if c_hit else None
        dm2={1:"BULL",-1:"BEAR",0:"NEUT"}
        corrected = " ← CORRECTED" if row["Forecast_Direction"] != comp["direction"] else ""
        print(f"  [{scored.index(row)+1:3d}] {row['Ticker']:<14s} Sent:{row['Forecast_Score']:+6.1f}({dm2[row['Forecast_Direction']]}) Tech:{row['Technical_Score']:+4d} Macro:{row['Macro_Score']:+4d} Fund:{row['Fundamental_Score']:+4d} → Comp:{comp['score']:+6.1f} {dm2[comp['direction']]} {'HIT' if c_hit else 'MISS'}{corrected}")

    t_bull=0; t_bear=0; t_neut=0; t_hit=0; t_total=0
    for row in filing + nonews:
        comp = compute_composite_no_news(row["Technical_Score"], row["Macro_Score"])
        row["Composite_Score"] = comp["score"]
        row["Composite_Direction"] = comp["direction"]
        row["Composite_Severity"] = classify_composite_severity(comp["score"]) if comp["score"] != 0 else ""
        row["Forecast_Direction"] = 0
        if comp["direction"] == 1: t_bull += 1
        elif comp["direction"] == -1: t_bear += 1
        else: t_neut += 1
        if comp["direction"] == row["Actual_Direction"]: t_hit += 1
        t_total += 1

    for row in all_rows:
        row.pop("_sector", None)

    scored_with_tech = [r for r in filing + nonews if r["Composite_Score"] != 0]
    print(f"\n  Tech-only scored: {len(scored_with_tech)}/{len(filing)+len(nonews)} | Bull:{t_bull} Bear:{t_bear} Neut:{t_neut}")
    if t_total > 0:
        print(f"  Tech-only hit rate: {t_hit}/{t_total} = {(t_hit/t_total)*100:.1f}%")

    # ── PHASE 4 ──
    print(f"\nPHASE 4: Streaks for {len(scored)} tickers...")
    print("-" * 110)
    hdf = load_history(); streaks = calculate_streaks(hdf, scored)
    for row in scored:
        s = streaks.get(row["Ticker"],{})
        row["Streak_Days"]=s.get("Streak_Days",0); row["Streak_Return"]=s.get("Streak_Return",0.0); row["Momentum"]=s.get("Momentum","Neutral")

    # ── OUTPUT ──
    pd.DataFrame(all_rows).to_csv(DATA_FILE, index=False)
    save_to_history(scored)

    sc=len(scored); fc=len(filing); nc2=len(nonews)
    bull=sum(1 for r in scored if r["Forecast_Direction"]==1)
    bear=sum(1 for r in scored if r["Forecast_Direction"]==-1)
    neut=sum(1 for r in scored if r["Forecast_Direction"]==0)
    hra=(ha/sc)*100 if sc>0 else 0; hrd=(hd/td2)*100 if td2>0 else 0
    chra=(cha/sc)*100 if sc>0 else 0; chrd=(chd/ctd)*100 if ctd>0 else 0
    corrected_count = sum(1 for r in scored if r["Forecast_Direction"] != r.get("Composite_Direction", r["Forecast_Direction"]))
    comp_bull = sum(1 for r in scored if r.get("Composite_Direction",0)==1)
    comp_bear = sum(1 for r in scored if r.get("Composite_Direction",0)==-1)
    total_scored = sc + len(scored_with_tech)

    print("\n" + "=" * 110)
    print(f"data.csv | {TODAY_IST} | ENGINE v3.1 | ALL TICKERS SCORED")
    print(f"TICKERS: {sc} news-scored | {fc} filing | {nc2} no-news | {total_scored} total with signals")
    print(f"WEIGHTS: News→ Sent={WEIGHTS_NEWS['sentiment']:.0%} Tech={WEIGHTS_NEWS['technical']:.0%} Macro={WEIGHTS_NEWS['macro']:.0%} Fund={WEIGHTS_NEWS['fundamental']:.0%}")
    print(f"         No-News→ Tech={WEIGHTS_NO_NEWS['technical']:.0%} Macro={WEIGHTS_NO_NEWS['macro']:.0%} (macro clamped ±15)")
    print()
    print(f"SENTIMENT-ONLY ({sc} with news):")
    print(f"  Overall:     {ha}/{sc} = {hra:.1f}%  |  Directional: {hd}/{td2} = {hrd:.1f}%")
    print(f"  Signals: Bull:{bull} Bear:{bear} Neutral:{neut}")
    print()
    print(f"COMPOSITE ({sc} with news):")
    print(f"  Overall:     {cha}/{sc} = {chra:.1f}%  |  Directional: {chd}/{ctd} = {chrd:.1f}%")
    print(f"  Signals: Bull:{comp_bull} Bear:{comp_bear} | Corrected: {corrected_count}")
    print()
    print(f"TECH-ONLY ({t_total} without news):")
    print(f"  Hit rate:    {t_hit}/{t_total} = {(t_hit/t_total)*100:.1f}%" if t_total > 0 else "  No data")
    print(f"  Signals: Bull:{t_bull} Bear:{t_bear} Neutral:{t_neut}")
    delta_d = chrd - hrd
    print(f"\nIMPROVEMENT: Directional {delta_d:+.1f}% ({hrd:.1f}% → {chrd:.1f}%)")
    print("=" * 110)


if __name__ == "__main__":
    execute_sentiment_engine()
