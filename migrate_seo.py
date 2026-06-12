"""migrate_seo.py — SEO meta tags, schema, canonical, performance fixes"""

import subprocess
from pathlib import Path


def main():
    print("=" * 70)
    print("  SEO MIGRATION — Meta, Schema, Canonical, Performance")
    print("=" * 70)

    print("\n[1/3] Patching index.html...")
    patch_index()

    print("\n[2/3] Patching dashboard.html...")
    patch_dashboard()

    print("\n[3/3] Patching disclaimer.html...")
    patch_disclaimer()

    print("\n[4/4] Staging changes...")
    subprocess.run(["git", "add", "-A"], capture_output=True)

    print("\n" + "=" * 70)
    print("  SEO MIGRATION COMPLETE")
    print("=" * 70)
    print("""
  Changes Applied:
    ✅ index.html       — Meta, OG, Twitter, Schema JSON-LD, Canonical,
                           Preconnect, Defer JS, theme-color, hreflang
    ✅ dashboard.html   — Meta, OG, Schema JSON-LD, Canonical
    ✅ disclaimer.html  — Canonical, Schema JSON-LD

  Next Steps:
    1. Submit sitemap in Google Search Console
    2. Request re-indexing for all 3 pages
    3. Test: https://pagespeed.web.dev/?url=https://xchart.in
""")


# ══════════════════════════════════════════════════════════════
# INDEX.HTML
# ══════════════════════════════════════════════════════════════

def patch_index():
    fp = Path("index.html")
    if not fp.exists():
        print("  ERROR: index.html not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content

    # ── 1. Fix <html lang> ──
    if '<html lang="en">' not in content:
        content = content.replace("<html>", '<html lang="en">')
        content = content.replace("<html >", '<html lang="en">')
        print("  Added lang='en' to <html>")

    # ── 2. Replace title ──
    old_title = "<title>xchart.in | Backtest Trading Rules on Nifty 500</title>"
    new_title = "<title>xchart.in | Backtest Trading Rules on Indian Stocks — Free Analytical Tool</title>"
    if old_title in content:
        content = content.replace(old_title, new_title)
        print("  Updated <title>")

    # ── 3. Replace meta description ──
    old_desc = '<meta name="description" content="Backtest your trading rules on 500+ Indian stocks with 3 years of historical data. Free analytical tool.">'
    new_desc = '<meta name="description" content="Free stock market analytical tool for Indian equities. Backtest your trading rules with 20 technical indicators on Nifty 500 stocks. Historical data analysis for educational purposes. Not investment advice.">'
    if old_desc in content:
        content = content.replace(old_desc, new_desc)
        print("  Updated meta description")

    # ── 4. Insert SEO block after meta description ──
    seo_block = """<meta name="keywords" content="stock backtest india, technical analysis tool, RSI backtest, MACD backtest, nifty 500 screening, stock analytics india, free backtesting tool, bollinger bands backtest, swing trading india">
<meta name="author" content="xchart.in">
<meta name="theme-color" content="#2563EB">
<link rel="canonical" href="https://xchart.in/" />
<link rel="alternate" hreflang="en-in" href="https://xchart.in/" />

<!-- Open Graph -->
<meta property="og:title" content="xchart.in — Free Stock Backtest & Analytics Tool">
<meta property="og:description" content="Backtest your trading rules on 500+ Indian stocks with 20 configurable indicators. Free analytical tool for educational purposes.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://xchart.in">
<meta property="og:site_name" content="xchart.in">
<meta property="og:locale" content="en_IN">

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="xchart.in — Free Stock Backtest Tool for Indian Equities">
<meta name="twitter:description" content="Backtest your trading rules on 500+ Indian stocks with 20 indicators. Free forever.">

<!-- Preconnect for performance -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://unpkg.com">
<link rel="preconnect" href="https://cdnjs.cloudflare.com">

<!-- Schema.org JSON-LD -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebApplication",
  "name": "xchart.in",
  "url": "https://xchart.in",
  "description": "Free stock market analytical tool for Indian equities. Backtest trading rules with 20 technical indicators on Nifty 500 stocks.",
  "applicationCategory": "FinanceApplication",
  "operatingSystem": "Web Browser",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "INR"
  },
  "featureList": [
    "20 configurable technical indicators",
    "3 signal modes (Weighted, AND, Majority)",
    "Downloadable HTML backtest reports",
    "Per-indicator contribution analysis",
    "Nifty 500 stock coverage",
    "3 years historical data"
  ],
  "author": {
    "@type": "Organization",
    "name": "xchart.in",
    "url": "https://xchart.in"
  },
  "isAccessibleForFree": true,
  "inLanguage": "en",
  "countryOfOrigin": {
    "@type": "Country",
    "name": "India"
  }
}
</script>"""

    # Insert after the new meta description
    if 'og:title' not in content:
        insert_after = new_desc
        if insert_after not in content:
            # Try finding any meta description
            import re
            m = re.search(r'<meta name="description"[^>]+>', content)
            if m:
                insert_after = m.group(0)
            else:
                print("  WARNING: Could not find insertion point for SEO block")
                insert_after = None

        if insert_after:
            content = content.replace(insert_after, insert_after + "\n" + seo_block)
            print("  Added: keywords, author, theme-color, canonical, hreflang")
            print("  Added: Open Graph tags")
            print("  Added: Twitter Card tags")
            print("  Added: Preconnect hints")
            print("  Added: Schema.org JSON-LD")
    else:
        print("  OG tags already present — skipping SEO block")

    # ── 5. Defer backtest.js ──
    old_script = '<script src="backtest.js"></script>'
    new_script = '<script src="backtest.js" defer></script>'
    # Also try with quotes variation
    old_script2 = "test.js\"></script>"
    new_script2 = "test.js\" defer></script>"

    if old_script in content and 'defer' not in content.split('backtest.js')[1][:20]:
        content = content.replace(old_script, new_script)
        print("  Added defer to backtest.js")
    elif old_script2 in content and 'defer' not in content:
        content = content.replace(old_script2, new_script2)
        print("  Added defer to backtest.js")
    else:
        print("  backtest.js defer — already set or not found")

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print("  ✅ index.html patched")
    else:
        print("  No changes needed")


# ══════════════════════════════════════════════════════════════
# DASHBOARD.HTML
# ══════════════════════════════════════════════════════════════

def patch_dashboard():
    fp = Path("dashboard.html")
    if not fp.exists():
        print("  ERROR: dashboard.html not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content

    # ── 1. Fix <html lang> ──
    if '<html lang="en">' not in content:
        content = content.replace("<html>", '<html lang="en">')
        print("  Added lang='en'")

    # ── 2. Update or add title ──
    import re
    title_match = re.search(r'<title>[^<]*</title>', content)
    new_title = '<title>xchart.in | Premium Analytics Dashboard — Multi-Layer Stock Analysis</title>'
    if title_match:
        old_t = title_match.group(0)
        if old_t != new_title:
            content = content.replace(old_t, new_title)
            print("  Updated <title>")
    else:
        # Add before </head>
        content = content.replace('</head>', new_title + '\n</head>')
        print("  Added <title>")

    # ── 3. Add/replace meta description ──
    desc_match = re.search(r'<meta name="description"[^>]*>', content)
    new_desc = '<meta name="description" content="Advanced multi-layer stock analytics for Indian equities. Technical indicators, fundamental screening, and market regime analysis. Educational analytical tool. Not SEBI registered. Not investment advice.">'
    if desc_match:
        content = content.replace(desc_match.group(0), new_desc)
        print("  Updated meta description")
    else:
        content = content.replace(new_title, new_title + '\n' + new_desc)
        print("  Added meta description")

    # ── 4. Add SEO block if not present ──
    if 'og:title' not in content:
        dashboard_seo = """<meta name="keywords" content="stock analytics india, technical analysis dashboard, fundamental screening, market regime, swing trading analytics, multi-layer analysis">
<meta name="author" content="xchart.in">
<meta name="theme-color" content="#2563EB">
<link rel="canonical" href="https://xchart.in/dashboard.html" />

<!-- Open Graph -->
<meta property="og:title" content="xchart.in — Premium Multi-Layer Stock Analytics">
<meta property="og:description" content="Multi-layer analytical dashboard combining technical, fundamental, and macro analysis for Indian equities. Educational tool only.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://xchart.in/dashboard.html">
<meta property="og:site_name" content="xchart.in">
<meta property="og:locale" content="en_IN">

<!-- Schema.org JSON-LD -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebApplication",
  "name": "xchart.in Premium Analytics",
  "url": "https://xchart.in/dashboard.html",
  "description": "Advanced multi-layer stock analytics for Indian equities combining technical, fundamental, and macro analysis.",
  "applicationCategory": "FinanceApplication",
  "operatingSystem": "Web Browser",
  "isPartOf": {
    "@type": "WebSite",
    "name": "xchart.in",
    "url": "https://xchart.in"
  },
  "author": {
    "@type": "Organization",
    "name": "xchart.in",
    "url": "https://xchart.in"
  },
  "inLanguage": "en"
}
</script>"""

        content = content.replace(new_desc, new_desc + "\n" + dashboard_seo)
        print("  Added: keywords, canonical, OG, Schema JSON-LD")
    else:
        print("  OG tags already present — skipping")

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print("  ✅ dashboard.html patched")
    else:
        print("  No changes needed")


# ══════════════════════════════════════════════════════════════
# DISCLAIMER.HTML
# ══════════════════════════════════════════════════════════════

def patch_disclaimer():
    fp = Path("disclaimer.html")
    if not fp.exists():
        print("  ERROR: disclaimer.html not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content

    # ── 1. Add canonical if missing ──
    if 'rel="canonical"' not in content:
        canonical_block = """<link rel="canonical" href="https://xchart.in/disclaimer.html" />
<meta name="author" content="xchart.in">

<!-- Schema.org JSON-LD -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "Disclaimer — xchart.in",
  "url": "https://xchart.in/disclaimer.html",
  "description": "Legal disclaimer and terms of use for xchart.in analytical tool.",
  "isPartOf": {
    "@type": "WebSite",
    "name": "xchart.in",
    "url": "https://xchart.in"
  }
}
</script>"""

        # Insert before </head>
        content = content.replace('</head>', canonical_block + '\n</head>')
        print("  Added: canonical, author, Schema JSON-LD")
    else:
        print("  Canonical already present — skipping")

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print("  ✅ disclaimer.html patched")
    else:
        print("  No changes needed")


if __name__ == "__main__":
    main()
