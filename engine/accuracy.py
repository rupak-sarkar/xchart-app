"""Per-ticker backtest accuracy with DYNAMIC horizons based on market cap.
Mega/Large caps get longer horizons, small caps get shorter ones.
Uses the SAME compute_tech_score() as live prediction."""
import pandas as pd
from engine.technical import compute_tech_score, detect_mcap_scale
from engine.utils import safe_int, safe_float


def get_dynamic_params(mcap, adx=None, price=None):
    """Determine forward_days and return_threshold based on stock characteristics.

    Returns: (forward_days, threshold_pct)
    """
    # Base horizon and threshold by market cap
    if mcap is not None and mcap > 100000:
        # Mega cap: >1 Lakh Cr
        fwd = 7; thresh = 0.3
    elif mcap is not None and mcap > 30000:
        # Large cap: 30K-1L Cr
        fwd = 5; thresh = 0.4
    elif mcap is not None and mcap > 10000:
        # Mid cap: 10K-30K Cr
        fwd = 3; thresh = 0.5
    else:
        # Small cap: <10K Cr (or unknown)
        fwd = 2; thresh = 0.8

    # ADX modifier: strong trend = let it develop longer
    if adx is not None:
        if adx > 35:
            fwd += 1  # strong trend needs time
        elif adx < 15:
            fwd = max(2, fwd - 1)  # no trend, resolve quickly

    # Price modifier: expensive stocks move less in %
    if price is not None:
        if price > 5000:
            thresh *= 0.8
        elif price < 200:
            thresh *= 1.5

    # Clamp
    fwd = max(2, min(10, fwd))
    thresh = max(0.2, min(1.5, round(thresh, 2)))

    return fwd, thresh


def get_category_label(mcap):
    """Human-readable category"""
    if mcap is not None and mcap > 100000:
        return "MEGA"
    elif mcap is not None and mcap > 30000:
        return "LARGE"
    elif mcap is not None and mcap > 10000:
        return "MID"
    else:
        return "SMALL"


def compute_per_ticker_accuracy(stock_df, mcap_threshold):
    """Backtest each ticker using DYNAMIC forward horizons based on market cap.
    Returns: dict {ticker: {BT_Swing, BT_1M, BT_3M, BT_6M, ...}}"""
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

        # Get market cap and price for dynamic params
        last_row = valid.iloc[-1]
        mcap = safe_float(last_row.get('Market_Cap'), None)
        price = safe_float(last_row.get('Close'), None)
        last_adx = safe_float(last_row.get('ADX_14'), None)

        # Get dynamic forward days and threshold
        forward_days, threshold = get_dynamic_params(mcap, last_adx, price)
        category = get_category_label(mcap)

        if len(valid) < 25 + forward_days:
            continue

        predictions = []

        for i in range(20, len(valid) - forward_days):
            # 21-row slice for scoring
            slice_start = max(0, i - 20)
            slice_df = valid.iloc[slice_start:i + 1]

            score, _ = compute_tech_score(slice_df, mcap_threshold)
            pred_dir = 1 if score > 15 else (-1 if score < -15 else 0)
            if pred_dir == 0:
                continue

            # Dynamic cumulative return over forward_days
            cum_ret = 0.0
            for d in range(1, forward_days + 1):
                idx = i + d
                if idx < len(valid):
                    dc = valid.iloc[idx].get('Close')
                    dp = valid.iloc[idx - 1].get('Close')
                    if pd.notna(dc) and pd.notna(dp) and dp > 0:
                        cum_ret += ((dc - dp) / dp) * 100

            # Dynamic threshold
            actual_dir = 1 if cum_ret > threshold else (-1 if cum_ret < -threshold else 0)
            hit = pred_dir == actual_dir
            predictions.append({
                "pred": pred_dir, "actual": actual_dir,
                "hit": hit, "score": score, "day_idx": i
            })

        if not predictions:
            continue

        total = len(predictions)

        # Swing: last prediction
        swing = "HIT" if predictions[-1]["hit"] else "MISS"
        swing_score = predictions[-1]["score"]

        # Horizons by count of directional predictions
        n_1m = min(22, total)
        n_3m = min(66, total)
        n_6m = total

        last_1m = predictions[-n_1m:]
        last_3m = predictions[-n_3m:]
        last_6m = predictions

        bt_1m = sum(1 for p in last_1m if p["hit"]) / len(last_1m) * 100
        bt_3m = sum(1 for p in last_3m if p["hit"]) / len(last_3m) * 100
        bt_6m = sum(1 for p in last_6m if p["hit"]) / len(last_6m) * 100

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
        }

        category_stats[category].append(bt_6m)

    # Print category summary
    print(f"\n  Per-category accuracy (long-term):")
    print(f"  {'Category':<10s} {'Tickers':>8s} {'Avg Acc':>8s} {'Horizon':>8s} {'Thresh':>8s}")
    print(f"  {'-'*45}")
    cat_params = {"MEGA": (7, 0.3), "LARGE": (5, 0.4), "MID": (3, 0.5), "SMALL": (2, 0.8)}
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        vals = category_stats[cat]
        if vals:
            avg = sum(vals) / len(vals)
            h, t = cat_params[cat]
            print(f"  {cat:<10s} {len(vals):>8d} {avg:>7.1f}% {h:>7d}d {t:>7.1f}%")

    return results


def print_accuracy_report(bt_results, scored_rows, hdf, today_rows):
    """Print comprehensive accuracy report with dynamic horizons"""
    print(f"\n{'='*110}")
    print(f"PREDICTION ACCURACY REPORT (v5.2 - Dynamic Horizon Backtest)")
    print(f"{'='*110}")

    if not bt_results:
        print("  No backtest results available")
        print(f"{'='*110}")
        return

    # Overall stats
    all_1m = [r["BT_1M"] for r in bt_results.values() if r["BT_1M_N"] >= 10]
    all_3m = [r["BT_3M"] for r in bt_results.values() if r["BT_3M_N"] >= 20]
    all_6m = [r["BT_6M"] for r in bt_results.values() if r["BT_6M_N"] >= 50]
    swing_hits = sum(1 for r in bt_results.values() if r["BT_Swing"] == "HIT")
    swing_total = len(bt_results)
    total_preds = sum(r["BT_Total_Preds"] for r in bt_results.values())

    print(f"\n  -- MODEL ACCURACY (dynamic horizon per market cap) --")
    print(f"  Total backtest predictions: {total_preds:,}")
    print(f"  Horizons: MEGA=7d LARGE=5d MID=3d SMALL=2d (±ADX/Price modifier)")
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

    # Per-category breakdown
    categories = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    for tk, r in bt_results.items():
        cat = r.get("BT_Category", "SMALL")
        if r["BT_6M_N"] >= 30:
            categories[cat].append(r["BT_6M"])

    print(f"\n  -- ACCURACY BY MARKET CAP CATEGORY --")
    print(f"  {'Category':<10s} {'Horizon':>8s} {'Thresh':>8s} {'Tickers':>8s} {'Avg Acc':>8s} {'Edge':>8s}")
    print(f"  {'-'*55}")
    cat_params = {"MEGA": ("7d", "0.3%"), "LARGE": ("5d", "0.4%"), "MID": ("3d", "0.5%"), "SMALL": ("2d", "0.8%")}
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        vals = categories[cat]
        if vals:
            avg = sum(vals) / len(vals)
            h, t = cat_params[cat]
            print(f"  {cat:<10s} {h:>8s} {t:>8s} {len(vals):>8d} {avg:>7.1f}% {avg-50:>+7.1f}%")

    # Top/Bottom performers
    sorted_1m = sorted(bt_results.items(), key=lambda x: x[1]["BT_1M"], reverse=True)
    sorted_1m = [(tk, r) for tk, r in sorted_1m if r["BT_1M_N"] >= 10]

    if sorted_1m:
        print(f"\n  -- TOP 10 MOST PREDICTABLE --")
        print(f"  {'Ticker':<14s} {'Cat':>5s} {'Swing':>6s} {'1M':>7s} {'3M':>7s} {'ALL':>7s} {'Preds':>6s} {'Fwd':>4s}")
        print(f"  {'-'*60}")
        for tk, r in sorted_1m[:10]:
            print(f"  {tk:<14s} {r['BT_Category']:>5s} {r['BT_Swing']:>6s} {r['BT_1M']:>6.1f}% {r['BT_3M']:>6.1f}% {r['BT_6M']:>6.1f}% {r['BT_Total_Preds']:>6d} {r['BT_Forward_Days']:>3d}d")

        print(f"\n  -- BOTTOM 10 LEAST PREDICTABLE --")
        for tk, r in sorted_1m[-10:]:
            print(f"  {tk:<14s} {r['BT_Category']:>5s} {r['BT_Swing']:>6s} {r['BT_1M']:>6.1f}% {r['BT_3M']:>6.1f}% {r['BT_6M']:>6.1f}% {r['BT_Total_Preds']:>6d} {r['BT_Forward_Days']:>3d}d")

    # Distribution
    if all_6m:
        above_55 = sum(1 for v in all_6m if v >= 55)
        above_50 = sum(1 for v in all_6m if v >= 50)
        below_45 = sum(1 for v in all_6m if v < 45)
        print(f"\n  -- DISTRIBUTION (long-term accuracy) --")
        print(f"  >55%: {above_55}/{len(all_6m)} tickers ({above_55/len(all_6m)*100:.0f}%)")
        print(f"  >50%: {above_50}/{len(all_6m)} tickers ({above_50/len(all_6m)*100:.0f}%)")
        print(f"  <45%: {below_45}/{len(all_6m)} tickers ({below_45/len(all_6m)*100:.0f}%)")

    # Live composite accuracy
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
                    if pc == actual:
                        dh += 1
                        nd_hit += 1
            if dd > 0:
                print(f"    {dates[i]} -> {dates[i+1]}: {dh}/{dd}={dh*100//dd}%")
        if nd_dir > 0:
            print(f"    AGGREGATE: {nd_hit}/{nd_dir} = {nd_hit/nd_dir*100:.1f}%")

        if len(dates) >= 4:
            print(f"\n  3-Day Cumulative (PRIMARY):")
            th = 0
            td = 0
            for i in range(len(dates) - 3):
                for _, s in all_data[all_data['Date'] == dates[i]].iterrows():
                    tk = s.get('Ticker', '')
                    pc = safe_int(s.get('Composite_Direction', s.get('Forecast_Direction', 0)))
                    if pc == 0:
                        continue
                    cr = 0.0
                    found = False
                    for j in range(i + 1, min(i + 4, len(dates))):
                        dr = all_data[(all_data['Date'] == dates[j]) & (all_data['Ticker'] == tk)]
                        if not dr.empty:
                            try:
                                cr += float(dr.iloc[0].get('Actual_Return_Pct', 0.0))
                            except:
                                pass
                            found = True
                    if not found:
                        continue
                    ad = 1 if cr > 0.5 else (-1 if cr < -0.5 else 0)
                    td += 1
                    if pc == ad:
                        th += 1
            if td > 0:
                print(f"    3-day: {th}/{td} = {th/td*100:.1f}%")
            else:
                print(f"    Not enough data yet")

    print(f"{'='*110}")
