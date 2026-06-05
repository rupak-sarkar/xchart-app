"""All constants, weights, thresholds, feeds, keyword sets"""
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_IST = NOW_IST.strftime("%Y-%m-%d")
TODAY_DATE = NOW_IST.date()
NEWS_START_DATE = TODAY_DATE - timedelta(days=3)
NEWS_CUTOFF_TIME = NOW_IST - timedelta(hours=2)

TICKERS_FILE = "tickers.csv"
HISTORY_FILE = "history.csv"
DATA_FILE = "data.csv"
STOCK_DATA_FILE = "stock_data.csv"

HISTORY_RETENTION_DAYS = 200  # increased for long-term tracking

WEIGHTS_NEWS = {"technical": 0.65, "sentiment": 0.10, "macro": 0.15, "fundamental": 0.10}
WEIGHTS_NO_NEWS = {"technical": 0.75, "macro": 0.15, "fundamental": 0.10}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-IN,en;q=0.9"
}

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

BAD_STRINGS = ('nan', 'none', 'n/a', 'null', '')
