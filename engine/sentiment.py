"""FinBERT scoring, catalyst filtering, headline classification"""
import re
from engine.config import (
    REPORTING_VERBS, PRICE_CONTEXT, CATALYST_VERBS, SECTOR_IMPACT_WORDS,
    MATERIAL_CATALYST_KEYWORDS, NOISE_HEADLINE_PATTERNS,
    NSE_ACTIONABLE_KEYWORDS, NSE_NOISE_KEYWORDS,
    SHORT_TERM_KEYWORDS, LONG_TERM_KEYWORDS
)

# FinBERT model (loaded lazily)
_tokenizer = None
_model = None

def _load_finbert():
    global _tokenizer, _model
    if _tokenizer is None:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        print("Initializing FinBERT...")
        FINBERT_MODEL = "ProsusAI/finbert"
        _tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL)
        _model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL)
    return _tokenizer, _model

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

def score_single_headline(hl):
    if not hl: return 0.0
    import torch
    tokenizer, model = _load_finbert()
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
