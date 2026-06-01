import pandas as pd
import random

def generate_dashboard_data():
    print("🧠 Python Engine: Processing data metrics...")
    
    # 1. Live/Active Assets (No realized outcome results yet)
    active_data = {
        "Ticker": ["RELIANCE", "TCS", "INFY", "HDFCBANK", "TATAMOTORS"],
        "Latest_Headline": [
            "Reliance Jio registers stable profit growth in Q4 report",
            "TCS signs multi-billion dollar transformation deal in Europe",
            "Infosys cuts annual revenue guidance amid spending freeze",
            "HDFC Bank merged entity posts stable loan metrics",
            "Tata Motors EV sales hit record high over holiday weekend"
        ],
        "Repeat_Count": [2, 1, 4, 1, 3],
        "Forecast_Score": [42.5, 68.1, -55.0, 12.3, 89.0],
        "Forecast_Direction": [1, 1, -1, 1, 1],
        "Actual_Direction": ["", "", "", "", ""], # Keep blank for UI filtering
        "Actual_Return_Pct": ["", "", "", "", ""]
    }

    # 2. Historical Logs (With validation data for the performance matrix)
    historical_data = {
        "Ticker": ["SBIN", "ICICIBANK", "WIPRO", "MARUTI", "BHARTIARTL"],
        "Latest_Headline": [
            "SBI gross NPA drops down drastically to record low level",
            "ICICI Bank beat estimates with robust interest income",
            "Wipro guidance misses analyst marks for third straight quarter",
            "Maruti Suzuki car production halts over global chip bottlenecks",
            "Bharti Airtel adds 3 million new wireless broadband clients"
        ],
        "Repeat_Count": [1, 2, 1, 5, 2],
        "Forecast_Score": [78.0, 52.0, -41.2, -63.5, 33.0],
        "Forecast_Direction": [1, 1, -1, -1, 1],
        "Actual_Direction": [1, 1, -1, 1, -1],     # 1 = Bullish, -1 = Bearish
        "Actual_Return_Pct": [2.4, 1.1, -3.2, 0.8, -1.5]
    }

    # Combine data frames and save directly to the repository root
    df_active = pd.DataFrame(active_data)
    df_history = pd.DataFrame(historical_data)
    final_df = pd.concat([df_active, df_history], ignore_index=True)
    
    final_df.to_csv("data.csv", index=False)
    print("✅ data.csv successfully generated!")

if __name__ == "__main__":
    generate_dashboard_data()
