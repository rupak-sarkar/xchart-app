import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

print("=" * 70)
print("  Screener.in Ticker Scraper → tickers.csv")
print("=" * 70)

# Scrape tickers from Screener.in
base_url = "https://www.screener.in/screens/2650136/good-stocks/?page="
hrefs = []

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

for page_num in range(1, 11):
    url = base_url + str(page_num)
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        page_links = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/company/' in href:
                page_links.append(href)
        hrefs.extend(page_links)
        print(f"  Page {page_num}: {len(page_links)} company links")
        if len(page_links) == 0:
            print(f"  No more results — stopping.")
            break
        time.sleep(1)
    except Exception as e:
        print(f"  Page {page_num}: Error - {e}")
        break

print(f"\n  Total raw links: {len(hrefs)}")

# Extract tickers from URLs
df_scraped = pd.DataFrame(hrefs, columns=['Column1'])
df_scraped['Company Name'] = df_scraped['Column1'].str.split('/').str[2]
df_scraped = df_scraped.drop_duplicates(subset='Company Name')
df_scraped['Ticker'] = df_scraped['Company Name'].str.upper()

# Clean: remove .NS suffix if present, strip whitespace
df_scraped['Ticker'] = df_scraped['Ticker'].str.replace('.NS', '', regex=False).str.strip()

# Remove empty/null
df_scraped = df_scraped[df_scraped['Ticker'].str.len() > 0]

# Build final CSV with Ticker,Sector format (sector blank — can be added later)
df_final = pd.DataFrame({
    'Ticker': df_scraped['Ticker'].values,
    'Sector': ''
})

# Sort alphabetically
df_final = df_final.sort_values('Ticker').reset_index(drop=True)

# Write tickers.csv
df_final.to_csv('tickers.csv', index=False)

print(f"\n{'=' * 70}")
print(f"  tickers.csv written — {len(df_final)} unique tickers")
print(f"{'=' * 70}")
print(f"\n  First 10: {df_final['Ticker'].head(10).tolist()}")
print(f"  Last 10:  {df_final['Ticker'].tail(10).tolist()}")
print(f"\n  Done! Commit tickers.csv to your repo.")
