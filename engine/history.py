"""History management + streak calculation"""
import pandas as pd
from engine.config import TODAY_IST, HISTORY_FILE, HISTORY_RETENTION_DAYS
from engine.utils import safe_int

def load_history():
    try:
        df = pd.read_csv(HISTORY_FILE)
        if 'Date' in df.columns:
            dates = sorted(df['Date'].unique(), reverse=True)[:HISTORY_RETENTION_DAYS]
            df = df[df['Date'].isin(dates)]
        return df
    except FileNotFoundError: return pd.DataFrame()

def save_to_history(rows):
    hdf = load_history(); tdf = pd.DataFrame(rows); tdf['Date'] = TODAY_IST
    if not hdf.empty and 'Date' in hdf.columns: hdf = hdf[hdf['Date'] != TODAY_IST]
    c = pd.concat([hdf, tdf], ignore_index=True)
    if 'Date' in c.columns:
        dates = sorted(c['Date'].unique(), reverse=True)[:HISTORY_RETENTION_DAYS]
        c = c[c['Date'].isin(dates)]
    c.to_csv(HISTORY_FILE, index=False)
    print(f"History: {len(c)} rows / {c['Date'].nunique()} days")

def calculate_streaks(hdf, tr):
    streaks = {}
    for row in tr:
        tk = row["Ticker"]; td = row["Forecast_Direction"]; ts = row["Forecast_Score"]; trr = row["Actual_Return_Pct"]
        th = pd.DataFrame()
        if not hdf.empty and 'Ticker' in hdf.columns:
            th = hdf[(hdf['Ticker'] == tk) & (hdf['Date'] != TODAY_IST)].sort_values('Date', ascending=False)
        sd = 1; sr = trr
        if not th.empty:
            for _, hr in th.iterrows():
                if safe_int(hr.get('Forecast_Direction', 0)) == td and td != 0: sd += 1; sr += float(hr.get('Actual_Return_Pct', 0))
                else: break
        ps = float(th.iloc[0].get('Forecast_Score', 0)) if not th.empty else None
        if td == 0: m = "Neutral"
        elif sd == 1: m = "New"
        elif ps is not None:
            if td == 1: m = ("Strong" if sd >= 3 else "Building") if ts >= ps else "Fading"
            elif td == -1: m = ("Strong" if sd >= 3 else "Building") if ts <= ps else "Fading"
            else: m = "Neutral"
        else: m = "New"
        streaks[tk] = {"Streak_Days": sd if td != 0 else 0, "Streak_Return": round(sr, 2), "Momentum": m}
    return streaks
