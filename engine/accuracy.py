"""Per-ticker backtest accuracy across 4 horizons + overall model report.
Uses the SAME compute_tech_score() as live prediction.
Backtest window: ALL available data (target 365+ predictions per ticker)"""
import pandas as pd
from engine.technical import compute_tech_score, detect_mcap_scale
from engine.utils import safe_int


def compute_per_ticker_accuracy(stock_df, mcap_threshold, forward_days=3):
    """Backtest each ticker using ALL available data for 365+ predictions.
    Returns: dict {ticker: {BT_Swing, BT_1M, BT_3M, BT_6M, ...}}"""
    if stock_df is None or stock_df.empty:
        return {}

    results = {}
    tickers = stock_df['Ticker'].unique()
    total_preds = 0
    total_hits = 0

    for tk in tickers:
        tk_data = stock_df[stock_df['Ticker'] == tk].sort_values('Date').reset_index(drop=True)
        valid = tk_data[tk_data['Close'].notna()].reset_index(drop=True)
        # Need at least warmup + forward days
        if len(valid) < 25 + forward_days:
            continue

        predictions = []

        # Start from day 20 (warmup) and go through ALL available data
        for i in range(20, len(valid) - forward_days):
            # Slice: 21 rows (matches S/R 20-day window)
            slice_start = max(0, i - 20)
            slice_df = valid.iloc[slice_start:i + 1]

            score, _ = compute_tech_score(slice_df, mcap_threshold)
            pred_dir = 1 if score > 15 else (-1 if score < -15 else 0)
            if pred_dir == 0:
                continue

            # 3-day cumulative return
            cum_ret = 0.0
            for d in range(1, forward_days + 1):
                idx = i + d
                if idx < len(valid):
                    dc = valid.iloc[idx].get('Close')
                    dp = valid.iloc[idx - 1].get('Close')
                    if pd.notna(dc) and pd.notna(dp) and dp > 0:
                        cum_ret += ((dc - dp) / dp) * 100

            actual_dir = 1 if cum_ret > 0.5 else (-1 if cum_ret < -0.5 else 0)
            hit = pred_dir == actual_dir
            predictions.append({"pred": pred_dir, "actual": actual_dir, "hit": hit, "score": score, "day_idx": i})

        if not predictions:
            continue

        total = len(predictions)
        total_preds += total
        total_hits += sum(1 for p in predictions if p["hit"])

        # Swing: last prediction result
        swing = "HIT" if predictions[-1]["hit"] else "MISS"
        swing_score = predictions[-1]["score"]

        # Horizons (by number of directional predictions)
        # 1M ≈ 22 trading days of directional predictions
        # 3M ≈ 66
        # 6M = all available
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
        }

    return results


def print_accuracy_report(bt_results, scored_rows, hdf, today_rows):
    """Print comprehensive accuracy report"""
    print(f"\n{'='*110}")
    print(f"PREDICTION ACCURACY REPORT (v5.1.1 — Multi-Horizon Backtest)")
    print(f"{'='*110}")

    if not bt_results:
        print("  No backtest results available")
        print(f"{'='*110}")
        return

    # ── Overall Model Stats ──
    all_1m = [r["BT_1M"] for r in bt_results.values() if r["BT_1M_N"] >= 10]
    all_3m = [r["BT_3M"] for r in bt_results.values() if r["BT_3M_N"] >= 20]
    all_6m = [r["BT_6M"] for r in bt_results.values() if r["BT_6M_N"] >= 50]
    swing_hits = sum(1 for r in bt_results.values() if r["BT_Swing"] == "HIT")
    swing_total = len(bt_results)
    total_preds = sum(r["BT_Total_Preds"] for r in bt_results.values())

    print(f"\n  -- MODEL ACCURACY BY HORIZON (3-day forward, tech scoring) --")
    print(f"  Total backtest predictions: {total_preds:,}")
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

    # ── Top/Bottom Performers ──
    sorted_1m = sorted(bt_results.items(), key=lambda x: x[1]["BT_1M"], reverse=True)
    sorted_1m = [(tk, r) for tk, r in sorted_1m if r["BT_1M_N"] >= 10]

    if sorted_1m:
        print(f"\n  -- TOP 10 MOST PREDICTABLE (1M accuracy) --")
        print(f"  {'Ticker':<14s} {'Swing':>6s} {'1M':>7s} {'3M':>7s} {'ALL':>7s} {'Preds':>7s}")
        print(f"  {'-'*52}")
        for tk, r in sorted_1m[:10]:
            print(f"  {tk:<14s} {r['BT_Swing']:>6s} {r['BT_1M']:>6.1f}% {r['BT_3M']:>6.1f}% {r['BT_6M']:>6.1f}% {r['BT_Total_Preds']:>7d}")

        print(f"\n  -- BOTTOM 10 LEAST PREDICTABLE --")
        for tk, r in sorted_1m[-10:]:
            print(f"  {tk:<14s} {r['BT_Swing']:>6s} {r['BT_1M']:>6.1f}% {r['BT_3M']:>6.1f}% {r['BT_6M']:>6.1f}% {r['BT_Total_Preds']:>7d}")

    # ── Distribution ──
    if all_6m:
        above_55 = sum(1 for v in all_6m if v >= 55)
        above_50 = sum(1 for v in all_6m if v >= 50)
        below_45 = sum(1 for v in all_6m if v < 45)
        print(f"\n  -- DISTRIBUTION (long-term accuracy) --")
        print(f"  >55% accuracy: {above_55}/{len(all_6m)} tickers ({above_55/len(all_6m)*100:.0f}%)")
        print(f"  >50% accuracy: {above_50}/{len(all_6m)} tickers ({above_50/len(all_6m)*100:.0f}%)")
        print(f"  <45% accuracy: {below_45}/{len(all_6m)} tickers ({below_45/len(all_6m)*100:.0f}%)")

    # ── Live Composite Accuracy (from history.csv) ──
    from engine.config import TODAY_IST
    print(f"\n  -- LIVE COMPOSITE ACCURACY (from history) --")
    today_df = pd.DataFrame(today_rows); today_df['Date'] = TODAY_IST
    if hdf.empty or 'Date' not in hdf.columns:
        all_data = today_df
    else:
        past = hdf[hdf['Date'] != TODAY_IST]
        all_data = pd.concat([past, today_df], ignore_index=True)
    dates = sorted(all_data['Date'].unique())
    if len(dates) < 2:
        print(f"  Need 2+ trading days (have {len(dates)})")
    else:
        nd_hit = 0; nd_dir = 0
        for i in range(len(dates) - 1):
            sr = all_data[all_data['Date'] == dates[i]]
            ar = all_data[all_data['Date'] == dates[i + 1]]
            if sr.empty or ar.empty: continue
            am = {}
            for _, a in ar.iterrows():
                tk = a.get('Ticker', '')
                if tk: am[tk] = safe_int(a.get('Actual_Direction', 0))
            dh = 0; dd = 0
            for _, s in sr.iterrows():
                tk = s.get('Ticker', '')
                if tk not in am: continue
                pc = safe_int(s.get('Composite_Direction', s.get('Forecast_Direction', 0)))
                if pc != 0:
                    dd += 1; nd_dir += 1
                    actual = am[tk]
                    if pc == actual:
                        dh += 1; nd_hit += 1
            if dd > 0: print(f"    {dates[i]} -> {dates[i+1]}: {dh}/{dd}={dh*100//dd}%")
        if nd_dir > 0: print(f"    AGGREGATE: {nd_hit}/{nd_dir} = {nd_hit/nd_dir*100:.1f}%")

        if len(dates) >= 4:
            print(f"\n  3-Day Cumulative (PRIMARY):")
            th = 0; td = 0
            for i in range(len(dates) - 3):
                for _, s in all_data[all_data['Date'] == dates[i]].iterrows():
                    tk = s.get('Ticker', '')
                    pc = safe_int(s.get('Composite_Direction', s.get('Forecast_Direction', 0)))
                    if pc == 0: continue
                    cr = 0.0; found = False
                    for j in range(i + 1, min(i + 4, len(dates))):
                        dr = all_data[(all_data['Date'] == dates[j]) & (all_data['Ticker'] == tk)]
                        if not dr.empty:
                            try: cr += float(dr.iloc[0].get('Actual_Return_Pct', 0.0))
                            except: pass
                            found = True
                    if not found: continue
                    ad = 1 if cr > 0.5 else (-1 if cr < -0.5 else 0)
                    td += 1
                    if pc == ad: th += 1
            if td > 0: print(f"    3-day: {th}/{td} = {th/td*100:.1f}%")
            else: print(f"    Not enough data yet")

    print(f"{'='*110}")
