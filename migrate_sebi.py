"""migrate_sebi.py -- One-time migration for SEBI compliance + backtest page + fixes.

Changes:
  1. app.py: Label changes (BULL->POSITIVE, BEAR->NEGATIVE, Signal->Momentum, etc.)
  2. index.html: Label changes + full disclaimer
  3. screener/premium_filter.py: Skip shareholding when unavailable + fallback
  4. screener/run_fundamentals.py: Fix .str accessor crash
  5. backtest.html: New SEBI-safe backtest page
  6. backtest.js: New weighted scoring backtest engine
  7. disclaimer.html: Full legal disclaimer

Run: python migrate_sebi.py
"""

import os
import re
from pathlib import Path


def replace_in_file(filepath, replacements):
    fp = Path(filepath)
    if not fp.exists():
        print(f"  SKIP (not found): {filepath}")
        return 0
    content = fp.read_text(encoding="utf-8")
    original = content
    count = 0
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            count += 1
    if content != original:
        fp.write_text(content, encoding="utf-8")
        print(f"  PATCHED {filepath} ({count} replacements)")
    else:
        print(f"  OK (no changes needed): {filepath}")
    return count


def patch_block(filepath, marker_start, marker_end, new_block):
    fp = Path(filepath)
    if not fp.exists():
        print(f"  SKIP (not found): {filepath}")
        return False
    content = fp.read_text(encoding="utf-8")
    start = content.find(marker_start)
    end = content.find(marker_end, start + len(marker_start) if start >= 0 else 0)
    if start < 0 or end < 0:
        print(f"  WARNING: Markers not found in {filepath}")
        print(f"    Looking for: {marker_start[:60]}...")
        return False
    end += len(marker_end)
    content = content[:start] + new_block + content[end:]
    fp.write_text(content, encoding="utf-8")
    print(f"  PATCHED block in {filepath}")
    return True


def write_file(filepath, content):
    fp = Path(filepath)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    print(f"  WROTE {filepath}")


def main():
    print("=" * 60)
    print("  SEBI COMPLIANCE MIGRATION")
    print("=" * 60)

    # ══════════════════════════════════════════════════════════
    # 1. PATCH app.py — Label changes only
    # ══════════════════════════════════════════════════════════
    print("\n[1/7] Patching app.py labels...")
    replace_in_file("app.py", [
        # Banner and headers
        ("PREDICTIVE Engine", "ANALYTICAL Engine"),
        ("PREDICTION + TRADE REPORT", "ANALYTICAL + BACKTEST REPORT"),
        ("PREDICTION", "ANALYSIS"),

        # Signal labels in print statements
        ('"BULL"', '"POSITIVE"'),
        ('"BEAR"', '"NEGATIVE"'),
        ('"NEUT"', '"NEUTRAL"'),

        # Signal labels with single quotes
        ("'BULL'", "'POSITIVE'"),
        ("'BEAR'", "'NEGATIVE'"),
        ("'NEUT'", "'NEUTRAL'"),

        # Direction labels
        ('dir_label = "BULL"', 'dir_label = "POSITIVE"'),
        ('dir_label = "BEAR"', 'dir_label = "NEGATIVE"'),
        ('dir_label = "NEUT"', 'dir_label = "NEUTRAL"'),

        # News direction
        ('"News_Direction"', '"News_Sentiment"'),
        ("News_Direction", "News_Sentiment"),

        # Column names for output
        ('"Signal"', '"Momentum"'),
        ('"Composite_Direction"', '"Momentum_Direction"'),

        # Print statement labels
        ("BULL Score:", "Sentiment:"),
        ("BULL NEUT", "POSITIVE NEUTRAL"),
        ("BULL HIT", "POSITIVE HIT"),
        ("BULL MISS", "POSITIVE MISS"),
        ("BEAR NEUT", "NEGATIVE NEUTRAL"),
        ("BEAR HIT", "NEGATIVE HIT"),
        ("BEAR MISS", "NEGATIVE MISS"),
        ("NEUT NEUT", "NEUTRAL NEUTRAL"),
        ("NEUT HIT", "NEUTRAL HIT"),

        # Report labels
        ("Bull:", "Positive:"),
        ("Bear:", "Negative:"),
        ("Neut:", "Neutral:"),
        ("SAME-DAY:", "SAME-DAY ALIGNMENT:"),
        ("LIVE ACCURACY", "HISTORICAL ALIGNMENT"),
        ("Tech-only: Bull:", "Tech-only: Positive:"),

        # Data.csv header print
        ("TICKERS:", "READINGS:"),
        ("directional", "directional momentum"),
        ("neutral", "neutral momentum"),
    ])

    # ══════════════════════════════════════════════════════════
    # 2. PATCH index.html — Label changes + disclaimer
    # ══════════════════════════════════════════════════════════
    print("\n[2/7] Patching index.html labels...")
    replace_in_file("index.html", [
        # Signal terminology
        ("BULL", "POSITIVE"),
        ("BEAR", "NEGATIVE"),
        ("Bull Signal", "Positive Momentum"),
        ("Bear Signal", "Negative Momentum"),
        ("bull signal", "positive momentum"),
        ("bear signal", "negative momentum"),

        # Section titles
        ("Today's Signals", "Today's Momentum Analysis"),
        ("Today&#39;s Signals", "Today&#39;s Momentum Analysis"),
        ("Signals", "Momentum Readings"),
        ("signals", "momentum readings"),

        # Accuracy
        ("Accuracy:", "Historical Alignment:"),
        ("accuracy:", "historical alignment:"),
        ("Accuracy", "Hist. Alignment"),

        # Signal references
        ("Signal Strength", "Momentum Strength"),
        ("signal strength", "momentum strength"),

        # Version badge
        ("v7.4 Signals", "v7.4 Analytics"),
        ("v7.4 signals", "v7.4 analytics"),

        # Hit/Win rate
        ("Win Rate", "Favorable Rate"),
        ("Hit Rate", "Alignment Rate"),
    ])

    # Add disclaimer to index.html footer if not already present
    idx_path = Path("index.html")
    if idx_path.exists():
        content = idx_path.read_text(encoding="utf-8")
        disclaimer_text = "xchart.in is an analytical tool for educational and research purposes only."
        if disclaimer_text not in content:
            # Try to insert before </body>
            footer_html = """
<div style="background:#151823;border-top:1px solid #2a2e3d;padding:12px 20px;font-size:10px;color:#8b949e;text-align:center;line-height:1.8">
  <strong>⚠️ Disclaimer:</strong> xchart.in is an analytical tool for educational and research purposes only.
  All results are based on historical data and mathematical models. Past performance does not guarantee future results.
  This platform does not provide investment advice, stock recommendations, or trading signals as defined by SEBI.
  Users are solely responsible for their investment decisions. Consult a SEBI-registered advisor before making investment decisions.
  Not SEBI registered. Charts by <a href="https://www.tradingview.com/" target="_blank" style="color:#3b82f6">TradingView</a>.
</div>
"""
            if "</body>" in content:
                content = content.replace("</body>", footer_html + "</body>")
                idx_path.write_text(content, encoding="utf-8")
                print("  ADDED disclaimer footer to index.html")
            else:
                print("  WARNING: Could not find </body> in index.html")

    # ══════════════════════════════════════════════════════════
    # 3. FIX screener/premium_filter.py
    # ══════════════════════════════════════════════════════════
    print("\n[3/7] Fixing screener/premium_filter.py...")

    pf_path = Path("screener/premium_filter.py")
    if pf_path.exists():
        content = pf_path.read_text(encoding="utf-8")
        original = content

        # Fix 1: Skip promoter_dii when no holding data
        old_block1 = """    # 12. (DII + Promoter) > 50%
    prom_dii = promoter + dii
    criteria['promoter_dii'] = (prom_dii > cfg['min_promoter_dii_holding'], prom_dii, cfg['min_promoter_dii_holding'])"""

        new_block1 = """    # 12. (DII + Promoter) > 50%
    prom_dii = promoter + dii
    if promoter > 0 or dii > 0:
        criteria['promoter_dii'] = (prom_dii > cfg['min_promoter_dii_holding'], prom_dii, cfg['min_promoter_dii_holding'])
    else:
        criteria['promoter_dii'] = (True, 0, "N/A (no holding data)")"""

        if old_block1 in content:
            content = content.replace(old_block1, new_block1)
            print("  Fixed: promoter_dii criteria (skip when no data)")
        else:
            print("  NOTE: promoter_dii block not found (may already be fixed)")

        # Fix 2: save_premium_tickers fallback
        old_save = '''def save_premium_tickers(tickers, results_df=None):
    """Save premium tickers to tickers.csv (feeds existing engine)."""
    if not tickers:
        print("  WARNING: No premium tickers to save!")
        return'''

        new_save = '''def save_premium_tickers(tickers, results_df=None):
    """Save premium tickers to tickers.csv (feeds existing engine)."""
    if not tickers:
        print("  WARNING: No premium tickers passed all criteria!")
        print("  -> Falling back to top tickers by criteria_met count")
        if results_df is not None and len(results_df) > 0:
            near_pass = results_df[results_df['Criteria_Met'] >= 12].sort_values(
                ['Criteria_Met', 'Market_Cap'], ascending=[False, False]
            )
            if len(near_pass) > 0:
                tickers = near_pass['Ticker'].tolist()[:200]
                print(f"  -> Selected {len(tickers)} near-pass tickers (>=12/14 criteria)")
            else:
                top_mcap = results_df[results_df['Market_Cap'] > 0].nlargest(150, 'Market_Cap')
                tickers = top_mcap['Ticker'].tolist()
                print(f"  -> Fallback: top {len(tickers)} by market cap")
        if not tickers:
            print("  -> CRITICAL: No tickers to save at all!")
            return'''

        if old_save in content:
            content = content.replace(old_save, new_save)
            print("  Fixed: save_premium_tickers fallback")
        else:
            print("  NOTE: save_premium_tickers block not found (may already be fixed)")

        if content != original:
            pf_path.write_text(content, encoding="utf-8")
    else:
        print("  SKIP (not found)")

    # ══════════════════════════════════════════════════════════
    # 4. FIX screener/run_fundamentals.py
    # ══════════════════════════════════════════════════════════
    print("\n[4/7] Fixing screener/run_fundamentals.py...")

    rf_path = Path("screener/run_fundamentals.py")
    if rf_path.exists():
        content = rf_path.read_text(encoding="utf-8")
        original = content

        old_sector = """        has_sector = 'Sector' in tk_df.columns and (tk_df['Sector'].str.strip() != '').sum() > 0"""
        new_sector = """        has_sector = False
        if 'Sector' in tk_df.columns and n_premium > 0:
            try:
                has_sector = (tk_df['Sector'].astype(str).str.strip() != '').sum() > 0
            except Exception:
                pass"""

        if old_sector in content:
            content = content.replace(old_sector, new_sector)
            print("  Fixed: .str accessor crash on empty/float Sector")
        else:
            print("  NOTE: Sector block not found (may already be fixed)")

        if content != original:
            rf_path.write_text(content, encoding="utf-8")
    else:
        print("  SKIP (not found)")

    # ══════════════════════════════════════════════════════════
    # 5. WRITE backtest.html (SEBI-safe)
    # ══════════════════════════════════════════════════════════
    print("\n[5/7] Writing backtest.html...")
    write_file("backtest.html", BACKTEST_HTML)

    # ══════════════════════════════════════════════════════════
    # 6. WRITE backtest.js (SEBI-safe)
    # ══════════════════════════════════════════════════════════
    print("\n[6/7] Writing backtest.js...")
    write_file("backtest.js", BACKTEST_JS)

    # ══════════════════════════════════════════════════════════
    # 7. WRITE disclaimer.html
    # ══════════════════════════════════════════════════════════
    print("\n[7/7] Writing disclaimer.html...")
    write_file("disclaimer.html", DISCLAIMER_HTML)

    # ── Git add ──
    import subprocess
    subprocess.run(["git", "add", "-A"], capture_output=True)

    # ── Report ──
    print("\n" + "=" * 60)
    print("  SEBI MIGRATION COMPLETE")
    print("=" * 60)
    print("""
  Changes applied:
    ✅ app.py — Labels: BULL→POSITIVE, BEAR→NEGATIVE, Signal→Momentum
    ✅ index.html — Labels + SEBI disclaimer footer
    ✅ screener/premium_filter.py — Shareholding skip + fallback
    ✅ screener/run_fundamentals.py — .str accessor fix
    ✅ backtest.html — New SEBI-safe backtest page
    ✅ backtest.js — New weighted scoring engine
    ✅ disclaimer.html — Full legal disclaimer

  Next steps:
    1. Commit will be done by workflow
    2. Re-trigger Fundamentals workflow
    3. Trigger OHLCV workflow (mode=full)
    4. Visit xchart.in/backtest.html
""")


# ══════════════════════════════════════════════════════════════
# EMBEDDED FILES
# ══════════════════════════════════════════════════════════════

DISCLAIMER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>xchart.in | Disclaimer & Terms</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0b10;color:#c9d1d9;min-height:100vh;padding:40px 20px}
.wrap{max-width:800px;margin:0 auto}
h1{font-size:28px;font-weight:800;color:#eef0f6;margin-bottom:8px}
h2{font-size:18px;font-weight:700;color:#eef0f6;margin-top:28px;margin-bottom:10px}
p{font-size:14px;line-height:1.8;margin-bottom:12px;color:#8b949e}
.highlight{background:#12141d;border:1px solid #252a3a;border-radius:10px;padding:20px;margin:20px 0}
.highlight p{color:#c9d1d9}
a{color:#3b82f6}
.back{display:inline-block;margin-top:20px;padding:10px 20px;background:#3b82f6;color:#fff;border-radius:6px;text-decoration:none;font-weight:600;font-size:13px}
</style>
</head>
<body>
<div class="wrap">
<h1>Disclaimer & Terms of Use</h1>
<p>Last updated: June 2026</p>

<div class="highlight">
<p><strong>xchart.in is an analytical tool for educational and research purposes only.</strong></p>
<p>This platform does not provide investment advice, stock recommendations, or trading signals as defined by the Securities and Exchange Board of India (SEBI). xchart.in is not registered with SEBI as a Research Analyst (RA) or Investment Adviser (IA).</p>
</div>

<h2>No Investment Advice</h2>
<p>All content on xchart.in — including but not limited to momentum readings, analytical scores, backtest results, fundamental data, and charts — is provided for informational and educational purposes only. Nothing on this platform constitutes a recommendation to buy, sell, or hold any security.</p>

<h2>Historical Data & Past Performance</h2>
<p>All backtest results, alignment rates, profit factors, and other metrics displayed on this platform are based on historical data and mathematical models. Past performance does not guarantee or indicate future results. Markets are inherently unpredictable and involve substantial risk of loss.</p>

<h2>User Responsibility</h2>
<p>Users are solely responsible for their investment decisions. By using xchart.in, you acknowledge that you understand the risks involved in trading and investing. You should consult a SEBI-registered investment adviser or research analyst before making any investment decisions.</p>

<h2>Data Sources</h2>
<p>Market data is sourced from publicly available sources including NSE, BSE, and third-party data providers. Fundamental data is derived from public filings. While we strive for accuracy, we do not guarantee the completeness or correctness of any data displayed.</p>

<h2>No Warranty</h2>
<p>xchart.in is provided "as is" without any warranty of any kind, express or implied. We do not warrant that the platform will be error-free, uninterrupted, or that the results obtained will be accurate or reliable.</p>

<h2>Limitation of Liability</h2>
<p>In no event shall xchart.in, its creators, or contributors be liable for any direct, indirect, incidental, special, or consequential damages arising from the use of this platform or reliance on any information provided herein.</p>

<h2>Third-Party Attribution</h2>
<p>Charts powered by <a href="https://www.tradingview.com/" target="_blank">TradingView</a>. Market data from Yahoo Finance and NSE India. Sentiment analysis uses FinBERT model.</p>

<h2>Contact</h2>
<p>For questions or concerns, please reach out via the repository at <a href="https://github.com/rupak-sarkar/xchart-app" target="_blank">github.com/rupak-sarkar/xchart-app</a>.</p>

<a href="/" class="back">← Back to Dashboard</a>
</div>
</body>
</html>"""

BACKTEST_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>xchart.in | Backtest Trading Rules on Nifty 500</title>
<meta name="description" content="Backtest your trading rules on 500+ Indian stocks with 3 years of historical data. Free analytical tool.">
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.4.1/papaparse.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0a0b10;--card:#12141d;--card2:#191c28;--card3:#1e2235;--border:#252a3a;--border2:#2f3548;--text:#c9d1d9;--text2:#7a8299;--white:#eef0f6;--bull:#22c55e;--bear:#ef4444;--neut:#eab308;--accent:#3b82f6;--accent2:#6366f1;--accent-glow:rgba(59,130,246,0.15);--gold:#f59e0b;--gold-glow:rgba(245,158,11,0.1);--radius:10px;--radius-lg:14px}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.hdr{background:var(--card);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.logo{font-size:22px;font-weight:800;color:var(--white);letter-spacing:-0.5px}.logo span{color:var(--accent)}
.badge{font-size:8px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:2px 7px;border-radius:10px;margin-left:6px;vertical-align:middle;font-weight:700;letter-spacing:0.5px}
.nav{display:flex;gap:20px;font-size:13px;font-weight:500}.nav a{color:var(--text2);transition:color 0.2s}.nav a:hover{color:var(--white)}
.hero{text-align:center;padding:44px 24px 32px;max-width:820px;margin:0 auto;position:relative}
.hero::before{content:'';position:absolute;top:-40px;left:50%;transform:translateX(-50%);width:600px;height:300px;background:radial-gradient(ellipse,var(--accent-glow) 0%,transparent 70%);pointer-events:none}
.hero h1{font-size:36px;font-weight:800;color:var(--white);margin-bottom:12px;line-height:1.15;letter-spacing:-1px;position:relative}
.hero h1 em{font-style:normal;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{font-size:15px;color:var(--text2);margin-bottom:20px;line-height:1.7;max-width:600px;margin-left:auto;margin-right:auto;position:relative}
.hero-pills{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;position:relative}
.pill{background:var(--card2);border:1px solid var(--border);border-radius:20px;padding:6px 16px;font-size:12px;font-weight:600;color:var(--text)}.pill .num{color:var(--accent);margin-right:4px}
.bt-wrap{display:flex;gap:14px;padding:0 20px 30px;max-width:1440px;margin:0 auto}
.bt-left{width:360px;flex-shrink:0;display:flex;flex-direction:column;gap:10px}
.bt-right{flex:1;min-width:0;display:flex;flex-direction:column;gap:10px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:16px 18px}
.card-t{font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:12px;font-weight:700;display:flex;align-items:center;gap:7px}
.card-t .icon{font-size:15px}
.search-wrap{position:relative}
.search-wrap input{width:100%;padding:12px 16px 12px 40px;background:var(--card2);border:2px solid var(--border);border-radius:var(--radius);color:var(--white);font-size:14px;font-weight:500;outline:none;transition:border-color 0.2s}
.search-wrap input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}
.search-wrap input::placeholder{color:var(--text2)}
.search-wrap .si{position:absolute;left:14px;top:50%;transform:translateY(-50%);font-size:16px;color:var(--text2)}
.ticker-info{display:flex;align-items:center;gap:8px;margin-top:8px;padding:8px 12px;background:var(--card2);border-radius:var(--radius);border:1px solid var(--border)}
.ticker-info .tk-name{font-size:16px;font-weight:700;color:var(--white)}
.ticker-info .tk-sector{font-size:11px;color:var(--text2);background:var(--card3);padding:2px 8px;border-radius:4px}
.ind-slot{background:var(--card2);border:1px solid var(--border);border-radius:var(--radius);padding:12px;margin-bottom:8px;transition:all 0.2s}
.ind-slot.active{border-color:var(--accent);background:rgba(59,130,246,0.04)}
.ind-slot-hdr{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.ind-slot-num{width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center}
.ind-slot-num.empty{background:var(--border);color:var(--text2)}
.ind-select{flex:1;padding:7px 10px;background:var(--card3);border:1px solid var(--border);border-radius:6px;color:var(--white);font-size:12px;font-weight:500;outline:none;cursor:pointer}
.ind-select:focus{border-color:var(--accent)}
.ind-remove{width:22px;height:22px;border-radius:50%;background:transparent;border:1px solid var(--border);color:var(--text2);font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all 0.2s}
.ind-remove:hover{background:var(--bear);border-color:var(--bear);color:#fff}
.ind-config{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.ind-param{display:flex;align-items:center;gap:4px;font-size:11px}
.ind-param label{color:var(--text2);min-width:50px}
.ind-param input{width:60px;padding:4px 6px;background:var(--card3);border:1px solid var(--border);border-radius:4px;color:var(--white);font-size:11px;text-align:center;outline:none}
.ind-param input:focus{border-color:var(--accent)}
.weight-wrap{margin-top:6px;display:flex;align-items:center;gap:6px}
.weight-wrap label{font-size:10px;color:var(--text2);min-width:45px}
.weight-slider{flex:1;-webkit-appearance:none;height:4px;border-radius:2px;background:var(--border);outline:none}
.weight-slider::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:var(--accent);cursor:pointer;border:2px solid var(--card)}
.weight-val{font-size:12px;font-weight:700;color:var(--accent);min-width:32px;text-align:right}
.weight-bar{height:8px;border-radius:4px;background:var(--border);overflow:hidden;margin-top:10px;display:flex}
.weight-bar .seg{height:100%;transition:width 0.3s}
.weight-total{display:flex;justify-content:space-between;align-items:center;margin-top:4px;font-size:11px}
.weight-total .wt-num{font-weight:700}.wt-ok{color:var(--bull)}.wt-err{color:var(--bear)}
.exit-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px}
.exit-item{display:flex;align-items:center;gap:6px;padding:6px 8px;background:var(--card2);border:1px solid var(--border);border-radius:6px;font-size:11px}
.exit-item input[type="checkbox"]{accent-color:var(--accent);width:14px;height:14px}
.exit-item input[type="number"]{width:45px;padding:3px;background:var(--card3);border:1px solid var(--border);border-radius:3px;color:var(--white);font-size:11px;text-align:center;outline:none}
.exit-item label{color:var(--text);flex:1;cursor:pointer}
.threshold-row{display:flex;align-items:center;gap:10px;margin-top:8px;padding:10px 12px;background:var(--card2);border-radius:var(--radius);border:1px solid var(--border)}
.threshold-row label{font-size:11px;color:var(--text2);flex:1}
.threshold-row input,.threshold-row select{width:70px;padding:5px;background:var(--card3);border:1px solid var(--border);border-radius:4px;color:var(--white);font-size:12px;outline:none}
.btn-run{width:100%;padding:14px;border:none;border-radius:var(--radius);font-size:15px;font-weight:700;cursor:pointer;letter-spacing:0.3px;transition:all 0.25s}
.btn-run.ready{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;box-shadow:0 4px 20px var(--accent-glow)}
.btn-run.ready:hover{transform:translateY(-2px);box-shadow:0 6px 28px rgba(59,130,246,0.3)}
.btn-run:disabled{background:var(--card2);color:var(--text2);cursor:not-allowed;transform:none;box-shadow:none}
.btn-add{width:100%;padding:10px;background:transparent;border:2px dashed var(--border);border-radius:var(--radius);color:var(--text2);font-size:12px;font-weight:600;cursor:pointer;transition:all 0.2s}
.btn-add:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-glow)}
.btn-add:disabled{opacity:0.3;cursor:not-allowed}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}
.kpi{background:var(--card2);border:1px solid var(--border);border-radius:var(--radius);padding:12px 10px;text-align:center}
.kpi-v{font-size:18px;font-weight:700;color:var(--white)}.kpi-l{font-size:9px;color:var(--text2);text-transform:uppercase;margin-top:3px;letter-spacing:0.3px}
.stock-profile{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:6px;margin-top:8px}
.sp-item{background:var(--card2);border:1px solid var(--border);border-radius:6px;padding:8px;text-align:center}
.sp-item .sp-v{font-size:14px;font-weight:700;color:var(--white)}.sp-item .sp-l{font-size:9px;color:var(--text2);margin-top:2px}
.premium-card{background:linear-gradient(135deg,rgba(245,158,11,0.06),rgba(245,158,11,0.02));border:1px solid var(--gold);border-radius:var(--radius-lg);padding:18px;text-align:center}
.premium-card h3{color:var(--gold);font-size:14px;margin-bottom:6px}.premium-card p{font-size:12px;color:var(--text2);line-height:1.6;margin-bottom:12px}
.btn-premium{padding:8px 20px;background:var(--gold);color:#000;border:none;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer}.btn-premium:hover{background:#d97706}
.chart-wrap{position:relative;min-height:380px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius-lg);overflow:hidden}
.chart-label{position:absolute;top:10px;left:14px;font-size:10px;color:var(--text2);text-transform:uppercase;letter-spacing:0.5px;font-weight:600;z-index:5}
.tbl{width:100%;border-collapse:collapse;font-size:11px}
.tbl th{color:var(--text2);font-weight:600;text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase}
.tbl td{padding:5px 8px;border-bottom:1px solid rgba(42,46,61,0.3);color:var(--white)}
.tbl tr:hover{background:var(--card2)}.tbl .win{color:var(--bull)}.tbl .loss{color:var(--bear)}
.placeholder{text-align:center;padding:60px 24px}
.placeholder .ph-icon{font-size:56px;margin-bottom:16px}.placeholder h3{font-size:18px;color:var(--white);font-weight:700;margin-bottom:8px}
.placeholder p{font-size:13px;color:var(--text2);line-height:1.6;max-width:400px;margin:0 auto}
.steps{display:flex;justify-content:center;gap:24px;margin-top:20px;flex-wrap:wrap}
.step{text-align:center}.step-num{width:28px;height:28px;border-radius:50%;background:var(--accent);color:#fff;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;margin:0 auto 6px}.step-text{font-size:11px;color:var(--text2)}
.status{font-size:11px;color:var(--text2);padding:6px 0;display:flex;align-items:center;gap:6px}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}.dot-ok{background:var(--bull)}.dot-err{background:var(--bear)}.dot-load{background:var(--neut);animation:pulse 1.5s ease infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.ftr{background:var(--card);border-top:1px solid var(--border);padding:12px 24px;font-size:10px;color:var(--text2);text-align:center;line-height:1.8;margin-top:30px}
@media(max-width:960px){.bt-wrap{flex-direction:column}.bt-left{width:100%}.hero h1{font-size:28px}.kpi-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:500px){.kpi-grid{grid-template-columns:repeat(2,1fr)}.exit-grid{grid-template-columns:1fr}.chart-wrap{min-height:260px}.hero{padding:30px 16px 20px}.stock-profile{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="hdr">
  <a href="/" class="logo">x<span>chart</span>.in<span class="badge">ANALYTICS</span></a>
  <div class="nav"><a href="/">Dashboard</a><a href="/backtest.html">Backtest</a><a href="/disclaimer.html">Disclaimer</a></div>
</div>
<div class="hero">
  <h1>Backtest <em>your</em> trading rules<br>on Nifty 500</h1>
  <p>Historical analysis tool for educational &amp; research purposes. Pick a stock, configure indicators, see how your rules performed on past data.</p>
  <div class="hero-pills">
    <div class="pill"><span class="num" id="hsTickers">500</span>Stocks</div>
    <div class="pill"><span class="num">3Y</span>History</div>
    <div class="pill"><span class="num">12</span>Indicators</div>
    <div class="pill"><span class="num">Free</span>Forever</div>
  </div>
</div>
<div class="bt-wrap">
  <div class="bt-left">
    <div class="card">
      <div class="card-t"><span class="icon">🔍</span> Select Stock</div>
      <div class="search-wrap"><span class="si">⌕</span><input type="text" id="tickerSearch" placeholder="Search by ticker or company name..." list="tickerList" autocomplete="off"><datalist id="tickerList"></datalist></div>
      <div id="tickerInfo" style="display:none"><div class="ticker-info"><span class="tk-name" id="tkName">—</span><span class="tk-sector" id="tkSector">—</span></div></div>
      <div class="status" id="dataStatus"><span class="dot dot-load"></span> Loading stock list...</div>
    </div>
    <div class="card">
      <div class="card-t"><span class="icon">📐</span> Indicators &amp; Weights <span style="color:var(--text2);font-weight:400;font-size:10px;margin-left:auto">(max 5)</span></div>
      <div id="indSlots"></div>
      <button class="btn-add" id="btnAddInd" onclick="addIndicatorSlot()">+ Add Indicator</button>
      <div class="weight-bar" id="weightBar"></div>
      <div class="weight-total"><span>Total Weight</span><span id="weightTotal" class="wt-num wt-err">0%</span></div>
    </div>
    <div class="card">
      <div class="card-t"><span class="icon">🎚️</span> Settings</div>
      <div class="threshold-row"><label>Entry threshold (composite)</label><span>±</span><input type="number" id="entryThreshold" value="20" min="5" max="50" step="5"></div>
      <div class="card-t" style="margin-top:14px"><span class="icon">🚪</span> Exit Rules</div>
      <div class="exit-grid">
        <div class="exit-item"><input type="checkbox" id="x_sl" checked><label for="x_sl">Stop Loss</label><input type="number" id="x_sl_val" value="5" min="1" max="20" step="0.5"><span style="color:var(--text2);font-size:10px">%</span></div>
        <div class="exit-item"><input type="checkbox" id="x_tp"><label for="x_tp">Target</label><input type="number" id="x_tp_val" value="10" min="2" max="50" step="1"><span style="color:var(--text2);font-size:10px">%</span></div>
        <div class="exit-item"><input type="checkbox" id="x_trail"><label for="x_trail">Trailing SL</label><input type="number" id="x_trail_val" value="3" min="1" max="15" step="0.5"><span style="color:var(--text2);font-size:10px">%</span></div>
        <div class="exit-item"><input type="checkbox" id="x_maxhold" checked><label for="x_maxhold">Max Hold</label><input type="number" id="x_maxhold_val" value="14" min="1" max="90" step="1"><span style="color:var(--text2);font-size:10px">days</span></div>
      </div>
      <div class="threshold-row" style="margin-top:8px"><label>Backtest period</label><select id="period"><option value="6m">6 Months</option><option value="1y" selected>1 Year</option><option value="2y">2 Years</option><option value="3y">3 Years</option></select></div>
    </div>
    <button class="btn-run" id="btnRun" disabled>▶ &nbsp;Select a stock first</button>
  </div>
  <div class="bt-right">
    <div class="card" id="placeholder"><div class="placeholder"><div class="ph-icon">📊</div><h3>Your rules, backtested on real data</h3><p>Build a weighted scoring model with your indicators and see historical performance. This is an analytical tool — not investment advice.</p><div class="steps"><div class="step"><div class="step-num">1</div><div class="step-text">Pick a stock</div></div><div class="step"><div class="step-num">2</div><div class="step-text">Add indicators</div></div><div class="step"><div class="step-num">3</div><div class="step-text">Set weights</div></div><div class="step"><div class="step-num">4</div><div class="step-text">Run &amp; analyze</div></div></div></div></div>
    <div class="card" id="kpiCard" style="display:none"><div class="card-t"><span class="icon">🎯</span> Backtest Summary — <span id="resultTicker" style="color:var(--accent)"></span></div><div class="kpi-grid" id="kpiGrid"></div><div style="margin-top:8px;font-size:10px;color:var(--text2)">ℹ️ Based on historical data. Past performance ≠ future results.</div></div>
    <div class="chart-wrap" id="chartWrap" style="display:none"><div class="chart-label">Price Chart with Entry/Exit Markers</div><div id="btChart" style="width:100%;height:380px"></div></div>
    <div class="chart-wrap" id="equityWrap" style="display:none"><div class="chart-label">Hypothetical Equity Curve (₹100 start)</div><div id="eqChart" style="width:100%;height:180px"></div></div>
    <div class="card" id="profileCard" style="display:none"><div class="card-t"><span class="icon">📋</span> Stock Profile <span style="color:var(--text2);font-weight:400;font-size:10px;margin-left:auto">Data from public filings</span></div><div class="stock-profile" id="stockProfile"></div><div style="margin-top:8px;font-size:10px;color:var(--text2)">ℹ️ Raw fundamental data for reference only. Not a recommendation.</div></div>
    <div id="premiumCard" style="display:none"><div class="premium-card"><h3>🔒 Advanced Analytics (Premium)</h3><p>Your backtest used technical indicators. Premium analytics includes multi-layer composite scoring, FinBERT news sentiment analysis, sector rotation detection, and 14-parameter fundamental quality filtering.</p><p style="font-size:10px;color:var(--text2)">All outputs are analytical tools. No investment advice is provided.</p><button class="btn-premium" onclick="window.location.href='/'">Explore Advanced Analytics →</button></div></div>
    <div class="card" id="tradeCard" style="display:none"><div class="card-t"><span class="icon">📋</span> Historical Triggers <span id="tradeCount" style="color:var(--text2);font-weight:400"></span></div><div style="max-height:320px;overflow-y:auto"><table class="tbl" id="tradeTable"><thead><tr><th>#</th><th>Entry Date</th><th>Entry ₹</th><th>Exit Date</th><th>Exit ₹</th><th>Days</th><th>Result</th><th>Exit Type</th></tr></thead><tbody id="tradeBody"></tbody></table></div></div>
  </div>
</div>
<div class="ftr">
  <strong>⚠️ Disclaimer:</strong> xchart.in is an analytical tool for educational and research purposes only. All results are based on historical data and mathematical models. Past performance does not guarantee future results. This platform does not provide investment advice, stock recommendations, or trading signals as defined by SEBI. Users are solely responsible for their investment decisions. Not SEBI registered. Charts by <a href="https://www.tradingview.com/" target="_blank" style="color:var(--accent)">TradingView</a>. | <a href="/disclaimer.html" style="color:var(--accent)">Full Disclaimer</a>
</div>
<script src="backtest.js"></script>
</body>
</html>"""

BACKTEST_JS = r"""/**
 * backtest.js - SEBI-safe weighted indicator scoring + walk-forward backtest
 * xchart.in analytical tool - educational/research purposes only
 */
(function(){"use strict";
var MAX_IND=5,DATA_BASE="screener_data/backtest_data/",TICKERS_CSV="screener_data/nifty500_tickers.csv",SCORES_CSV="screener_data/nifty500_scores.csv";
var IND_COLORS=["#3b82f6","#22c55e","#f59e0b","#ef4444","#8b5cf6"];
var TICKERS=[],TICKER_DATA=null,SCORES_DATA={},slots=[],mainChart=null,eqChart=null;
var pf=function(v){return parseFloat(v)||0},r2=function(v){return Math.round(v*100)/100};

// ── Indicator computations ──
function computeSMA(c,p){var r=new Array(c.length).fill(null);for(var i=p-1;i<c.length;i++){var s=0;for(var j=i-p+1;j<=i;j++)s+=c[j];r[i]=s/p}return r}
function computeEMA(c,p){var r=new Array(c.length).fill(null),k=2/(p+1),s=0;for(var i=0;i<p;i++)s+=c[i];r[p-1]=s/p;for(var i=p;i<c.length;i++)r[i]=c[i]*k+r[i-1]*(1-k);return r}
function computeRSI(c,p){var r=new Array(c.length).fill(null);if(c.length<p+1)return r;var aG=0,aL=0;for(var i=1;i<=p;i++){var d=c[i]-c[i-1];if(d>0)aG+=d;else aL-=d}aG/=p;aL/=p;r[p]=aL===0?100:100-100/(1+aG/aL);for(var i=p+1;i<c.length;i++){var d=c[i]-c[i-1];aG=(aG*(p-1)+(d>0?d:0))/p;aL=(aL*(p-1)+(d<0?-d:0))/p;r[i]=aL===0?100:100-100/(1+aG/aL)}return r}
function computeMACD(c){var e12=computeEMA(c,12),e26=computeEMA(c,26);var line=c.map(function(_,i){return e12[i]!==null&&e26[i]!==null?e12[i]-e26[i]:null});var vl=[],vi=[];line.forEach(function(v,i){if(v!==null){vl.push(v);vi.push(i)}});var sig=new Array(c.length).fill(null);if(vl.length>=9){var se=computeEMA(vl,9);se.forEach(function(v,i){if(v!==null)sig[vi[i]]=v})}return{line:line,signal:sig}}
function computeBB(c,p){p=p||20;var u=new Array(c.length).fill(null),l=new Array(c.length).fill(null);for(var i=p-1;i<c.length;i++){var sl=c.slice(i-p+1,i+1),m=sl.reduce(function(a,b){return a+b},0)/p,v=sl.reduce(function(a,b){return a+(b-m)*(b-m)},0)/p;u[i]=m+2*Math.sqrt(v);l[i]=m-2*Math.sqrt(v)}return{upper:u,lower:l}}
function computeSuperTrend(h,l,c){var n=c.length,dir=new Array(n).fill(0);var tr=[0];for(var i=1;i<n;i++)tr.push(Math.max(h[i]-l[i],Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1])));var atr=new Array(n).fill(null);for(var i=9;i<n;i++){var s=0;for(var j=i-9;j<=i;j++)s+=tr[j];atr[i]=s/10}var fv=-1;for(var i=0;i<n;i++){if(atr[i]!==null){fv=i;break}}if(fv<0)return dir;var fu=(h[fv]+l[fv])/2+3*atr[fv],fl=(h[fv]+l[fv])/2-3*atr[fv];dir[fv]=c[fv]>fu?-1:1;for(var i=fv+1;i<n;i++){if(atr[i]===null){dir[i]=dir[i-1];continue}var hl2=(h[i]+l[i])/2,lb=hl2-3*atr[i],ub=hl2+3*atr[i];fl=(lb>fl||c[i-1]<fl)?lb:fl;fu=(ub<fu||c[i-1]>fu)?ub:fu;if(dir[i-1]<=0&&c[i]>fu)dir[i]=-1;else if(dir[i-1]>=0&&c[i]<fl)dir[i]=1;else dir[i]=dir[i-1]}return dir}
function computeADX(h,l,c){var n=c.length,r=new Array(n).fill(null);if(n<15)return r;var tr=[0],pDM=[0],mDM=[0];for(var i=1;i<n;i++){tr.push(Math.max(h[i]-l[i],Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1])));var up=h[i]-h[i-1],dn=l[i-1]-l[i];pDM.push(up>dn&&up>0?up:0);mDM.push(dn>up&&dn>0?dn:0)}var a=1/14,at=0,sp=0,sm=0;for(var i=0;i<14;i++){at+=tr[i];sp+=pDM[i];sm+=mDM[i]}at/=14;sp/=14;sm/=14;var dx=[];for(var i=14;i<n;i++){at=at*(1-a)+tr[i]*a;sp=sp*(1-a)+pDM[i]*a;sm=sm*(1-a)+mDM[i]*a;var pdi=at>0?100*sp/at:0,mdi=at>0?100*sm/at:0,ds=pdi+mdi;dx.push(ds>0?100*Math.abs(pdi-mdi)/ds:0);if(dx.length>=14)r[i]=dx.slice(-14).reduce(function(a,b){return a+b},0)/14}return r}
function computeATRPct(h,l,c){var n=c.length,r=new Array(n).fill(null);var tr=[0];for(var i=1;i<n;i++)tr.push(Math.max(h[i]-l[i],Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1])));for(var i=13;i<n;i++){var s=0;for(var j=i-13;j<=i;j++)s+=tr[j];r[i]=c[i]>0?(s/14)/c[i]*100:null}return r}

// ── Indicator definitions ──
var INDICATORS={
  rsi:{name:"RSI (14)",params:[{id:"oversold",label:"Oversold",def:30,min:10,max:45},{id:"overbought",label:"Overbought",def:70,min:55,max:90}],score:function(d,i,p){var v=d.rsi[i];if(v===null)return 0;var os=p.oversold||30,ob=p.overbought||70,mid=(os+ob)/2;if(v<=os)return 100;if(v>=ob)return-100;return Math.round((mid-v)/(mid-os)*100)}},
  sma_cross:{name:"SMA Crossover",params:[{id:"fast",label:"Fast",def:9,min:2,max:50},{id:"slow",label:"Slow",def:22,min:5,max:200}],score:function(d,i,p){var f=d["sma_"+(p.fast||9)],s=d["sma_"+(p.slow||22)];if(!f||!s||f[i]===null||s[i]===null||s[i]===0)return 0;return Math.max(-100,Math.min(100,Math.round((f[i]-s[i])/s[i]*2000)))}},
  macd:{name:"MACD (12/26/9)",params:[],score:function(d,i){var l=d.macd_line[i],s=d.macd_signal[i];if(l===null||s===null)return 0;var diff=l-s,c=d.closes[i]||1;return Math.max(-100,Math.min(100,Math.round(diff/c*10000)))}},
  supertrend:{name:"SuperTrend",params:[],score:function(d,i){return d.st_dir[i]===-1?80:d.st_dir[i]===1?-80:0}},
  bb_position:{name:"Bollinger Band Position",params:[],score:function(d,i){var u=d.bb_upper[i],l=d.bb_lower[i],c=d.closes[i];if(u===null||l===null||!c)return 0;var range=u-l;if(range<=0)return 0;return Math.round((0.5-(c-l)/range)*200)}},
  adx_trend:{name:"ADX Trend Strength",params:[{id:"threshold",label:"Threshold",def:25,min:15,max:40}],score:function(d,i,p){var a=d.adx[i];if(a===null)return 0;var t=p.threshold||25;if(a<t)return 0;var str=Math.min((a-t)/(50-t)*100,100);var dir=d.sma_9&&d.sma_22&&d.sma_9[i]!==null&&d.sma_22[i]!==null?(d.sma_9[i]>d.sma_22[i]?1:-1):0;return Math.round(str*dir)}},
  ema_cross:{name:"EMA Crossover",params:[{id:"fast",label:"Fast",def:9,min:2,max:50},{id:"slow",label:"Slow",def:21,min:5,max:100}],score:function(d,i,p){var f=d["ema_"+(p.fast||9)],s=d["ema_"+(p.slow||21)];if(!f||!s||f[i]===null||s[i]===null||s[i]===0)return 0;return Math.max(-100,Math.min(100,Math.round((f[i]-s[i])/s[i]*2000)))}},
  price_vs_sma200:{name:"Price vs SMA 200",params:[],score:function(d,i){var s=d.sma_200?d.sma_200[i]:null,c=d.closes[i];if(s===null||!c||s===0)return 0;return Math.max(-100,Math.min(100,Math.round((c-s)/s*500)))}},
  volume_spike:{name:"Volume Spike",params:[{id:"lookback",label:"Lookback",def:20,min:5,max:50}],score:function(d,i,p){var lb=p.lookback||20;if(i<lb||!d.volumes)return 0;var s=0;for(var j=i-lb;j<i;j++)s+=(d.volumes[j]||0);var avg=s/lb;if(avg<=0)return 0;var ratio=(d.volumes[i]||0)/avg;var dir=d.closes[i]>d.closes[i-1]?1:-1;if(ratio>2)return Math.round(80*dir);if(ratio>1.5)return Math.round(50*dir);return 0}},
  rsi_momentum:{name:"RSI Momentum",params:[],score:function(d,i){if(i<5)return 0;var r=d.rsi[i],rp=d.rsi[i-5];if(r===null||rp===null)return 0;return Math.max(-100,Math.min(100,Math.round((r-rp)*3)))}},
  atr_filter:{name:"ATR Volatility Filter",params:[{id:"min_atr",label:"Min ATR%",def:2,min:0.5,max:10}],score:function(d,i,p){var a=d.atr_pct?d.atr_pct[i]:null;if(a===null)return 0;var m=p.min_atr||2;if(a<m)return-30;if(a>m*3)return-20;return 30}},
  sma9_reversal:{name:"SMA9 Reversal (Trend)",params:[],score:function(d,i){if(i<2)return 0;var s9=d.sma_9,s22=d.sma_22,s200=d.sma_200,c=d.closes;if(!s9||!s22||!s200||s9[i]===null||s9[i-1]===null||s22[i]===null||s200[i]===null)return 0;var rising=s9[i]>s9[i-1];var falling=s9[i]<s9[i-1];if(rising&&c[i]>s9[i]&&s9[i]>s22[i])return 80;if(falling&&c[i]<s9[i]&&s9[i]<s22[i])return-80;return 0}}
};

// ── Data loading ──
function loadTickerList(){
  Papa.parse(TICKERS_CSV,{download:true,header:true,complete:function(r){
    TICKERS=r.data.filter(function(row){return((row.Ticker||row.Symbol||"").trim())&&(row.Ticker||row.Symbol||"").trim()!=="nan"}).map(function(row){return{ticker:(row.Ticker||row.Symbol||"").trim(),name:(row.Company_Name||"").trim(),industry:(row.Industry||"").trim()}});
    var dl=document.getElementById("tickerList");dl.innerHTML="";TICKERS.forEach(function(t){var o=document.createElement("option");o.value=t.ticker;o.textContent=t.ticker+(t.name?" — "+t.name:"");dl.appendChild(o)});
    document.getElementById("hsTickers").textContent=TICKERS.length;updateStatus("ok",TICKERS.length+" stocks ready.");
  },error:function(){updateStatus("err","Could not load stock list.")}});
  // Load scores CSV for stock profile
  Papa.parse(SCORES_CSV,{download:true,header:true,complete:function(r){r.data.forEach(function(row){var tk=(row.Ticker||"").trim();if(tk)SCORES_DATA[tk]=row})},error:function(){}});
}
function loadTickerData(ticker){
  updateStatus("load","Loading "+ticker+"...");document.getElementById("btnRun").disabled=true;document.getElementById("btnRun").className="btn-run";
  fetch(DATA_BASE+ticker+".json").then(function(r){if(!r.ok)throw new Error(r.status);return r.json()}).then(function(data){
    TICKER_DATA=data;var info=TICKERS.find(function(t){return t.ticker===ticker})||{};
    document.getElementById("tickerInfo").style.display="block";document.getElementById("tkName").textContent=ticker;document.getElementById("tkSector").textContent=info.industry||info.name||"—";
    updateStatus("ok",ticker+": "+data.rows+" days ("+data.first_date+" → "+data.last_date+")");validateAndEnable();
  }).catch(function(){TICKER_DATA=null;document.getElementById("tickerInfo").style.display="none";updateStatus("err",ticker+" not found.")});
}
function updateStatus(type,msg){var el=document.getElementById("dataStatus");el.innerHTML='<span class="dot dot-'+(type==="ok"?"ok":type==="err"?"err":"load")+'"></span> '+msg}

// ── Slot management ──
function addIndicatorSlot(){if(slots.length>=MAX_IND)return;var id="s_"+Date.now(),w=slots.length===0?100:Math.max(5,Math.floor((100-getTotalWeight())/(MAX_IND-slots.length+1)));slots.push({id:id,indicator:"",weight:w,params:{}});renderSlots();updateWeightBar();validateAndEnable()}
function removeSlot(id){slots=slots.filter(function(s){return s.id!==id});renderSlots();updateWeightBar();validateAndEnable()}
window.addIndicatorSlot=addIndicatorSlot;window.removeSlot=removeSlot;
window.updateSlotIndicator=function(id,v){var s=slots.find(function(x){return x.id===id});if(s){s.indicator=v;s.params={};if(v&&INDICATORS[v])INDICATORS[v].params.forEach(function(p){s.params[p.id]=p.def})}renderSlots();validateAndEnable()};
window.updateSlotParam=function(id,pid,v){var s=slots.find(function(x){return x.id===id});if(s)s.params[pid]=parseFloat(v)||0};
window.updateSlotWeight=function(id,v){var s=slots.find(function(x){return x.id===id});if(s)s.weight=parseInt(v)||0;renderSlots();updateWeightBar();validateAndEnable()};
function getTotalWeight(){return slots.reduce(function(s,x){return s+(x.weight||0)},0)}
function renderSlots(){
  var c=document.getElementById("indSlots");c.innerHTML="";
  slots.forEach(function(slot,idx){
    var opts='<option value="">— Select indicator —</option>';Object.keys(INDICATORS).forEach(function(k){opts+='<option value="'+k+'"'+(slot.indicator===k?" selected":"")+'>'+INDICATORS[k].name+'</option>'});
    var ph="";if(slot.indicator&&INDICATORS[slot.indicator])INDICATORS[slot.indicator].params.forEach(function(p){var v=slot.params[p.id]!==undefined?slot.params[p.id]:p.def;ph+='<div class="ind-param"><label>'+p.label+'</label><input type="number" value="'+v+'" min="'+(p.min||0)+'" max="'+(p.max||999)+'" onchange="updateSlotParam(\''+slot.id+"','"+p.id+"',this.value)\"></div>"});
    var d=document.createElement("div");d.className="ind-slot"+(slot.indicator?" active":"");d.id=slot.id;
    d.innerHTML='<div class="ind-slot-hdr"><div class="ind-slot-num'+(slot.indicator?"":" empty")+'" style="background:'+(slot.indicator?IND_COLORS[idx%IND_COLORS.length]:"")+'">'+(idx+1)+'</div><select class="ind-select" onchange="updateSlotIndicator(\''+slot.id+"',this.value)\">"+opts+'</select><button class="ind-remove" onclick="removeSlot(\''+slot.id+"')\" title=\"Remove\">✕</button></div>"+(ph?'<div class="ind-config">'+ph+"</div>":"")+'<div class="weight-wrap"><label>Weight</label><input type="range" class="weight-slider" min="0" max="100" step="5" value="'+slot.weight+'" oninput="updateSlotWeight(\''+slot.id+"',this.value)\" style=\"accent-color:"+IND_COLORS[idx%IND_COLORS.length]+"\"><span class=\"weight-val\">"+slot.weight+"%</span></div>";
    c.appendChild(d)});
  var btn=document.getElementById("btnAddInd");btn.disabled=slots.length>=MAX_IND;btn.textContent=slots.length>=MAX_IND?"Maximum 5 indicators reached":"+ Add Indicator ("+(MAX_IND-slots.length)+" remaining)";
}
function updateWeightBar(){var bar=document.getElementById("weightBar"),tot=document.getElementById("weightTotal"),tw=getTotalWeight();bar.innerHTML="";slots.forEach(function(s,i){if(s.weight>0){var seg=document.createElement("div");seg.className="seg";seg.style.width=s.weight+"%";seg.style.background=IND_COLORS[i%IND_COLORS.length];bar.appendChild(seg)}});tot.textContent=tw+"%";tot.className="wt-num "+(tw===100?"wt-ok":"wt-err")}
function validateAndEnable(){var tw=getTotalWeight(),has=slots.some(function(s){return s.indicator}),ok=TICKER_DATA&&has&&tw===100;var btn=document.getElementById("btnRun");btn.disabled=!ok;btn.className="btn-run"+(ok?" ready":"");if(!TICKER_DATA)btn.textContent="▶  Select a stock first";else if(!has)btn.textContent="▶  Add at least one indicator";else if(tw!==100)btn.textContent="▶  Weights must equal 100% (currently "+tw+"%)";else btn.textContent="▶  Run Backtest"}

// ── Backtest engine ──
function runBacktest(){
  if(!TICKER_DATA)return;var ohlcv=TICKER_DATA.ohlcv;
  var period=document.getElementById("period").value,cutoff={"6m":130,"1y":260,"2y":520,"3y":9999}[period]||260;
  if(ohlcv.length>cutoff)ohlcv=ohlcv.slice(-cutoff);var n=ohlcv.length;if(n<30){updateStatus("err","Not enough data.");return}
  var dates=[],opens=[],highs=[],lows=[],closes=[],volumes=[];
  ohlcv.forEach(function(r){dates.push(r.d);opens.push(r.o);highs.push(r.h);lows.push(r.l);closes.push(r.c);volumes.push(r.v)});
  var data={dates:dates,opens:opens,highs:highs,lows:lows,closes:closes,volumes:volumes,rsi:computeRSI(closes,14),macd_line:computeMACD(closes).line,macd_signal:computeMACD(closes).signal,bb_upper:computeBB(closes).upper,bb_lower:computeBB(closes).lower,adx:computeADX(highs,lows,closes),st_dir:computeSuperTrend(highs,lows,closes),atr_pct:computeATRPct(highs,lows,closes)};
  [9,22,50,200].forEach(function(p){data["sma_"+p]=computeSMA(closes,p)});[9,21].forEach(function(p){data["ema_"+p]=computeEMA(closes,p)});
  // Dynamic SMAs for user-selected periods
  slots.forEach(function(s){if(s.indicator==="sma_cross"){var f=s.params.fast||9,sl=s.params.slow||22;if(!data["sma_"+f])data["sma_"+f]=computeSMA(closes,f);if(!data["sma_"+sl])data["sma_"+sl]=computeSMA(closes,sl)}if(s.indicator==="ema_cross"){var f=s.params.fast||9,sl=s.params.slow||21;if(!data["ema_"+f])data["ema_"+f]=computeEMA(closes,f);if(!data["ema_"+sl])data["ema_"+sl]=computeEMA(closes,sl)}});
  data.sma_9=data.sma_9||computeSMA(closes,9);data.sma_22=data.sma_22||computeSMA(closes,22);data.sma_200=data.sma_200||computeSMA(closes,200);
  var active=slots.filter(function(s){return s.indicator&&s.weight>0}),threshold=pf(document.getElementById("entryThreshold").value)||20;
  var composite=new Array(n).fill(0);
  for(var i=0;i<n;i++){var wSum=0,tW=0;active.forEach(function(s){var ind=INDICATORS[s.indicator];if(!ind)return;wSum+=ind.score(data,i,s.params)*s.weight;tW+=s.weight});composite[i]=tW>0?wSum/tW:0}
  var slE=document.getElementById("x_sl").checked,slV=pf(document.getElementById("x_sl_val").value)/100;
  var tpE=document.getElementById("x_tp").checked,tpV=pf(document.getElementById("x_tp_val").value)/100;
  var trE=document.getElementById("x_trail").checked,trV=pf(document.getElementById("x_trail_val").value)/100;
  var mhE=document.getElementById("x_maxhold").checked,mhV=parseInt(document.getElementById("x_maxhold_val").value)||14;
  var trades=[],markers=[],inTrade=false,ep=0,ei=0,peak=0,warmup=30;
  for(var i=warmup;i<n;i++){
    if(!inTrade){
      if(composite[i]>threshold){inTrade=true;ep=closes[i];ei=i;peak=closes[i];markers.push({time:dates[i],position:"belowBar",color:"#22c55e",shape:"arrowUp",text:"ENTRY +"+Math.round(composite[i])})}
    }else{
      if(closes[i]>peak)peak=closes[i];var hd=i-ei,ret=(closes[i]-ep)/ep,ex=null;
      if(slE&&ret<=-slV)ex="SL";else if(tpE&&ret>=tpV)ex="Target";else if(trE&&peak>ep&&closes[i]<peak*(1-trV))ex="Trail";
      if(!ex&&mhE&&hd>=mhV)ex="MaxHold";if(!ex&&composite[i]<-threshold)ex="Flip";
      if(ex){var rp=r2(ret*100);trades.push({entry_date:dates[ei],exit_date:dates[i],entry_price:r2(ep),exit_price:r2(closes[i]),return_pct:rp,hold_days:hd,exit_reason:ex,win:rp>0});markers.push({time:dates[i],position:"aboveBar",color:rp>0?"#22c55e":"#ef4444",shape:"arrowDown",text:(rp>0?"+":"")+rp.toFixed(1)+"%"});inTrade=false}
    }
  }
  // KPIs
  var tt=trades.length,wins=trades.filter(function(t){return t.win}),losses=trades.filter(function(t){return!t.win});
  var wr=tt>0?r2(wins.length/tt*100):0;
  var avgW=wins.length>0?r2(wins.reduce(function(s,t){return s+t.return_pct},0)/wins.length):0;
  var avgL=losses.length>0?r2(losses.reduce(function(s,t){return s+Math.abs(t.return_pct)},0)/losses.length):0;
  var totRet=r2(trades.reduce(function(s,t){return s+t.return_pct},0));
  var gW=wins.reduce(function(s,t){return s+t.return_pct},0),gL=losses.reduce(function(s,t){return s+Math.abs(t.return_pct)},0);
  var profitF=gL>0?r2(gW/gL):(gW>0?999:0);
  var avgH=tt>0?r2(trades.reduce(function(s,t){return s+t.hold_days},0)/tt):0;
  var eq=100,pk=100,mDD=0;trades.forEach(function(t){eq*=(1+t.return_pct/100);if(eq>pk)pk=eq;var dd=(pk-eq)/pk*100;if(dd>mDD)mDD=dd});mDD=r2(mDD);
  var slX=trades.filter(function(t){return t.exit_reason==="SL"}).length;
  displayKPIs(TICKER_DATA.ticker,{trades:tt,winRate:wr,avgWin:avgW,avgLoss:avgL,totalReturn:totRet,profitFactor:profitF,avgHold:avgH,maxDD:mDD,slExits:slX,period:period});
  displayChart(ohlcv,markers);displayEquity(trades);displayProfile(TICKER_DATA.ticker);displayTrades(trades);
  document.getElementById("placeholder").style.display="none";document.getElementById("premiumCard").style.display="block";
  updateStatus("ok",TICKER_DATA.ticker+": "+tt+" triggers | PF "+profitF+" | Alignment "+wr+"% | Hypothetical "+(totRet>0?"+":"")+totRet+"%");
}

// ── Display functions ──
function displayKPIs(tk,k){document.getElementById("kpiCard").style.display="block";document.getElementById("resultTicker").textContent=tk+" ("+k.period.toUpperCase()+")";var pfC=k.profitFactor>=1.2?"var(--bull)":k.profitFactor<0.9?"var(--bear)":"var(--white)";var retC=k.totalReturn>0?"var(--bull)":"var(--bear)";document.getElementById("kpiGrid").innerHTML=mkK(k.trades,"Hist. Triggers")+mkK(k.winRate+"%","Favorable Rate",k.winRate>=50?"var(--bull)":"var(--bear)")+mkK(k.profitFactor,"Profit Factor",pfC)+mkK((k.totalReturn>0?"+":"")+k.totalReturn+"%","Hypothetical Return",retC)+mkK("+"+k.avgWin+"%","Avg Favorable","var(--bull)")+mkK("-"+k.avgLoss+"%","Avg Unfavorable","var(--bear)")+mkK(k.avgHold+"d","Avg Hold")+mkK(k.maxDD+"%","Max Drawdown","var(--bear)")+mkK(k.slExits,"SL Exits","var(--neut)")}
function mkK(v,l,c){return'<div class="kpi"><div class="kpi-v" style="color:'+(c||"var(--white)")+'">'+v+'</div><div class="kpi-l">'+l+"</div></div>"}
function displayProfile(tk){
  var s=SCORES_DATA[tk];if(!s){document.getElementById("profileCard").style.display="none";return}
  document.getElementById("profileCard").style.display="block";
  var sp=document.getElementById("stockProfile");
  sp.innerHTML=mkSP("ROCE",fmtPct(s.ROCE))+mkSP("ROE",fmtPct(s.ROE))+mkSP("D/E",fmtNum(s.Debt_to_Equity))+mkSP("OPM",fmtPct(s.OPM))+mkSP("PE",fmtNum(s.PE))+mkSP("3Y Growth",fmtPct(s.Profit_Growth_3Y))+mkSP("MCap (Cr)",fmtNum(s.Market_Cap))+mkSP("Quality",fmtNum(s.Quality_Score)+"/100");
}
function mkSP(l,v){return'<div class="sp-item"><div class="sp-v">'+v+'</div><div class="sp-l">'+l+"</div></div>"}
function fmtPct(v){v=parseFloat(v);return isNaN(v)?"—":v.toFixed(1)+"%"}
function fmtNum(v){v=parseFloat(v);return isNaN(v)?"—":v>=1000?Math.round(v).toLocaleString("en-IN"):v.toFixed(1)}
function displayChart(ohlcv,markers){
  document.getElementById("chartWrap").style.display="block";var c=document.getElementById("btChart");c.innerHTML="";
  if(mainChart)try{mainChart.remove()}catch(e){}
  mainChart=LightweightCharts.createChart(c,{width:c.clientWidth,height:380,layout:{background:{type:"solid",color:"#12141d"},textColor:"#7a8299",fontSize:10},grid:{vertLines:{color:"#1a1d29"},horzLines:{color:"#1a1d29"}},crosshair:{mode:LightweightCharts.CrosshairMode.Normal},rightPriceScale:{borderColor:"#252a3a"},timeScale:{borderColor:"#252a3a"}});
  var cs=mainChart.addCandlestickSeries({upColor:"#22c55e",downColor:"#ef4444",borderUpColor:"#22c55e",borderDownColor:"#ef4444",wickUpColor:"#22c55e88",wickDownColor:"#ef444488"});
  cs.setData(ohlcv.map(function(r){return{time:r.d,open:r.o,high:r.h,low:r.l,close:r.c}}));
  if(markers.length){markers.sort(function(a,b){return a.time.localeCompare(b.time)});cs.setMarkers(markers)}
  mainChart.timeScale().fitContent();new ResizeObserver(function(){if(mainChart)mainChart.applyOptions({width:c.clientWidth})}).observe(c);
}
function displayEquity(trades){
  if(!trades.length){document.getElementById("equityWrap").style.display="none";return}
  document.getElementById("equityWrap").style.display="block";var c=document.getElementById("eqChart");c.innerHTML="";
  if(eqChart)try{eqChart.remove()}catch(e){}
  eqChart=LightweightCharts.createChart(c,{width:c.clientWidth,height:180,layout:{background:{type:"solid",color:"#12141d"},textColor:"#7a8299",fontSize:10},grid:{vertLines:{color:"#1a1d29"},horzLines:{color:"#1a1d29"}},rightPriceScale:{borderColor:"#252a3a"},timeScale:{borderColor:"#252a3a"}});
  var eq=100,eqD=[{time:trades[0].entry_date,value:100}];trades.forEach(function(t){eq*=(1+t.return_pct/100);eqD.push({time:t.exit_date,value:r2(eq)})});
  var clr=eq>=100?"#22c55e":"#ef4444";eqChart.addAreaSeries({lineColor:clr,topColor:clr+"40",bottomColor:clr+"05",lineWidth:2,priceLineVisible:false,lastValueVisible:true}).setData(eqD);
  eqChart.addLineSeries({color:"#7a829944",lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false}).setData([{time:eqD[0].time,value:100},{time:eqD[eqD.length-1].time,value:100}]);
  eqChart.timeScale().fitContent();new ResizeObserver(function(){if(eqChart)eqChart.applyOptions({width:c.clientWidth})}).observe(c);
}
function displayTrades(trades){
  document.getElementById("tradeCard").style.display="block";document.getElementById("tradeCount").textContent="("+trades.length+" triggers)";
  var tb=document.getElementById("tradeBody");tb.innerHTML="";
  trades.forEach(function(t,i){var rc=t.return_pct>0?"win":"loss",icon=t.win?"✅":"❌";var tr=document.createElement("tr");tr.innerHTML='<td style="color:var(--text2)">'+(i+1)+"</td><td>"+t.entry_date+"</td><td>₹"+t.entry_price+"</td><td>"+t.exit_date+"</td><td>₹"+t.exit_price+"</td><td>"+t.hold_days+"d</td><td class=\""+rc+'" style="font-weight:700">'+icon+" "+(t.return_pct>0?"+":"")+t.return_pct.toFixed(1)+"%</td><td style=\"color:var(--text2)\">"+t.exit_reason+"</td>";tb.appendChild(tr)});
}

// ── Events ──
document.getElementById("tickerSearch").addEventListener("change",function(){var v=this.value.toUpperCase().trim();if(v&&TICKERS.some(function(t){return t.ticker===v}))loadTickerData(v)});
document.getElementById("tickerSearch").addEventListener("input",function(){var v=this.value.toUpperCase().trim();if(v&&TICKERS.some(function(t){return t.ticker===v}))loadTickerData(v)});
document.getElementById("btnRun").addEventListener("click",function(){var btn=this;btn.disabled=true;var orig=btn.textContent;btn.textContent="⏳ Running...";setTimeout(function(){try{runBacktest()}catch(e){updateStatus("err","Error: "+e.message);console.error(e)}btn.disabled=false;btn.textContent=orig;btn.className="btn-run ready"},50)});
document.addEventListener("keydown",function(e){if(e.key==="Enter"&&!document.getElementById("btnRun").disabled)document.getElementById("btnRun").click()});

// ── Init ──
addIndicatorSlot();loadTickerList();
})();"""


if __name__ == "__main__":
    main()
