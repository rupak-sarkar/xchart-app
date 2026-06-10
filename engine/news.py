"""RSS fetching, news cache building, yfinance/google news"""
import re, time, json, urllib.parse
import feedparser, requests
from datetime import datetime, timezone, date
from pathlib import Path
from engine.config import (
    IST, NEWS_START_DATE, NEWS_CUTOFF_TIME, BROWSER_HEADERS,
    ALL_CHECK CACHE FIRST — skip all RSS if fresh                     ║    ALL_FEEDS, SOURCE_WEIGHTS, NSE_SOURCES, SOURCE_LABELS, SOURCE_SEARCH_URLS,
    # ╚══════════════════════════════════════════════════════════════════╝
    if _news_cache_fresh():
        cached = _load_news_cache()
        if cached is not None:
            return cached

    # ── FRESH FETCH ──
    cache = {}; st = {"sc": 0, "rp": 0, "nn": 0, "kp": 0}
    source_summary = {}

    for sk, url in ALL_FEEDS.items():
        print(f"Fetching {sk}...")
        feed = fetch_rss_with_headers(url, sk)
        if not feed or not feed.entries:
            print(f"   {sk}: No entries")
            source_summary[sk] = {"predictive": 0, "total": 0, "notes": "No entries"}
            continue
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

        notes_parts = []
        if stc: notes_parts.append(f"{stc} outside window")
        if rp: notes_parts.append(f"{rp} reporting")
        if nc: notes_parts.append(f"{nc} NSE noise")
        notes_str = ", ".join(notes_parts)
        print(f"   {sk}: {mc} predictive from {len(feed.entries)}" + (f" ({notes_str})" if notes_str else ""))
        source_summary[sk] = {"predictive": mc, "total": len(feed.entries), "notes": notes_str}
        time.sleep(0.3)

    rl = {k for k in cache if not k.startswith("_filing_")}
    print(f"\nCache: {len(rl)}/{len(tl)} predictive | Scanned:{st['sc']} Reporting:{st['rp']} NSEnoise:{st['nn']} Kept:{st['kp']}")

    # ╔══════════════════════════════════════════════════════════════════╗
    # ║  SAVE TO CACHE                                                  ║
    # ╚══════════════════════════════════════════════════════════════════╝
    _save_news_cache(cache, source_summary)

    return cache


# ── Remaining functions (unchanged) ───────────────────────────────────────

def get_yfinance_news(tk, ar=None):
    import yfinance as yf
    try:
        news = getattr(yf.Ticker(f"{tk}.NS"), 'news', None)
        if news and isinstance(news, list):
            for item in news:
                if not isinstance(item, dict): continue
                hl = item.get("title", item.get("headline", ""))
                if not hl: continue
                hc, _ = classify_headline(hl, ar)
                if hc == "reporting": continue
                nu = item.get("link", item.get("url", "")); pts = item.get("providerPublishTime") or item.get("publish_time")
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

def get_live_price_return(tk):
    import yfinance as yf
    clean = tk.replace('.NS', '').replace('.BO', '').strip()
    symbols = [f"{clean}.BO", f"{clean}.NS"] if clean.isdigit() else [f"{clean}.NS", f"{clean}.BO"]
    for symbol in symbols:
        try:
            h = yf.Ticker(symbol).history(period="5d")
            if len(h) >= 2: return round(((h['Close'].iloc[-1] - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100, 2)
        except: continue
    return 0.0
    COMPANY_ALIASES
)
from engine.sentiment import classify_headline, classify_nse_headline

feedparser.USER_AGENT = BROWSER_HEADERS["User-Agent"]

# ── News Cache Config ─────────────────────────────────────────────────────
NEWS_CACHE_FILE = Path("news_cache.json")
NEWS_CACHE_TTL_HOURS = 4


def _news_cache_fresh():
    """Check if news cache exists and is within TTL for today."""
    if not NEWS_CACHE_FILE.exists():
        return False
    try:
        with open(NEWS_CACHE_FILE, "r") as f:
            cache = json.load(f)
        cached_at = datetime.fromisoformat(cache.get("cached_at", "2000-01-01"))
        age_hours = (datetime.now() - cached_at).total_seconds() / 3600
        cache_date = cache.get("date", "")
        if age_hours < NEWS_CACHE_TTL_HOURS and cache_date == date.today().strftime("%Y-%m-%d"):
            print(f"  ⚡ News cache fresh ({age_hours:.1f}h old). Loading from cache.")
            return True
    except Exception:
        pass
    return False


def _load_news_cache():
    """Load cached news_cache dict from disk."""
    try:
        with open(NEWS_CACHE_FILE, "r") as f:
            cache = json.load(f)
        data = cache.get("news_cache", {})
        sources = cache.get("sources", {})
        # Print source summary
        for src, info in sources.items():
            notes = info.get("notes", "")
            print(f"   {src}: {info.get('predictive', 0)} predictive from {info.get('total', 0)}{' (' + notes + ')' if notes else ''} [CACHED]")
        real_keys = {k for k in data if not k.startswith("_filing_")}
        n_articles = sum(len(v) for k, v in data.items() if not k.startswith("_filing_"))
        print(f"\nCache: {len(real_keys)} predictive | {n_articles} articles [FROM CACHE]")
        return data
    except Exception as e:
        print(f"  ⚠️  Cache load failed: {e}")
        return None


def _save_news_cache(news_cache, source_summary):
    """Save news_cache dict to disk."""
    payload = {
        "date": date.today().strftime("%Y-%m-%d"),
        "cached_at": datetime.now().isoformat(),
        "sources": source_summary,
        "news_cache": news_cache,
    }
    try:
        with open(NEWS_CACHE_FILE, "w") as f:
            json.dump(payload, f, default=str)
        n_articles = sum(len(v) for v in news_cache.values())
        print(f"  💾 Saved {n_articles} articles to news cache")
    except Exception as e:
        print(f"  ⚠️  Cache save failed: {e}")


# ── Existing helpers (unchanged) ──────────────────────────────────────────

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


# ── Main build function (with cache) ─────────────────────────────────────

def build_news_cache(tl):
    # ╔══════════════════════════════════════════════════════════════════╗
