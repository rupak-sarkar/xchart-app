"""Per-ticker backtest + Trade Simulation v6.2.
Hysteresis: Entry ±25, Exit ±30 (sticky signals).
Stop-loss: -3% within 3 days.
Min hold: 3 days (no whipsaw).
Neutral=HIT for direction accuracy."""
import pandas as pd
from engine.technical import compute_tech_score, detect_mcap_scale
from engine.utils import safe_int, safe_float


CATEGORY_PARAMS = {
    "MEGA":  {"forward_days": 14, "threshold": 0.8},
    "LARGE": {"forward_days": 14, "threshold": 0.8},
    "MID":   {"forward_days": 7,  "threshold": 0.5},
    "SMALL": {"forward_days": 5,  "threshold": 0.5},
}

# Trade parameters
ENTRY_THRESHOLD = 25      # Need score > +25 to go LONG, < -25 to go SHORT
EXIT_THRESHOLD = 30       # Need score < -30 to exit LONG, > +30 to exit SHORT
MIN_HOLD_DAYS = 3         # Minimum days before allowing signal flip
STOP_LOSS_PCT = -3.0      # Cut losers at -3%
STOP_LOSS_CHECK_DAY = 3   # Check stop-loss after this many days


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
    """Neutral=HIT. Only opposite = MISS."""
    if pred_dir == 1:
        return actual_dir != -1
    elif pred_dir == -1:
        return actual_dir != 1
    return False


def simulate_trades(valid_df, mcap_threshold):
    """Trade simulation with hysteresis + stop-loss.

    ENTRY: Score must exceed ±ENTRY_THRESHOLD to open position.
    EXIT:  Score must exceed ±EXIT_THRESHOLD in OPPOSITE direction
           OR stop-loss triggered at STOP_LOSS_PCT after STOP_LOSS_CHECK_DAY.
    HOLD:  Minimum MIN_HOLD_DAYS before any exit allowed.
    NEUTRAL zone: If score between thresholds, HOLD current position.

    Returns list of completed trades.
    """
    if len(valid_df) < 25:
        return []

    trades = []
    current_position = 0    # 0=flat, 1=long, -1=short
    entry_price = None
    entry_date = None
    entry_idx = None

    for i in range(20, len(valid_df)):
        slice_start = max(0, i - 20)
        slice_df = valid_df.iloc[slice_start:i + 1]

        score, _, _ = compute_tech_score(slice_df, mcap_threshold)

        close = valid_df.iloc[i].get('Close')
        date = valid_df.iloc[i].get('Date', '')

        if close is None or pd.isna(close) or close <= 0:
            continue

        holding_days = (i - entry_idx) if entry_idx is not None else 0

        # ── CHECK STOP-LOSS (if in position) ──
        if current_position != 0 and entry_price is not None:
            if holding_days >= STOP_LOSS_CHECK_DAY:
                if current_position == 1:
                    unrealized = ((close - entry_price) / entry_price) * 100
                else:
                    unrealized = ((entry_price - close) / entry_price) * 100

                if unrealized <= STOP_LOSS_PCT:
                    # Stop-loss triggered — close position
                    trades.append({
                        "direction": "LONG" if current_position == 1 else "SHORT",
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(close, 2),
                        "entry_date": entry_date,
                        "exit_date": date,
                        "return_pct": round(unrealized, 2),
                        "holding_days": holding_days,
                        "win": False,
                        "exit_reason": "STOP_LOSS",
                    })
                    current_position = 0
                    entry_price = None
                    entry_date = None
                    entry_idx = None
                    continue

        # ── SIGNAL LOGIC WITH HYSTERESIS ──

        if current_position == 0:
            # FLAT — need strong signal to enter
            if score > ENTRY_THRESHOLD:
                current_position = 1
                entry_price = close
                entry_date = date
                entry_idx = i
            elif score < -ENTRY_THRESHOLD:
                current_position = -1
                entry_price = close
                entry_date = date
                entry_idx = i

        elif current_position == 1:
            # LONG — need strong OPPOSITE signal to exit
            # Must hold minimum days
            if holding_days < MIN_HOLD_DAYS:
                continue

            if score < -EXIT_THRESHOLD:
                # Strong bear signal — exit long, enter short
                ret_pct = ((close - entry_price) / entry_price) * 100
                trades.append({
                    "direction": "LONG",
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(close, 2),
                    "entry_date": entry_date,
                    "exit_date": date,
                    "return_pct": round(ret_pct, 2),
                    "holding_days": holding_days,
                    "win": ret_pct > 0,
                    "exit_reason": "SIGNAL_FLIP",
                })
                # Enter short
                current_position = -1
                entry_price = close
                entry_date = date
                entry_idx = i

        elif current_position == -1:
            # SHORT — need strong OPPOSITE signal to exit
            if holding_days < MIN_HOLD_DAYS:
                continue

            if score > EXIT_THRESHOLD:
                # Strong bull signal — exit short, enter long
                ret_pct = ((entry_price - close) / entry_price) * 100
                trades.append({
                    "direction": "SHORT",
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(close, 2),
                    "entry_date": entry_date,
                    "exit_date": date,
                    "return_pct": round(ret_pct, 2),
                    "holding_days": holding_days,
                    "win": ret_pct > 0,
                    "exit_reason": "SIGNAL_FLIP",
                })
                # Enter long
                current_position = 1
                entry_price = close
                entry_date = date
                entry_idx = i

    # Close any open position at end
    if current_position != 0 and entry_price is not None:
        last_close = valid_df.iloc[-1].get('Close')
        last_date = valid_df.iloc[-1].get('Date', '')
        if last_close and pd.notna(last_close) and last_close > 0:
            holding_days = len(valid_df) - 1 - entry_idx if entry_idx is not None else 0
            if current_position == 1:
                ret_pct = ((last_close - entry_price) / entry_price) * 100
            else:
                ret_pct = ((entry_price - last_close) / entry_price) * 100
            trades.append({
                "direction": "LONG" if current_position == 1 else "SHORT",
                "entry_price": round(entry_price, 2),
                "exit_price": round(last_close, 2),
                "entry_date": entry_date,
                "exit_date": last_date,
                "return_pct": round(ret_pct, 2),
                "holding_days": holding_days,
                "win": ret_pct > 0,
                "exit_reason": "END_OF_DATA",
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

    long_wr = (
        sum(1 for t in long_trades if t["win"]) / len(long_trades) * 100
        if long_trades else 0
    )
    short_wr = (
        sum(1 for t in short_trades if t["win"]) / len(short_trades) * 100
        if short_trades else 0
    )

    # Stop-loss stats
    sl_trades = [t for t in trades if t.get("exit_reason") == "STOP_LOSS"]
    signal_trades = [t for t in trades if t.get("exit_reason") == "SIGNAL_FLIP"]

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
        "stop_loss_exits": len(sl_trades),
        "signal_flip_exits": len(signal_trades),
    }


def compute_per_ticker_accuracy(stock_df, mcap_threshold):
    """Backtest: direction accuracy + trade simulation."""
    if stock_df is None or stock_df.empty:
        return {}

    results = {}
    tickers = stock_df['Ticker'].unique()
    category_stats = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    category_trades = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}

    for tk in tickers:
        tk_data = (
            stock_df[stock_df['Ticker'] == tk]
            .sort_values('Date')
            .reset_index(drop=True)
        )
        valid = tk_data[tk_data['Close'].notna()].reset_index(drop=True)

        if len(valid) < 30:
            continue

        last_row = valid.iloc[-1]
        mcap = safe_float(last_row.get('Market_Cap'), None)
        category = get_category_label(mcap)
        params = CATEGORY_PARAMS[category]
        forward_days = params["forward_days"]
        threshold = params["threshold"]

        # ── Direction accuracy ──
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

        # ── Trade simulation ──
        trades = simulate_trades(valid, mcap_threshold)
        trade_stats = compute_trade_stats(trades)

        if not predictions and not trade_stats:
            continue

        total = len(predictions) if predictions else 0
        strong_hits = sum(1 for p in predictions if p["pred"] == p["actual"]) if predictions else 0
        neutral_hits = sum(1 for p in predictions if p["hit"] and p["actual"] == 0) if predictions else 0
        misses = sum(1 for p in predictions if not p["hit"]) if predictions else 0
        strict_acc = strong_hits / total * 100 if total > 0 else 0

        swing = ""
        swing_score = 0
        bt_1m = 0.0
        bt_3m = 0.0
        bt_6m = 0.0
        n_1m = 0
        n_3m = 0

        if predictions:
            swing = "HIT" if predictions[-1]["hit"] else "MISS"
            swing_score = predictions[-1]["score"]
            n_1m = min(22, total)
            n_3m = min(66, total)
            last_1m = predictions[-n_1m:]
            last_3m = predictions[-n_3m:]
            bt_1m = sum(1 for p in last_1m if p["hit"]) / len(last_1m) * 100
            bt_3m = sum(1 for p in last_3m if p["hit"]) / len(last_3m) * 100
            bt_6m = sum(1 for p in predictions if p["hit"]) / total * 100

        results[tk] = {
            "BT_Swing": swing,
            "BT_Swing_Score": swing_score,
            "BT_1M": round(bt_1m, 1),
            "BT_3M": round(bt_3m, 1),
            "BT_6M": round(bt_6m, 1),
            "BT_1M_N": n_1m,
            "BT_3M_N": n_3m,
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

        if total > 0:
            category_stats[category].append(bt_6m)
        if trade_stats:
            category_trades[category].append(trade_stats)

    # Direction summary
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
            cat_tickers = [
                tk for tk, r in results.items()
                if r["BT_Category"] == cat and r["BT_Total_Preds"] > 0
            ]
            n_strict = len(cat_tickers)
            avg_strict = (
                sum(results[tk]["BT_Strict_Acc"] for tk in cat_tickers) / n_strict
                if n_strict > 0 else 0
            )
            p = CATEGORY_PARAMS[cat]
            print(
                f"  {cat:<10s} {len(vals):>8d} {avg_new:>7.1f}% "
                f"{avg_strict:>7.1f}% {p['forward_days']:>7d}d"
            )

    # Trade summary
    print(f"\n  Per-category TRADE SIMULATION (hysteresis + stop-loss):")
    print(f"  Entry:±{ENTRY_THRESHOLD} Exit:±{EXIT_THRESHOLD} MinHold:{MIN_HOLD_DAYS}d SL:{STOP_LOSS_PCT}%@{STOP_LOSS_CHECK_DAY}d")
    print(
        f"  {'Category':<10s} {'Trades':>7s} {'WinRate':>8s} "
        f"{'AvgWin':>8s} {'AvgLoss':>8s} {'PF':>6s} "
        f"{'TotalRet':>9s} {'AvgHold':>8s} {'SL%':>5s}"
    )
    print(f"  {'-'*75}")
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        ct = category_trades[cat]
        if not ct:
            continue
        n = len(ct)
        tot_t = sum(t["total_trades"] for t in ct)
        tot_w = sum(t["wins"] for t in ct)
        wr = tot_w / tot_t * 100 if tot_t > 0 else 0
        avg_w = sum(t["avg_win_pct"] for t in ct) / n
        avg_l = sum(t["avg_loss_pct"] for t in ct) / n
        total_g = sum(t["avg_win_pct"] * t["wins"] for t in ct)
        total_ls = sum(t["avg_loss_pct"] * t["losses"] for t in ct)
        pf = total_g / total_ls if total_ls > 0 else 0
        avg_ret = sum(t["total_return_pct"] for t in ct) / n
        avg_hold = sum(t["avg_holding_days"] for t in ct) / n
        tot_sl = sum(t.get("stop_loss_exits", 0) for t in ct)
        sl_pct = tot_sl / tot_t * 100 if tot_t > 0 else 0
        print(
            f"  {cat:<10s} {tot_t:>7d} {wr:>7.1f}% "
            f"{avg_w:>7.2f}% {avg_l:>7.2f}% {pf:>5.2f} "
            f"{avg_ret:>+8.1f}% {avg_hold:>7.1f}d {sl_pct:>4.1f}%"
        )

    return results


def print_accuracy_report(bt_results, scored_rows, hdf, today_rows):
    """Print accuracy + trade report."""
    print(f"\n{'='*110}")
    print(f"PREDICTION ACCURACY + TRADE REPORT (v6.2 Hysteresis + Stop-Loss)")
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
        print(f"  TRADE SIMULATION (Hysteresis Entry:±{ENTRY_THRESHOLD} Exit:±{EXIT_THRESHOLD} MinHold:{MIN_HOLD_DAYS}d SL:{STOP_LOSS_PCT}%)")
        print(f"  {'='*90}")

        all_trades_count = sum(r.get("TR_total_trades", 0) for r in bt_results.values())
        all_wins = sum(r.get("TR_wins", 0) for r in bt_results.values())
        all_losses = sum(r.get("TR_losses", 0) for r in bt_results.values())
        all_sl = sum(r.get("TR_stop_loss_exits", 0) for r in bt_results.values())
        all_flip = sum(r.get("TR_signal_flip_exits", 0) for r in bt_results.values())
        overall_wr = all_wins / all_trades_count * 100 if all_trades_count > 0 else 0

        print(f"\n  Total trades: {all_trades_count:,}")
        print(f"  Win rate: {all_wins}/{all_trades_count} = {overall_wr:.1f}%")
        print(f"  Exits: {all_flip} signal flips | {all_sl} stop-losses")

        # Per-category
        print(
            f"\n  {'Category':<10s} {'Trades':>7s} {'WinR':>6s} "
            f"{'AvgWin':>8s} {'AvgLoss':>8s} {'PF':>6s} "
            f"{'AvgRet':>8s} {'Hold':>6s} {'SL':>5s}"
        )
        print(f"  {'-'*70}")
        for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
            cat_rs = [
                r for r in bt_results.values()
                if r.get("BT_Category") == cat and r.get("TR_total_trades", 0) > 0
            ]
            if not cat_rs:
                continue
            n = len(cat_rs)
            tot_t = sum(r["TR_total_trades"] for r in cat_rs)
            tot_w = sum(r["TR_wins"] for r in cat_rs)
            wr = tot_w / tot_t * 100 if tot_t > 0 else 0
            avg_w = sum(r["TR_avg_win_pct"] for r in cat_rs) / n
            avg_l = sum(r["TR_avg_loss_pct"] for r in cat_rs) / n
            total_g = sum(r["TR_avg_win_pct"] * r["TR_wins"] for r in cat_rs)
            total_ls = sum(r["TR_avg_loss_pct"] * r["TR_losses"] for r in cat_rs)
            pf = total_g / total_ls if total_ls > 0 else 0
            avg_ret = sum(r["TR_total_return_pct"] for r in cat_rs) / n
            avg_hold = sum(r["TR_avg_holding_days"] for r in cat_rs) / n
            tot_sl = sum(r.get("TR_stop_loss_exits", 0) for r in cat_rs)
            sl_pct = tot_sl / tot_t * 100 if tot_t > 0 else 0
            print(
                f"  {cat:<10s} {tot_t:>7d} {wr:>5.1f}% "
                f"{avg_w:>7.2f}% {avg_l:>7.2f}% {pf:>5.2f} "
                f"{avg_ret:>+7.1f}% {avg_hold:>5.1f}d {sl_pct:>4.1f}%"
            )

        # Long vs Short
        all_long = sum(r.get("TR_long_trades", 0) for r in bt_results.values())
        all_short = sum(r.get("TR_short_trades", 0) for r in bt_results.values())
        long_wrs = [
            r["TR_long_win_rate"] for r in bt_results.values()
            if r.get("TR_long_trades", 0) > 0
        ]
        short_wrs = [
            r["TR_short_win_rate"] for r in bt_results.values()
            if r.get("TR_short_trades", 0) > 0
        ]
        avg_long_wr = sum(long_wrs) / len(long_wrs) if long_wrs else 0
        avg_short_wr = sum(short_wrs) / len(short_wrs) if short_wrs else 0

        print(f"\n  LONG trades:  {all_long:>6d} | Avg win rate: {avg_long_wr:.1f}%")
        print(f"  SHORT trades: {all_short:>6d} | Avg win rate: {avg_short_wr:.1f}%")

        # Top/Bottom by PF
        sorted_pf = sorted(
            [
                (tk, r) for tk, r in bt_results.items()
                if r.get("TR_total_trades", 0) >= 5
            ],
            key=lambda x: x[1].get("TR_profit_factor", 0),
            reverse=True,
        )
        if sorted_pf:
            print(f"\n  -- TOP 10 MOST PROFITABLE (by Trade PF) --")
            print(
                f"  {'Ticker':<14s} {'Cat':>5s} {'Trades':>7s} {'WinR':>6s} "
                f"{'AvgW':>7s} {'AvgL':>7s} {'PF':>6s} {'TotRet':>8s} "
                f"{'Hold':>6s} {'SL':>4s}"
            )
            print(f"  {'-'*80}")
            for tk, r in sorted_pf[:10]:
                sl_n = r.get('TR_stop_loss_exits', 0)
                print(
                    f"  {tk:<14s} {r['BT_Category']:>5s} "
                    f"{r['TR_total_trades']:>7d} {r['TR_win_rate']:>5.1f}% "
                    f"{r['TR_avg_win_pct']:>6.2f}% {r['TR_avg_loss_pct']:>6.2f}% "
                    f"{r['TR_profit_factor']:>5.2f} "
                    f"{r['TR_total_return_pct']:>+7.1f}% "
                    f"{r['TR_avg_holding_days']:>5.1f}d {sl_n:>4d}"
                )

            print(f"\n  -- BOTTOM 10 LEAST PROFITABLE --")
            for tk, r in sorted_pf[-10:]:
                sl_n = r.get('TR_stop_loss_exits', 0)
                print(
                    f"  {tk:<14s} {r['BT_Category']:>5s} "
                    f"{r['TR_total_trades']:>7d} {r['TR_win_rate']:>5.1f}% "
                    f"{r['TR_avg_win_pct']:>6.2f}% {r['TR_avg_loss_pct']:>6.2f}% "
                    f"{r['TR_profit_factor']:>5.2f} "
                    f"{r['TR_total_return_pct']:>+7.1f}% "
                    f"{r['TR_avg_holding_days']:>5.1f}d {sl_n:>4d}"
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
                pc = safe_int(
                    s.get('Composite_Direction', s.get('Forecast_Direction', 0))
                )
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
