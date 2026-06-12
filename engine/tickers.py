"""engine/tickers.py -- Ticker loading + screener.in scraper."""

import os
import time
import pandas as pd
from pathlib import Path

TICKERS_FILE = Path("output/tickers.csv")


def is_bad_str(s):
    s = str(s).strip().lower()
    return s in ("", "nan", "none", "0", "other")


def load_tickers():
    """Load tickers from output/tickers.csv."""
    if TICKERS_FILE.exists():
        try:
            df = pd.read_csv(TICKERS_FILE)
            df.columns = df.columns.str.strip()
            if "Ticker" not in df.columns:
                first_col = df.columns[0]
                df.rename(columns={first_col: "Ticker"}, inplace=True)
            tks = [t.replace(".NS", "") for t in df["Ticker"].dropna().str.strip().str.upper().tolist() if t]
            s = set()
            u = []
            for t in tks:
                if t not in s:
                    s.add(t)
                    u.append(t)
            sm = {}
            if "Sector" in df.columns:
                for _, r in df.iterrows():
                    tk = str(r["Ticker"]).strip().upper().replace(".NS", "")
                    sc = str(r.get("Sector", "")).strip()
                    if tk and sc and not is_bad_str(sc):
                        sm[tk] = sc
            print(f"Loaded {len(u)} tickers from {TICKERS_FILE} (sector map: {len(sm)} entries)")
            return u, sm
        except Exception as e:
            print(f"Error loading tickers: {e}")
    return ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ICICIBANK", "ITC"], {}


def update_tickers():
    """Scrape screener.in public screen and write output/tickers.csv."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("ERROR: requests/beautifulsoup4 not installed")
        return

    print("=" * 70)
    print("  Screener.in Ticker Scraper -> output/tickers.csv")
    print("=" * 70)

    base_url = "https://www.screener.in/screens/2650136/good-stocks/?page="
    hrefs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    for page_num in range(1, 15):
        url = base_url + str(page_num)
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            page_links = []
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "/company/" in href:
                    page_links.append(href)
            hrefs.extend(page_links)
            print(f"  Page {page_num}: {len(page_links)} company links")
            if len(page_links) == 0:
                print("  No more results - stopping.")
                break
            time.sleep(1.5)
        except Exception as e:
            print(f"  Page {page_num}: Error - {e}")
            break

    print(f"\n  Total raw links: {len(hrefs)}")

    if not hrefs:
        print("  ERROR: No tickers scraped! Keeping existing tickers.csv.")
        return

    df_scraped = pd.DataFrame(hrefs, columns=["Column1"])
    df_scraped["Company Name"] = df_scraped["Column1"].str.split("/").str[2]
    df_scraped = df_scraped.drop_duplicates(subset="Company Name")
    df_scraped["Ticker"] = df_scraped["Company Name"].str.upper()
    df_scraped["Ticker"] = df_scraped["Ticker"].str.replace(".NS", "", regex=False).str.strip()
    df_scraped = df_scraped[df_scraped["Ticker"].str.len() > 0]

    df_final = pd.DataFrame({"Ticker": df_scraped["Ticker"].values, "Sector": ""})
    df_final = df_final.sort_values("Ticker").reset_index(drop=True)

    # Safety: dont overwrite with far fewer tickers
    if TICKERS_FILE.exists():
        existing = pd.read_csv(TICKERS_FILE)
        if len(df_final) < len(existing) * 0.5:
            print(f"  WARNING: Scraped {len(df_final)} but existing has {len(existing)}. Keeping existing.")
            return

    TICKERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_final.to_csv(TICKERS_FILE, index=False)

    print(f"\n{'=' * 70}")
    print(f"  output/tickers.csv written - {len(df_final)} unique tickers")
    print(f"{'=' * 70}")
    print(f"  First 10: {df_final['Ticker'].head(10).tolist()}")
    print(f"  Last 10:  {df_final['Ticker'].tail(10).tolist()}")
