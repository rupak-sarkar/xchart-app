"""LightGBM ML + Ensemble scoring.
Walk-forward with neutral=HIT (fair comparison).
Ensemble: per-ticker best of ML vs Rule."""
import pandas as pd
import numpy as np
from engine.features import (
    FEATURE_NAMES, extract_all_features,
    extract_live_features, get_horizon_and_threshold,
)
from engine.accuracy import (
    compute_atr_pct, get_dynamic_threshold,
    is_hit as direction_is_hit, ATR_LOOKBACK,
)
from engine.utils import safe_float

try:
    from lightgbm import LGBMClassifier
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False

LGBM_PARAMS = {
    'n_estimators': 150, 'max_depth': 5,
    'learning_rate': 0.05, 'min_child_samples': 50,
    'subsample': 0.8, 'colsample_bytree': 0.8,
    'reg_alpha': 0.1, 'reg_lambda': 1.0,
    'random_state': 42, 'verbose': -1, 'n_jobs': -1,
}


def _train_model(train_df, feature_cols):
    dir_df = train_df[train_df['Label'] != 0].copy()
    if len(dir_df) < 100:
        return None
    dir_df['y'] = (dir_df['Label'] == 1).astype(int)
    X = dir_df[feature_cols]
    y = dir_df['y']
    model = LGBMClassifier(**LGBM_PARAMS)
    model.fit(X, y)
    return model


def walk_forward_backtest(features_df, stock_df=None, mcap_threshold=10000):
    """Walk-forward with neutral=HIT for fair comparison with rule-based."""
    if not HAS_LGBM or features_df.empty:
        return {}

    feature_cols = [c for c in FEATURE_NAMES if c in features_df.columns]
    if len(feature_cols) < 10:
        return {}

    results = {}

    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        cat_df = features_df[features_df['Category'] == cat].copy()
        if cat_df.empty:
            continue
        cat_df = cat_df.sort_values('Date').reset_index(drop=True)
        dates = sorted(cat_df['Date'].unique())
        n_dates = len(dates)
        if n_dates < 100:
            print(f"  {cat}: Skip — only {n_dates} dates")
            continue

        fwd, _ = get_horizon_and_threshold(cat)
        step = max(30, int(n_dates * 0.1))
        gap = fwd
        all_preds = []
        fold = 0
        train_end = int(n_dates * 0.5)

        while train_end < n_dates:
            fold += 1
            pred_end = min(train_end + step, n_dates)
            safe_end = max(0, train_end - gap)
            train_dates = set(dates[:safe_end])
            pred_dates = set(dates[train_end:pred_end])

            train_data = cat_df[cat_df['Date'].isin(train_dates)]
            pred_data = cat_df[cat_df['Date'].isin(pred_dates)]

            dir_pred = pred_data[pred_data['Label'] != 0]
            if len(train_data[train_data['Label'] != 0]) < 100 or len(dir_pred) == 0:
                train_end = pred_end
                continue

            model = _train_model(train_data, feature_cols)
            if model is None:
                train_end = pred_end
                continue

            X_p = dir_pred[feature_cols]
            y_proba = model.predict_proba(X_p)
            y_pred = model.predict(X_p)

            for j, (_, row) in enumerate(dir_pred.iterrows()):
                prob_up = float(y_proba[j][1]) if y_proba.shape[1] > 1 else 0.5
                ml_dir = 1 if y_pred[j] == 1 else -1
                actual_label = row['Label']
                actual_ret = row['Return']

                # Apply dynamic ATR threshold for neutral=HIT
                # Use the threshold from the features extraction
                threshold = row.get('Threshold', 0.8)
                if actual_ret > threshold:
                    actual_dir = 1
                elif actual_ret < -threshold:
                    actual_dir = -1
                else:
                    actual_dir = 0

                # neutral=HIT: only opposite = miss
                hit = direction_is_hit(ml_dir, actual_dir)
                strict_hit = ml_dir == actual_dir

                all_preds.append({
                    'Ticker': row['Ticker'],
                    'Date': row['Date'],
                    'Category': cat,
                    'ML_Direction': ml_dir,
                    'ML_Prob_Up': round(prob_up, 3),
                    'ML_Score': round((prob_up - 0.5) * 200, 1),
                    'Actual_Direction': actual_dir,
                    'Actual_Return': actual_ret,
                    'Hit': hit,
                    'Strict_Hit': strict_hit,
                    'Fold': fold,
                })

            train_end = pred_end

        if not all_preds:
            continue

        pdf = pd.DataFrame(all_preds)
        total = len(pdf)
        hits = int(pdf['Hit'].sum())
        strict_hits = int(pdf['Strict_Hit'].sum())
        acc = hits / total * 100
        strict_acc = strict_hits / total * 100

        # Per-ticker accuracy
        ticker_acc = {}
        for tk in pdf['Ticker'].unique():
            tp = pdf[pdf['Ticker'] == tk]
            if len(tp) >= 10:
                ticker_acc[tk] = {
                    'accuracy': round(tp['Hit'].sum() / len(tp) * 100, 1),
                    'strict_accuracy': round(tp['Strict_Hit'].sum() / len(tp) * 100, 1),
                    'total': len(tp),
                    'hits': int(tp['Hit'].sum()),
                }

        # Profit factor
        hit_r = pdf[pdf['Hit']]['Actual_Return'].abs()
        miss_r = pdf[~pdf['Hit']]['Actual_Return'].abs()
        avg_hit = float(hit_r.mean()) if len(hit_r) > 0 else 0
        avg_miss = float(miss_r.mean()) if len(miss_r) > 0 else 0
        pf = avg_hit / avg_miss if avg_miss > 0 else 0

        results[cat] = {
            'predictions': pdf,
            'accuracy': round(acc, 1),
            'strict_accuracy': round(strict_acc, 1),
            'total': total, 'hits': hits,
            'folds': fold,
            'ticker_acc': ticker_acc,
            'avg_hit_return': round(avg_hit, 2),
            'avg_miss_return': round(avg_miss, 2),
            'profit_factor': round(pf, 2),
        }

        print(
            f"    {cat:>6s}: {acc:.1f}% (strict:{strict_acc:.1f}%) "
            f"({hits}/{total}) | {len(ticker_acc)} tickers | "
            f"{fold} folds | PF:{pf:.2f}"
        )

    return results


def train_live_models(features_df):
    if not HAS_LGBM or features_df.empty:
        return {}
    feature_cols = [c for c in FEATURE_NAMES if c in features_df.columns]
    models = {}
    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        cat_df = features_df[features_df['Category'] == cat]
        if len(cat_df[cat_df['Label'] != 0]) < 100:
            continue
        model = _train_model(cat_df, feature_cols)
        if model is not None:
            models[cat] = model
    return models


def predict_live(models, live_features_df):
    if not HAS_LGBM or not models or live_features_df.empty:
        return {}
    feature_cols = [c for c in FEATURE_NAMES if c in live_features_df.columns]
    out = {}
    for cat, model in models.items():
        cdf = live_features_df[live_features_df['Category'] == cat]
        if cdf.empty:
            continue
        X = cdf[feature_cols]
        try:
            proba = model.predict_proba(X)
            preds = model.predict(X)
        except Exception as e:
            print(f"  ML error {cat}: {e}")
            continue
        for j, (_, row) in enumerate(cdf.iterrows()):
            p_up = float(proba[j][1]) if proba.shape[1] > 1 else 0.5
            out[row['Ticker']] = {
                'ML_Score': round((p_up - 0.5) * 200, 1),
                'ML_Direction': 1 if preds[j] == 1 else -1,
                'ML_Prob_Up': round(p_up, 3),
                'ML_Category': cat,
            }
    return out


def build_ensemble(wf_results, rule_bt_results, live_preds):
    """Per-ticker ensemble: pick whichever model has higher backtest accuracy.
    Returns dict {ticker: {ensemble_direction, ensemble_score, source, ...}}.
    """
    ensemble = {}

    # Get per-ticker ML accuracy
    ml_ticker_acc = {}
    for cat, data in wf_results.items():
        for tk, info in data.get('ticker_acc', {}).items():
            ml_ticker_acc[tk] = info

    # Get per-ticker rule accuracy
    rule_ticker_acc = {}
    if rule_bt_results:
        for tk, r in rule_bt_results.items():
            if r.get("BT_6M_N", 0) >= 30:
                rule_ticker_acc[tk] = {
                    'accuracy': r["BT_6M"],
                    'total': r["BT_6M_N"],
                }

    # For each ticker with live predictions
    all_tickers = set(list(ml_ticker_acc.keys()) + list(rule_ticker_acc.keys()))

    ml_wins = 0
    rule_wins = 0

    for tk in all_tickers:
        ml_acc = ml_ticker_acc.get(tk, {}).get('accuracy', 0)
        rule_acc = rule_ticker_acc.get(tk, {}).get('accuracy', 0)

        ml_pred = live_preds.get(tk, {})
        rule_pred = rule_bt_results.get(tk, {})

        # Rule direction from composite (if available) or tech score
        rule_dir = 0
        rule_score = 0
        if rule_pred:
            s = rule_pred.get("BT_Swing_Score", 0)
            if s > 20:
                rule_dir = 1
            elif s < -20:
                rule_dir = -1
            rule_score = s

        ml_dir = ml_pred.get('ML_Direction', 0)
        ml_score = ml_pred.get('ML_Score', 0)

        # Pick best model
        if ml_acc > rule_acc and ml_acc > 50:
            source = "ML"
            ens_dir = ml_dir
            ens_score = ml_score
            ml_wins += 1
        elif rule_acc > ml_acc and rule_acc > 50:
            source = "RULE"
            ens_dir = rule_dir
            ens_score = rule_score
            rule_wins += 1
        elif ml_acc > 0 and rule_acc > 0:
            # Both below 50% or equal — use whichever is higher
            if ml_acc >= rule_acc:
                source = "ML"
                ens_dir = ml_dir
                ens_score = ml_score
                ml_wins += 1
            else:
                source = "RULE"
                ens_dir = rule_dir
                ens_score = rule_score
                rule_wins += 1
        elif ml_dir != 0:
            source = "ML_ONLY"
            ens_dir = ml_dir
            ens_score = ml_score
        elif rule_dir != 0:
            source = "RULE_ONLY"
            ens_dir = rule_dir
            ens_score = rule_score
        else:
            source = "NONE"
            ens_dir = 0
            ens_score = 0

        # Agreement bonus
        agreement = "AGREE" if ml_dir == rule_dir and ml_dir != 0 else "DISAGREE" if ml_dir != 0 and rule_dir != 0 and ml_dir != rule_dir else "PARTIAL"

        ensemble[tk] = {
            'Ensemble_Direction': ens_dir,
            'Ensemble_Score': ens_score,
            'Ensemble_Source': source,
            'ML_Accuracy': ml_acc,
            'Rule_Accuracy': rule_acc,
            'ML_Direction': ml_dir,
            'ML_Score': ml_score,
            'Rule_Direction': rule_dir,
            'Rule_Score': rule_score,
            'Agreement': agreement,
        }

    print(f"\n  Ensemble selection: ML wins {ml_wins} | Rule wins {rule_wins}")
    agree = sum(1 for v in ensemble.values() if v['Agreement'] == 'AGREE')
    disagree = sum(1 for v in ensemble.values() if v['Agreement'] == 'DISAGREE')
    print(f"  Agreement: {agree} agree | {disagree} disagree")

    return ensemble


def get_feature_importance(models, features_df):
    feature_cols = [c for c in FEATURE_NAMES if c in features_df.columns]
    importance = {}
    for cat, model in models.items():
        imp = model.feature_importances_
        importance[cat] = sorted(zip(feature_cols, imp), key=lambda x: x[1], reverse=True)
    return importance


def print_ml_report(wf_results, rule_bt_results, ensemble=None):
    print(f"\n{'='*110}")
    print(f"ML + ENSEMBLE REPORT (neutral=HIT)")
    print(f"{'='*110}")

    if not wf_results:
        print("  No ML results")
        print(f"{'='*110}")
        return

    print(f"\n  -- ML vs RULE (both neutral=HIT) --")
    print(f"  {'Cat':<8s} {'ML Acc':>7s} {'ML Str':>7s} {'Rule':>7s} {'Edge':>7s} {'ML PF':>6s} {'Preds':>7s}")
    print(f"  {'-'*50}")

    total_ml_hits = 0
    total_ml_preds = 0

    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        if cat not in wf_results:
            continue
        ml = wf_results[cat]
        total_ml_hits += ml['hits']
        total_ml_preds += ml['total']

        rule_accs = []
        if rule_bt_results:
            for tk, r in rule_bt_results.items():
                if r.get('BT_Category') == cat and r.get('BT_6M_N', 0) >= 30:
                    rule_accs.append(r['BT_6M'])
        rule_avg = sum(rule_accs) / len(rule_accs) if rule_accs else 0
        edge = ml['accuracy'] - rule_avg

        print(
            f"  {cat:<8s} {ml['accuracy']:>6.1f}% {ml['strict_accuracy']:>6.1f}% "
            f"{rule_avg:>6.1f}% {edge:>+6.1f}% {ml['profit_factor']:>5.2f} {ml['total']:>7d}"
        )

    if total_ml_preds > 0:
        overall = total_ml_hits / total_ml_preds * 100
        print(f"\n  OVERALL ML: {total_ml_hits}/{total_ml_preds} = {overall:.1f}%")

    # Ensemble report
    if ensemble:
        print(f"\n  -- ENSEMBLE SELECTION --")
        ml_selected = sum(1 for v in ensemble.values() if v['Ensemble_Source'] in ('ML', 'ML_ONLY'))
        rule_selected = sum(1 for v in ensemble.values() if v['Ensemble_Source'] in ('RULE', 'RULE_ONLY'))
        agree = sum(1 for v in ensemble.values() if v['Agreement'] == 'AGREE')
        disagree = sum(1 for v in ensemble.values() if v['Agreement'] == 'DISAGREE')

        print(f"  ML selected:   {ml_selected} tickers")
        print(f"  Rule selected: {rule_selected} tickers")
        print(f"  Models agree:    {agree} tickers")
        print(f"  Models disagree: {disagree} tickers")

        # Show disagreements
        if disagree > 0:
            print(f"\n  -- DISAGREEMENTS (ML ≠ Rule) --")
            dm = {1: "BULL", -1: "BEAR", 0: "NEUT"}
            print(f"  {'Ticker':<14s} {'ML':>5s} {'Rule':>5s} {'Pick':>6s} {'ML%':>5s} {'Rule%':>6s}")
            print(f"  {'-'*44}")
            dis = [(tk, v) for tk, v in ensemble.items() if v['Agreement'] == 'DISAGREE']
            dis.sort(key=lambda x: abs(x[1]['ML_Accuracy'] - x[1]['Rule_Accuracy']), reverse=True)
            for tk, v in dis[:15]:
                print(
                    f"  {tk:<14s} {dm.get(v['ML_Direction'],'?'):>5s} "
                    f"{dm.get(v['Rule_Direction'],'?'):>5s} "
                    f"{v['Ensemble_Source']:>6s} "
                    f"{v['ML_Accuracy']:>4.0f}% {v['Rule_Accuracy']:>5.0f}%"
                )

    # Top ML tickers
    all_ta = {}
    for cat, data in wf_results.items():
        for tk, info in data['ticker_acc'].items():
            all_ta[tk] = {**info, 'category': cat}

    if all_ta:
        st = sorted(all_ta.items(), key=lambda x: x[1]['accuracy'], reverse=True)
        print(f"\n  -- TOP 10 ML --")
        print(f"  {'Ticker':<14s} {'Cat':>5s} {'ML%':>6s} {'Strict':>7s} {'N':>5s}")
        print(f"  {'-'*40}")
        for tk, info in st[:10]:
            print(f"  {tk:<14s} {info['category']:>5s} {info['accuracy']:>5.1f}% {info['strict_accuracy']:>6.1f}% {info['total']:>5d}")

        print(f"\n  -- BOTTOM 10 ML --")
        for tk, info in st[-10:]:
            print(f"  {tk:<14s} {info['category']:>5s} {info['accuracy']:>5.1f}% {info['strict_accuracy']:>6.1f}% {info['total']:>5d}")

    print(f"{'='*110}")


def run_ml_pipeline(stock_df, mcap_threshold, rule_bt_results=None):
    if not HAS_LGBM:
        print("  LightGBM not installed")
        return {}, {}, {}, {}

    print("  Extracting features...")
    features_df = extract_all_features(stock_df, mcap_threshold)
    if features_df.empty:
        print("  No features")
        return {}, {}, {}, {}

    total = len(features_df)
    directional = len(features_df[features_df['Label'] != 0])
    n_tickers = features_df['Ticker'].nunique()
    print(f"  -> {total:,} samples | {directional:,} directional | {n_tickers} tickers")

    print("\n  Walk-forward (neutral=HIT):")
    wf_results = walk_forward_backtest(features_df, stock_df, mcap_threshold)

    print("\n  Training live models...")
    models = train_live_models(features_df)
    print(f"  -> {len(models)} models")

    print("  Live predictions...")
    live_feat = extract_live_features(stock_df, mcap_threshold)
    live_preds = predict_live(models, live_feat) if models and not live_feat.empty else {}
    print(f"  -> {len(live_preds)} predictions")

    # Ensemble
    ensemble = {}
    if wf_results and rule_bt_results:
        print("\n  Building ensemble...")
        ensemble = build_ensemble(wf_results, rule_bt_results, live_preds)

    # Feature importance
    if models:
        importance = get_feature_importance(models, features_df)
        print("\n  Top 5 features:")
        for cat, feats in importance.items():
            top5 = [f"{n}({v:.0f})" for n, v in feats[:5]]
            print(f"    {cat}: {', '.join(top5)}")

    print_ml_report(wf_results, rule_bt_results, ensemble)

    return wf_results, live_preds, models, ensemble
