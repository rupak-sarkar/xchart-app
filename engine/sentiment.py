"""FinBERT scoring v7.1 — catalyst-first, relaxed noise filter"""
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


def _has_catalyst_keyword(text):
    """Check if text contains any material catalyst keyword."""
    for catalyst in MATERIAL_CATALYST_KEYWORDS:
        if catalyst in text:
            return True
    return False


def _has_noise_pattern(text):
    """Check if text matches a noise pattern."""
    for noise in NOISE_HEADLINE_PATTERNS:
        if noise in text:
            return True
    return False


def _has_monetary_amount(text):
    """Check for monetary amounts like Rs 500 crore, $2 billion, etc."""
    return bool(re.search(
        r'(?:rs\.?|inr|₹|\$|usd)\s*[\d,]+\s*(?:crore|cr|million|mn|billion|bn|lakh)',
        text
    ))


def is_material_catalyst(headline):
    """v7.1 — Catalyst-first check. Catalyst keywords override noise patterns.

    Priority order:
    1. If headline has a catalyst keyword → CATALYST (even if it also has noise words)
    2. If headline has monetary amounts → CATALYST
    3. If headline has catalyst verbs + numbers → CATALYST
    4. If headline has sector impact words → CATALYST
    5. If headline is pure noise (no catalyst at all) → NOISE
    6. Default → CATALYST (let FinBERT decide sentiment)
    """
    if not headline:
        return False
    text = headline.lower()

    # ── Step 1: Catalyst keywords ALWAYS win ──
    if _has_catalyst_keyword(text):
        return True

    # ── Step 2: Monetary amounts are always material ──
    if _has_monetary_amount(text):
        return True

    # ── Step 3: Catalyst verb + number = material ──
    words = set(re.findall(r'[a-z]+', text))
    if bool(words & CATALYST_VERBS) and bool(re.search(r'\d+', text)):
        return True

    # ── Step 4: Catalyst verb alone (without number) is still useful ──
    if bool(words & CATALYST_VERBS):
        return True

    # ── Step 5: Sector impact words are material ──
    if bool(words & SECTOR_IMPACT_WORDS):
        return True

    # ── Step 6: NOW check noise — only if nothing above matched ──
    if _has_noise_pattern(text):
        return False

    # ── Step 7: Default — let it through, FinBERT will score it ──
    # If a headline made it through RSS matching to a ticker,
    # it's likely relevant. Let FinBERT decide the sentiment.
    return True


def classify_headline(headline, actual_return=None):
    """Classify headline as reporting vs predictive."""
    text = headline.lower()
    words = set(re.findall(r'[a-z]+', text))

    # % match with actual return = pure reporting
    pct_matches = re.findall(r'(\d+\.?\d*)\s*%', text)
    if pct_matches and actual_return is not None:
        for ps in pct_matches:
            try:
                if abs(float(ps) - abs(actual_return)) < 3.0:
                    return "reporting", "% match"
            except:
                pass

    has_rv = bool(words & REPORTING_VERBS)
    has_pc = bool(words & PRICE_CONTEXT)
    has_pct = bool(re.search(r'\d+\.?\d*\s*%', text))

    # Strict reporting: needs all three (verb + context + %)
    if has_rv and has_pc and has_pct:
        return "reporting", "verb+context+%"

    # Reporting verb + price context (e.g., "shares surged today")
    if has_rv and has_pc:
        # But if it also has catalyst keywords, it's predictive
        if _has_catalyst_keyword(text):
            return "predictive", "catalyst+reporting"
        return "reporting", "verb+context"

    # Catalyst verb = predictive
    if bool(words & CATALYST_VERBS):
        return "predictive", "catalyst"

    # Sector impact = predictive
    if bool(words & SECTOR_IMPACT_WORDS):
        return "predictive", "sector"

    # Reporting verb + % but no price context — could go either way
    if has_rv and has_pct:
        if _has_catalyst_keyword(text):
            return "predictive", "catalyst+pct"
        return "reporting", "verb+%"

    # NSE actionable
    for kw in NSE_ACTIONABLE_KEYWORDS:
        if kw in text:
            return "predictive", "actionable"

    return "predictive", "default"


def classify_nse_headline(hl):
    """Classify NSE announcement as actionable or noise."""
    t = hl.lower()
    for kw in NSE_ACTIONABLE_KEYWORDS:
        if kw in t:
            return "actionable"
    for kw in NSE_NOISE_KEYWORDS:
        if kw in t:
            return "noise"
    return "noise"


def classify_severity(s):
    """Classify sentiment score severity."""
    if s >= 60:
        return "Very Bullish"
    elif s >= 25:
        return "Bullish"
    elif s >= 5:
        return "Mildly Bullish"
    elif s >= -5:
        return "Neutral"
    elif s >= -25:
        return "Mildly Bearish"
    elif s >= -60:
        return "Bearish"
    else:
        return "Very Bearish"


def classify_impact(entries):
    """Classify time impact of news entries."""
    c = " ".join(e["headline"] for e in entries).lower()
    s = sum(1 for kw in SHORT_TERM_KEYWORDS if kw in c)
    l = sum(1 for kw in LONG_TERM_KEYWORDS if kw in c)
    if s > 0 and l > 0:
        return "Both"
    elif l > 0:
        return "Long-term"
    elif s > 0:
        return "Short-term"
    return "Short-term"


def classify_composite_severity(s):
    """Classify composite score severity."""
    if s >= 40:
        return "Strong Buy"
    elif s >= 20:
        return "Buy"
    elif s >= 8:
        return "Mild Buy"
    elif s >= -8:
        return "Neutral"
    elif s >= -20:
        return "Mild Sell"
    elif s >= -40:
        return "Sell"
    else:
        return "Strong Sell"


def score_single_headline(hl):
    """Score a single headline with FinBERT."""
    if not hl:
        return 0.0
    import torch
    tokenizer, model = _load_finbert()
    try:
        i = tokenizer([hl], padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad():
            o = model(**i)
        p = torch.nn.functional.softmax(o.logits, dim=-1)
        return (p[0][0].item() - p[0][1].item()) * 100.0
    except:
        return 0.0


def compute_aggregated_score(entries):
    """Compute aggregated FinBERT score from catalyst entries.

    v7.1: More headlines pass through → better signal diversity.
    Returns: (score, direction, catalyst_count, noise_count)
    """
    if not entries:
        return 0.0, 0, 0, 0

    catalyst_entries = [e for e in entries if is_material_catalyst(e["headline"])]
    noise_count = len(entries) - len(catalyst_entries)
    catalyst_count = len(catalyst_entries)

    if not catalyst_entries:
        # v7.1: If ALL headlines were filtered, score the best-weighted one anyway
        # This prevents zero-scoring when we have relevant headlines
        if entries:
            best = max(entries, key=lambda e: e.get("weight", 1.0))
            r = score_single_headline(best["headline"])
            if abs(r) > 10:  # Only if FinBERT has a strong opinion
                direction = 1 if r > 5 else (-1 if r < -5 else 0)
                return round(r * 0.5, 1), direction, 0, noise_count  # Dampened
        return 0.0, 0, catalyst_count, noise_count

    tw = 0.0
    ws = 0.0
    for e in catalyst_entries:
        r = score_single_headline(e["headline"])
        w = e.get("weight", 1.0)
        ws += r * w
        tw += w

    if tw == 0:
        return 0.0, 0, catalyst_count, noise_count

    s = ws / tw
    direction = 1 if s > 5 else (-1 if s < -5 else 0)
    return round(s, 1), direction, catalyst_count, noise_count
