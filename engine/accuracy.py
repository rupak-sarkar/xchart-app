"""Per-ticker backtest + Trade Simulation v6.3.
Dynamic ATR threshold for neutral band.
ATR-based stop-loss (volatile stocks get wider SL).
Hysteresis: Entry ±25, Exit ±30.
Min hold: 3 days. Neutral=HIT."""
import numpy as np
import pandas as pd
from engine.technical import compute_tech_score, detect_mcap_scale
from engine.utils import safe_int, safe_float


CATEGORY_PARAMS = {
    "MEGA":  {"forward_days": 14},
    "LARGE": {"forward_days": 14},
    "MID":   {"forward_days": 7},
    "SMALL": {"forward_days": 5},
}

# Trade parameters
ENTRY_THRESHOLD = 25
EXIT_THRESHOLD = 30
MIN_HOLD_DAYS = 3

# ATR-based stop-loss
# SL = -SL_ATR_MULT × ATR_pct × sqrt(STOP_LOSS_CHECK_DAY)
SL_ATR_MULT = 1.5
STOP_LOSS_CHECK_DAY = 3
SL_MIN = -2.0    # minimum SL (tightest)
SL_MAX = -12.0   # maximum SL (widest)

# ATR for neutral threshold
ATR_MULTIPLIER = 0.2
ATR_LOOKBACK = 20


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
    if pred_dir == 1:
        return actual_dir != -1
    elif pred_dir == -1:
        return actual_dir != 1
    return False


def compute_atr_pct(valid_df, idx, lookback=ATR_LOOKBACK):
    """ATR as % of close. No look-ahead."""
    if idx < lookback or idx >= len(valid_df):
        return None
    start = max(0, idx - lookback + 1)
    window = valid_df.iloc[start:idx + 1]
    if len(window) < 5:
        return None
    if 'High' not in window.columns or 'Low' not in window.columns:
        return None
    highs = window['High'].values
    lows = window['Low'].values
    closes = window['Close'].values
    if len(highs) < 2:
        return None
    true_ranges = []
    for j in range(1, len(highs)):
        h, l, pc = highs[j], lows[j], closes[j - 1]
        if pd.isna(h) or pd.isna(l) or pd.isna(pc) or pc <= 0:
            continue
        true_ranges.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not true_ranges:
        return None
    atr = np.mean(true_ranges)
    cc = closes[-1]
    if pd.isna(cc) or cc <= 0:
        return None
    return (atr / cc) * 100


def get_dynamic_threshold(atr_pct, forward_days):
    if atr_pct is None or atr_pct <= 0:
        return 1.5
    threshold = atr_pct * np.sqrt(forward_days) * ATR_MULTIPLIER
    return max(0.5, min(8.0, round(threshold, 2)))


def get_dynamic_stop_loss(atr_pct):
    """ATR-based stop-loss threshold.
    SL = -SL_ATR_MULT × ATR_pct × sqrt(STOP_LOSS_CHECK_DAY)
    Clamped between SL_MIN and SL_MAX.

    Examples:
      MEGA  ATR=1.2%: SL = -1.5×1.2×1.73 = -3.1%
      LARGE ATR=1.8%: SL = -1.5×1.8×1.73 = -4.7%
      MID   ATR=2.2%: SL = -1.5×2.2×1.73 = -5.7%
      SMALL ATR=3.5%: SL = -1.5×3.5×1.73 = -9.1%
    """
    if atr_pct is None or atr_pct <= 0:
        return -5.0  # fallback
    sl = -SL_ATR_MULT * atr_pct * np.sqrt(STOP_LOSS_CHECK_DAY)
    return max(SL_MAX, min(SL_MIN, round(sl, 1)))


def get_ticker_atr_pct(valid_df, lookback=ATR_LOOKBACK):
    if len(valid_df) < lookback + 1:
        return None
    return compute_atr_pct(valid_df, len(valid_df) - 1, lookback)


def simulate_trades(valid_df, mcap_threshold):
    """Trade simulation with hysteresis + ATR-based stop-loss."""
    if len(valid_df) < 25:
        return [], {}

    trades = []
    current_position = 0
    entry_price = None
    entry_date = None
    entry_idx = None
    entry_sl = -5.0  # will be set dynamically at entry

    for i in range(20, len(valid_df)):
        slice_start = max(0, i - 20)
        slice_df = valid_df.iloc[slice_start:i + 1]
        score, _, _ = compute_tech_score(slice_df, mcap_threshold)

        close = valid_df.iloc[i].get('Close')
        date = valid_df.iloc[i].get('Date', '')
        if close is None or pd.isna(close) or close <= 0:
            continue

        holding_days = (i - entry_idx) if entry_idx is not None else 0

        # ATR-based stop-loss check
        if current_position != 0 and entry_price is not None:
            if holding_days >= STOP_LOSS_CHECK_DAY:
                if current_position == 1:
                    unrealized = ((close - entry_price) / entry_price) * 100
                else:
                    unrealized = ((entry_price - close) / entry_price) * 100

                if unrealized <= entry_sl:
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
                        "stop_loss_level": entry_sl,
                    })
                    current_position = 0
                    entry_price = None
                    entry_date = None
                    entry_idx = None
                    continue

        # Signal logic with hysteresis
        if current_position == 0:
            if score > ENTRY_THRESHOLD or score < -ENTRY_THRESHOLD:
                # Compute ATR-based stop-loss at ENTRY
                atr = compute_atr_pct(valid_df, i)
                entry_sl = get_dynamic_stop_loss(atr)

                current_position = 1 if score > ENTRY_THRESHOLD else -1
                entry_price = close
                entry_date = date
                entry_idx = i

        elif current_position == 1:
            if holding_days < MIN_HOLD_DAYS:
                continue
            if score < -EXIT_THRESHOLD:
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
                    "stop_loss_level": entry_sl,
                })
                atr = compute_atr_pct(valid_df, i)
                entry_sl = get_dynamic_stop_loss(atr)
                current_position = -1
                entry_price = close
                entry_date = date
                entry_idx = i

        elif current_position == -1:
            if holding_days < MIN_HOLD_DAYS:
                continue
            if score > EXIT_THRESHOLD:
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
                    "stop_loss_level": entry_sl,
                })
                atr = compute_atr_pct(valid_df, i)
                entry_sl = get_dynamic_stop_loss(atr)
                current_position = 1
                entry_price = close
                entry_date = date
                entry_idx = i

    # Close open position
    if current_position != 0 and entry_price is not None:
        lc = valid_df.iloc[-1].get('Close')
        ld = valid_df.iloc[-1].get('Date', '')
        if lc and pd.notna(lc) and lc > 0:
            hd = len(valid_df) - 1 - entry_idx if entry_idx else 0
            rp = (((lc - entry_price) / entry_price) * 100
                  if current_position == 1
                  else ((entry_price - lc) / entry_price) * 100)
            trades.append({
                "direction": "LONG" if current_position == 1 else "SHORT",
                "entry_price": round(entry_price, 2),
                "exit_price": round(lc, 2),
                "entry_date": entry_date,
                "exit_date": ld,
                "return_pct": round(rp, 2),
                "holding_days": hd,
                "win": rp > 0,
                "exit_reason": "END_OF_DATA",
                "stop_loss_level": entry_sl,
            })

    # Aggregate SL stats
    sl_levels = [t["stop_loss_level"] for t in trades if "stop_loss_level" in t]
    sl_info = {
        "avg_sl": round(np.mean(sl_levels), 1) if sl_levels else -5.0,
        "min_sl": round(min(sl_levels), 1) if sl_levels else -5.0,
        "max_sl": round(max(sl_levels), 1) if sl_levels else -5.0,
    }

    return trades, sl_info


def compute_trade_stats(trades):
    if not trades:
        return {}
    total = len(trades)
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    nw = len(wins)
    nl = len(losses)
    wr = nw / total * 100
    aw = sum(t["return_pct"] for t in wins) / nw if nw > 0 else 0
    al = abs(sum(t["return_pct"] for t in losses) / nl) if nl > 0 else 0
    tg = sum(t["return_pct"] for t in wins)
    tl = abs(sum(t["return_pct"] for t in losses))
    pf = tg / tl if tl > 0 else 999
    ah = sum(t["holding_days"] for t in trades) / total
    tr = sum(t["return_pct"] for t in trades)
    lt = [t for t in trades if t["direction"] == "LONG"]
    st = [t for t in trades if t["direction"] == "SHORT"]
    lwr = sum(1 for t in lt if t["win"]) / len(lt) * 100 if lt else 0
    swr = sum(1 for t in st if t["win"]) / len(st) * 100 if st else 0
    sl_exits = [t for t in trades if t.get("exit_reason") == "STOP_LOSS"]
    sf_exits = [t for t in trades if t.get("exit_reason") == "SIGNAL_FLIP"]
    return {
        "total_trades": total, "wins": nw, "losses": nl,
        "win_rate": round(wr, 1),
        "avg_win_pct": round(aw, 2), "avg_loss_pct": round(al, 2),
        "profit_factor": round(pf, 2), "total_return_pct": round(tr, 2),
        "avg_holding_days": round(ah, 1),
        "long_trades": len(lt), "short_trades": len(st),
        "long_win_rate": round(lwr, 1), "short_win_rate": round(swr, 1),
        "stop_loss_exits": len(sl_exits),
        "signal_flip_exits": len(sf_exits),
    }


def compute_per_ticker_accuracy(stock_df, mcap_threshold):
    """Backtest: dynamic ATR direction + ATR stop-loss trades."""
    if stock_df is None or stock_df.empty:
        return {}

    results = {}
    tickers = stock_df['Ticker'].unique()
    cat_stats = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    cat_trades = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    cat_thresholds = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    cat_atrs = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    cat_sls = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}

    for tk in tickers:
        tk_data = (
            stock_df[stock_df['Ticker'] == tk]
            .sort_values('Date').reset_index(drop=True)
        )
        valid = tk_data[tk_data['Close'].notna()].reset_index(drop=True)
        if len(valid) < 30:
            continue

        mcap = safe_float(valid.iloc[-1].get('Market_Cap'), None)
        category = get_category_label(mcap)
        fwd = CATEGORY_PARAMS[category]["forward_days"]
        ticker_atr = get_ticker_atr_pct(valid)
        ticker_sl = get_dynamic_stop_loss(ticker_atr)

        if ticker_atr is not None:
            cat_atrs[category].append(ticker_atr)
            cat_sls[category].append(ticker_sl)

        # Direction accuracy
        predictions = []
        thresholds_used = []
        if len(valid) >= 25 + fwd:
            for i in range(20, len(valid) - fwd):
                ss = max(0, i - 20)
                sc, _, _ = compute_tech_score(valid.iloc[ss:i + 1], mcap_threshold)
                pd_dir = 1 if sc > 20 else (-1 if sc < -20 else 0)
                if pd_dir == 0:
                    continue
                atr = compute_atr_pct(valid, i)
                thr = get_dynamic_threshold(atr, fwd)
                thresholds_used.append(thr)
                bc = valid.iloc[i].get('Close')
                ec = valid.iloc[i + fwd].get('Close')
                if pd.isna(bc) or pd.isna(ec) or bc <= 0:
                    continue
                cr = ((ec - bc) / bc) * 100
                ad = 1 if cr > thr else (-1 if cr < -thr else 0)
                predictions.append({
                    "pred": pd_dir, "actual": ad,
                    "hit": is_hit(pd_dir, ad),
                    "score": sc, "cum_ret": cr,
                    "threshold": thr, "day_idx": i,
                })

        # Trade simulation
        trades, sl_info = simulate_trades(valid, mcap_threshold)
        ts = compute_trade_stats(trades)

        if not predictions and not ts:
            continue

        total = len(predictions)
        sh = sum(1 for p in predictions if p["pred"] == p["actual"]) if predictions else 0
        nh = sum(1 for p in predictions if p["hit"] and p["actual"] == 0) if predictions else 0
        ms = sum(1 for p in predictions if not p["hit"]) if predictions else 0
        sa = sh / total * 100 if total > 0 else 0
        avg_t = sum(thresholds_used) / len(thresholds_used) if thresholds_used else 1.5

        swing = ""
        swing_score = 0
        b1 = b3 = b6 = 0.0
        n1 = n3 = 0
        if predictions:
            swing = "HIT" if predictions[-1]["hit"] else "MISS"
            swing_score = predictions[-1]["score"]
            n1 = min(22, total)
            n3 = min(66, total)
            b1 = sum(1 for p in predictions[-n1:] if p["hit"]) / n1 * 100
            b3 = sum(1 for p in predictions[-n3:] if p["hit"]) / n3 * 100
            b6 = sum(1 for p in predictions if p["hit"]) / total * 100

        results[tk] = {
            "BT_Swing": swing, "BT_Swing_Score": swing_score,
            "BT_1M": round(b1, 1), "BT_3M": round(b3, 1), "BT_6M": round(b6, 1),
            "BT_1M_N": n1, "BT_3M_N": n3, "BT_6M_N": total,
            "BT_Total_Preds": total, "BT_Forward_Days": fwd,
            "BT_Threshold": round(avg_t, 2),
            "BT_ATR_Pct": round(ticker_atr, 2) if ticker_atr else 0,
            "BT_SL_Level": round(ticker_sl, 1),
            "BT_Category": category,
            "BT_Strong_Hits": sh, "BT_Neutral_Hits": nh,
            "BT_Misses": ms, "BT_Strict_Acc": round(sa, 1),
            **{f"TR_{k}": v for k, v in ts.items()},
        }
        if total > 0:
            cat_stats[category].append(b6)
            cat_thresholds[category].append(avg_t)
        if ts:
            cat_trades[category].append(ts)

    # Summary
    print(f"\n  Per-category accuracy (dynamic ATR threshold, neutral=HIT):")
    print(
        f"  {'Cat':<8s} {'N':>4s} {'DirAcc':>7s} {'Strict':>7s} "
        f"{'ATR%':>6s} {'Thresh':>7s} {'SL':>6s} {'Fwd':>4s}"
    )
    print(f"  {'-'*52}")
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        vals = cat_stats[cat]
        if not vals:
            continue
        avg_new = sum(vals) / len(vals)
        ct = [tk for tk, r in results.items()
              if r["BT_Category"] == cat and r["BT_Total_Preds"] > 0]
        avg_strict = sum(results[t]["BT_Strict_Acc"] for t in ct) / len(ct) if ct else 0
        avg_atr = sum(cat_atrs[cat]) / len(cat_atrs[cat]) if cat_atrs[cat] else 0
        avg_th = sum(cat_thresholds[cat]) / len(cat_thresholds[cat]) if cat_thresholds[cat] else 0
        avg_sl = sum(cat_sls[cat]) / len(cat_sls[cat]) if cat_sls[cat] else 0
        f = CATEGORY_PARAMS[cat]["forward_days"]
        print(
            f"  {cat:<8s} {len(vals):>4d} {avg_new:>6.1f}% {avg_strict:>6.1f}% "
            f"{avg_atr:>5.2f}% ±{avg_th:>5.2f}% {avg_sl:>5.1f}% {f:>3d}d"
        )

    print(f"\n  Per-category TRADE SIMULATION (ATR stop-loss):")
    print(
        f"  Entry:±{ENTRY_THRESHOLD} Exit:±{EXIT_THRESHOLD} "
        f"MinHold:{MIN_HOLD_DAYS}d SL: {SL_ATR_MULT}×ATR×√{STOP_LOSS_CHECK_DAY}"
    )
    print(
        f"  {'Cat':<8s} {'Trades':>7s} {'WinR':>6s} {'AvgW':>7s} "
        f"{'AvgL':>7s} {'PF':>6s} {'TotRet':>8s} {'Hold':>6s} "
        f"{'SL%':>5s} {'AvgSL':>6s}"
    )
    print(f"  {'-'*72}")
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        ct = cat_trades[cat]
        if not ct:
            continue
        n = len(ct)
        tot_t = sum(t["total_trades"] for t in ct)
        tot_w = sum(t["wins"] for t in ct)
        wr = tot_w / tot_t * 100 if tot_t > 0 else 0
        aw = sum(t["avg_win_pct"] for t in ct) / n
        al = sum(t["avg_loss_pct"] for t in ct) / n
        tg = sum(t["avg_win_pct"] * t["wins"] for t in ct)
        tl = sum(t["avg_loss_pct"] * t["losses"] for t in ct)
        pf = tg / tl if tl > 0 else 0
        ar = sum(t["total_return_pct"] for t in ct) / n
        ah = sum(t["avg_holding_days"] for t in ct) / n
        tot_sl = sum(t.get("stop_loss_exits", 0) for t in ct)
        sl_p = tot_sl / tot_t * 100 if tot_t > 0 else 0
        avg_sl = sum(cat_sls[cat]) / len(cat_sls[cat]) if cat_sls[cat] else 0
        print(
            f"  {cat:<8s} {tot_t:>7d} {wr:>5.1f}% {aw:>6.2f}% "
            f"{al:>6.2f}% {pf:>5.2f} {ar:>+7.1f}% {ah:>5.1f}d "
            f"{sl_p:>4.1f}% {avg_sl:>5.1f}%"
        )

    return results


def print_accuracy_report(bt_results, scored_rows, hdf, today_rows):
    print(f"\n{'='*110}")
    print(f"PREDICTION + TRADE REPORT (v6.3 ATR-SL + Hysteresis)")
    print(f"{'='*110}")

    if not bt_results:
        print("  No results")
        print(f"{'='*110}")
        return

    tp = sum(r["BT_Total_Preds"] for r in bt_results.values())
    a1 = [r["BT_1M"] for r in bt_results.values() if r["BT_1M_N"] >= 10]
    a3 = [r["BT_3M"] for r in bt_results.values() if r["BT_3M_N"] >= 20]
    a6 = [r["BT_6M"] for r in bt_results.values() if r["BT_6M_N"] >= 50]
    sh = sum(1 for r in bt_results.values() if r["BT_Swing"] == "HIT")
    st = sum(1 for r in bt_results.values() if r["BT_Swing"] != "")
    ts = sum(r.get("BT_Strong_Hits", 0) for r in bt_results.values())
    tn = sum(r.get("BT_Neutral_Hits", 0) for r in bt_results.values())
    tm = sum(r.get("BT_Misses", 0) for r in bt_results.values())

    if tp > 0:
        print(f"\n  -- OUTCOME BREAKDOWN ({tp:,} predictions) --")
        print(f"  Strong HITs:   {ts:>7,} ({ts/tp*100:.1f}%)")
        print(f"  Neutral HITs:  {tn:>7,} ({tn/tp*100:.1f}%)")
        print(f"  MISSes:        {tm:>7,} ({tm/tp*100:.1f}%)")

    all_atrs = [r["BT_ATR_Pct"] for r in bt_results.values() if r.get("BT_ATR_Pct", 0) > 0]
    all_th = [r["BT_Threshold"] for r in bt_results.values() if r.get("BT_Threshold", 0) > 0]
    all_sl = [r["BT_SL_Level"] for r in bt_results.values() if r.get("BT_SL_Level")]
    if all_atrs:
        print(f"\n  -- DYNAMIC THRESHOLDS --")
        print(f"  ATR% range: {min(all_atrs):.2f}%—{max(all_atrs):.2f}% (avg:{sum(all_atrs)/len(all_atrs):.2f}%)")
        print(f"  Neutral band: ±{min(all_th):.2f}%—±{max(all_th):.2f}% (avg:±{sum(all_th)/len(all_th):.2f}%)")
    if all_sl:
        print(f"  Stop-loss: {min(all_sl):.1f}%—{max(all_sl):.1f}% (avg:{sum(all_sl)/len(all_sl):.1f}%)")
        print(f"  Formula: -{SL_ATR_MULT}×ATR%×√{STOP_LOSS_CHECK_DAY}")

    print(f"\n  -- DIRECTION ACCURACY --")
    print(f"  {'Horizon':<20s} {'Accuracy':>10s} {'Tickers':>8s} {'Edge':>8s}")
    print(f"  {'-'*48}")
    if st > 0:
        sp = sh / st * 100
        print(f"  {'Swing':<20s} {sp:>9.1f}% {st:>8d} {sp-50:>+7.1f}%")
    for label, arr in [("1M", a1), ("3M", a3), ("ALL", a6)]:
        if arr:
            a = sum(arr) / len(arr)
            print(f"  {label:<20s} {a:>9.1f}% {len(arr):>8d} {a-50:>+7.1f}%")

    cats = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    scts = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    cths = {"MEGA": [], "LARGE": [], "MID": [], "SMALL": []}
    for tk, r in bt_results.items():
        c = r.get("BT_Category", "SMALL")
        if r.get("BT_6M_N", 0) >= 30:
            cats[c].append(r["BT_6M"])
            scts[c].append(r.get("BT_Strict_Acc", 0))
            cths[c].append(r.get("BT_Threshold", 0))

    print(f"\n  -- BY CATEGORY --")
    print(f"  {'Cat':<8s} {'New':>6s} {'Strict':>7s} {'Boost':>7s} {'Thresh':>8s} {'N':>4s}")
    print(f"  {'-'*43}")
    for c in ["MEGA", "LARGE", "MID", "SMALL"]:
        v = cats[c]
        if v:
            an = sum(v) / len(v)
            as_ = sum(scts[c]) / len(scts[c])
            at = sum(cths[c]) / len(cths[c]) if cths[c] else 0
            print(f"  {c:<8s} {an:>5.1f}% {as_:>6.1f}% {an-as_:>+6.1f}% ±{at:>6.2f}% {len(v):>4d}")

    # Trade report
    ht = any(r.get("TR_total_trades", 0) > 0 for r in bt_results.values())
    if ht:
        print(f"\n  {'='*90}")
        print(f"  TRADE SIMULATION (ATR Stop-Loss)")
        print(f"  {'='*90}")
        atc = sum(r.get("TR_total_trades", 0) for r in bt_results.values())
        aw = sum(r.get("TR_wins", 0) for r in bt_results.values())
        asl = sum(r.get("TR_stop_loss_exits", 0) for r in bt_results.values())
        asf = sum(r.get("TR_signal_flip_exits", 0) for r in bt_results.values())
        owr = aw / atc * 100 if atc > 0 else 0
        print(f"\n  Trades: {atc:,} | Wins: {owr:.1f}% | SL exits: {asl} | Signal flips: {asf}")

        print(f"\n  {'Cat':<8s} {'Trades':>7s} {'WinR':>6s} {'AvgW':>7s} {'AvgL':>7s} {'PF':>6s} {'Ret':>8s} {'Hold':>6s} {'SL%':>5s}")
        print(f"  {'-'*62}")
        for c in ["MEGA", "LARGE", "MID", "SMALL"]:
            cr = [r for r in bt_results.values() if r.get("BT_Category") == c and r.get("TR_total_trades", 0) > 0]
            if not cr:
                continue
            n = len(cr)
            tt = sum(r["TR_total_trades"] for r in cr)
            tw = sum(r["TR_wins"] for r in cr)
            wr = tw / tt * 100 if tt > 0 else 0
            aw = sum(r["TR_avg_win_pct"] for r in cr) / n
            al = sum(r["TR_avg_loss_pct"] for r in cr) / n
            tg = sum(r["TR_avg_win_pct"] * r["TR_wins"] for r in cr)
            tl = sum(r["TR_avg_loss_pct"] * r["TR_losses"] for r in cr)
            pf = tg / tl if tl > 0 else 0
            ar = sum(r["TR_total_return_pct"] for r in cr) / n
            ah = sum(r["TR_avg_holding_days"] for r in cr) / n
            tsl = sum(r.get("TR_stop_loss_exits", 0) for r in cr)
            slp = tsl / tt * 100 if tt > 0 else 0
            print(f"  {c:<8s} {tt:>7d} {wr:>5.1f}% {aw:>6.2f}% {al:>6.2f}% {pf:>5.2f} {ar:>+7.1f}% {ah:>5.1f}d {slp:>4.1f}%")

        al_l = sum(r.get("TR_long_trades", 0) for r in bt_results.values())
        al_s = sum(r.get("TR_short_trades", 0) for r in bt_results.values())
        lw = [r["TR_long_win_rate"] for r in bt_results.values() if r.get("TR_long_trades", 0) > 0]
        sw = [r["TR_short_win_rate"] for r in bt_results.values() if r.get("TR_short_trades", 0) > 0]
        print(f"\n  LONG:  {al_l:>6d} | WR: {sum(lw)/len(lw):.1f}%" if lw else "")
        print(f"  SHORT: {al_s:>6d} | WR: {sum(sw)/len(sw):.1f}%" if sw else "")

        spf = sorted(
            [(tk, r) for tk, r in bt_results.items() if r.get("TR_total_trades", 0) >= 5],
            key=lambda x: x[1].get("TR_profit_factor", 0), reverse=True
        )
        if spf:
            print(f"\n  -- TOP 10 PROFITABLE --")
            print(f"  {'Ticker':<14s} {'Cat':>5s} {'Tr':>4s} {'WR':>5s} {'AvgW':>6s} {'AvgL':>6s} {'PF':>5s} {'Ret':>8s} {'Hld':>5s} {'ATR':>5s} {'SL':>5s}")
            print(f"  {'-'*78}")
            for tk, r in spf[:10]:
                print(
                    f"  {tk:<14s} {r['BT_Category']:>5s} {r['TR_total_trades']:>4d} "
                    f"{r['TR_win_rate']:>4.0f}% {r['TR_avg_win_pct']:>5.1f}% "
                    f"{r['TR_avg_loss_pct']:>5.1f}% {r['TR_profit_factor']:>4.1f} "
                    f"{r['TR_total_return_pct']:>+7.1f}% {r['TR_avg_holding_days']:>4.0f}d "
                    f"{r.get('BT_ATR_Pct',0):>4.1f}% {r.get('BT_SL_Level',0):>4.1f}%"
                )
            print(f"\n  -- BOTTOM 10 --")
            for tk, r in spf[-10:]:
                print(
                    f"  {tk:<14s} {r['BT_Category']:>5s} {r['TR_total_trades']:>4d} "
                    f"{r['TR_win_rate']:>4.0f}% {r['TR_avg_win_pct']:>5.1f}% "
                    f"{r['TR_avg_loss_pct']:>5.1f}% {r['TR_profit_factor']:>4.1f} "
                    f"{r['TR_total_return_pct']:>+7.1f}% {r['TR_avg_holding_days']:>4.0f}d "
                    f"{r.get('BT_ATR_Pct',0):>4.1f}% {r.get('BT_SL_Level',0):>4.1f}%"
                )

    if a6:
        print(f"\n  -- DISTRIBUTION --")
        for lbl, thr in [("≥70%", 70), ("≥60%", 60), ("≥50%", 50)]:
            c = sum(1 for v in a6 if v >= thr)
            print(f"  {lbl}: {c}/{len(a6)} ({c/len(a6)*100:.0f}%)")
        c45 = sum(1 for v in a6 if v < 45)
        print(f"  <45%: {c45}/{len(a6)} ({c45/len(a6)*100:.0f}%)")

    # Live composite
    from engine.config import TODAY_IST
    print(f"\n  -- LIVE ACCURACY --")
    tdf = pd.DataFrame(today_rows)
    tdf['Date'] = TODAY_IST
    if hdf.empty or 'Date' not in hdf.columns:
        ad = tdf
    else:
        ad = pd.concat([hdf[hdf['Date'] != TODAY_IST], tdf], ignore_index=True)
    dates = sorted(ad['Date'].unique())
    if len(dates) < 2:
        print(f"  Need 2+ days")
    else:
        nh = nd = 0
        for i in range(len(dates) - 1):
            sr = ad[ad['Date'] == dates[i]]
            ar = ad[ad['Date'] == dates[i + 1]]
            if sr.empty or ar.empty:
                continue
            am = {a.get('Ticker', ''): safe_int(a.get('Actual_Direction', 0)) for _, a in ar.iterrows() if a.get('Ticker', '')}
            dh = dd = 0
            for _, s in sr.iterrows():
                tk = s.get('Ticker', '')
                if tk not in am:
                    continue
                pc = safe_int(s.get('Composite_Direction', s.get('Forecast_Direction', 0)))
                if pc != 0:
                    dd += 1; nd += 1
                    if is_hit(pc, am[tk]):
                        dh += 1; nh += 1
            if dd > 0:
                print(f"    {dates[i]}->{dates[i+1]}: {dh}/{dd}={dh*100//dd}%")
        if nd > 0:
            print(f"    AGG: {nh}/{nd}={nh/nd*100:.1f}%")
    print(f"{'='*110}")
