#!/usr/bin/env python3
"""
xchart-app v7.4 — Multi-Layer Predictive Trading Engine
LC: Strict SMA9 reversal | SC: BB-centric | ATR SL | sigma-band
"""

import os
import sys
import json
import re
import time
import traceback
import numpy as np
import pandas as pd
import feedparser
from datetime import datetime, timedelta, timezone

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


VERSION = "7.4"
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


def load_tickers():
    """Load tickers from CSV."""
    if not os.path.exists(TICKERS_FILE):
        print("No tickers file found")
        return [], {}
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


def _is_reporting(title):
    """Check if headline is a reporting/results headline."""
    tl = title.lower()
    return any(kw in tl for kw in REPORTING_KW)


def _is_nse_noise(title):
    """Check if headline is NSE procedural noise."""
    tl = title.lower()
    return any(kw in tl for kw in NSE_NOISE_KW)


def _is_predictive(title):
    """Check if headline is predictive/catalyst."""
    tl = title.lower()
    if _is_reporting(title):
        return False
    return any(kw in tl for kw in PREDICTIVE_KW)


def _parse_pub_date(entry):
    """Parse publication date from RSS entry."""
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
    """Match ticker symbols in headline text."""
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
    """Fetch predictive news from RSS feeds."""
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


class FinBERTScorer:
    """FinBERT sentiment scorer for catalyst headlines."""

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
        pos = probs[0].item()
        neg = probs[1].item()
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


def compute_fund_score(ticker, stock_df):
    """Compute fundamental score from stock data."""
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
    elif 0 < roe < 5:
        score -= 5
    if pe == 0 and pb == 0 and roe == 0:
        score = 5 if mcap > 10000 else 0
    return score


def compute_market_regime():
    """Compute market regime from Nifty and NSE breadth data."""
    import yfinance as yf
    regime = {
        'regime': 'UNKNOWN', 'nifty_5d': 0, 'breadth': 50,
        'avg_rsi': 50, 'lt_breadth': 50
    }
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
        nse_url = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
        import urllib.request
        req = urllib.request.Request(nse_url, headers={'User-Agent': 'Mozilla/5.0'})
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
                high52 = float(s.get('yearHigh', '0').replace(',', ''))
                low52 = float(s.get('yearLow', '0').replace(',', ''))
                prev = float(s.get('previousClose', '0').replace(',', ''))
                if ltp <= 0 or prev <= 0:
                    continue
                total_stocks += 1
                mid_range = (high52 + low52) / 2
                if ltp > mid_range:
                    above_sma22 += 1
                est_rsi = 30 + (ltp - low52) / max(high52 - low52, 1) * 40
                rsi_sum += est_rsi
                pct_from_low = (ltp - low52) / low52 * 100 if low52 > 0 else 0
                if pct_from_low > 20:
                    above_sma200 += 1
            except (ValueError, TypeError):
                continue
        if total_stocks > 0:
            regime['breadth'] = round(above_sma22 / total_stocks * 100)
            regime['avg_rsi'] = round(rsi_sum / total_stocks, 1)
            regime['lt_breadth'] = round(above_sma200 / total_stocks * 100)
    except Exception:
        pass

    n5 = regime['nifty_5d']
    br = regime['breadth']

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
    print(f"  -> Breadth: {br}%")
    print(f"  -> REGIME: {regime['regime']}")
    return regime


def compute_sector_strength(stock_df, tickers, mcap_threshold):
    """Compute sector relative strength from SMA22."""
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
            if close > 0 and sma22 > 0:
                rel = (close - sma22) / sma22 * 100
                sectors[broad]['scores'].append(rel)

    sector_scores = {}
    print(f"\nComputing sector strength...")
    for sec, data in sorted(sectors.items(),
                            key=lambda x: np.mean(x[1]['scores']) if x[1]['scores'] else 0):
        avg = round(np.mean(data['scores'])) if data['scores'] else 0
        n = len(data['tickers'])
        sector_scores[sec] = avg
        print(f"    {sec} ({n}): {avg:+d}")
    return sector_scores


def generate_chart_data(ticker, stock_df, history_df, output_dir):
    """Generate chart JSON with OHLCV, indicators, and signal markers."""
    tk = stock_df[stock_df['Ticker'] == ticker].sort_values('Date').tail(365)
    if tk.empty:
        return

    data = {
        'ohlc': [], 'volume': [], 'markers': [],
        'sma9': [], 'sma22': [], 'sma200': [],
        'ema9': [], 'ema21': [],
        'bb_upper': [], 'bb_lower': [],
        'rsi': [], 'adx': [],
        'macd_line': [], 'macd_signal': [], 'macd_hist': [],
        'ichi_tenkan': [], 'ichi_kijun': [],
        'ichi_spanA': [], 'ichi_spanB': [],
        'st_bull': [], 'st_bear': [], 'vwap': [],
    }

    date_set = set()

    for _, row in tk.iterrows():
        d = str(row['Date'])[:10]
        date_set.add(d)
        o = float(row.get('Open', 0) or 0)
        h = float(row.get('High', 0) or 0)
        l = float(row.get('Low', 0) or 0)
        c = float(row.get('Close', 0) or 0)
        v = float(row.get('Volume', 0) or 0)

        if c <= 0:
            continue

        data['ohlc'].append({'time': d, 'open': o, 'high': h, 'low': l, 'close': c})
        data['volume'].append({
            'time': d, 'value': v,
            'color': 'rgba(34,197,94,0.3)' if c >= o else 'rgba(239,68,68,0.3)'
        })

        ind_map = [
            ('SMA_9', 'sma9'), ('SMA_22', 'sma22'), ('SMA_200', 'sma200'),
            ('EMA_9', 'ema9'), ('EMA_21', 'ema21'),
            ('BB_Upper', 'bb_upper'), ('BB_Lower', 'bb_lower'),
            ('RSI_14', 'rsi'), ('ADX_14', 'adx'),
            ('MACD_Line', 'macd_line'), ('MACD_Signal', 'macd_signal'),
            ('Ichi_Tenkan', 'ichi_tenkan'), ('Ichi_Kijun', 'ichi_kijun'),
        ]
        for col, key in ind_map:
            val = row.get(col)
            if val is not None and not pd.isna(val):
                data[key].append({'time': d, 'value': round(float(val), 4)})

        mh_val = row.get('MACD_Hist')
        if mh_val is not None and not pd.isna(mh_val):
            mh = float(mh_val)
            data['macd_hist'].append({
                'time': d, 'value': round(mh, 4),
                'color': 'rgba(34,197,94,0.5)' if mh >= 0 else 'rgba(239,68,68,0.5)'
            })

        st = row.get('ST_Direction')
        if st is not None and not pd.isna(st):
            if int(st) < 0:
                data['st_bull'].append({'time': d, 'value': l})
            else:
                data['st_bear'].append({'time': d, 'value': h})

    # Signal markers from history
    if history_df is not None and not history_df.empty:
        htk = history_df[history_df['Ticker'] == ticker]
        for _, hr in htk.iterrows():
            hd = str(hr.get('Date', ''))[:10]
            if hd not in date_set:
                continue
            raw_dir = hr.get('Composite_Direction', 0)
            if pd.isna(raw_dir):
                continue
            hdir = int(raw_dir)
            if hdir == 1:
                data['markers'].append({
                    'time': hd, 'position': 'belowBar',
                    'color': '#22c55e', 'shape': 'arrowUp', 'text': 'BULL'
                })
            elif hdir == -1:
                data['markers'].append({
                    'time': hd, 'position': 'aboveBar',
                    'color': '#ef4444', 'shape': 'arrowDown', 'text': 'BEAR'
                })

    data['markers'].sort(key=lambda m: m['time'])

    out_path = os.path.join(output_dir, f"{ticker}.json")
    with open(out_path, 'w') as f:
        json.dump(data, f)


def main():
    """Main engine entry point."""
    today = datetime.now().strftime('%Y-%m-%d')
    now_str = datetime.now().strftime('%I:%M %p')

    # Step 0: Data sync + recompute indicators
    ensure_data_exists()
    recompute_indicators()

    tickers, sector_map = load_tickers()
    if not tickers:
        print("No tickers found!")
        return

    # Init FinBERT
    scorer = FinBERTScorer()
    tickers, sector_map = load_tickers()

    # Load stock data
    stock_df = load_stock_data()
    if stock_df.empty:
        print("No stock data!")
        return

    mcap_threshold = detect_mcap_scale(stock_df)
    print(f"  -> MCap threshold: {mcap_threshold}")

    # Header
    print(f"\nPREDICTIVE Engine v{VERSION} - {len(tickers)} tickers | {today}")
    cutoff_date = (datetime.now() - timedelta(hours=NEWS_LOOKBACK_HRS)).strftime('%Y-%m-%d')
    print(f"News: {cutoff_date} to {now_str} | CATALYST-ONLY FinBERT")
    print(f"Tech: MEGA/LARGE=SMA9-reversal(strict) | MID/SMALL=BB-centric")
    print(f"Horizons: MEGA={HORIZONS['MEGA']}d LARGE={HORIZONS['LARGE']}d "
          f"MID={HORIZONS['MID']}d SMALL={HORIZONS['SMALL']}d")
    print(f"MinHold: MEGA={HOLD_DAYS['MEGA']}d LARGE={HOLD_DAYS['LARGE']}d "
          f"MID={HOLD_DAYS['MID']}d SMALL={HOLD_DAYS['SMALL']}d")
    print(f"SL: ATR-based LC | {STOP_LOSS_PCT}% fixed SC | Neutral band: sigma-based")
    print(f"Entry: +/-{ENTRY_THRESHOLD_LC} | Exit: +/-{EXIT_THRESHOLD_LC}")
    print('=' * 110)

    # PHASE 1: News
    print(f"\nPHASE 1: Fetching predictive news...")
    print('-' * 110)
    news_cache = fetch_predictive_news(tickers, NEWS_LOOKBACK_HRS)
    print('-' * 110)

    # PHASE 2: FinBERT scoring
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
        actual_ret = 0
        if not tk.empty:
            mcap = safe_float(tk.iloc[-1].get('Market_Cap', 0), 0)
            close_now = safe_float(tk.iloc[-1].get('Close', 0), 0)
            cat = _classify_cap(mcap, mcap_threshold)
            fwd = HORIZONS[cat]
            close_prev = None
            if len(tk) >= fwd + 1:
                close_prev = safe_float(tk.iloc[-(fwd + 1)].get('Close', 0), 0)
            if close_prev and close_prev > 0:
                actual_ret = (close_now - close_prev) / close_prev * 100

        if total_score > FINBERT_BULL:
            direction = 'BULL'
        elif total_score < FINBERT_BEAR:
            direction = 'BEAR'
        else:
            direction = 'NEUT'

        hit = 'HIT' if ((total_score > 0 and actual_ret > 0) or
                        (total_score < 0 and actual_ret < 0) or
                        (abs(actual_ret) < 0.25)) else 'MISS'

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

    cat_total = sum(s['n_catalysts'] for s in scored_tickers.values())
    print(f"\n  Catalysts: {cat_total} scored")

    # PHASE 3: Multi-layer analysis
    print(f"\nPHASE 3: Multi-layer analysis ({len(tickers)} tickers)...")
    print('-' * 110)

    print("Loading stock data...")
    stock_df = load_stock_data()
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
        tech_scores[t] = {'score': score, 'signals': signals, 'info': info}
        if info.get('is_largecap'):
            lc_count += 1
        else:
            smc_count += 1
        scored_count += 1

    print(f"  -> {scored_count}/{len(tickers)} scored | LC:{lc_count} SMC:{smc_count}")

    # Fundamentals
    print(f"Computing fundamentals...")
    fund_scores = {}
    fund_nonzero = 0
    for t in tickers:
        fs = compute_fund_score(t, stock_df)
        fund_scores[t] = fs
        if fs != 0:
            fund_nonzero += 1
    print(f"  -> {fund_nonzero}/{len(tickers)} with non-zero fund score")

    # Sectors
    sector_scores_map = {}
    mapped = 0
    unique_sectors = set()
    for t in tickers:
        sec = get_sector_from_stock_data(t, stock_df)
        broad = get_broad_sector(sec)
        if broad and broad != 'Other':
            mapped += 1
            unique_sectors.add(broad)
        sector_scores_map[t] = broad
    print(f"  -> {mapped}/{len(tickers)} mapped to {len(unique_sectors)} sectors")

    # Market regime
    regime = compute_market_regime()

    # Sector strength
    sector_strength = compute_sector_strength(stock_df, tickers, mcap_threshold)

    # PHASE 3b: Backtest
    print(f"\nPHASE 3b: Backtest (ATR SL for LC, {abs(STOP_LOSS_PCT)}% SL for SC)...")
    bt_results = compute_per_ticker_accuracy(stock_df, mcap_threshold)

    # Composite scoring
    print(f"\nComputing composite + regime adjustment...")
    reg = regime['regime']
    if reg == 'STRONG_BEAR':
        bull_damp, bear_damp = 0.5, 1.2
    elif reg == 'MILD_BEAR':
        bull_damp, bear_damp = 0.8, 1.0
    elif reg == 'STRONG_BULL':
        bull_damp, bear_damp = 1.2, 0.5
    elif reg == 'MILD_BULL':
        bull_damp, bear_damp = 1.0, 0.8
    else:
        bull_damp, bear_damp = 1.0, 1.0
    print(f"  Regime: {reg} -> bull_damp={bull_damp} bear_damp={bear_damp}")
    print('-' * 110)

    all_rows = []
    tech_bull = 0
    tech_bear = 0
    tech_neut = 0
    tech_hits = 0
    tech_total_dir = 0

    for i, t in enumerate(tickers):
        if t not in tech_scores:
            continue

        ts = tech_scores[t]
        tech = ts['score']
        info = ts['info']

        ns = scored_tickers.get(t, {})
        news = ns.get('news_score', 0)

        broad = sector_scores_map.get(t, 'Other')
        sector_sc = sector_strength.get(broad, 0)
        macro = sector_sc

        fund = fund_scores.get(t, 0)

        composite = tech * W_TECH + news * W_NEWS + macro * W_MACRO + fund * W_FUND

        if composite > 0:
            composite *= bull_damp
        elif composite < 0:
            composite *= bear_damp

        if news > 40 and composite < news * 0.3:
            composite = news * 0.3
        elif news < -40 and composite > news * 0.3:
            composite = news * 0.3

        mcap = 0
        tk = stock_df[stock_df['Ticker'] == t]
        if not tk.empty:
            mcap = safe_float(tk.iloc[-1].get('Market_Cap', 0), 0)
        cat = _classify_cap(mcap, mcap_threshold)
        horizon = HORIZONS[cat]

        if cat in ('MEGA', 'LARGE'):
            entry_thresh = ENTRY_THRESHOLD_LC
        else:
            entry_thresh = ENTRY_THRESHOLD_SC

        if composite > entry_thresh:
            direction = 1
            dir_label = 'BULL'
            tech_bull += 1
        elif composite < -entry_thresh:
            direction = -1
            dir_label = 'BEAR'
            tech_bear += 1
        else:
            direction = 0
            dir_label = 'NEUT'
            tech_neut += 1

        corrected = False
        if ns and ns.get('news_dir') == 'BULL' and direction == -1:
            if abs(news) > abs(composite) * 0.5:
                direction = 0
                dir_label = 'NEUT'
                corrected = True
        elif ns and ns.get('news_dir') == 'BEAR' and direction == 1:
            if abs(news) > abs(composite) * 0.5:
                direction = 0
                dir_label = 'NEUT'
                corrected = True

        actual_ret = 0
        if not tk.empty and len(tk) > horizon:
            close_now = safe_float(tk.iloc[-1].get('Close', 0), 0)
            close_prev = safe_float(tk.iloc[-(horizon + 1)].get('Close', 0), 0)
            if close_prev > 0:
                actual_ret = (close_now - close_prev) / close_prev * 100

        if direction != 0:
            actual_dir = 1 if actual_ret > 0.25 else (-1 if actual_ret < -0.25 else 0)
            hit_result = is_hit(direction, actual_dir)
            if hit_result is not None:
                tech_total_dir += 1
                if hit_result:
                    tech_hits += 1
                hit_label = 'HIT' if hit_result else 'MISS'
            else:
                hit_label = 'NEUT'
        else:
            hit_label = 'NEUT'

        bt = bt_results.get(t, {})
        bt_acc = bt.get('BT_6M', 0)

        if t in scored_tickers or direction != 0 or corrected:
            bt_str = f"BT:{bt_acc:.0f}%/{cat}" if bt_acc > 0 else ""
            corr_str = "<- CORRECTED" if corrected else ""
            print(f"  [{i + 1:>3}] {t:<14} Tech: {tech:>+3.0f} Macro: {macro:>+3.0f} "
                  f"Fund: {fund:>+3.0f} -> Comp: {composite:>+5.1f} {dir_label} {hit_label} "
                  f"{corr_str} {bt_str} H:{horizon}d")

        row = {
            'Ticker': t,
            'Date': today,
            'Tech_Score': round(tech, 1),
            'News_Score': round(news, 1),
            'Macro_Score': round(macro, 1),
            'Fund_Score': round(fund, 1),
            'Composite_Score': round(composite, 1),
            'Composite_Direction': direction,
            'Direction_Label': dir_label,
            'Composite_Severity': dir_label,
            'Horizon': horizon,
            'Category': cat,
            'BT_Category': cat,
            'Sector': broad,
            'Actual_Return_Pct': round(actual_ret, 2),
            'Hit': hit_label,
            'BT_Accuracy': bt_acc,
            'BT_6M': bt_acc,
            'BT_1M': bt.get('BT_1M', 0),
            'BT_3M': bt.get('BT_3M', 0),
            'BT_Forward_Days': bt.get('BT_Forward_Days', horizon),
            'BT_Threshold': bt.get('BT_Threshold', 0),
            'BT_ATR_Pct': bt.get('BT_ATR_Pct', 0),
            'BT_SL_Level': bt.get('BT_SL_Level', -5.0),
            'BT_Avg_SL': bt.get('BT_Avg_SL', 5.0),
            'BT_PF': bt.get('TR_profit_factor', 0),
            'BT_Trades': bt.get('TR_total_trades', 0),
            'BT_Signal_Rate': bt.get('BT_Signal_Rate', 0),
            'TR_profit_factor': bt.get('TR_profit_factor', 0),
            'TR_total_trades': bt.get('TR_total_trades', 0),
            'TR_win_rate': bt.get('TR_win_rate', 0),
            'TR_avg_win_pct': bt.get('TR_avg_win_pct', 0),
            'TR_avg_loss_pct': bt.get('TR_avg_loss_pct', 0),
            'TR_total_return_pct': bt.get('TR_total_return_pct', 0),
            'TR_avg_holding_days': bt.get('TR_avg_holding_days', 0),
            'TR_long_win_rate': bt.get('TR_long_win_rate', 0),
            'TR_short_win_rate': bt.get('TR_short_win_rate', 0),
            'N_Catalysts': ns.get('n_catalysts', 0) if ns else 0,
            'News_Direction': ns.get('news_dir', '') if ns else '',
            'Corrected': corrected,
        }
        all_rows.append(row)

    if tech_total_dir > 0:
        print(f"\n  Tech-only: Bull:{tech_bull} Bear:{tech_bear} Neut:{tech_neut} | "
              f"Hit:{tech_hits}/{tech_total_dir} = {tech_hits / tech_total_dir * 100:.1f}%")

    # PHASE 4: Save
    print(f"\nPHASE 4: Save...")
    print('-' * 110)

    result_df = pd.DataFrame(all_rows)
    result_df.to_csv(OUTPUT_FILE, index=False)

    if os.path.exists(HISTORY_FILE):
        hdf = pd.read_csv(HISTORY_FILE)
        hdf = pd.concat([hdf, result_df], ignore_index=True)
        hdf = hdf.drop_duplicates(subset=['Ticker', 'Date'], keep='last')
    else:
        hdf = result_df.copy()
    hdf.to_csv(HISTORY_FILE, index=False)
    n_dates = hdf['Date'].nunique()
    print(f"History: {len(hdf)} rows / {n_dates} days")

    # PHASE 5: Charts + meta
    print(f"\nPHASE 5: Generating chart JSON + meta...")
    print('-' * 110)

    os.makedirs(CHARTS_DIR, exist_ok=True)
    for t in tickers:
        generate_chart_data(t, stock_df, hdf, CHARTS_DIR)
    print(f"  -> Chart JSON: {len(tickers)} tickers in {CHARTS_DIR}/")

    # Meta
    avg_pf = 0
    avg_acc = 0
    if bt_results:
        pf_vals = [r['TR_profit_factor'] for r in bt_results.values()
                   if r.get('TR_total_trades', 0) >= 5]
        acc_vals = [r['BT_6M'] for r in bt_results.values()
                    if r.get('BT_Dir_Preds', 0) > 0]
        avg_pf = round(np.mean(pf_vals), 2) if pf_vals else 0
        avg_acc = round(np.mean(acc_vals), 1) if acc_vals else 0

    meta = {
        'date': today,
        'version': VERSION,
        'tickers': len(tickers),
        'regime': regime['regime'],
        'nifty_5d': regime['nifty_5d'],
        'breadth': regime['breadth'],
        'avg_rsi': regime.get('avg_rsi', 50),
        'lt_breadth': regime.get('lt_breadth', 50),
        'avg_accuracy': avg_acc,
        'avg_profit_factor': avg_pf,
        'entry_threshold_lc': ENTRY_THRESHOLD_LC,
        'entry_threshold_sc': ENTRY_THRESHOLD_SC,
        'horizons': HORIZONS,
        'hold_days': HOLD_DAYS,
        'stop_loss': STOP_LOSS_PCT,
        'bull_count': tech_bull,
        'bear_count': tech_bear,
        'neut_count': tech_neut,
    }
    with open(META_FILE, 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"  -> meta.json saved (PF:{avg_pf} Acc:{avg_acc}%)")

    # Summary
    news_count = len(scored_tickers)
    no_news = len(all_rows) - news_count

    total_preds = sum(r.get('BT_Total_Preds', 0) for r in bt_results.values()) if bt_results else 0
    avg_1m = 0
    if bt_results:
        m1_vals = [r['BT_1M'] for r in bt_results.values() if r.get('BT_Dir_Preds', 0) > 0]
        avg_1m = np.mean(m1_vals) if m1_vals else 0

    print(f"\n{'=' * 110}")
    print(f"{OUTPUT_FILE} | {today} | ENGINE v{VERSION} ATR SL + strict SMA9")
    print(f"TICKERS: {news_count} news | {no_news} no-news")
    print(f"REGIME: {regime['regime']} (breadth={regime['breadth']}% nifty={regime['nifty_5d']}%)")
    print(f"STRATEGY: LC({lc_count}) SMC({smc_count}) | MEGA/LARGE=SMA9-rev(strict) | MID/SMALL=BB")
    print(f"BACKTEST: {len(bt_results)} tickers | {total_preds:,} preds | 1M:{avg_1m:.1f}% ALL:{avg_acc}%")

    dir_rows = [r for r in all_rows if r['Composite_Direction'] != 0]
    same_hits = sum(1 for r in dir_rows if r['Hit'] == 'HIT')
    same_total = len(dir_rows)
    same_pct = same_hits / same_total * 100 if same_total > 0 else 0
    flips = sum(1 for r in all_rows if r.get('Corrected', False))
    print(f"SAME-DAY: {same_hits}/{same_total} = {same_pct:.1f}% | "
          f"Bull:{tech_bull} Bear:{tech_bear} | Flips:{flips}")
    print('=' * 110)

    print_accuracy_report(bt_results, scored_tickers, hdf, all_rows)


if __name__ == '__main__':
    main()
