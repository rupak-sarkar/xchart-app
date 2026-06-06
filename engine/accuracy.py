"""Per-ticker backtest with corrected hit/miss logic.
v6.1: BULL->NEUTRAL = HIT (not against prediction)
      BEAR->NEUTRAL = HIT (not against prediction)
      Only opposite direction = MISS
Horizons: MEGA=14d LARGE=14d MID=7d SMALL=5d"""
import pandas as pd
from engine.technical import compute_tech_score, detect_mcap_scale
from engine.utils import safe_int, safe_float


# Fixed horizons per category
CATEGORY_PARAMS = {
    "MEGA":  {"forward_days": 14, "threshold": 0.8},
    "LARGE": {"forward_days": 14, "threshold": 0.8},
    "MID":   {"forward_days": 7,  "threshold": 0.5},
    "SMALL": {"forward_days": 5,  "threshold": 0.5},
}


def get_category_label(mcap):
    if mcap is not None and mcap > 100000:
        return "MEGA"
    elif mcap is not None and mcap > 30000:
        return "LARGE"
    elif mcap is not None and mcap > 10000:
        return "MID"
    else:
        return "SMALL"


def is_hit(pred_dir, actual_dir):
    """Corrected hit/miss logic.
    BULL prediction: HIT if actual is BULL or NEUTRAL (not against)
    BEAR prediction: HIT if actual is BEAR or NEUTRAL (not against)
    Only count MISS when market moves AGAINST the prediction.
    """
    if pred_dir == 1:
        return actual_dir != -1  # HIT if BULL or NEUTRAL, MISS only if BEAR
    elif pred_dir == -1:
        return actual_dir != 1   # HIT if BEAR or NEUTRAL, MISS only if BULL
    return False


def compute_per_ticker_accuracy(stock_df, mcap_threshold):
    """Backtest each ticker with corrected hit/miss logic."""
    if stock_df is None or stock_df.empty:
        return {}

    results = {}
    tickers = stock_df['Ticker'].unique()
    category_stats = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}

    for tk in tickers:
        tk_data = stock_df[stock_df['Ticker'] == tk].sort_values('Date').reset_index(drop=True)
        valid = tk_data[tk_data['Close'].notna()].reset_index(drop=True)

        if len(valid) < 30:
            continue

        last_row = valid.iloc[-1]
        mcap = safe_float(last_row.get('Market_Cap'), None)
        category = get_category_label(mcap)
        params = CATEGORY_PARAMS[category]
        forward_days = params["forward_days"]
        threshold = params["threshold"]

        if len(valid) < 25 + forward_days:
            continue

        predictions = []

        for i in range(20, len(valid) - forward_days):
            slice_start = max(0, i - 20)
            slice_df = valid.iloc[slice_start:i + 1]

            score, _, _ = compute_tech_score(slice_df, mcap_threshold)

            pred_dir = 1 if score > 20 else (-1 if score < -20 else 0)
            if pred_dir == 0:
                continue

            base_close = valid.iloc[i].get('Close')
            end_close = valid.iloc[i + forward_days].get('Close')

            if pd.isna(base_close) or pd.isna(end_close) or base_close <= 0:
                continue

            cum_ret = ((end_close - base_close) / base_close) * 100

            # 3-way actual direction
            if cum_ret > threshold:
                actual_dir = 1
            elif cum_ret < -threshold:
                actual_dir = -1
            else:
                actual_dir = 0  # NEUTRAL

            # Corrected hit logic
            hit = is_hit(pred_dir, actual_dir)

            predictions.append({
                "pred": pred_dir,
                "actual": actual_dir,
                "hit": hit,
                "score": score,
                "cum_ret": cum_ret,
                "day_idx": i,
            })

        if not predictions:
            continue

        total = len(predictions)

        # Count by outcome type
        strong_hits = sum(1 for p in predictions if p["pred"] == p["actual"])
        neutral_hits = sum(1 for p in predictions if p["hit"] and p["actual"] == 0)
        misses = sum(1 for p in predictions if not p["hit"])
        total_hits = sum(1 for p in predictions if p["hit"])

        swing = "HIT" if predictions[-1]["hit"] else "MISS"
        swing_score = predictions[-1]["score"]

        n_1m = min(22, total)
        n_3m = min(66, total)
        n_6m = total

        last_1m = predictions[-n_1m:]
        last_3m = predictions[-n_3m:]
        last_6m = predictions

        bt_1m = sum(1 for p in last_1m if p["hit"]) / len(last_1m) * 100
        bt_3m = sum(1 for p in last_3m if p["hit"]) / len(last_3m) * 100
        bt_6m = sum(1 for p in last_6m if p["hit"]) / len(last_6m) * 100

        # Strict accuracy (old way — for comparison)
        strict_hits = sum(1 for p in predictions if p["pred"] == p["actual"])
        strict_acc = strict_hits / total * 100

        # Profit factor
        hits_list = [p for p in predictions if p["hit"]]
        miss_list = [p for p in predictions if not p["hit"]]
        avg_hit_ret = sum(abs(p["cum_ret"]) for p in hits_list) / len(hits_list) if hits_list else 0
        avg_miss_ret = sum(abs(p["cum_ret"]) for p in miss_list) / len(miss_list) if miss_list else 0

        results[tk] = {
            "BT_Swing": swing,
            "BT_Swing_Score": swing_score,
            "BT_1M": round(bt_1m, 1),
            "BT_3M": round(bt_3m, 1),
            "BT_6M": round(bt_6m, 1),
            "BT_1M_N": len(last_1m),
            "BT_3M_N": len(last_3m),
            "BT_6M_N": n_6m,
            "BT_Total_Preds": total,
            "BT_Forward_Days": forward_days,
            "BT_Threshold": threshold,
            "BT_Category": category,
            "BT_Avg_Hit_Ret": round(avg_hit_ret, 2),
            "BT_Avg_Miss_Ret": round(avg_miss_ret, 2),
            "BT_Strong_Hits": strong_hits,
            "BT_Neutral_Hits": neutral_hits,
            "BT_Misses": misses,
            "BT_Strict_Acc": round(strict_acc, 1),
        }

        category_stats[category].append(bt_6m)

    # Summary
    print(f"\n  Per-category accuracy (corrected: neutral=HIT):")
    print(
        f"  {'Category':<10s} {'Tickers':>8s} {'New Acc':>8s} "
        f"{'Strict':>8s} {'Horizon':>8s} {'Thresh':>8s}"
    )
    print(f"  {'-'*54}")
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        vals = category_stats[cat]
        if vals:
            avg_new = sum(vals) / len(vals)
            cat_tickers = [tk for tk, r in results.items() if r["BT_Category"] == cat]
            avg_strict = sum(results[tk]["BT_Strict_Acc"] for tk in cat_tickers) / len(cat_tickers)
            p = CATEGORY_PARAMS[cat]
            print(
                f"  {cat:<10s} {len(vals):>8d} {avg_new:>7.1f}% "
                f"{avg_strict:>7.1f}% {p['forward_days']:>7d}d {p['threshold']:>7.1f}%"
            )

    return results


def print_accuracy_report(bt_results, scored_rows, hdf, today_rows):
    """Print accuracy report with corrected hit/miss logic."""
    print(f"\n{'='*110}")
    print(f"PREDICTION ACCURACY REPORT (v6.1 - Neutral=HIT, Fixed Horizons)")
    print(f"{'='*110}")

    if not bt_results:
        print("  No backtest results available")
        print(f"{'='*110}")
        return

    all_1m = [r["BT_1M"] for r in bt_results.values() if r["BT_1M_N"] >= 10]
    all_3m = [r["BT_3M"] for r in bt_results.values() if r["BT_3M_N"] >= 20]
    all_6m = [r["BT_6M"] for r in bt_results.values() if r["BT_6M_N"] >= 50]
    swing_hits = sum(1 for r in bt_results.values() if r["BT_Swing"] == "HIT")
    swing_total = len(bt_results)
    total_preds = sum(r["BT_Total_Preds"] for r in bt_results.values())

    # Overall outcome breakdown
    total_strong = sum(r["BT_Strong_Hits"] for r in bt_results.values())
    total_neutral = sum(r["BT_Neutral_Hits"] for r in bt_results.values())
    total_miss = sum(r["BT_Misses"] for r in bt_results.values())

    print(f"\n  -- OUTCOME BREAKDOWN ({total_preds:,} predictions) --")
    print(f"  Strong HITs (pred=actual):     {total_strong:>7,} ({total_strong/total_preds*100:.1f}%)")
    print(f"  Neutral HITs (not against):    {total_neutral:>7,} ({total_neutral/total_preds*100:.1f}%)")
    print(f"  MISSes (opposite direction):   {total_miss:>7,} ({total_miss/total_preds*100:.1f}%)")
    print(f"  Total HITs:                    {total_strong+total_neutral:>7,} ({(total_strong+total_neutral)/total_preds*100:.1f}%)")

    print(f"\n  -- MODEL ACCURACY (neutral=HIT) --")
    print(f"  Horizons: MEGA=14d LARGE=14d MID=7d SMALL=5d")
    print(f"\n  {'Horizon':<20s} {'Accuracy':>10s} {'Tickers':>10s} {'Edge vs 50%':>12s}")
    print(f"  {'-'*55}")
    if swing_total > 0:
        sp = swing_hits / swing_total * 100
        print(f"  {'Swing (last pred)':<20s} {sp:>9.1f}% {swing_total:>10d} {sp-50:>+11.1f}%")
    if all_1m:
        avg1 = sum(all_1m) / len(all_1m)
        print(f"  {'Short-term (1M)':<20s} {avg1:>9.1f}% {len(all_1m):>10d} {avg1-50:>+11.1f}%")
    if all_3m:
        avg3 = sum(all_3m) / len(all_3m)
        print(f"  {'Mid-term (3M)':<20s} {avg3:>9.1f}% {len(all_3m):>10d} {avg3-50:>+11.1f}%")
    if all_6m:
        avg6 = sum(all_6m) / len(all_6m)
        print(f"  {'Long-term (ALL)':<20s} {avg6:>9.1f}% {len(all_6m):>10d} {avg6-50:>+11.1f}%")

    # Per-category
    categories = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    strict_cats = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    for tk, r in bt_results.items():
        cat = r.get("BT_Category", "SMALL")
        if r["BT_6M_N"] >= 30:
            categories[cat].append(r["BT_6M"])
            strict_cats[cat].append(r["BT_Strict_Acc"])

    print(f"\n  -- ACCURACY BY CATEGORY (new vs strict) --")
    print(
        f"  {'Category':<10s} {'Horizon':>8s} {'New Acc':>8s} "
        f"{'Strict':>8s} {'Boost':>8s} {'Tickers':>8s}"
    )
    print(f"  {'-'*54}")
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        vals = categories[cat]
        svals = strict_cats[cat]
        if vals:
            avg_new = sum(vals) / len(vals)
            avg_strict = sum(svals) / len(svals)
            boost = avg_new - avg_strict
            h = CATEGORY_PARAMS[cat]["forward_days"]
            print(
                f"  {cat:<10s} {h:>7d}d {avg_new:>7.1f}% "
                f"{avg_strict:>7.1f}% {boost:>+7.1f}% {len(vals):>8d}"
            )

    # Profit factor
    all_hit_ret = []
    all_miss_ret = []
    for r in bt_results.values():
        if r["BT_Avg_Hit_Ret"] > 0:
            all_hit_ret.append(r["BT_Avg_Hit_Ret"])
        if r["BT_Avg_Miss_Ret"] > 0:
            all_miss_ret.append(r["BT_Avg_Miss_Ret"])
    if all_hit_ret and all_miss_ret:
        avg_hr = sum(all_hit_ret) / len(all_hit_ret)
        avg_mr = sum(all_miss_ret) / len(all_miss_ret)
        pf = avg_hr / avg_mr if avg_mr > 0 else 0
        print(f"\n  -- PROFIT FACTOR --")
        print(f"  Avg return when HIT:  {avg_hr:>6.2f}%")
        print(f"  Avg return when MISS: {avg_mr:>6.2f}%")
        print(f"  Profit Factor: {pf:.2f} {'(profitable)' if pf > 1 else '(needs work)'}")

    # Top/Bottom
    sorted_1m = sorted(bt_results.items(), key=lambda x: x[1]["BT_1M"], reverse=True)
    sorted_1m = [(tk, r) for tk, r in sorted_1m if r["BT_1M_N"] >= 10]

    if sorted_1m:
        print(f"\n  -- TOP 10 MOST PREDICTABLE --")
        print(
            f"  {'Ticker':<14s} {'Cat':>5s} {'Swing':>6s} {'1M':>7s} "
            f"{'3M':>7s} {'ALL':>7s} {'Strict':>7s} {'Preds':>6s} {'PF':>5s}"
        )
        print(f"  {'-'*70}")
        for tk, r in sorted_1m[:10]:
            pf_tk = r['BT_Avg_Hit_Ret'] / r['BT_Avg_Miss_Ret'] if r['BT_Avg_Miss_Ret'] > 0 else 0
            print(
                f"  {tk:<14s} {r['BT_Category']:>5s} {r['BT_Swing']:>6s} "
                f"{r['BT_1M']:>6.1f}% {r['BT_3M']:>6.1f}% {r['BT_6M']:>6.1f}% "
                f"{r['BT_Strict_Acc']:>6.1f}% {r['BT_Total_Preds']:>6d} {pf_tk:>4.1f}x"
            )

        print(f"\n  -- BOTTOM 10 LEAST PREDICTABLE --")
        for tk, r in sorted_1m[-10:]:
            pf_tk = r['BT_Avg_Hit_Ret'] / r['BT_Avg_Miss_Ret'] if r['BT_Avg_Miss_Ret'] > 0 else 0
            print(
                f"  {tk:<14s} {r['BT_Category']:>5s} {r['BT_Swing']:>6s} "
                f"{r['BT_1M']:>6.1f}% {r['BT_3M']:>6.1f}% {r['BT_6M']:>6.1f}% "
                f"{r['BT_Strict_Acc']:>6.1f}% {r['BT_Total_Preds']:>6d} {pf_tk:>4.1f}x"
            )

    # Distribution
    if all_6m:
        above_70 = sum(1 for v in all_6m if v >= 70)
        above_60 = sum(1 for v in all_6m if v >= 60)
        above_50 = sum(1 for v in all_6m if v >= 50)
        below_45 = sum(1 for v in all_6m if v < 45)
        print(f"\n  -- DISTRIBUTION (long-term accuracy) --")
        print(f"  >70%: {above_70}/{len(all_6m)} tickers ({above_70/len(all_6m)*100:.0f}%)")
        print(f"  >60%: {above_60}/{len(all_6m)} tickers ({above_60/len(all_6m)*100:.0f}%)")
        print(f"  >50%: {above_50}/{len(all_6m)} tickers ({above_50/len(all_6m)*100:.0f}%)")
        print(f"  <45%: {below_45}/{len(all_6m)} tickers ({below_45/len(all_6m)*100:.0f}%)")

    # Live composite
    from engine.config import TODAY_IST
    print(f"\n  -- LIVE COMPOSITE ACCURACY (from history) --")
    today_df = pd.DataFrame(today_rows)
    today_df['Date'] = TODAY_IST
    if hdf.empty or 'Date' not in hdf.columns:
        all_data = today_df
    else:
        past = hdf[hdf['Date'] != TODAY_IST]
        all_data = pd.concat([past, today_df], ignore_index=True)
    dates = sorted(all_data['Date'].unique())
    if len(dates) < 2:
        print(f"  Need 2+ trading days (have {len(dates)})")
    else:
        nd_hit = 0
        nd_dir = 0
        for i in range(len(dates) - 1):
            sr = all_data[all_data['Date'] == dates[i]]
            ar = all_data[all_data['Date'] == dates[i + 1]]
            if sr.empty or ar.empty:
                continue
            am = {}
            for _, a in ar.iterrows():
                tk = a.get('Ticker', '')
                if tk:
                    am[tk] = safe_int(a.get('Actual_Direction', 0))
            dh = 0
            dd = 0
            for _, s in sr.iterrows():
                tk = s.get('Ticker', '')
                if tk not in am:
                    continue
                pc = safe_int(s.get('Composite_Direction', s.get('Forecast_Direction', 0)))
                if pc != 0:
                    dd += 1
                    nd_dir += 1
                    actual = am[tk]
                    if is_hit(pc, actual):
                        dh += 1
                        nd_hit += 1
            if dd > 0:
                print(f"    {dates[i]} -> {dates[i+1]}: {dh}/{dd}={dh*100//dd}%")
        if nd_dir > 0:
            print(f"    AGGREGATE: {nd_hit}/{nd_dir} = {nd_hit/nd_dir*100:.1f}%")

    print(f"{'='*110}")
