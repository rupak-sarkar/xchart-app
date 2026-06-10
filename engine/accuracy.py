"""
accuracy.py  –  v7.4 Backtest + Trade Simulation + Live Accuracy (horizon-aware)
"""

import numpy as np
import pandas as pd

# ── Constants ──────────────────────────────────────────────────────────────

ENTRY_THRESHOLD_LC  = 20
ENTRY_THRESHOLD_SC  = 20
EXIT_THRESHOLD_LC   = 20
EXIT_THRESHOLD_SC   = 20

HORIZONS   = {"MEGA": 28, "LARGE": 21, "MID": 14, "SMALL": 7}
HOLD_DAYS  = {"MEGA": 14, "LARGE": 10, "MID": 7,  "SMALL": 5}
SL_FIXED   = 0.05          # 5 % fixed SL for MID / SMALL
ATR_MULT   = {"MEGA": 2.5, "LARGE": 2.0}
ATR_FLOOR  = 0.03
ATR_CAP    = 0.10

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  FIX: MCap threshold aligned with app.py (was hardcoded different) ║
# ╚══════════════════════════════════════════════════════════════════════╝
MCAP_THRESHOLD = 10000      # in crores – same as app.py

CAP_LABELS = {"MEGA": "MEGA", "LARGE": "LARGE", "MID": "MID", "SMALL": "SMALL"}


# ── Helpers ────────────────────────────────────────────────────────────────

def _classify_cap(row):
    """Return cap category from row (tries several column names)."""
    for col in ("Category", "BT_Category", "Cap"):
        v = str(row.get(col, "")).strip().upper()
        if v in CAP_LABELS:
            return v
    # ╔══════════════════════════════════════════════════════════════════╗
    # ║  FIX: Use same thresholds as app.py classify_cap()            ║
    # ║  OLD: MEGA>=200000, LARGE>=50000, MID>=10000                  ║
    # ║  NEW: MEGA>=100000, LARGE>=20000, MID>=5000  (threshold-based)║
    # ╚══════════════════════════════════════════════════════════════════╝
    mcap = float(row.get("Market_Cap", 0) or 0)
    if mcap >= MCAP_THRESHOLD * 10:     # 100,000 Cr
        return "MEGA"
    elif mcap >= MCAP_THRESHOLD * 2:    #  20,000 Cr
        return "LARGE"
    elif mcap >= MCAP_THRESHOLD * 0.5:  #   5,000 Cr
        return "MID"
    return "SMALL"


def _sl_for(cat, atr_pct):
    """Return stop-loss fraction for a category."""
    if cat in ("MID", "SMALL"):
        return SL_FIXED
    mult = ATR_MULT.get(cat, 2.0)
    sl = mult * atr_pct
    return max(ATR_FLOOR, min(sl, ATR_CAP))


def _sigma_threshold(returns, factor=1.0):
    """Neutral band = factor * std-dev of recent returns."""
    if returns is None or len(returns) < 10:
        return 0.04
    return max(0.01, factor * float(np.std(returns)))


# ── Per-ticker accuracy (walk-forward) ─────────────────────────────────────

def compute_per_ticker_accuracy(df, ticker, cat=None, horizon=None):
    """
    Walk-forward backtest for a single ticker.
    Returns dict with accuracy stats and trade simulation results.
    """
    tdf = df[df["Ticker"].astype(str).str.strip() == str(ticker).strip()].copy()
    if tdf.empty or "Composite_Score" not in tdf.columns:
        return None

    tdf = tdf.sort_values("Date").reset_index(drop=True)
    if len(tdf) < 30:
        return None

    if cat is None:
        cat = _classify_cap(tdf.iloc[-1])

    fwd      = horizon or HORIZONS.get(cat, 14)
    hold_min = HOLD_DAYS.get(cat, 7)
    is_lc    = cat in ("MEGA", "LARGE")
    entry_th = ENTRY_THRESHOLD_LC if is_lc else ENTRY_THRESHOLD_SC
    exit_th  = EXIT_THRESHOLD_LC  if is_lc else EXIT_THRESHOLD_SC

    # ATR for SL
    atr_pct = float(tdf["ATR_Pct"].iloc[-1]) / 100.0 if "ATR_Pct" in tdf.columns else 0.04
    sl_pct  = _sl_for(cat, atr_pct)

    closes  = tdf["Close"].values.astype(float)
    scores  = tdf["Composite_Score"].values.astype(float) if "Composite_Score" in tdf.columns else np.zeros(len(tdf))

    # sigma threshold per ticker
    rets = pd.Series(closes).pct_change().dropna().values
    sigma_th = _sigma_threshold(rets)

    # ── Walk-forward direction predictions ──
    total = 0; hits = 0; dir_total = 0; dir_hits = 0
    sig_count = 0

    for i in range(len(tdf) - fwd):
        sc = scores[i]

        # Classify prediction
        if abs(sc) < entry_th:
            pred = 0  # neutral
        elif sc >= entry_th:
            pred = 1  # bull
        else:
            pred = -1  # bear

        future_ret = (closes[i + fwd] - closes[i]) / closes[i]

        # Classify actual
        if abs(future_ret) <= sigma_th:
            actual = 0
        elif future_ret > 0:
            actual = 1
        else:
            actual = -1

        total += 1

        if pred == 0:
            # Neutral pred: soft hit if actual is also neutral
            if actual == 0:
                hits += 1
        else:
            sig_count += 1
            dir_total += 1
            if pred == actual:
                dir_hits += 1
                hits += 1
            elif actual == 0:
                # Neutral actual on directional pred = soft hit
                dir_hits += 1
                hits += 1

    sig_rate = sig_count / total * 100 if total else 0
    dir_acc  = dir_hits / dir_total * 100 if dir_total else 0
    overall  = hits / total * 100 if total else 0

    # ── Trade Simulation ──
    trades = []
    pos = 0; entry_price = 0; entry_idx = 0; entry_dir = 0
    held = 0; flips = 0; sl_exits = 0

    for i in range(len(tdf)):
        sc = scores[i] if i < len(scores) else 0
        price = closes[i]

        if pos == 0:
            # Entry
            if sc >= entry_th:
                pos = 1; entry_price = price; entry_idx = i; entry_dir = 1; held = 0
            elif sc <= -entry_th:
                pos = -1; entry_price = price; entry_idx = i; entry_dir = -1; held = 0
        else:
            held += 1
            # Check SL
            if entry_dir == 1:
                ret = (price - entry_price) / entry_price
            else:
                ret = (entry_price - price) / entry_price

            hit_sl = ret <= -sl_pct

            # Check exit signal (opposite or neutral beyond hold)
            opp_signal = (entry_dir == 1 and sc <= -exit_th) or (entry_dir == -1 and sc >= exit_th)
            neut_past_hold = abs(sc) < exit_th and held >= hold_min

            if hit_sl or opp_signal or neut_past_hold or i == len(tdf) - 1:
                # Calculate actual return
                if entry_dir == 1:
                    trade_ret = (price - entry_price) / entry_price
                else:
                    trade_ret = (entry_price - price) / entry_price

                exit_reason = "SL" if hit_sl else ("flip" if opp_signal else "hold")
                trades.append({
                    "entry_idx": entry_idx, "exit_idx": i,
                    "direction": entry_dir, "return_pct": trade_ret * 100,
                    "hold_days": held, "exit_reason": exit_reason
                })
                if hit_sl:
                    sl_exits += 1
                if opp_signal:
                    flips += 1

                # Re-enter if opposite signal
                if opp_signal:
                    pos = -entry_dir; entry_price = price; entry_idx = i
                    entry_dir = pos; held = 0
                else:
                    pos = 0

    # Aggregate trades
    n_trades = len(trades)
    wins = [t for t in trades if t["return_pct"] > 0]
    losses = [t for t in trades if t["return_pct"] <= 0]
    n_wins = len(wins)
    win_rate = n_wins / n_trades * 100 if n_trades else 0
    avg_win  = np.mean([w["return_pct"] for w in wins]) if wins else 0
    avg_loss = np.mean([abs(l["return_pct"]) for l in losses]) if losses else 0
    gross_win  = sum(w["return_pct"] for w in wins)
    gross_loss = sum(abs(l["return_pct"]) for l in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else 0
    total_ret = sum(t["return_pct"] for t in trades)
    avg_hold = np.mean([t["hold_days"] for t in trades]) if trades else 0

    return {
        "Ticker": ticker, "Category": cat,
        "total_preds": total, "dir_preds": dir_total,
        "dir_hits": dir_hits, "dir_accuracy": dir_acc,
        "signal_rate": sig_rate, "sigma_threshold": sigma_th * 100,
        "overall_accuracy": overall, "forward_days": fwd,
        "atr_pct": atr_pct * 100, "sl_pct": sl_pct * 100,
        # Trade sim
        "TR_total_trades": n_trades, "TR_win_rate": win_rate,
        "TR_avg_win_pct": avg_win, "TR_avg_loss_pct": avg_loss,
        "TR_profit_factor": pf, "TR_total_return_pct": total_ret,
        "TR_avg_holding_days": avg_hold,
        "TR_sl_exits": sl_exits, "TR_flips": flips,
    }


# ── Multi-period accuracy ─────────────────────────────────────────────────

def compute_accuracy_periods(df, ticker, cat=None):
    """Compute accuracy at swing, 1M, 3M, ALL horizons."""
    if cat is None:
        tdf = df[df["Ticker"].astype(str).str.strip() == str(ticker).strip()]
        if tdf.empty:
            return {}
        cat = _classify_cap(tdf.iloc[-1])

    swing_h = HORIZONS.get(cat, 14)
    results = {}
    for label, h in [("swing", swing_h), ("1M", 22), ("3M", 66), ("ALL", None)]:
        r = compute_per_ticker_accuracy(df, ticker, cat=cat, horizon=h or swing_h)
        if r:
            results[label] = r
    return results


# ── Print full accuracy report ─────────────────────────────────────────────

def print_accuracy_report(df, tickers, history_df=None):
    """Print the full prediction + trade report."""

    print("\n" + "=" * 106)
    print("PREDICTION + TRADE REPORT (v7.4 — Strict SMA9 + ATR SL)")
    print("=" * 106)

    all_results = []
    for tk in tickers:
        r = compute_per_ticker_accuracy(df, tk)
        if r:
            all_results.append(r)

    if not all_results:
        print("  No results to display.")
        return all_results

    rdf = pd.DataFrame(all_results)
    total_preds = rdf["total_preds"].sum()
    total_dir   = rdf["dir_preds"].sum()
    sig_rate    = total_dir / total_preds * 100 if total_preds else 0

    print(f"\n  Total predictions: {total_preds:,} | Directional: {total_dir:,} ({sig_rate:.0f}% signal rate)")

    # ── Direction accuracy by horizon ──
    print("\n  -- DIRECTION ACCURACY (neutral EXCLUDED, neutral actual = soft HIT) --")
    print(f"  {'Horizon':<25s} {'Accuracy':>8s}  {'Tickers':>7s}    {'Edge':>6s}")
    print("  " + "-" * 48)

    for label in ["swing", "1M", "3M", "ALL"]:
        accs = []
        for tk in tickers:
            periods = compute_accuracy_periods(df, tk)
            if label in periods:
                a = periods[label]["dir_accuracy"]
                if periods[label]["dir_preds"] > 0:
                    accs.append(a)
        if accs:
            avg_a = np.mean(accs)
            print(f"  {label.capitalize():<25s} {avg_a:>7.1f}%  {len(accs):>7d}    {avg_a - 50:>+.1f}%")

    # ── Per-category accuracy ──
    print("\n  -- BY CATEGORY --")
    print(f"  {'Cat':<10s} {'DirAcc':>6s}  {'SigRate':>7s}   {'σ-Thr':>6s}  {'Entry':>5s}   {'AvgSL':>5s}   {'Fwd':>4s}  {' N':>5s}")
    print("  " + "-" * 65)

    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        cr = rdf[rdf["Category"] == cat]
        if cr.empty:
            continue
        cr_dir = cr[cr["dir_preds"] > 0]
        if cr_dir.empty:
            continue

        w_acc = (cr_dir["dir_hits"].sum() / cr_dir["dir_preds"].sum() * 100) if cr_dir["dir_preds"].sum() > 0 else 0
        avg_sig = cr_dir["signal_rate"].mean()
        avg_sigma = cr_dir["sigma_threshold"].mean()
        is_lc = cat in ("MEGA", "LARGE")
        entry = ENTRY_THRESHOLD_LC if is_lc else ENTRY_THRESHOLD_SC
        avg_sl = cr_dir["sl_pct"].mean()
        fwd = HORIZONS[cat]

        print(f"  {cat:<10s} {w_acc:>5.1f}%  {avg_sig:>6.1f}%  ±{avg_sigma:>.2f}%  ± {entry:<2d}    {avg_sl:>.1f}%   {fwd:>2d}d  {len(cr_dir):>5d}")

    # ── Trade simulation ──
    print(f"\n  {'=' * 80}")
    print("  TRADE SIMULATION (ATR-based SL for LC, 5.0% fixed for SC)")
    print(f"  MEGA SL: {ATR_MULT['MEGA']}×ATR (floor {ATR_FLOOR*100:.1f}%, cap {ATR_CAP*100:.1f}%)")
    print(f"  LARGE SL: {ATR_MULT['LARGE']}×ATR (floor {ATR_FLOOR*100:.1f}%, cap {ATR_CAP*100:.1f}%)")
    print(f"  Entry: LC±{ENTRY_THRESHOLD_LC} SC±{ENTRY_THRESHOLD_SC} | Exit: LC±{EXIT_THRESHOLD_LC} SC±{EXIT_THRESHOLD_SC}")
    print(f"  MinHold: MEGA={HOLD_DAYS['MEGA']}d LARGE={HOLD_DAYS['LARGE']}d MID={HOLD_DAYS['MID']}d SMALL={HOLD_DAYS['SMALL']}d")
    print(f"  {'=' * 80}")

    tr = rdf[rdf["TR_total_trades"] >= 1]
    total_trades = int(tr["TR_total_trades"].sum())
    total_wins = int((tr["TR_win_rate"] * tr["TR_total_trades"] / 100).sum())
    total_sl = int(tr["TR_sl_exits"].sum())
    total_flips = int(tr["TR_flips"].sum())
    overall_wr = total_wins / total_trades * 100 if total_trades else 0

    if total_trades:
        print(f"\n  Trades: {total_trades:,} | Wins: {overall_wr:.1f}% | SL exits: {total_sl} ({total_sl/total_trades*100:.0f}%) | Signal flips: {total_flips} ({total_flips/total_trades*100:.0f}%)")

    print(f"\n  {'Cat':<10s} {'Trades':>6s}  {'WinR':>5s}   {'AvgW':>6s}   {'AvgL':>6s}    {'PF':>5s}    {'Ret':>6s}  {'Hold':>6s}  {'SL%':>4s}  {'Flip':>4s}  {'AvgSL':>5s}")
    print("  " + "-" * 88)

    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        cr = tr[tr["Category"] == cat]
        if cr.empty or cr["TR_total_trades"].sum() == 0:
            continue
        nt   = int(cr["TR_total_trades"].sum())
        nw   = int((cr["TR_win_rate"] * cr["TR_total_trades"] / 100).sum())
        wr   = nw / nt * 100 if nt else 0
        aw   = (cr["TR_avg_win_pct"] * cr["TR_total_trades"]).sum() / nt if nt else 0
        al   = (cr["TR_avg_loss_pct"] * cr["TR_total_trades"]).sum() / nt if nt else 0
        gw   = (cr["TR_avg_win_pct"] * cr["TR_win_rate"] / 100 * cr["TR_total_trades"]).sum()
        gl   = (cr["TR_avg_loss_pct"] * (100 - cr["TR_win_rate"]) / 100 * cr["TR_total_trades"]).sum()
        p_f  = gw / gl if gl > 0 else 0
        ret  = cr["TR_total_return_pct"].sum() / len(cr) if len(cr) else 0
        hld  = (cr["TR_avg_holding_days"] * cr["TR_total_trades"]).sum() / nt if nt else 0
        sl_p = int(cr["TR_sl_exits"].sum()) / nt * 100 if nt else 0
        flp  = int(cr["TR_flips"].sum())
        asl  = cr["sl_pct"].mean()

        sign = "+" if ret > 0 else ""
        print(f"  {cat:<10s} {nt:>6d}  {wr:>4.1f}%  {aw:>5.2f}%  {al:>5.2f}%  {p_f:>5.2f}  {sign}{ret:>5.1f}%  {hld:>4.1f}d {sl_p:>4.1f}%  {flp:>4d}  {asl:>4.1f}%")

    # ── Top 10 / Bottom 10 ──
    tr_valid = rdf[rdf["TR_total_trades"] >= 5].copy()
    if len(tr_valid) > 0:
        tr_valid = tr_valid.sort_values("TR_profit_factor", ascending=False)

        print(f"\n  -- TOP 10 PROFITABLE --")
        print(f"  {'Ticker':<18s} {'Cat':>5s}  {'Tr':>3s}   {'WR':>4s}  {'AvgW':>5s}  {'AvgL':>5s}   {'PF':>5s}     {'Ret':>6s}  {'Hld':>4s}  {'Flp':>3s}   {'SL':>4s}")
        print("  " + "-" * 85)
        for _, r in tr_valid.head(10).iterrows():
            sign = "+" if r["TR_total_return_pct"] > 0 else ""
            print(f"  {r['Ticker']:<18s} {r['Category']:>5s}  {int(r['TR_total_trades']):>3d}  {r['TR_win_rate']:>4.0f}%  {r['TR_avg_win_pct']:>4.1f}%  {r['TR_avg_loss_pct']:>4.1f}%  {r['TR_profit_factor']:>5.2f}  {sign}{r['TR_total_return_pct']:>5.1f}%  {r['TR_avg_holding_days']:>3.0f}d  {int(r['TR_flips']):>3d}  {r['sl_pct']:>4.1f}%")

        print(f"\n  -- BOTTOM 10 --")
        print(f"  {'Ticker':<18s} {'Cat':>5s}  {'Tr':>3s}   {'WR':>4s}  {'AvgW':>5s}  {'AvgL':>5s}   {'PF':>5s}     {'Ret':>6s}  {'Hld':>4s}  {'Flp':>3s}   {'SL':>4s}")
        print("  " + "-" * 85)
        for _, r in tr_valid.tail(10).iloc[::-1].iterrows():
            sign = "+" if r["TR_total_return_pct"] > 0 else ""
            print(f"  {r['Ticker']:<18s} {r['Category']:>5s}  {int(r['TR_total_trades']):>3d}  {r['TR_win_rate']:>4.0f}%  {r['TR_avg_win_pct']:>4.1f}%  {r['TR_avg_loss_pct']:>4.1f}%  {r['TR_profit_factor']:>5.2f}  {sign}{r['TR_total_return_pct']:>5.1f}%  {r['TR_avg_holding_days']:>3.0f}d  {int(r['TR_flips']):>3d}  {r['sl_pct']:>4.1f}%")

    # ── Distribution ──
    dir_valid = rdf[rdf["dir_preds"] > 0]
    no_signal = rdf[rdf["dir_preds"] == 0]
    if len(dir_valid) > 0:
        print(f"\n  -- DISTRIBUTION (directional only, {len(dir_valid)} tickers with signals) --")
        for thresh in [70, 60, 50]:
            cnt = len(dir_valid[dir_valid["dir_accuracy"] >= thresh])
            print(f"  ≥{thresh}%: {cnt}/{len(dir_valid)} ({cnt/len(dir_valid)*100:.0f}%)")
        below_45 = len(dir_valid[dir_valid["dir_accuracy"] < 45])
        print(f"  <45%: {below_45}/{len(dir_valid)} ({below_45/len(dir_valid)*100:.0f}%)")
        if len(no_signal) > 0:
            print(f"  No signals: {len(no_signal)} tickers (all neutral predictions)")

    # ── Live accuracy (horizon-aware) ──
    if history_df is not None and len(history_df) > 0 and "Date" in history_df.columns:
        print(f"\n  -- LIVE ACCURACY (horizon-aware) --")
        hdf = history_df.copy()
        hdf["Date"] = hdf["Date"].astype(str).str[:10]
        hdf["Composite_Direction"] = pd.to_numeric(hdf.get("Composite_Direction", 0), errors="coerce").fillna(0).astype(int)

        dates = sorted(hdf["Date"].unique())

        # Next-day accuracy (legacy — for continuity)
        nd_hits = 0; nd_total = 0
        per_day = []
        for i in range(len(dates) - 1):
            d_from = dates[i]; d_to = dates[i + 1]
            preds = hdf[(hdf["Date"] == d_from) & (hdf["Composite_Direction"] != 0)]
            if preds.empty:
                continue
            day_h = 0; day_t = 0
            for _, pr in preds.iterrows():
                tk = str(pr["Ticker"]).strip()
                pred_dir = int(pr["Composite_Direction"])
                nxt = hdf[(hdf["Date"] == d_to) & (hdf["Ticker"].astype(str).str.strip() == tk)]
                if nxt.empty:
                    continue
                act_ret = float(nxt.iloc[0].get("Actual_Return_Pct", 0) or 0)
                day_t += 1; nd_total += 1
                if (pred_dir == 1 and act_ret > 0) or (pred_dir == -1 and act_ret < 0):
                    day_h += 1; nd_hits += 1
            if day_t > 0:
                per_day.append((d_from, d_to, day_h, day_t))

        for d_from, d_to, h, t in per_day:
            print(f"    {d_from}->{d_to}: {h}/{t}={h/t*100:.0f}%")
        if nd_total > 0:
            print(f"    AGG (next-day): {nd_hits}/{nd_total}={nd_hits/nd_total*100:.1f}%")

        # Horizon-aware accuracy
        h_hits = 0; h_total = 0; h_pending = 0
        for _, pr in hdf[hdf["Composite_Direction"] != 0].iterrows():
            tk = str(pr["Ticker"]).strip()
            pred_dir = int(pr["Composite_Direction"])
            sig_date = pr["Date"]
            cat = str(pr.get("Category", pr.get("BT_Category", "MID"))).strip().upper()
            if cat not in HORIZONS:
                cat = "MID"
            horizon = HORIZONS[cat]

            future_dates = [d for d in dates if d > sig_date]
            if len(future_dates) < horizon:
                h_pending += 1
                continue

            eval_date = future_dates[min(horizon - 1, len(future_dates) - 1)]
            eval_row = hdf[(hdf["Ticker"].astype(str).str.strip() == tk) & (hdf["Date"] == eval_date)]
            if eval_row.empty:
                h_pending += 1
                continue

            act_ret = float(eval_row.iloc[0].get("Actual_Return_Pct", 0) or 0)
            h_total += 1
            if (pred_dir == 1 and act_ret > 0) or (pred_dir == -1 and act_ret < 0):
                h_hits += 1

        if h_total > 0:
            print(f"    HORIZON-AWARE: {h_hits}/{h_total}={h_hits/h_total*100:.1f}%")
        if h_pending > 0:
            print(f"    Pending (horizon not reached): {h_pending} signals")
        if h_total == 0 and h_pending > 0:
            print(f"    No signals have reached their horizon yet ({h_pending} pending)")

    print("=" * 106)

    return all_results
