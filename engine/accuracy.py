"""Backtest v7.1 — σ-based neutral band (tighter), 5% SL, cap-aware horizons."""
import numpy as np
import pandas as pd
from engine.utils import safe_float

# ── Wider thresholds to reduce signal frequency ──
ENTRY_THRESHOLD = 30
EXIT_THRESHOLD = 40
HOLD_DAYS = {'MEGA': 28, 'LARGE': 21, 'MID': 14, 'SMALL': 7}
HORIZONS = {'MEGA': 28, 'LARGE': 21, 'MID': 14, 'SMALL': 7}
STOP_LOSS_PCT = -5.0  # Fixed 5% stop-loss

# For chart signal markers
MIN_HOLD_DAYS = 7


def _classify_cap(mcap, threshold):
    """Classify ticker by market cap."""
    if mcap > threshold * 5:
        return 'MEGA'
    elif mcap > threshold:
        return 'LARGE'
    elif mcap > threshold * 0.3:
        return 'MID'
    else:
        return 'SMALL'


def _compute_sigma_threshold(returns, forward_days):
    """Dynamic neutral band — tighter than raw σ√t.

    Uses 0.5× multiplier to keep band meaningful.
    Shorter horizons get tighter bands.
    Clamped to 0.8%–3.5% to avoid inflated accuracy.
    """
    if len(returns) < 25:
        return 1.0

    rolling_std = returns.rolling(20).std()
    recent_std = rolling_std.iloc[-1]

    if pd.isna(recent_std) or recent_std <= 0:
        recent_std = returns.std()

    if pd.isna(recent_std) or recent_std <= 0:
        return 1.0

    # 0.5× multiplier instead of 1× to keep band meaningful
    threshold = recent_std * np.sqrt(forward_days) * 100 * 0.5

    # Tighter clamp: 0.8% to 3.5%
    return max(0.8, min(3.5, threshold))


def is_hit(pred_dir, actual_dir):
    """Check if prediction was correct. Neutral predictions = HIT."""
    if pred_dir == 0:
        return True
    return pred_dir == actual_dir


def compute_per_ticker_accuracy(stock_df, mcap_threshold):
    """Compute backtest accuracy for each ticker with σ-based neutral band."""
    results = {}

    for ticker in stock_df['Ticker'].unique():
        tk = stock_df[stock_df['Ticker'] == ticker].sort_values('Date').reset_index(drop=True)
        tk = tk[tk['Close'].notna()].reset_index(drop=True)

        if len(tk) < 60:
            continue

        close = tk['Close'].astype(float)

        # Classify cap
        mcap = safe_float(tk.iloc[-1].get('Market_Cap', 0), 0)
        cat = _classify_cap(mcap, mcap_threshold)

        fwd = HORIZONS[cat]
        min_hold = HOLD_DAYS[cat]

        # Daily returns for σ calculation
        daily_returns = close.pct_change().dropna()

        # Compute per-window σ thresholds
        all_preds = []
        hits_1m = []
        hits_3m = []
        hits_all = []

        from engine.technical import compute_tech_score

        # Trade simulation
        trades = []
        current_pos = 0  # 0=flat, 1=long, -1=short
        entry_price = 0
        entry_idx = 0
        entry_dir = 0
        sl_exits = 0
        flip_exits = 0

        for i in range(max(30, fwd), len(tk) - fwd):
            window = tk.iloc[max(0, i - 30):i + 1]
            score, _, _ = compute_tech_score(window, mcap_threshold)

            future_close = close.iloc[min(i + fwd, len(close) - 1)]
            current_close = close.iloc[i]
            actual_return_pct = (future_close - current_close) / current_close * 100

            # σ-based dynamic threshold for this window
            ret_window = daily_returns.iloc[max(0, i - 50):i]
            sigma_thresh = _compute_sigma_threshold(ret_window, fwd)

            # Direction based on threshold
            if actual_return_pct > sigma_thresh:
                actual_dir = 1
            elif actual_return_pct < -sigma_thresh:
                actual_dir = -1
            else:
                actual_dir = 0  # Neutral = within noise band

            # Prediction direction
            if score > ENTRY_THRESHOLD:
                pred_dir = 1
            elif score < -ENTRY_THRESHOLD:
                pred_dir = -1
            else:
                pred_dir = 0

            hit = is_hit(pred_dir, actual_dir)
            all_preds.append(hit)

            # Rolling accuracy
            hits_1m.append(hit)
            hits_3m.append(hit)

            # ── TRADE SIMULATION ──
            if current_pos == 0:
                # Enter trade
                if score > ENTRY_THRESHOLD:
                    current_pos = 1
                    entry_price = current_close
                    entry_idx = i
                    entry_dir = 1
                elif score < -ENTRY_THRESHOLD:
                    current_pos = -1
                    entry_price = current_close
                    entry_idx = i
                    entry_dir = -1
            else:
                hold_days = i - entry_idx
                pnl_pct = ((current_close - entry_price) / entry_price * 100) * current_pos

                # Check 5% stop-loss
                if pnl_pct <= STOP_LOSS_PCT:
                    trades.append({
                        'dir': current_pos,
                        'pnl': pnl_pct,
                        'hold': hold_days,
                        'exit': 'sl',
                    })
                    sl_exits += 1
                    current_pos = 0
                    continue

                # Check for signal flip (only after min hold)
                if hold_days >= min_hold:
                    if current_pos == 1 and score < -EXIT_THRESHOLD:
                        trades.append({
                            'dir': current_pos,
                            'pnl': pnl_pct,
                            'hold': hold_days,
                            'exit': 'flip',
                        })
                        flip_exits += 1
                        # Flip to short
                        current_pos = -1
                        entry_price = current_close
                        entry_idx = i
                        entry_dir = -1
                    elif current_pos == -1 and score > EXIT_THRESHOLD:
                        trades.append({
                            'dir': current_pos,
                            'pnl': pnl_pct,
                            'hold': hold_days,
                            'exit': 'flip',
                        })
                        flip_exits += 1
                        # Flip to long
                        current_pos = 1
                        entry_price = current_close
                        entry_idx = i
                        entry_dir = 1

        # Close any open position
        if current_pos != 0 and len(tk) > 0:
            final_close = close.iloc[-1]
            pnl = ((final_close - entry_price) / entry_price * 100) * current_pos
            trades.append({
                'dir': current_pos,
                'pnl': pnl,
                'hold': len(tk) - 1 - entry_idx,
                'exit': 'end',
            })

        total_preds = len(all_preds)
        if total_preds < 10:
            continue

        # Compute accuracies
        bt_all = sum(all_preds) / total_preds * 100
        bt_1m = sum(hits_1m[-22:]) / min(22, len(hits_1m)) * 100 if hits_1m else 0
        bt_3m = sum(hits_3m[-66:]) / min(66, len(hits_3m)) * 100 if hits_3m else 0

        # Swing accuracy (last fwd predictions)
        swing_preds = all_preds[-fwd:] if len(all_preds) >= fwd else all_preds
        bt_swing = sum(swing_preds) / len(swing_preds) * 100 if swing_preds else 0

        # Current σ threshold
        current_sigma = _compute_sigma_threshold(daily_returns, fwd)

        # ATR for reference
        tr = pd.concat([
            tk['High'].astype(float) - tk['Low'].astype(float),
            (tk['High'].astype(float) - close.shift()).abs(),
            (tk['Low'].astype(float) - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        atr_pct = (atr / close.iloc[-1] * 100) if close.iloc[-1] > 0 else 0

        # Trade stats
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]
        total_trades = len(trades)
        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
        avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
        avg_loss = abs(np.mean([t['pnl'] for t in losses])) if losses else 0
        total_return = sum(t['pnl'] for t in trades)
        avg_hold = np.mean([t['hold'] for t in trades]) if trades else 0

        gross_wins = sum(t['pnl'] for t in wins) if wins else 0
        gross_losses = abs(sum(t['pnl'] for t in losses)) if losses else 0.001
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0

        long_trades = [t for t in trades if t['dir'] == 1]
        short_trades = [t for t in trades if t['dir'] == -1]
        long_wr = len([t for t in long_trades if t['pnl'] > 0]) / len(long_trades) * 100 if long_trades else 0
        short_wr = len([t for t in short_trades if t['pnl'] > 0]) / len(short_trades) * 100 if short_trades else 0

        results[ticker] = {
            'BT_Swing': round(bt_swing, 1),
            'BT_1M': round(bt_1m, 1),
            'BT_3M': round(bt_3m, 1),
            'BT_6M': round(bt_all, 1),
            'BT_1M_N': min(22, len(hits_1m)),
            'BT_Total_Preds': total_preds,
            'BT_Forward_Days': fwd,
            'BT_Threshold': round(current_sigma, 2),
            'BT_ATR_Pct': round(atr_pct, 2),
            'BT_SL_Level': STOP_LOSS_PCT,
            'BT_Category': cat,
            'TR_total_trades': total_trades,
            'TR_wins': len(wins),
            'TR_losses': len(losses),
            'TR_win_rate': round(win_rate, 1),
            'TR_avg_win_pct': round(avg_win, 2),
            'TR_avg_loss_pct': round(avg_loss, 2),
            'TR_profit_factor': round(profit_factor, 2),
            'TR_total_return_pct': round(total_return, 1),
            'TR_avg_holding_days': round(avg_hold, 1),
            'TR_long_trades': len(long_trades),
            'TR_short_trades': len(short_trades),
            'TR_long_win_rate': round(long_wr, 1),
            'TR_short_win_rate': round(short_wr, 1),
            'TR_stop_loss_exits': sl_exits,
            'TR_signal_flip_exits': flip_exits,
        }

    # Print summary
    if results:
        cats = {}
        for tk, r in results.items():
            c = r['BT_Category']
            if c not in cats:
                cats[c] = []
            cats[c].append(r)

        print(f"\n  Per-category accuracy (σ-based threshold, 5% SL):")
        print(f"  {'Cat':<10} {'N':>3}  {'DirAcc':>6}  {'σ-Thresh':>8}  {'SL':>6}  {'Fwd':>4}")
        print(f"  {'-'*52}")
        for c in ['MEGA', 'LARGE', 'MID', 'SMALL']:
            if c not in cats:
                continue
            items = cats[c]
            n = len(items)
            avg_acc = np.mean([r['BT_6M'] for r in items])
            avg_thresh = np.mean([r['BT_Threshold'] for r in items])
            fwd = HORIZONS[c]
            print(f"  {c:<10} {n:>3}  {avg_acc:>5.1f}%  "
                  f"±{avg_thresh:>5.2f}%  {STOP_LOSS_PCT:>5.1f}%  {fwd:>3}d")

        print(f"\n  Per-category TRADE SIMULATION (5% fixed SL):")
        print(f"  Entry:±{ENTRY_THRESHOLD} Exit:±{EXIT_THRESHOLD} MinHold:cap-based SL:{STOP_LOSS_PCT}%")
        print(f"  {'Cat':<10}{'Trades':>6} {'WinR':>6} {'AvgW':>7} {'AvgL':>7} {'PF':>6} {'TotRet':>8} {'Hold':>6} {'SL%':>5}")
        print(f"  {'-'*72}")
        for c in ['MEGA', 'LARGE', 'MID', 'SMALL']:
            if c not in cats:
                continue
            items = cats[c]
            tt = sum(r['TR_total_trades'] for r in items)
            trade_items = [r for r in items if r['TR_total_trades'] > 0]
            if not trade_items:
                continue
            wr = np.mean([r['TR_win_rate'] for r in trade_items])
            aw = np.mean([r['TR_avg_win_pct'] for r in trade_items])
            al = np.mean([r['TR_avg_loss_pct'] for r in trade_items])
            pf_items = [r for r in items if r['TR_total_trades'] >= 5]
            pf_val = np.mean([r['TR_profit_factor'] for r in pf_items]) if pf_items else 0
            tr = np.mean([r['TR_total_return_pct'] for r in trade_items])
            hd = np.mean([r['TR_avg_holding_days'] for r in trade_items])
            sl = sum(r['TR_stop_loss_exits'] for r in items)
            slp = sl / tt * 100 if tt > 0 else 0
            print(f"  {c:<10}{tt:>6} {wr:>5.1f}% {aw:>6.2f}% {al:>6.2f}% {pf_val:>5.2f} {tr:>+7.1f}% {hd:>5.1f}d {slp:>4.1f}%")

    return results


def print_accuracy_report(bt_results, scored, hdf, all_rows):
    """Print the full accuracy report."""
    if not bt_results:
        return

    print(f"\n{'='*110}")
    print(f"PREDICTION + TRADE REPORT (v7.1 σ-band + 5% SL)")
    print(f"{'='*110}")

    total_preds = sum(r['BT_Total_Preds'] for r in bt_results.values())

    # Direction accuracy by horizon
    print(f"\n  -- DIRECTION ACCURACY --")
    print(f"  {'Horizon':<24} {'Accuracy':>8}  {'Tickers':>7}  {'Edge':>8}")
    print(f"  {'-'*48}")
    for label, key in [('Swing', 'BT_Swing'), ('1M', 'BT_1M'), ('3M', 'BT_3M'), ('ALL', 'BT_6M')]:
        vals = [r[key] for r in bt_results.values() if r[key] > 0]
        if vals:
            avg = np.mean(vals)
            print(f"  {label:<24} {avg:>7.1f}%  {len(vals):>7}  {avg-50:>+7.1f}%")

    # By category
    print(f"\n  -- BY CATEGORY --")
    print(f"  {'Cat':<10} {'Acc':>6}  {'σ-Thresh':>8}  {'Horizon':>7}  {'MinHold':>7}  {'N':>4}")
    print(f"  {'-'*50}")
    for c in ['MEGA', 'LARGE', 'MID', 'SMALL']:
        items = [r for r in bt_results.values() if r['BT_Category'] == c]
        if not items:
            continue
        avg_acc = np.mean([r['BT_6M'] for r in items])
        avg_thresh = np.mean([r['BT_Threshold'] for r in items])
        print(f"  {c:<10} {avg_acc:>5.1f}%  ±{avg_thresh:>5.2f}%  "
              f"{HORIZONS[c]:>5}d  {HOLD_DAYS[c]:>5}d  {len(items):>4}")

    # Trade simulation summary
    all_trades = sum(r['TR_total_trades'] for r in bt_results.values())
    all_wins = sum(r['TR_wins'] for r in bt_results.values())
    all_sl = sum(r['TR_stop_loss_exits'] for r in bt_results.values())
    all_flips = sum(r['TR_signal_flip_exits'] for r in bt_results.values())

    print(f"\n  {'='*80}")
    print(f"  TRADE SIMULATION (5% Fixed Stop-Loss)")
    print(f"  {'='*80}")
    if all_trades > 0:
        print(f"\n  Trades: {all_trades:,} | Wins: {all_wins/all_trades*100:.1f}% | "
              f"SL exits: {all_sl} | Signal flips: {all_flips}")
    else:
        print(f"\n  Trades: 0")

    print(f"\n  {'Cat':<10}{'Trades':>6} {'WinR':>6} {'AvgW':>7} {'AvgL':>7} {'PF':>6} "
          f"{'Ret':>8} {'Hold':>6} {'SL%':>5}")
    print(f"  {'-'*62}")
    for c in ['MEGA', 'LARGE', 'MID', 'SMALL']:
        items = [r for r in bt_results.values() if r['BT_Category'] == c and r['TR_total_trades'] >= 5]
        if not items:
            continue
        tt = sum(r['TR_total_trades'] for r in items)
        wr = np.mean([r['TR_win_rate'] for r in items])
        aw = np.mean([r['TR_avg_win_pct'] for r in items])
        al = np.mean([r['TR_avg_loss_pct'] for r in items])
        pf_val = np.mean([r['TR_profit_factor'] for r in items])
        tr = np.mean([r['TR_total_return_pct'] for r in items])
        hd = np.mean([r['TR_avg_holding_days'] for r in items])
        sl = sum(r['TR_stop_loss_exits'] for r in items)
        slp = sl / tt * 100 if tt > 0 else 0
        print(f"  {c:<10}{tt:>6} {wr:>5.1f}% {aw:>6.2f}% {al:>6.2f}% {pf_val:>5.2f} "
              f"{tr:>+7.1f}% {hd:>5.1f}d {slp:>4.1f}%")

    # Top/Bottom 10
    by_pf = sorted(
        [(tk, r) for tk, r in bt_results.items() if r['TR_total_trades'] >= 5],
        key=lambda x: x[1]['TR_profit_factor'], reverse=True
    )

    if by_pf:
        print(f"\n  -- TOP 10 PROFITABLE --")
        print(f"  {'Ticker':<16} {'Cat':>5} {'Tr':>4} {'WR':>5} {'AvgW':>6} {'AvgL':>6} "
              f"{'PF':>5} {'Ret':>8} {'Hld':>5} {'SL':>5}")
        print(f"  {'-'*78}")
        for tk, r in by_pf[:10]:
            print(f"  {tk:<16} {r['BT_Category']:>5} {r['TR_total_trades']:>4} "
                  f"{r['TR_win_rate']:>4.0f}% {r['TR_avg_win_pct']:>5.1f}% "
                  f"{r['TR_avg_loss_pct']:>5.1f}% {r['TR_profit_factor']:>5.2f} "
                  f"{r['TR_total_return_pct']:>+7.1f}% {r['TR_avg_holding_days']:>4.0f}d "
                  f"{r['BT_SL_Level']:>5.1f}%")

        print(f"\n  -- BOTTOM 10 --")
        print(f"  {'Ticker':<16} {'Cat':>5} {'Tr':>4} {'WR':>5} {'AvgW':>6} {'AvgL':>6} "
              f"{'PF':>5} {'Ret':>8} {'Hld':>5} {'SL':>5}")
        print(f"  {'-'*78}")
        for tk, r in by_pf[-10:][::-1]:
            print(f"  {tk:<16} {r['BT_Category']:>5} {r['TR_total_trades']:>4} "
                  f"{r['TR_win_rate']:>4.0f}% {r['TR_avg_win_pct']:>5.1f}% "
                  f"{r['TR_avg_loss_pct']:>5.1f}% {r['TR_profit_factor']:>5.2f} "
                  f"{r['TR_total_return_pct']:>+7.1f}% {r['TR_avg_holding_days']:>4.0f}d "
                  f"{r['BT_SL_Level']:>5.1f}%")

    # Distribution
    acc_vals = [r['BT_6M'] for r in bt_results.values()]
    n = len(acc_vals)
    print(f"\n  -- DISTRIBUTION --")
    for thresh in [70, 60, 50]:
        cnt = sum(1 for a in acc_vals if a >= thresh)
        print(f"  ≥{thresh}%: {cnt}/{n} ({cnt/n*100:.0f}%)")
    cnt45 = sum(1 for a in acc_vals if a < 45)
    print(f"  <45%: {cnt45}/{n} ({cnt45/n*100:.0f}%)")

    # Live accuracy from history
    if hdf is not None and not hdf.empty and 'Date' in hdf.columns:
        print(f"\n  -- LIVE ACCURACY --")
        dates = sorted(hdf['Date'].unique())

        # Per-day
        for i in range(len(dates) - 1):
            d1, d2 = dates[i], dates[i + 1]
            rows1 = hdf[hdf['Date'] == d1]
            rows2 = hdf[hdf['Date'] == d2]
            merged = rows1.merge(rows2, on='Ticker', suffixes=('_1', '_2'))
            if merged.empty:
                continue
            hits = 0
            total = 0
            for _, mr in merged.iterrows():
                raw_dir = mr.get('Composite_Direction_1', 0)
                if pd.isna(raw_dir):
                    continue
                dir1 = int(raw_dir)
                ret2 = safe_float(mr.get('Actual_Return_Pct_2', 0), 0)
                if dir1 == 0:
                    continue
                total += 1
                actual = 1 if ret2 > 0.25 else (-1 if ret2 < -0.25 else 0)
                if dir1 == actual or actual == 0:
                    hits += 1
            if total > 0:
                print(f"    {d1}->{d2}: {hits}/{total}={hits/total*100:.0f}%")

        # Aggregate
        all_h = 0
        all_t = 0
        for i in range(len(dates) - 1):
            d1, d2 = dates[i], dates[i + 1]
            rows1 = hdf[hdf['Date'] == d1]
            rows2 = hdf[hdf['Date'] == d2]
            merged = rows1.merge(rows2, on='Ticker', suffixes=('_1', '_2'))
            for _, mr in merged.iterrows():
                raw_dir = mr.get('Composite_Direction_1', 0)
                if pd.isna(raw_dir):
                    continue
                dir1 = int(raw_dir)
                ret2 = safe_float(mr.get('Actual_Return_Pct_2', 0), 0)
                if dir1 == 0:
                    continue
                all_t += 1
                actual = 1 if ret2 > 0.25 else (-1 if ret2 < -0.25 else 0)
                if dir1 == actual or actual == 0:
                    all_h += 1
        if all_t > 0:
            print(f"    AGG: {all_h}/{all_t}={all_h/all_t*100:.1f}%")

    print(f"{'='*110}")
