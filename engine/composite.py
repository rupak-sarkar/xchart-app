"""Composite scoring + regime adjustment
v5.2.1: Directional threshold raised to ±20 for higher quality signals"""
from engine.config import WEIGHTS_NEWS, WEIGHTS_NO_NEWS

DIRECTION_THRESHOLD = 20  # was 15 — fewer but higher quality signals


def compute_composite_news(sentiment, technical, macro, fundamental):
    w = dict(WEIGHTS_NEWS)
    if technical != 0 and sentiment != 0:
        td = 1 if technical > 0 else -1
        sd = 1 if sentiment > 0 else -1
        if td == sd and abs(sentiment) > 50:
            w["technical"] += 0.05
            w["sentiment"] += 0.05
            w["macro"] -= 0.05
            w["fundamental"] -= 0.05
    comp = round(
        technical * w["technical"]
        + sentiment * w["sentiment"]
        + macro * w["macro"]
        + fundamental * w["fundamental"],
        1,
    )
    direction = 1 if comp > DIRECTION_THRESHOLD else (-1 if comp < -DIRECTION_THRESHOLD else 0)
    return {"score": comp, "direction": direction}


def compute_composite_no_news(technical, macro, fundamental=0):
    w = WEIGHTS_NO_NEWS
    cm = max(-25, min(25, macro))
    comp = round(
        technical * w["technical"]
        + cm * w["macro"]
        + fundamental * w["fundamental"],
        1,
    )
    direction = 1 if comp > DIRECTION_THRESHOLD else (-1 if comp < -DIRECTION_THRESHOLD else 0)
    return {"score": comp, "direction": direction}


def apply_regime_adjustment(comp_score, regime):
    r = regime["regime"]
    if comp_score > 0:
        if r == "BEAR":
            comp_score = round(comp_score * 0.60, 1)
        elif r == "MILD_BEAR":
            comp_score = round(comp_score * 0.80, 1)
        elif r == "BULL":
            comp_score = round(comp_score * 1.10, 1)
    elif comp_score < 0:
        if r == "BULL":
            comp_score = round(comp_score * 0.60, 1)
        elif r == "MILD_BULL":
            comp_score = round(comp_score * 0.80, 1)
        elif r == "BEAR":
            comp_score = round(comp_score * 1.10, 1)
    direction = 1 if comp_score > DIRECTION_THRESHOLD else (-1 if comp_score < -DIRECTION_THRESHOLD else 0)
    return comp_score, direction
