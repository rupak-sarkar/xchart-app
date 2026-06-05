"""Ticker loading and management"""
import os
import pandas as pd
from engine.config import TICKERS_FILE
from engine.utils import is_bad_str

def load_tickers():
    if os.path.exists(TICKERS_FILE):
        try:
            df = pd.read_csv(TICKERS_FILE); df.columns = df.columns.str.strip()
            if 'Ticker' not in df.columns:
                df.rename(columns={df.columns[0]: 'Ticker'}, inplace=True)
            tks = [t.replace('.NS', '') for t in df['Ticker'].dropna().str.strip().str.upper().tolist() if t]
            s = set(); u = []
            for t in tks:
                if t not in s: s.add(t); u.append(t)
            sm = {}
            if 'Sector' in df.columns:
                for _, r in df.iterrows():
                    tk = str(r['Ticker']).strip().upper().replace('.NS', '')
                    sc = str(r.get('Sector', '')).strip()
                    if tk and sc and not is_bad_str(sc): sm[tk] = sc
            print(f"Loaded {len(u)} tickers from {TICKERS_FILE} (sector map: {len(sm)} entries)")
            return u, sm
        except Exception as e: print(f"Error loading tickers: {e}")
    return ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ICICIBANK", "ITC"], {}
