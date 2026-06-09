#!/usr/bin/env python3
"""
xchart-app v7.3 — Multi-Layer Predictive Trading Engine
LC: SMA9 reversal trigger | SC: BB-centric | σ-band | 5% SL
"""

import os, sys, json, re, time, traceback
import numpy as np
import pandas as pd
import feedparser
from datetime import datetime, timedelta, timezone

# ── Engine imports ──
from engine.data_fetcher import ensure_data_exists
from engine.technical import (
    load_stock_data, compute_tech_score, detect_mcap_scale,
    get_sector_from_stock_data, get_broad_sector
)
from engine.accuracy import (
    compute_per_ticker_accuracy, print_accuracy_report,
    ENTRY_THRESHOLD_LC, ENTRY_THRESHOLD_SC,
    EXIT_THRESHOLD_LC, EXIT_THRESHOLD_SC,
    HORIZONS, HOLD_DAYS, STOP_LOSS_PCT, is_hit, _classify_cap
)
from engine.utils import safe_float
from create_stock_data import recompute_indicators

try:
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    HAS_FINBERT = True
except ImportError:
    HAS_FINBERT = False

# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════
VERSION = "7.3"
TICKERS_FILE = 'tickers.csv'
DATA_FILE = 'stock_data.csv'
OUTPUT_FILE = 'data.csv'
HISTORY_FILE = 'history.csv'
CHARTS_DIR = 'charts'
META_FILE = 'meta.json'

W_TECH = 0.65
W_NEWS = 0.10
W_MACRO = 0.16
W_FUND = 0.11
FINBERT_BULL = 5
FINBERT_BEAR = -5
NEWS_LOOKBACK_HRS = 72

RSS_FEEDS = {
    'mc_topnews':     'https://www.moneycontrol.com/rss/MCtopnews.xml',
    'mc_business':    'https://www.moneycontrol.com/rss/business.xml',
    'mc_markets':     'https://www.moneycontrol.com/rss/marketreports.xml',
    'mc_stocks':      'https://www.moneycontrol.com/rss/stocksnews.xml',
    'et_markets':     'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',
    'et_stocks':      'https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms',
    'et_news':        'https://economictimes.indiatimes.com/news/rssfeeds/1715249553.cms',
    'ndtv_business':  'https://feeds.feedburner.com/ndtvprofit-latest',
    'mint_market':    'https://www.livemint.com/rss/market',
    'mint_companies': 'https://www.livemint.com/rss/companies',
    'nse_announce':   'https://www.nseindia.com/api/corporate-announcements?index=equities',
    'nse_actions':    'https://www.nseindia.com/api/corporate-actions?index=equities',
    'fe_markets':     'https://www.financialexpress.com/market/',
    'fe_companies':   'https://www.financialexpress.com/industry/companies/feed/',
    'bl_markets':     'https://www.thehindubusinessline.com/markets/feeder/default.rss',
    'bl_stocks':      'https://www.thehindubusinessline.com/markets/stock-markets/feeder/default.rss',
    'bl_companies':   'https://www.thehindubusinessline.com/companies/feeder/default.rss',
}

REPORTING_KW = [
    'quarterly result', 'q1 result', 'q2 result', 'q3 result', 'q4 result',
    'net profit', 'revenue rose', 'revenue fell', 'reports profit', 'reports loss',
    'earnings', 'fy25', 'fy26', 'annual report', 'agm', 'board approves dividend',
]
NSE_NOISE_KW = [
    'board meeting', 'record date', 'trading window', 'loss of certificate',
    'duplicate share', 'intimation', 'disclosure under', 'reg 29', 'reg 31',
    'reg 39', 'reg 74', 'certificate', 'general meeting', 'alteration',
    'change in director', 'newspaper', 'advertisement', 'book closure',
]
PREDICTIVE_KW = [
    'upgrade', 'downgrade', 'target', 'outlook', 'forecast', 'expansion',
    'acquisition', 'merger', 'buyback', 'stake', 'deal', 'order win',
    'contract', 'partnership', 'launch', 'approve', 'fdi', 'fii', 'dii',
    'bull', 'bear', 'rally', 'crash', 'surge', 'plunge', 'breakout',
    'invest', 'capex', 'capacity', 'commissioning', 'plant', 'ipo',
    'restructur', 'divest', 'demerger', 'rights issue', 'preferential',
    'sector rotat', 'rate cut', 'rate hike', 'tariff', 'sanction',
    'regulation', 'policy', 'subsidy', 'ban', 'recall', 'penalty',
]


# ═══════════════════════════════════════════════════════════════
# TICKER LOADING
# ═══════════════════════════════════════════════════════════════
def load_tickers():
    if not os.path.exists(TICKERS_FILE):
        print(f"⚠️ {TICKERS_FILE} not found"); return [], {}
    df = pd.read_csv(TICKERS_FILE)
    tickers = df.iloc[:, 0].astype(str).str.strip().tolist()
    sector_map = {}
    if 'Sector' in df.columns:
        for _, r in df.iterrows():
            t = str(r.iloc[0]).strip()
            s = str(r.get('Sector', '')).strip()
            if s and s.lower() not in ('nan', 'none', ''):
                sector_map[t] = s
    print(f"Loaded {len(tickers)} tickers from {TICKERS_FILE} (sector map: {len(sector_map)} entries)")
    return tickers, sector_map


# ═══════════════════════════════════════════════════════════════
# NEWS FETCHING
# ═══════════════════════════════════════════════════════════════
def _is_reporting(title):
    tl = title.lower()
    return any(kw in tl for kw in REPORTING_KW)

def _is_nse_noise(title):
    tl = title.lower()
    return any(kw in tl for kw in NSE_NOISE_KW)

def _is_predictive(title):
    tl = title.lower()
    if _is_reporting(title):
        return False
    return any(kw in tl for kw in PREDICTIVE_KW)

def _parse_pub_date(entry):
    for key in ('published_parsed', 'updated_parsed'):
        pp = entry.get(key)
        if pp:
            try:
                return datetime(*pp[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    for key in ('published', 'updated'):
        ds = entry.get(key, '')
        if ds:
            for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%dT%H:%M:%S%z',
                        '%a, %d %b %Y %H:%M:%S GMT'):
                try:
                    return datetime.strptime(ds.strip(), fmt).replace(tzinfo=timezone.utc)
                except Exception:
                    continue
    return None

def _match_tickers(title, tickers):
    matched = []
    tl = title.upper()
    for t in tickers:
        t_clean = t.replace('&', '').replace('-', '')
        if len(t_clean) < 3:
            continue
        pattern = r'\b' + re.escape(t_clean) + r'\b'
        if re.search(pattern, tl.replace('&', '').replace('-', '')):
            matched.append(t)
    return matched

def fetch_predictive_news(tickers, lookback_hrs=72):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hrs)
    news_cache = {}
    total_scanned = 0
    total_reporting = 0
    total_nse_noise = 0
    total_kept = 0

    for source, url in RSS_FEEDS.items():
        print(f"Fetching {source}...")
        try:
            if 'nseindia.com/api' in url:
                import urllib.request
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'application/json',
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                entries = data if isinstance(data, list) else []
                is_nse_api = True
            else:
                feed = feedparser.parse(url)
                entries = feed.get('entries', [])
                is_nse_api = False
        except Exception as e:
            print(f"   {source}: {e}")
            print(f"   {source}: No entries")
            continue

        predictive_count = 0
        reporting_count = 0
        nse_noise_count = 0
        outside_count = 0

        for entry in entries:
            if is_nse_api:
                title = entry.get('subject', '') or entry.get('desc', '') or ''
                symbol = entry.get('symbol', '')
            else:
                title = entry.get('title', '')
                symbol = ''

            if not title:
                continue
            total_scanned += 1

            pub_date = _parse_pub_date(entry) if not is_nse_api else None
            if pub_date and pub_date < cutoff:
                outside_count += 1
                continue

            if _is_nse_noise(title):
                nse_noise_count += 1
                total_nse_noise += 1
                continue

            if _is_reporting(title):
                reporting_count += 1
                total_reporting += 1
                continue

            if not _is_predictive(title):
                continue

            if is_nse_api and symbol:
                matched = [symbol] if symbol in tickers else []
            else:
                matched = _match_tickers(title, tickers)

            if matched:
                for t in matched:
                    if t not in news_cache:
                        news_cache[t] = []
                    news_cache[t].append({
                        'title': title,
                        'source': source,
                        'date': pub_date.isoformat() if pub_date else '',
                    })
                predictive_count += 1
                total_kept += 1
            else:
                predictive_count += 1
                total_kept += 1

        parts = [f"{predictive_count} predictive from {len(entries)}"]
        if outside_count:
            parts.append(f"{outside_count} outside window")
        if reporting_count:
            parts.append(f"{reporting_count} reporting")
        if nse_noise_count:
            parts.append(f"{nse_noise_count} NSE noise")
        print(f"   {source}: {', '.join(parts)}")

    print(f"\nCache: {len(news_cache)}/{len(tickers)} predictive | "
          f"Scanned:{total_scanned} Reporting:{total_reporting} "
          f"NSEnoise:{total_nse_noise} Kept:{total_kept}")
    return news_cache


# ═══════════════════════════════════════════════════════════════
# FINBERT SCORING
# ═══════════════════════════════════════════════════════════════
class FinBERTScorer:
    def __init__(self):
        if not HAS_FINBERT:
            self.model = None
            return
        print("Initializing FinBERT...")
        model_name = "ProsusAI/finbert"
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.eval()

    def score(self, text):
        if not self.model:
            return 0.0
        inputs = self.tokenizer(text, return_tensors='pt', truncation=True, max_length=512)
        with torch.no_grad():
            outputs = self.model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
        pos, neg, neu = probs[0].item(), probs[1].item(), probs[2].item()
        return (pos - neg) * 100

    def score_catalysts(self, headlines):
        if not headlines:
            return 0.0, 0, 0
        total = 0.0
        n_cat = 0
        for h in headlines:
            title = h['title'] if isinstance(h, dict) else h
            s = self.score(title)
            total += s
            n_cat += 1
        return total, n_cat, len(headlines)


# ═══════════════════════════════════════════════════════════════
# FUNDAMENTAL SCORING
# ═══════════════════════════════════════════════════════════════
def compute_fund_score(ticker, stock_df):
    tk = stock_df[stock_df['Ticker'] == ticker]
    if tk.empty:
        return 0
    last = tk.iloc[-1]
    mcap = safe_float(last.get('Market_Cap', 0), 0)
    if mcap <= 0:
        return 0
    score = 0
    pe = safe_float(last.get('PE_Ratio', 0), 0)
    if pe > 0:
        if pe < 15:
            score += 15
        elif pe < 25:
            score += 5
        elif pe > 50:
            score -= 15
        elif pe > 35:
            score -= 10
    div_yield = safe_float(last.get('Dividend_Yield', 0), 0)
    if div_yield > 3:
        score += 10
    elif div_yield > 1.5:
        score += 5
    pb = safe_float(last.get('PB_Ratio', 0), 0)
    if pb > 0:
        if pb < 1.5:
            score += 10
        elif pb > 5:
            score -= 10
    roe = safe_float(last.get('ROE', 0), 0)
    if roe > 20:
        score += 10
    elif roe > 12:
        score += 5
    elif roe < 5 and roe > 0:
        score -= 5
    if pe == 0 and pb == 0 and roe == 0:
        score = 5 if mcap > 10000 else 0
    return score


# ═══════════════════════════════════════════════════════════════
# MARKET REGIME
# ═══════════════════════════════════════════════════════════════
def compute_market_regime():
    import yfinance as yf
    regime = {'regime': 'UNKNOWN', 'nifty_5d': 0, 'breadth': 50,
              'avg_rsi': 50, 'lt_breadth': 50}
    try:
        nifty = yf.download('^NSEI', period='1mo', progress=False)
        if not nifty.empty:
            close = nifty['Close']
            if hasattr(close, 'iloc') and len(close) >= 6:
                ret5 = (float(close.iloc[-1]) - float(close.iloc[-6])) / float(close.iloc[-6]) * 100
                regime['nifty_5d'] = round(ret5, 2)
    except Exception:
        pass

    try:
        broad = yf.download('^NSEI', period='6mo', progress=False)
        if not broad.empty and len(broad) > 22:
            close_b = broad['Close'].squeeze()
            sma22 = close_b.rolling(22).mean()
            above = (close_b > sma22).sum()
            total_b = len(close_b.dropna())
            regime['breadth'] = round(above / max(total_b, 1) * 100)
    except Exception:
        pass

    try:
        all_stocks = yf.download(
            '^NSEI', period='3mo', progress=False
        )
        # Breadth from NSE broad market
        nse_url = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
        import urllib.request
        req = urllib.request.Request(nse_url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            stocks = data.get('data', [])
            above_sma22 = 0
            total_stocks = 0
            rsi_sum = 0
            above_sma200 = 0
            for s in stocks:
                try:
                    ltp = float(s.get('lastPrice', '0').replace(',', ''))
                    op = float(s.get('open', '0').replace(',', ''))
                    if ltp > 0:
                        total_stocks += 1
                except Exception:
                    continue
            if total_stocks > 0:
                regime['breadth'] = round(above_sma22 / total_stocks * 100)
        except Exception:
            pass
    except Exception:
        pass

    n5 = regime['nifty_5d']
    br = regime['breadth']
    rsi_avg = regime.get('avg_rsi', 50)
    lt = regime.get('lt_breadth', 50)

    if br >= 65 and n5 > 1:
        regime['regime'] = 'STRONG_BULL'
    elif br >= 55 and n5 > 0:
        regime['regime'] = 'MILD_BULL'
    elif br <= 35 and n5 < -1:
        regime['regime'] = 'STRONG_BEAR'
    elif br <= 45 and n5 < 0:
        regime['regime'] = 'MILD_BEAR'
    else:
        regime['regime'] = 'CHOPPY'

    print(f"\nComputing market regime...")
    print(f"  -> Nifty 5d: {n5}%")
    print(f"  -> SMA22 breadth: {br}%")
    print(f"  -> Avg RSI: {rsi_avg}")
    print(f"  -> SMA200 breadth: {lt}%")
    print(f"  -> REGIME: {regime['regime']} (breadth={br}% nifty={n5}% rsi={rsi_avg} lt={lt}%)")
    return regime


def compute_sector_strength(stock_df, tickers, mcap_threshold):
    sectors = {}
    for t in tickers:
        sec = get_sector_from_stock_data(t, stock_df)
        broad = get_broad_sector(sec)
        if broad not in sectors:
            sectors[broad] = {'tickers': [], 'scores': []}
        sectors[broad]['tickers'].append(t)
        tk = stock_df[stock_df['Ticker'] == t]
        if not tk.empty:
            last = tk.iloc[-1]
            close = safe_float(last.get('Close'), 0)
            sma22 = safe_float(last.get('SMA_22'), close)
            sma200 = safe_float(last.get('SMA_200'), close)
            if close > 0 and sma22 > 0:
                rel = (close - sma22) / sma22 * 100
                sectors[broad]['scores'].append(rel)

    sector_scores = {}
    print(f"\nComputing sector strength...")
    if sectors:
        print(f"  -> {len(sectors)} broad sectors")
    for sec, data in sorted(sectors.items(), key=lambda x: np.mean(x[1]['scores']) if x[1]['scores'] else 0):
        avg = round(np.mean(data['scores'])) if data['scores'] else 0
        n = len(data['tickers'])
        sector_scores[sec] = avg
        print(f"    {sec} ({n}): {avg:+d} [data-driven]")
    return sector_scores


# ═══════════════════════════════════════════════════════════════
# CHART DATA GENERATION
# ═══════════════════════════════════════════════════════════════
def generate_chart_data(ticker, stock_df, output_dir):
    tk = stock_df[stock_df['Ticker'] == ticker].sort_values('Date').tail(365)
    if tk.empty:
        return
    cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume',
            'SMA_9', 'SMA_22', 'SMA_50', 'SMA_200',
            'EMA_9', 'EMA_21', 'RSI_14',
            'MACD_Line', 'MACD_Signal', 'MACD_Hist',
            'BB_Upper', 'BB_Lower', 'ADX_14', 'ST_Direction',
            'Ichi_Tenkan', 'Ichi_Kijun', 'ATR_14']
    available = [c for c in cols if c in tk.columns]
    chart_df = tk[available].copy()
    chart_df.to_csv(os.path.join(output_dir, f"{ticker}.csv"), index=False)


# ═══════════════════════════════════════════════════════════════
# MAIN ENGINE
# ═══════════════════════════════════════════════════════════════
def main():
    today = datetime.now().strftime('%Y-%m-%d')
    now_str = datetime.now().strftime('%I:%M %p')

    # ── Step 0: Data sync + recompute ──
    ensure_data_exists()
    recompute_indicators()

    tickers, sector_map = load_tickers()
    if not tickers:
        print("No tickers found!"); return

    # ── Init FinBERT ──
    scorer = FinBERTScorer()
    tickers, sector_map = load_tickers()

    # ── Load stock data ──
    stock_df = load_stock_data()
    if stock_df.empty:
        print("No stock data!"); return

    mcap_threshold = detect_mcap_scale(stock_df)
    print(f"  -> MCap threshold: {mcap_threshold}")

    # Header
    print(f"\nPREDICTIVE Engine v{VERSION} - {len(tickers)} tickers | {today}")
    cutoff_date = (datetime.now() - timedelta(hours=NEWS_LOOKBACK_HRS)).strftime('%Y-%m-%d')
    print(f"News: {cutoff_date} to {now_str} | CATALYST-ONLY FinBERT")
    print(f"Tech: MEGA/LARGE=SMA9-reversal | MID/SMALL=BB-centric")
    print(f"Horizons: MEGA={HORIZONS['MEGA']}d LARGE={HORIZONS['LARGE']}d "
          f"MID={HORIZONS['MID']}d SMALL={HORIZONS['SMALL']}d")
    print(f"MinHold: MEGA={HOLD_DAYS['MEGA']}d LARGE={HOLD_DAYS['LARGE']}d "
          f"MID={HOLD_DAYS['MID']}d SMALL={HOLD_DAYS['SMALL']}d")
    print(f"SL: {STOP_LOSS_PCT}% fixed | Neutral band: σ-based (std×√horizon)")
    print(f"Entry: ±{ENTRY_THRESHOLD_LC} | Exit: ±{EXIT_THRESHOLD_LC}")
    print(f"Validation: neutral=HIT | Per-ticker: Swing/1M/3M/ALL")
    print('=' * 110)

    # ══════════════════════════════════════════════
    # PHASE 1: News
    # ══════════════════════════════════════════════
    print(f"\nPHASE 1: Fetching predictive news...")
    print('-' * 110)
    news_cache = fetch_predictive_news(tickers, NEWS_LOOKBACK_HRS)
    print('-' * 110)

    # ══════════════════════════════════════════════
    # PHASE 2: FinBERT scoring
    # ══════════════════════════════════════════════
    print(f"\nPHASE 2: FinBERT scoring (CATALYST-ONLY)...")
    print('-' * 110)

    scored_tickers = {}
    idx = 0
    for t in tickers:
        headlines = news_cache.get(t, [])
        if not headlines:
            continue
        total_score, n_cat, n_h = scorer.score_catalysts(headlines)
        mcap = 0
        tk = stock_df[stock_df['Ticker'] == t]
        if not tk.empty:
            mcap = safe_float(tk.iloc[-1].get('Market_Cap', 0), 0)
            close_now = safe_float(tk.iloc[-1].get('Close', 0), 0)
            cat = _classify_cap(mcap, mcap_threshold)
            fwd = HORIZONS[cat]
            close_prev = None
            if len(tk) >= fwd + 1:
                close_prev = safe_float(tk.iloc[-(fwd + 1)].get('Close', 0), 0)
            actual_ret = ((close_now - close_prev) / close_prev * 100) if close_prev and close_prev > 0 else 0
        else:
            actual_ret = 0

        if total_score > FINBERT_BULL:
            direction = 'BULL'
        elif total_score < FINBERT_BEAR:
            direction = 'BEAR'
        else:
            direction = 'NEUT'

        hit = 'HIT' if (total_score > 0 and actual_ret > 0) or \
                       (total_score < 0 and actual_ret < 0) or \
                       (abs(actual_ret) < 0.25) else 'MISS'

        idx += 1
        print(f"[{idx:>3}] {t:<14} {direction:>4} Score: {total_score:>+5.1f} "
              f"Ret: {actual_ret:>+.2f}% {hit} [{n_cat}cat/{n_h}h]")

        scored_tickers[t] = {
            'news_score': total_score,
            'news_dir': direction,
            'news_hit': hit,
            'n_catalysts': n_cat,
            'n_headlines': n_h,
        }

    print(f"\n  Catalysts: {sum(s['n_catalysts'] for s in scored_tickers.values())} scored")

    # ══════════════════════════════════════════════
    # PHASE 3: Multi-layer analysis
    # ══════════════════════════════════════════════
    print(f"\nPHASE 3: Multi-layer analysis ({len(tickers)} tickers)...")
    print('-' * 110)

    print("Loading stock data...")
    stock_df = load_stock_data()
    n_tickers = stock_df['Ticker'].nunique()
    print(f"  -> MCap threshold: {mcap_threshold}")

    # Tech scores
    print(f"Computing technical scores (v{VERSION} cap-aware)...")
    tech_scores = {}
    lc_count = 0
    smc_count = 0
    scored_count = 0
    for i, t in enumerate(tickers):
        tk = stock_df[stock_df['Ticker'] == t].sort_values('Date')
        tk = tk[tk['Close'].notna()]
        if len(tk) < 20:
            continue
        window = tk.tail(200).reset_index(drop=True)
        debug = i < 3
        score, signals, info = compute_tech_score(window, mcap_threshold, debug=debug)
        tech_scores[t] = {'score': score, 'signals': signals, 'info': info
