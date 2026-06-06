"""Separate ML + Ensemble pipeline.
Run: python ml_run.py"""
import pandas as pd
from engine.technical import load_stock_data, detect_mcap_scale
from engine.ml_model import run_ml_pipeline
from engine.accuracy import compute_per_ticker_accuracy
from engine.config import TODAY_IST


def run():
    print(f"ML + Ensemble Pipeline v6.3 | {TODAY_IST}")
    print("=" * 110)

    print("\nLoading stock data...")
    stock_df = load_stock_data()
    if stock_df.empty:
        print("ERROR: No stock data")
        return

    mcap_threshold = detect_mcap_scale(stock_df)

    print("\nRunning rule-based backtest...")
    bt_results = compute_per_ticker_accuracy(stock_df, mcap_threshold)

    print("\nRunning ML + Ensemble pipeline...")
    print("=" * 110)
    wf_results, live_preds, models, ensemble = run_ml_pipeline(
        stock_df, mcap_threshold, rule_bt_results=bt_results
    )

    # Save ML predictions
    if live_preds:
        ml_df = pd.DataFrame([
            {"Ticker": tk, **vals}
            for tk, vals in live_preds.items()
        ])
        ml_df.to_csv("ml_predictions.csv", index=False)
        print(f"\nSaved {len(ml_df)} ML predictions to ml_predictions.csv")

    # Save ensemble predictions
    if ensemble:
        ens_df = pd.DataFrame([
            {"Ticker": tk, **vals}
            for tk, vals in ensemble.items()
        ])
        ens_df.to_csv("ensemble_predictions.csv", index=False)
        print(f"Saved {len(ens_df)} ensemble predictions to ensemble_predictions.csv")

        # Summary
        dm = {1: "BULL", -1: "BEAR", 0: "NEUT"}
        bull = sum(1 for v in ensemble.values() if v['Ensemble_Direction'] == 1)
        bear = sum(1 for v in ensemble.values() if v['Ensemble_Direction'] == -1)
        neut = sum(1 for v in ensemble.values() if v['Ensemble_Direction'] == 0)
        print(f"\n  Ensemble summary: BULL:{bull} BEAR:{bear} NEUT:{neut}")

    print("\n" + "=" * 110)
    print("Pipeline complete")
    print("=" * 110)


if __name__ == "__main__":
    run()
