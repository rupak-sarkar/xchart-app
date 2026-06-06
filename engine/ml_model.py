"""LightGBM ML scoring with walk-forward validation.
Trains per-category models using expanding window.
No look-ahead bias — strict temporal splits with purging gap."""
import pandas as pd
import numpy as np
from engine.features import (
    FEATURE_NAMES,
    extract_all_features,
    extract_live_features,
    get_horizon_and_threshold,
)
from engine.utils import safe_float

try:
    from lightgbm import LGBMClassifier
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False


# Conservative hyperparameters
LGBM_PARAMS = {
    'n_estimators': 150,
    'max_depth': 5,
    'learning_rate': 0.05,
    'min_child_samples': 50,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'reg_alpha': 0.1,
    'reg_lambda': 1.0,
    'random_state': 42,
    'verbose': -1,
    'n_jobs': -1,
}


def _train_model(train_df, feature_cols):
    """Train binary classifier: UP (1) vs DOWN (0). Drops neutral."""
    dir_df = train_df[train_df['Label'] != 0].copy()
    if len(dir_df) < 100:
        return None
    dir_df['y'] = (dir_df['Label'] == 1).astype(int)
    X = dir_df[feature_cols]
    y = dir_df['y']
    model = LGBMClassifier(**LGBM_PARAMS)
    model.fit(X, y)
    return model


def walk_forward_backtest(features_df):
    """Walk-forward per category with expanding window + purging gap.
    Returns dict {category: {accuracy, predictions, ...}}.
    """
    if not HAS_LGBM or features_df.empty:
        return {}

    feature_cols = [c for c in FEATURE_NAMES if c in features_df.columns]
    if len(feature_cols) < 10:
        print(f"  WARNING: Only {len(feature_cols)} features. Need 10+.")
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
            print(f"  {cat}: Skip — only {n_dates} dates (need 100+)")
            continue

        fwd, _ = get_horizon_and_threshold(cat)
        initial_pct = 0.5
        step = max(30, int(n_dates * 0.1))
        gap = fwd  # purging gap to prevent label leakage

        all_preds = []
        fold = 0
        train_end = int(n_dates * initial_pct)

        while train_end < n_dates:
            fold += 1
            pred_end = min(train_end + step, n_dates)

            # Purge: remove last `gap` dates from training labels
            safe_end = max(0, train_end - gap)
            train_dates = set(dates[:safe_end])
            pred_dates = set(dates[train_end:pred_end])

            train_data = cat_df[cat_df['Date'].isin(train_dates)]
            pred_data = cat_df[cat_df['Date'].isin(pred_dates)]

            dir_pred = pred_data[pred_data['Label'] != 0]
            dir_train = train_data[train_data['Label'] != 0]

            if len(dir_train) < 100 or len(dir_pred) == 0:
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
                actual_dir = 1 if row['Label'] == 1 else -1
                all_preds.append({
                    'Ticker': row['Ticker'],
                    'Date': row['Date'],
                    'Category': cat,
                    'ML_Direction': ml_dir,
                    'ML_Prob_Up': round(prob_up, 3),
                    'ML_Score': round((prob_up - 0.5) * 200, 1),
                    'Actual_Direction': actual_dir,
                    'Actual_Return': row['Return'],
                    'Hit': ml_dir == actual_dir,
                    'Fold': fold,
                })

            train_end = pred_end

        if not all_preds:
            print(f"  {cat}: No predictions generated")
            continue

        pdf = pd.DataFrame(all_preds)
        total = len(pdf)
        hits = int(pdf['Hit'].sum())
        acc = hits / total * 100

        # Per-ticker accuracy
        ticker_acc = {}
        for tk in pdf['Ticker'].unique():
            tp = pdf[pdf['Ticker'] == tk]
            if len(tp) >= 10:
                ticker_acc[tk] = {
                    'accuracy': round(tp['Hit'].sum() / len(tp) * 100, 1),
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
            'total': total,
            'hits': hits,
            'folds': fold,
            'ticker_acc': ticker_acc,
            'avg_hit_return': round(avg_hit, 2),
            'avg_miss_return': round(avg_miss, 2),
            'profit_factor': round(pf, 2),
        }

        print(
            f"    {cat:>6s}: {acc:.1f}% ({hits}/{total}) | "
            f"{len(ticker_acc)} tickers | {fold} folds | PF:{pf:.2f}"
        )

    return results


def train_live_models(features_df):
    """Train final models on ALL data for live prediction."""
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
    """Predict direction for today using trained models.
    Returns dict {ticker: {ML_Score, ML_Direction, ML_Prob_Up, ML_Category}}.
    """
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
            print(f"  ML predict error {cat}: {e}")
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


def get_feature_importance(models, features_df):
    feature_cols = [c for c in FEATURE_NAMES if c in features_df.columns]
    importance = {}
    for cat, model in models.items():
        imp = model.feature_importances_
        feat_imp = sorted(zip(feature_cols, imp), key=lambda x: x[1], reverse=True)
        importance[cat] = feat_imp
    return importance


def print_ml_report(wf_results, rule_bt_results):
    """Print ML vs Rule-based comparison."""
    print(f"\n{'='*110}")
    print(f"ML MODEL REPORT (LightGBM Walk-Forward)")
    print(f"{'='*110}")

    if not wf_results:
        print("  No ML results available")
        print(f"{'='*110}")
        return

    print(f"\n  -- ML vs RULE-BASED ACCURACY --")
    print(
        f"  {'Category':<10s} {'ML Acc':>8s} {'Rule Acc':>10s} "
        f"{'ML Edge':>8s} {'ML PF':>7s} {'Rule PF':>8s} {'ML Preds':>9s}"
    )
    print(f"  {'-'*65}")

    total_ml_hits = 0
    total_ml_preds = 0

    for cat in ["MEGA", "LARGE", "MID", "SMALL"]:
        if cat not in wf_results:
            continue
        ml = wf_results[cat]
        total_ml_hits += ml['hits']
        total_ml_preds += ml['total']

        rule_accs = []
        rule_pfs = []
        if rule_bt_results:
            for tk, r in rule_bt_results.items():
                if r.get('BT_Category') == cat and r.get('BT_6M_N', 0) >= 30:
                    rule_accs.append(r['BT_6M'])
                    hr = r.get('BT_Avg_Hit_Ret', 0)
                    mr = r.get('BT_Avg_Miss_Ret', 0)
                    if mr > 0:
                        rule_pfs.append(hr / mr)

        rule_avg = sum(rule_accs) / len(rule_accs) if rule_accs else 0
        rule_pf = sum(rule_pfs) / len(rule_pfs) if rule_pfs else 0
        edge = ml['accuracy'] - rule_avg

        print(
            f"  {cat:<10s} {ml['accuracy']:>7.1f}% {rule_avg:>9.1f}% "
            f"{edge:>+7.1f}% {ml['profit_factor']:>6.2f} "
            f"{rule_pf:>7.2f} {ml['total']:>9d}"
        )

    if total_ml_preds > 0:
        overall = total_ml_hits / total_ml_preds * 100
        print(f"\n  OVERALL ML: {total_ml_hits}/{total_ml_preds} = {overall:.1f}%")

    # Top / bottom tickers
    all_ta = {}
    for cat, data in wf_results.items():
        for tk, info in data['ticker_acc'].items():
            all_ta[tk] = {**info, 'category': cat}

    if all_ta:
        st = sorted(all_ta.items(), key=lambda x: x[1]['accuracy'], reverse=True)
        print(f"\n  -- TOP 10 ML-PREDICTABLE --")
        print(f"  {'Ticker':<14s} {'Cat':>5s} {'ML Acc':>8s} {'Preds':>6s}")
        print(f"  {'-'*36}")
        for tk, info in st[:10]:
            print(f"  {tk:<14s} {info['category']:>5s} {info['accuracy']:>7.1f}% {info['total']:>6d}")

        print(f"\n  -- BOTTOM 10 --")
        for tk, info in st[-10:]:
            print(f"  {tk:<14s} {info['category']:>5s} {info['accuracy']:>7.1f}% {info['total']:>6d}")

    print(f"{'='*110}")


def run_ml_pipeline(stock_df, mcap_threshold, rule_bt_results=None):
    """Main entry point.
    Returns (wf_results, live_predictions, models).
    """
    if not HAS_LGBM:
        print("  LightGBM not installed — pip install lightgbm")
        return {}, {}, {}

    print("  Extracting features...")
    features_df = extract_all_features(stock_df, mcap_threshold)
    if features_df.empty:
        print("  No features — skipping ML")
        return {}, {}, {}

    total = len(features_df)
    directional = len(features_df[features_df['Label'] != 0])
    n_tickers = features_df['Ticker'].nunique()
    print(
        f"  -> {total:,} samples | {directional:,} directional | "
        f"{n_tickers} tickers"
    )

    # Walk-forward
    print("\n  Walk-forward validation:")
    wf_results = walk_forward_backtest(features_df)

    # Train live models on ALL data
    print("\n  Training live models (full data)...")
    models = train_live_models(features_df)
    print(f"  -> {len(models)} category models trained")

    # Live predictions
    print("  Extracting live features...")
    live_feat = extract_live_features(stock_df, mcap_threshold)
    live_preds = {}
    if not live_feat.empty and models:
        live_preds = predict_live(models, live_feat)
        print(f"  -> {len(live_preds)} live predictions")

    # Feature importance
    if models:
        feature_cols = [c for c in FEATURE_NAMES if c in features_df.columns]
        importance = get_feature_importance(models, features_df)
        print("\n  Top 5 features per category:")
        for cat, feats in importance.items():
            top5 = [f"{n}({v:.0f})" for n, v in feats[:5]]
            print(f"    {cat}: {', '.join(top5)}")

    # Report
    print_ml_report(wf_results, rule_bt_results)

    return wf_results, live_preds, models
