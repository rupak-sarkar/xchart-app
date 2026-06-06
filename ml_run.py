"""Separate ML scoring pipeline.
Run independently: python ml_run.py
Does NOT affect data.csv or rule-based scoring."""
import pandas as pd
from engine.technical import load_stock_data, detect_mcap_scale
from engine.ml_model import run_ml_pipeline
from engine.accuracy import compute_per_ticker_accuracy
from engine.config import TODAY_IST


def run():
    print(f"ML Pipeline v6.1 | {TODAY_IST}")
    print("=" * 110)

    print("\nLoading stock data...")
    stock_df = load_stock_data()
    if stock_df.empty:
        print("ERROR: No stock data")
        return

    mcap_threshold = detect_mcap_scale(stock_df)

    print("\nRunning rule-based backtest (for comparison)...")
    bt_results = compute_per_ticker_accuracy(stock_df, mcap_threshold)

    print("\nRunning ML pipeline...")
    print("=" * 110)
    wf_results, live_preds, models = run_ml_pipeline(
        stock_df, mcap_threshold, rule_bt_results=bt_results
    )

    # Save ML predictions
    if live_preds:
        ml_df = pd.DataFrame([
            {"Ticker": tk, **vals}
            for tk, vals in live_preds.items()
        ])
        ml_df.to_csv("ml_predictions.csv", index=False)
        print(f"\nSaved {len(ml_df)} predictions to ml_predictions.csv")

    print("\n" + "=" * 110)
    print("ML Pipeline complete")
    print("=" * 110)


if __name__ == "__main__":
    run()
