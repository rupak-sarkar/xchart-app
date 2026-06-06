"""Per-ticker backtest + Trade Simulation.
v6.1.1: Signal-to-signal profit calculation.
BULL->BEAR switch = close long, open short.
Neutral=HIT for direction accuracy.
Trade PF = total gains / total losses (signal-based)."""
import pandas as pd
from engine.technical import compute_tech_score, detect_mcap_scale
from engine.utils import safe_int, safe_float


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
    """Neutral=HIT logic. Only opposite = MISS."""
    if pred_dir == 1:
        return actual_dir != -1
    elif pred_dir == -1:
        return actual_dir != 1
    return False


# ═══════════════════════════════════════════════════════════════
# TRADE SIMULATION (signal-to-signal)
# ═══════════════════════════════════════════════════════════════

def simulate_trades(valid_df, mcap_threshold, score_threshold=20):
    """Simulate trades based on signal switches.

    BULL signal → enter LONG at close
    BEAR signal → exit LONG, enter SHORT at close
    NEUT signal → hold current position

    Returns list of completed trades with entry/exit/return/holding days.
    """
    if len(valid_df) < 25:
        return []

    trades = []
    current_position = 0  # 0=flat, 1=long, -1=short
    entry_price = None
    entry_date = None
    entry_idx = None
    prev_direction = 0

    for i in range(20, len(valid_df)):
        slice_start = max(0, i - 20)
        slice_df = valid_df.iloc[slice_start:i + 1]

        score, _, _ = compute_tech_score(slice_df, mcap_threshold)

        if score > score_threshold:
            new_dir = 1
        elif score < -score_threshold:
            new_dir = -1
        else:
            new_dir = 0

        close = valid_df.iloc[i].get('Close')
        date = valid_df.iloc[i].get('Date', '')

        if close is None or pd.isna(close) or close <= 0:
            continue

        # Signal switch logic
        if new_dir != 0 and new_dir != current_position:
            # Close existing position if any
            if current_position != 0 and entry_price is not None:
                if current_position == 1:
                    ret_pct = ((close - entry_price) / entry_price) * 100
                else:
                    ret_pct = ((entry_price - close) / entry_price) * 100

                holding_days = i - entry_idx if entry_idx is not None else 0

                trades.append({
                    "direction": "LONG" if current_position == 1 else "SHORT",
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(close, 2),
                    "entry_date": entry_date,
                    "exit_date": date,
                    "return_pct": round(ret_pct, 2),
                    "holding_days": holding_days,
                    "win": ret_pct > 0,
                })

            # Open new position
            current_position = new_dir
            entry_price = close
            entry_date = date
            entry_idx = i

        prev_direction = new_dir

    # Close any open position at the end
    if current_position != 0 and entry_price is not None:
        last_close = valid_df.iloc[-1].get('Close')
        last_date = valid_df.iloc[-1].get('Date', '')
        if last_close and pd.notna(last_close) and last_close > 0:
            if current_position == 1:
                ret_pct = ((last_close - entry_price) / entry_price) * 100
            else:
                ret_pct = ((entry_price - last_close) / entry_price) * 100

            holding_days = len(valid_df) - 1 - entry_idx if entry_idx is not None else 0

            trades.append({
                "direction": "LONG" if current_position == 1 else "SHORT",
                "entry_price": round(entry_price, 2),
                "exit_price": round(last_close, 2),
                "entry_date": entry_date,
                "exit_date": last_date,
                "return_pct": round(ret_pct, 2),
                "holding_days": holding_days,
                "win": ret_pct > 0,
            })

    return trades


def compute_trade_stats(trades):
    """Compute trading statistics from completed trades."""
    if not trades:
        return {}

    total = len(trades)
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    n_wins = len(wins)
    n_losses = len(losses)

    win_rate = n_wins / total * 100

    avg_win = sum(t["return_pct"] for t in wins) / n_wins if n_wins > 0 else 0
    avg_loss = abs(sum(t["return_pct"] for t in losses) / n_losses) if n_losses > 0 else 0

    total_gains = sum(t["return_pct"] for t in wins)
    total_losses = abs(sum(t["return_pct"] for t in losses))

    profit_factor = total_gains / total_losses if total_losses > 0 else 999

    avg_holding = sum(t["holding_days"] for t in trades) / total
    total_return = sum(t["return_pct"] for t in trades)

    long_trades = [t for t in trades if t["direction"] == "LONG"]
    short_trades = [t for t in trades if t["direction"] == "SHORT"]

    long_wr = sum(1 for t in long_trades if t["win"]) / len(long_trades) * 100 if long_trades else 0
    short_wr = sum(1 for t in short_trades if t["win"]) / len(short_trades) * 100 if short_trades else 0

    return {
        "total_trades": total,
        "wins": n_wins,
        "losses": n_losses,
        "win_rate": round(win_rate, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "total_return_pct": round(total_return, 2),
        "avg_holding_days": round(avg_holding, 1),
        "long_trades": len(long_trades),
        "short_trades": len(short_trades),
        "long_win_rate": round(long_wr, 1),
        "short_win_rate": round(short_wr, 1),
    }


# ═══════════════════════════════════════════════════════════════
# DIRECTIONAL ACCURACY (neutral=HIT)
# ═══════════════════════════════════════════════════════════════

def compute_per_ticker_accuracy(stock_df, mcap_threshold):
    """Backtest: direction accuracy + trade simulation."""
    if stock_df is None or stock_df.empty:
        return {}

    results = {}
    tickers = stock_df['Ticker'].unique()
    category_stats = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    category_trades = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}

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

        # ── Direction accuracy (existing) ──
        predictions = []
        if len(valid) >= 25 + forward_days:
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
                if cum_ret > threshold:
                    actual_dir = 1
                elif cum_ret < -threshold:
                    actual_dir = -1
                else:
                    actual_dir = 0

                hit = is_hit(pred_dir, actual_dir)
                predictions.append({
                    "pred": pred_dir,
                    "actual": actual_dir,
                    "hit": hit,
                    "score": score,
                    "cum_ret": cum_ret,
                    "day_idx": i,
                })

        # ── Trade simulation (signal-to-signal) ──
        trades = simulate_trades(valid, mcap_threshold)
        trade_stats = compute_trade_stats(trades)

        if not predictions:
            if trade_stats:
                results[tk] = {
                    "BT_Swing": "",
                    "BT_Swing_Score": 0,
                    "BT_1M": 0.0, "BT_3M": 0.0, "BT_6M": 0.0,
                    "BT_1M_N": 0, "BT_3M_N": 0, "BT_6M_N": 0,
                    "BT_Total_Preds": 0,
                    "BT_Forward_Days": forward_days,
                    "BT_Threshold": threshold,
                    "BT_Category": category,
                    "BT_Strong_Hits": 0, "BT_Neutral_Hits": 0, "BT_Misses": 0,
                    "BT_Strict_Acc": 0.0,
                    **{f"TR_{k}": v for k, v in trade_stats.items()},
                }
            continue

        total = len(predictions)
        strong_hits = sum(1 for p in predictions if p["pred"] == p["actual"])
        neutral_hits = sum(1 for p in predictions if p["hit"] and p["actual"] == 0)
        misses = sum(1 for p in predictions if not p["hit"])
        strict_acc = strong_hits / total * 100

        swing = "HIT" if predictions[-1]["hit"] else "MISS"
        swing_score = predictions[-1]["score"]

        n_1m = min(22, total)
        n_3m = min(66, total)

        last_1m = predictions[-n_1m:]
        last_3m = predictions[-min(n_3m, total):]
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
            "BT_6M_N": total,
            "BT_Total_Preds": total,
            "BT_Forward_Days": forward_days,
            "BT_Threshold": threshold,
            "BT_Category": category,
            "BT_Strong_Hits": strong_hits,
            "BT_Neutral_Hits": neutral_hits,
            "BT_Misses": misses,
            "BT_Strict_Acc": round(strict_acc, 1),
            **{f"TR_{k}": v for k, v in trade_stats.items()},
        }

        category_stats[category].append(bt_6m)
        if trade_stats:
            category_trades[category].append(trade_stats)

    # Summary
    print(f"\n  Per-category accuracy (corrected: neutral=HIT):")
    print(
        f"  {'Category':<10s} {'Tickers':>8s} {'Dir Acc':>8s} "
        f"{'Strict':>8s} {'Horizon':>8s}"
    )
    print(f"  {'-'*46}")
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        vals = category_stats[cat]
        if vals:
            avg_new = sum(vals) / len(vals)
            cat_tickers = [tk for tk, r in results.items() if r["BT_Category"] == cat]
            avg_strict = sum(
                results[tk]["BT_Strict_Acc"] for tk in cat_tickers
                if results[tk]["BT_Total_Preds"] > 0
            )
            n_strict = sum(1 for tk in cat_tickers if results[tk]["BT_Total_Preds"] > 0)
            avg_strict = avg_strict / n_strict if n_strict > 0 else 0
            p = CATEGORY_PARAMS[cat]
            print(
                f"  {cat:<10s} {len(vals):>8d} {avg_new:>7.1f}% "
                f"{avg_strict:>7.1f}% {p['forward_days']:>7d}d"
            )

    # Trade summary
    print(f"\n  Per-category TRADE SIMULATION (signal-to-signal):")
    print(
        f"  {'Category':<10s} {'Trades':>7s} {'WinRate':>8s} "
        f"{'AvgWin':>8s} {'AvgLoss':>8s} {'PF':>6s} "
        f"{'TotalRet':>9s} {'AvgHold':>8s}"
    )
    print(f"  {'-'*70}")
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        ct = category_trades[cat]
        if ct:
            avg_trades = sum(t["total_trades"] for t in ct) / len(ct)
            avg_wr = sum(t["win_rate"] for t in ct) / len(ct)
            avg_win = sum(t["avg_win_pct"] for t in ct) / len(ct)
            avg_loss = sum(t["avg_loss_pct"] for t in ct) / len(ct)
            total_gains = sum(
                t["avg_win_pct"] * t["wins"] for t in ct
            )
            total_losses = sum(
                t["avg_loss_pct"] * t["losses"] for t in ct
            )
            pf = total_gains / total_losses if total_losses > 0 else 0
            avg_ret = sum(t["total_return_pct"] for t in ct) / len(ct)
            avg_hold = sum(t["avg_holding_days"] for t in ct) / len(ct)
            print(
                f"  {cat:<10s} {avg_trades:>6.0f} {avg_wr:>7.1f}% "
                f"{avg_win:>7.2f}% {avg_loss:>7.2f}% {pf:>5.2f} "
                f"{avg_ret:>+8.1f}% {avg_hold:>7.1f}d"
            )

    return results


def print_accuracy_report(bt_results, scored_rows, hdf, today_rows):
    """Print accuracy + trade simulation report."""
    print(f"\n{'='*110}")
    print(f"PREDICTION ACCURACY + TRADE REPORT (v6.1.1)")
    print(f"{'='*110}")

    if not bt_results:
        print("  No backtest results available")
        print(f"{'='*110}")
        return

    total_preds = sum(r["BT_Total_Preds"] for r in bt_results.values())
    all_1m = [r["BT_1M"] for r in bt_results.values() if r["BT_1M_N"] >= 10]
    all_3m = [r["BT_3M"] for r in bt_results.values() if r["BT_3M_N"] >= 20]
    all_6m = [r["BT_6M"] for r in bt_results.values() if r["BT_6M_N"] >= 50]
    swing_hits = sum(1 for r in bt_results.values() if r["BT_Swing"] == "HIT")
    swing_total = sum(1 for r in bt_results.values() if r["BT_Swing"] != "")

    # Outcome breakdown
    total_strong = sum(r.get("BT_Strong_Hits", 0) for r in bt_results.values())
    total_neutral = sum(r.get("BT_Neutral_Hits", 0) for r in bt_results.values())
    total_miss = sum(r.get("BT_Misses", 0) for r in bt_results.values())

    if total_preds > 0:
        print(f"\n  -- OUTCOME BREAKDOWN ({total_preds:,} directional predictions) --")
        print(f"  Strong HITs (pred=actual):     {total_strong:>7,} ({total_strong/total_preds*100:.1f}%)")
        print(f"  Neutral HITs (not against):    {total_neutral:>7,} ({total_neutral/total_preds*100:.1f}%)")
        print(f"  MISSes (opposite direction):   {total_miss:>7,} ({total_miss/total_preds*100:.1f}%)")

    # Direction accuracy
    print(f"\n  -- DIRECTION ACCURACY (neutral=HIT) --")
    print(f"  {'Horizon':<20s} {'Accuracy':>10s} {'Tickers':>10s} {'Edge':>10s}")
    print(f"  {'-'*53}")
    if swing_total > 0:
        sp = swing_hits / swing_total * 100
        print(f"  {'Swing (last)':<20s} {sp:>9.1f}% {swing_total:>10d} {sp-50:>+9.1f}%")
    if all_1m:
        a = sum(all_1m) / len(all_1m)
        print(f"  {'Short-term (1M)':<20s} {a:>9.1f}% {len(all_1m):>10d} {a-50:>+9.1f}%")
    if all_3m:
        a = sum(all_3m) / len(all_3m)
        print(f"  {'Mid-term (3M)':<20s} {a:>9.1f}% {len(all_3m):>10d} {a-50:>+9.1f}%")
    if all_6m:
        a = sum(all_6m) / len(all_6m)
        print(f"  {'Long-term (ALL)':<20s} {a:>9.1f}% {len(all_6m):>10d} {a-50:>+9.1f}%")

    # Per-category direction
    categories = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    strict_cats = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    for tk, r in bt_results.items():
        cat = r.get("BT_Category", "SMALL")
        if r.get("BT_6M_N", 0) >= 30:
            categories[cat].append(r["BT_6M"])
            strict_cats[cat].append(r.get("BT_Strict_Acc", 0))

    print(f"\n  -- DIRECTION BY CATEGORY --")
    print(
        f"  {'Category':<10s} {'New Acc':>8s} {'Strict':>8s} "
        f"{'Boost':>8s} {'Tickers':>8s}"
    )
    print(f"  {'-'*45}")
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        vals = categories[cat]
        svals = strict_cats[cat]
        if vals:
            avg_new = sum(vals) / len(vals)
            avg_strict = sum(svals) / len(svals)
            print(
                f"  {cat:<10s} {avg_new:>7.1f}% {avg_strict:>7.1f}% "
                f"{avg_new-avg_strict:>+7.1f}% {len(vals):>8d}"
            )

    # ═══ TRADE SIMULATION REPORT ═══
    has_trades = any(r.get("TR_total_trades", 0) > 0 for r in bt_results.values())
    if has_trades:
        print(f"\n  {'='*90}")
        print(f"  TRADE SIMULATION (signal-to-signal: BULL entry -> BEAR exit)")
        print(f"  {'='*90}")

        # Overall trade stats
        all_trades_count = sum(r.get("TR_total_trades", 0) for r in bt_results.values())
        all_wins = sum(r.get("TR_wins", 0) for r in bt_results.values())
        all_losses = sum(r.get("TR_losses", 0) for r in bt_results.values())
        overall_wr = all_wins / all_trades_count * 100 if all_trades_count > 0 else 0

        print(f"\n  Total trades: {all_trades_count:,}")
        print(f"  Win rate: {all_wins}/{all_trades_count} = {overall_wr:.1f}%")

        # Per-category trade stats
        print(f"\n  {'Category':<10s} {'Trades':>7s} {'WinRate':>8s} {'AvgWin':>8s} {'AvgLoss':>8s} {'PF':>6s} {'AvgRet':>8s} {'Hold':>6s}")
        print(f"  {'-'*68}")
        for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
            cat_rs = [r for r in bt_results.values()
                      if r.get("BT_Category") == cat and r.get("TR_total_trades", 0) > 0]
            if not cat_rs:
                continue
            n = len(cat_rs)
            tot_t = sum(r["TR_total_trades"] for r in cat_rs)
            tot_w = sum(r["TR_wins"] for r in cat_rs)
            tot_l = sum(r["TR_losses"] for r in cat_rs)
            wr = tot_w / tot_t * 100 if tot_t > 0 else 0
            avg_w = sum(r["TR_avg_win_pct"] for r in cat_rs) / n
            avg_l = sum(r["TR_avg_loss_pct"] for r in cat_rs) / n
            total_g = sum(r["TR_avg_win_pct"] * r["TR_wins"] for r in cat_rs)
            total_ls = sum(r["TR_avg_loss_pct"] * r["TR_losses"] for r in cat_rs)
            pf = total_g / total_ls if total_ls > 0 else 0
            avg_ret = sum(r["TR_total_return_pct"] for r in cat_rs) / n
            avg_hold = sum(r["TR_avg_holding_days"] for r in cat_rs) / n
            print(
                f"  {cat:<10s} {tot_t:>7d} {wr:>7.1f}% "
                f"{avg_w:>7.2f}% {avg_l:>7.2f}% {pf:>5.2f} "
                f"{avg_ret:>+7.1f}% {avg_hold:>5.1f}d"
            )

        # Long vs Short
        all_long = sum(r.get("TR_long_trades", 0) for r in bt_results.values())
        all_short = sum(r.get("TR_short_trades", 0) for r in bt_results.values())
        long_wrs = [r["TR_long_win_rate"] for r in bt_results.values() if r.get("TR_long_trades", 0) > 0]
        short_wrs = [r["TR_short_win_rate"] for r in bt_results.values() if r.get("TR_short_trades", 0) > 0]
        avg_long_wr = sum(long_wrs) / len(long_wrs) if long_wrs else 0
        avg_short_wr = sum(short_wrs) / len(short_wrs) if short_wrs else 0

        print(f"\n  LONG trades:  {all_long:>6d} | Avg win rate: {avg_long_wr:.1f}%")
        print(f"  SHORT trades: {all_short:>6d} | Avg win rate: {avg_short_wr:.1f}%")

        # Top/Bottom by trade PF
        sorted_pf = sorted(
            [(tk, r) for tk, r in bt_results.items() if r.get("TR_total_trades", 0) >= 5],
            key=lambda x: x[1].get("TR_profit_factor", 0),
            reverse=True,
        )
        if sorted_pf:
            print(f"\n  -- TOP 10 MOST PROFITABLE (by Trade PF) --")
            print(
                f"  {'Ticker':<14s} {'Cat':>5s} {'Trades':>7s} {'WinR':>6s} "
                f"{'AvgW':>7s} {'AvgL':>7s} {'PF':>6s} {'TotRet':>8s} {'Hold':>6s}"
            )
            print(f"  {'-'*75}")
            for tk, r in sorted_pf[:10]:
                print(
                    f"  {tk:<14s} {r['BT_Category']:>5s} "
                    f"{r['TR_total_trades']:>7d} {r['TR_win_rate']:>5.1f}% "
                    f"{r['TR_avg_win_pct']:>6.2f}% {r['TR_avg_loss_pct']:>6.2f}% "
                    f"{r['TR_profit_factor']:>5.2f} "
                    f"{r['TR_total_return_pct']:>+7.1f}% "
                    f"{r['TR_avg_holding_days']:>5.1f}d"
                )

            print(f"\n  -- BOTTOM 10 LEAST PROFITABLE --")
            for tk, r in sorted_pf[-10:]:
                print(
                    f"  {tk:<14s} {r['BT_Category']:>5s} "
                    f"{r['TR_total_trades']:>7d} {r['TR_win_rate']:>5.1f}% "
                    f"{r['TR_avg_win_pct']:>6.2f}% {r['TR_avg_loss_pct']:>6.2f}% "
                    f"{r['TR_profit_factor']:>5.2f} "
                    f"{r['TR_total_return_pct']:>+7.1f}% "
                    f"{r['TR_avg_holding_days']:>5.1f}d"
                )

    # Distribution
    if all_6m:
        above_60 = sum(1 for v in all_6m if v >= 60)
        above_50 = sum(1 for v in all_6m if v >= 50)
        below_45 = sum(1 for v in all_6m if v < 45)
        print(f"\n  -- DISTRIBUTION (direction accuracy) --")
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
