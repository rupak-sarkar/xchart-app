"""Backtest v7.4 — Strict SMA9, ATR-based SL for LC, fixed SL for SC."""
import numpy as np
import pandas as pd
from engine.utils import safe_float

# ── Unified entry/exit thresholds ──
ENTRY_THRESHOLD_LC = 20
ENTRY_THRESHOLD_SC = 20
EXIT_THRESHOLD_LC = 20
EXIT_THRESHOLD_SC = 20

# Legacy exports
ENTRY_THRESHOLD = 20
EXIT_THRESHOLD = 20

# ATR-based SL for LC
ATR_SL_MULTIPLIER_MEGA = 2.5    # MEGA: SL = 2.5 × ATR%
ATR_SL_MULTIPLIER_LARGE = 2.0   # LARGE: SL = 2.0 × ATR%
ATR_SL_FLOOR = 3.0              # Minimum SL %
ATR_SL_CAP = 10.0               # Maximum SL %

# Fixed SL for SC
STOP_LOSS_PCT = -5.0             # MID/SMALL fixed SL

HOLD_DAYS = {'MEGA': 14, 'LARGE': 10, 'MID': 7, 'SMALL': 5}
HORIZONS = {'MEGA': 28, 'LARGE': 21, 'MID': 14, 'SMALL': 7}

MIN_HOLD_DAYS = 7


def _classify_cap(mcap, threshold):
    if mcap > threshold * 5:
        return 'MEGA'
    elif mcap > threshold:
        return 'LARGE'
    elif mcap > threshold * 0.3:
        return 'MID'
    else:
        return 'SMALL'


def _get_thresholds(cat):
    if cat in ('MEGA', 'LARGE'):
        return ENTRY_THRESHOLD_LC, EXIT_THRESHOLD_LC
    else:
        return ENTRY_THRESHOLD_SC, EXIT_THRESHOLD_SC


def _compute_atr_sl(cat, high, low, close, idx, period=14):
    """Compute ATR-based stop-loss percentage for LC stocks."""
    if cat not in ('MEGA', 'LARGE'):
        return abs(STOP_LOSS_PCT)

    start = max(0, idx - period)
    h = high.iloc[start:idx + 1].astype(float)
    l = low.iloc[start:idx + 1].astype(float)
    c = close.iloc[start:idx + 1].astype(float)

    if len(c) < 5:
        return abs(STOP_LOSS_PCT)

    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(min(period, len(tr))).mean().iloc[-1]

    current_close = c.iloc[-1]
    if pd.isna(atr) or current_close <= 0:
        return abs(STOP_LOSS_PCT)

    atr_pct = (atr / current_close) * 100

    if cat == 'MEGA':
        sl = atr_pct * ATR_SL_MULTIPLIER_MEGA
    else:
        sl = atr_pct * ATR_SL_MULTIPLIER_LARGE

    return max(ATR_SL_FLOOR, min(ATR_SL_CAP, sl))


def _compute_sigma_threshold(returns, forward_days):
    """Dynamic neutral band — 0.75× multiplier, clamped 1.5-5.0%."""
    if len(returns) < 25:
        return 1.5
    rolling_std = returns.rolling(20).std()
    recent_std = rolling_std.iloc[-1]
    if pd.isna(recent_std) or recent_std <= 0:
        recent_std = returns.std()
    if pd.isna(recent_std) or recent_std <= 0:
        return 1.5
    threshold = recent_std * np.sqrt(forward_days) * 100 * 0.75
    return max(1.5, min(5.0, threshold))


def is_hit(pred_dir, actual_dir):
    """v7.4 — Fair accuracy.
    Neutral predictions → excluded.
    Directional + neutral actual → HIT.
    Directional + same actual → HIT.
    Directional + opposite actual → MISS.
    """
    if pred_dir == 0:
        return None
    if pred_dir == actual_dir:
        return True
    if actual_dir == 0:
        return True
    return False


def compute_per_ticker_accuracy(stock_df, mcap_threshold):
    """Compute backtest accuracy with ATR-based SL for LC, fixed SL for SC."""
    results = {}

    for ticker in stock_df['Ticker'].unique():
        tk = stock_df[stock_df['Ticker'] == ticker].sort_values('Date').reset_index(drop=True)
        tk = tk[tk['Close'].notna()].reset_index(drop=True)
        if len(tk) < 60:
            continue

        close = tk['Close'].astype(float)
        high = tk['High'].astype(float)
        low = tk['Low'].astype(float)
        mcap = safe_float(tk.iloc[-1].get('Market_Cap', 0), 0)
        cat = _classify_cap(mcap, mcap_threshold)
        fwd = HORIZONS[cat]
        min_hold = HOLD_DAYS[cat]
        entry_thresh, exit_thresh = _get_thresholds(cat)
        is_lc = cat in ('MEGA', 'LARGE')

        daily_returns = close.pct_change().dropna()

        dir_preds = []
        dir_hits = []
        all_preds_incl_neut = []

        from engine.technical import compute_tech_score

        # Trade simulation
        trades = []
        current_pos = 0
        entry_price = 0
        entry_idx = 0
        entry_sl = abs(STOP_LOSS_PCT)
        sl_exits = 0
        flip_exits = 0

        for i in range(max(30, fwd), len(tk) - fwd):
            window = tk.iloc[max(0, i - 200):i + 1]
            score, _, _ = compute_tech_score(window, mcap_threshold)

            future_close = close.iloc[min(i + fwd, len(close) - 1)]
            current_close = close.iloc[i]
            actual_return_pct = (future_close - current_close) / current_close * 100

            ret_window = daily_returns.iloc[max(0, i - 50):i]
            sigma_thresh = _compute_sigma_threshold(ret_window, fwd)

            if actual_return_pct > sigma_thresh:
                actual_dir = 1
            elif actual_return_pct < -sigma_thresh:
                actual_dir = -1
            else:
                actual_dir = 0

            if score > entry_thresh:
                pred_dir = 1
            elif score < -entry_thresh:
                pred_dir = -1
            else:
                pred_dir = 0

            all_preds_incl_neut.append(pred_dir)

            if pred_dir != 0:
                result = is_hit(pred_dir, actual_dir)
                dir_preds.append(pred_dir)
                dir_hits.append(result)

            # ── TRADE SIMULATION ──
            if current_pos == 0:
                if score > entry_thresh:
                    current_pos = 1
                    entry_price = current_close
                    entry_idx = i
                    # Compute SL at entry
                    if is_lc:
                        entry_sl = _compute_atr_sl(cat, high, low, close, i)
                    else:
                        entry_sl = abs(STOP_LOSS_PCT)
                elif score < -entry_thresh:
                    current_pos = -1
                    entry_price = current_close
                    entry_idx = i
                    if is_lc:
                        entry_sl = _compute_atr_sl(cat, high, low, close, i)
                    else:
                        entry_sl = abs(STOP_LOSS_PCT)
            else:
                hold_days = i - entry_idx
                pnl_pct = ((current_close - entry_price) / entry_price * 100) * current_pos

                # ATR-based SL for LC, fixed for SC
                if pnl_pct <= -entry_sl:
                    trades.append({'dir': current_pos, 'pnl': pnl_pct,
                                   'hold': hold_days, 'exit': 'sl',
                                   'sl_level': entry_sl})
                    sl_exits += 1
                    current_pos = 0
                    continue

                # Signal flip after min hold
                if hold_days >= min_hold:
                    if current_pos == 1 and score < -exit_thresh:
                        trades.append({'dir': current_pos, 'pnl': pnl_pct,
                                       'hold': hold_days, 'exit': 'flip',
                                       'sl_level': entry_sl})
                        flip_exits += 1
                        current_pos = -1
                        entry_price = current_close
                        entry_idx = i
                        if is_lc:
                            entry_sl = _compute_atr_sl(cat, high, low, close, i)
                        else:
                            entry_sl = abs(STOP_LOSS_PCT)
                    elif current_pos == -1 and score > exit_thresh:
                        trades.append({'dir': current_pos, 'pnl': pnl_pct,
                                       'hold': hold_days, 'exit': 'flip',
                                       'sl_level': entry_sl})
                        flip_exits += 1
                        current_pos = 1
                        entry_price = current_close
                        entry_idx = i
                        if is_lc:
                            entry_sl = _compute_atr_sl(cat, high, low, close, i)
                        else:
                            entry_sl = abs(STOP_LOSS_PCT)

        # Close open position
        if current_pos != 0 and len(tk) > 0:
            final_close = close.iloc[-1]
            pnl = ((final_close - entry_price) / entry_price * 100) * current_pos
            trades.append({'dir': current_pos, 'pnl': pnl,
                           'hold': len(tk) - 1 - entry_idx, 'exit': 'end',
                           'sl_level': entry_sl})

        total_all = len(all_preds_incl_neut)
        total_dir = len(dir_preds)
        if total_all < 10:
            continue

        dir_acc = sum(dir_hits) / total_dir * 100 if total_dir > 0 else 0

        dir_1m = sum(dir_hits[-22:]) / max(1, len(dir_hits[-22:])) * 100 if dir_hits else 0
        dir_3m = sum(dir_hits[-66:]) / max(1, len(dir_hits[-66:])) * 100 if dir_hits else 0
        swing_hits = dir_hits[-fwd:] if len(dir_hits) >= fwd else dir_hits
        dir_swing = sum(swing_hits) / max(1, len(swing_hits)) * 100 if swing_hits else 0

        signal_rate = total_dir / total_all * 100 if total_all > 0 else 0
        current_sigma = _compute_sigma_threshold(daily_returns, fwd)

        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        atr_pct = (atr / close.iloc[-1] * 100) if close.iloc[-1] > 0 else 0

        # Avg SL used
        avg_sl = np.mean([t.get('sl_level', abs(STOP_LOSS_PCT)) for t in trades]) if trades else abs(STOP_LOSS_PCT)

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
            'BT_Swing': round(dir_swing, 1),
            'BT_1M': round(dir_1m, 1),
            'BT_3M': round(dir_3m, 1),
            'BT_6M': round(dir_acc, 1),
            'BT_1M_N': min(22, len(dir_hits)),
            'BT_Total_Preds': total_all,
            'BT_Dir_Preds': total_dir,
            'BT_Signal_Rate': round(signal_rate, 1),
            'BT_Forward_Days': fwd,
            'BT_Threshold': round(current_sigma, 2),
            'BT_ATR_Pct': round(atr_pct, 2),
            'BT_Avg_SL': round(avg_sl, 1),
            'BT_SL_Level': round(-avg_sl, 1),
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
        for tk_name, r in results.items():
            c = r['BT_Category']
            if c not in cats:
                cats[c] = []
            cats[c].append(r)

        print(f"\n  Per-category accuracy (DIRECTIONAL ONLY, neutral excluded):")
        print(f"  {'Cat':<10} {'N':>3}  {'DirAcc':>6}  {'SigRate':>7}  {'σ-Thr':>6}  {'Entry':>5}  {'AvgSL':>6}  {'Fwd':>4}")
        print(f"  {'-'*60}")
        for c in ['MEGA', 'LARGE', 'MID', 'SMALL']:
            if c not in cats:
                continue
            items = cats[c]
            n = len(items)
            dir_items = [r for r in items if r['BT_Dir_Preds'] > 0]
            avg_acc = np.mean([r['BT_6M'] for r in dir_items]) if dir_items else 0
            avg_sr = np.mean([r['BT_Signal_Rate'] for r in items])
            avg_thresh = np.mean([r['BT_Threshold'] for r in items])
            avg_sl = np.mean([r['BT_Avg_SL'] for r in items])
            et, _ = _get_thresholds(c)
            print(f"  {c:<10} {n:>3}  {avg_acc:>5.1f}%  {avg_sr:>5.1f}%  ±{avg_thresh:>4.2f}%  "
                  f"±{et:>3}  {avg_sl:>5.1f}%  {HORIZONS[c]:>3}d")

        print(f"\n  Per-category TRADE SIMULATION:")
        sl_desc_parts = []
        for c in ['MEGA', 'LARGE']:
            if c in cats:
                avg_sl = np.mean([r['BT_Avg_SL'] for r in cats[c]])
                sl_desc_parts.append(f"{c}={avg_sl:.1f}%ATR")
        sl_desc_parts.append(f"MID/SMALL={abs(STOP_LOSS_PCT)}%fixed")
        print(f"  SL: {' | '.join(sl_desc_parts)}")
        print(f"  Entry: LC±{ENTRY_THRESHOLD_LC} SC±{ENTRY_THRESHOLD_SC} | "
              f"Exit: LC±{EXIT_THRESHOLD_LC} SC±{EXIT_THRESHOLD_SC} | MinHold:cap-based")
        print(f"  {'Cat':<10}{'Trades':>6} {'WinR':>6} {'AvgW':>7} {'AvgL':>7} {'PF':>6} "
              f"{'TotRet':>8} {'Hold':>6} {'SL%':>5} {'Flip':>5} {'AvgSL':>6}")
        print(f"  {'-'*85}")
        for c in ['MEGA', 'LARGE', 'MID', 'SMALL']:
            if c not in cats:
                continue
            items = cats[c]
            tt = sum(r['TR_total_trades'] for r in items)
            trade_items = [r for r in items if r['TR_total_trades'] > 0]
            if not trade_items:
                print(f"  {c:<10}     0")
                continue
            wr = np.mean([r['TR_win_rate'] for r in trade_items])
            aw = np.mean([r['TR_avg_win_pct'] for r in trade_items])
            al = np.mean([r['TR_avg_loss_pct'] for r in trade_items])
            pf_items = [r for r in items if r['TR_total_trades'] >= 5]
            pf_val = np.mean([r['TR_profit_factor'] for r in pf_items]) if pf_items else 0
            tr_val = np.mean([r['TR_total_return_pct'] for r in trade_items])
            hd = np.mean([r['TR_avg_holding_days'] for r in trade_items])
            sl = sum(r['TR_stop_loss_exits'] for r in items)
            fl = sum(r['TR_signal_flip_exits'] for r in items)
            slp = sl / tt * 100 if tt > 0 else 0
            avg_sl = np.mean([r['BT_Avg_SL'] for r in items])
            print(f"  {c:<10}{tt:>6} {wr:>5.1f}% {aw:>6.2f}% {al:>6.2f}% {pf_val:>5.2f} "
                  f"{tr_val:>+7.1f}% {hd:>5.1f}d {slp:>4.1f}% {fl:>4} {avg_sl:>5.1f}%")

    return results


def print_accuracy_report(bt_results, scored, hdf, all_rows):
    """Print full accuracy report."""
    if not bt_results:
        return

    print(f"\n{'='*110}")
    print(f"PREDICTION + TRADE REPORT (v7.4 — Strict SMA9 + ATR SL)")
    print(f"{'='*110}")

    total_preds = sum(r['BT_Total_Preds'] for r in bt_results.values())
    total_dir = sum(r.get('BT_Dir_Preds', 0) for r in bt_results.values())

    if total_preds > 0:
        print(f"\n  Total predictions: {total_preds:,} | Directional: {total_dir:,} "
              f"({total_dir/total_preds*100:.0f}% signal rate)")

    print(f"\n  -- DIRECTION ACCURACY (neutral EXCLUDED, neutral actual = soft HIT) --")
    print(f"  {'Horizon':<24} {'Accuracy':>8}  {'Tickers':>7}  {'Edge':>8}")
    print(f"  {'-'*48}")
    for label, key in [('Swing', 'BT_Swing'), ('1M', 'BT_1M'), ('3M', 'BT_3M'), ('ALL', 'BT_6M')]:
        vals = [r[key] for r in bt_results.values() if r.get('BT_Dir_Preds', 0) > 0 and r[key] > 0]
        if vals:
            avg = np.mean(vals)
            print(f"  {label:<24} {avg:>7.1f}%  {len(vals):>7}  {avg-50:>+7.1f}%")

    print(f"\n  -- BY CATEGORY --")
    print(f"  {'Cat':<10} {'DirAcc':>6}  {'SigRate':>7}  {'σ-Thr':>6}  {'Entry':>5}  {'AvgSL':>6}  {'Fwd':>4}  {'N':>4}")
    print(f"  {'-'*65}")
    for c in ['MEGA', 'LARGE', 'MID', 'SMALL']:
        items = [r for r in bt_results.values() if r['BT_Category'] == c]
        if not items:
            continue
        dir_items = [r for r in items if r.get('BT_Dir_Preds', 0) > 0]
        avg_acc = np.mean([r['BT_6M'] for r in dir_items]) if dir_items else 0
        avg_sr = np.mean([r.get('BT_Signal_Rate', 0) for r in items])
        avg_thresh = np.mean([r['BT_Threshold'] for r in items])
        avg_sl = np.mean([r['BT_Avg_SL'] for r in items])
        et, _ = _get_thresholds(c)
        print(f"  {c:<10} {avg_acc:>5.1f}%  {avg_sr:>5.1f}%  ±{avg_thresh:>4.2f}%  "
              f"±{et:>3}  {avg_sl:>5.1f}%  {HORIZONS[c]:>3}d  {len(items):>4}")

    # Trade simulation
    all_trades = sum(r['TR_total_trades'] for r in bt_results.values())
    all_wins = sum(r['TR_wins'] for r in bt_results.values())
    all_sl = sum(r['TR_stop_loss_exits'] for r in bt_results.values())
    all_flips = sum(r['TR_signal_flip_exits'] for r in bt_results.values())

    print(f"\n  {'='*80}")
    print(f"  TRADE SIMULATION (ATR-based SL for LC, {abs(STOP_LOSS_PCT)}% fixed for SC)")
    print(f"  MEGA SL: {ATR_SL_MULTIPLIER_MEGA}×ATR (floor {ATR_SL_FLOOR}%, cap {ATR_SL_CAP}%)")
    print(f"  LARGE SL: {ATR_SL_MULTIPLIER_LARGE}×ATR (floor {ATR_SL_FLOOR}%, cap {ATR_SL_CAP}%)")
    print(f"  Entry: LC±{ENTRY_THRESHOLD_LC} SC±{ENTRY_THRESHOLD_SC} | "
          f"Exit: LC±{EXIT_THRESHOLD_LC} SC±{EXIT_THRESHOLD_SC}")
    print(f"  MinHold: MEGA={HOLD_DAYS['MEGA']}d LARGE={HOLD_DAYS['LARGE']}d "
          f"MID={HOLD_DAYS['MID']}d SMALL={HOLD_DAYS['SMALL']}d")
    print(f"  {'='*80}")
    if all_trades > 0:
        print(f"\n  Trades: {all_trades:,} | Wins: {all_wins/all_trades*100:.1f}% | "
              f"SL exits: {all_sl} ({all_sl/all_trades*100:.0f}%) | "
              f"Signal flips: {all_flips} ({all_flips/all_trades*100:.0f}%)")

    print(f"\n  {'Cat':<10}{'Trades':>6} {'WinR':>6} {'AvgW':>7} {'AvgL':>7} {'PF':>6} "
          f"{'Ret':>8} {'Hold':>6} {'SL%':>5} {'Flip':>5} {'AvgSL':>6}")
    print(f"  {'-'*80}")
    for c in ['MEGA', 'LARGE', 'MID', 'SMALL']:
        items = [r for r in bt_results.values() if r['BT_Category'] == c and r['TR_total_trades'] >= 3]
        if not items:
            continue
        tt = sum(r['TR_total_trades'] for r in items)
        wr = np.mean([r['TR_win_rate'] for r in items])
        aw = np.mean([r['TR_avg_win_pct'] for r in items])
        al = np.mean([r['TR_avg_loss_pct'] for r in items])
        pf_items = [r for r in items if r['TR_total_trades'] >= 5]
        pf_val = np.mean([r['TR_profit_factor'] for r in pf_items]) if pf_items else 0
        tr_val = np.mean([r['TR_total_return_pct'] for r in items])
        hd = np.mean([r['TR_avg_holding_days'] for r in items])
        sl = sum(r['TR_stop_loss_exits'] for r in items)
        fl = sum(r['TR_signal_flip_exits'] for r in items)
        slp = sl / tt * 100 if tt > 0 else 0
        avg_sl = np.mean([r['BT_Avg_SL'] for r in items])
        print(f"  {c:<10}{tt:>6} {wr:>5.1f}% {aw:>6.2f}% {al:>6.2f}% {pf_val:>5.2f} "
              f"{tr_val:>+7.1f}% {hd:>5.1f}d {slp:>4.1f}% {fl:>4} {avg_sl:>5.1f}%")

    # Top/Bottom 10
    by_pf = sorted(
        [(tk_name, r) for tk_name, r in bt_results.items() if r['TR_total_trades'] >= 5],
        key=lambda x: x[1]['TR_profit_factor'], reverse=True
    )
    if by_pf:
        print(f"\n  -- TOP 10 PROFITABLE --")
        print(f"  {'Ticker':<16} {'Cat':>5} {'Tr':>4} {'WR':>5} {'AvgW':>6} {'AvgL':>6} "
              f"{'PF':>5} {'Ret':>8} {'Hld':>5} {'Flp':>4} {'SL':>5}")
        print(f"  {'-'*85}")
        for tk_name, r in by_pf[:10]:
            print(f"  {tk_name:<16} {r['BT_Category']:>5} {r['TR_total_trades']:>4} "
                  f"{r['TR_win_rate']:>4.0f}% {r['TR_avg_win_pct']:>5.1f}% "
                  f"{r['TR_avg_loss_pct']:>5.1f}% {r['TR_profit_factor']:>5.2f} "
                  f"{r['TR_total_return_pct']:>+7.1f}% {r['TR_avg_holding_days']:>4.0f}d "
                  f"{r['TR_signal_flip_exits']:>4} {r['BT_Avg_SL']:>4.1f}%")

        print(f"\n  -- BOTTOM 10 --")
        print(f"  {'Ticker':<16} {'Cat':>5} {'Tr':>4} {'WR':>5} {'AvgW':>6} {'AvgL':>6} "
              f"{'PF':>5} {'Ret':>8} {'Hld':>5} {'Flp':>4} {'SL':>5}")
        print(f"  {'-'*85}")
        for tk_name, r in by_pf[-10:][::-1]:
            print(f"  {tk_name:<16} {r['BT_Category']:>5} {r['TR_total_trades']:>4} "
                  f"{r['TR_win_rate']:>4.0f}% {r['TR_avg_win_pct']:>5.1f}% "
                  f"{r['TR_avg_loss_pct']:>5.1f}% {r['TR_profit_factor']:>5.2f} "
                  f"{r['TR_total_return_pct']:>+7.1f}% {r['TR_avg_holding_days']:>4.0f}d "
                  f"{r['TR_signal_flip_exits']:>4} {r['BT_Avg_SL']:>4.1f}%")

    # Distribution
    dir_items = [r for r in bt_results.values() if r.get('BT_Dir_Preds', 0) > 0]
    acc_vals = [r['BT_6M'] for r in dir_items]
    n = len(acc_vals)
    if n > 0:
        print(f"\n  -- DISTRIBUTION (directional only, {n} tickers with signals) --")
        for thresh in [70, 60, 50]:
            cnt = sum(1 for a in acc_vals if a >= thresh)
            print(f"  ≥{thresh}%: {cnt}/{n} ({cnt/n*100:.0f}%)")
        cnt45 = sum(1 for a in acc_vals if a < 45)
        print(f"  <45%: {cnt45}/{n} ({cnt45/n*100:.0f}%)")
        no_signal = sum(1 for r in bt_results.values() if r.get('BT_Dir_Preds', 0) == 0)
        if no_signal > 0:
            print(f"  No signals: {no_signal} tickers (all neutral predictions)")

    # Live accuracy
    if hdf is not None and not hdf.empty and 'Date' in hdf.columns:
        print(f"\n  -- LIVE ACCURACY --")
        dates = sorted(hdf['Date'].unique())
        all_h = 0
        all_t = 0
        for i in range(len(dates) - 1):
            d1, d2 = dates[i], dates[i + 1]
            rows1 = hdf[hdf['Date'] == d1]
            rows2 = hdf[hdf['Date'] == d2]
            merged = rows1.merge(rows2, on='Ticker', suffixes=('_1', '_2'))
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
            all_h += hits
            all_t += total
        if all_t > 0:
            print(f"    AGG: {all_h}/{all_t}={all_h/all_t*100:.1f}%")

    print(f"{'='*110}")
