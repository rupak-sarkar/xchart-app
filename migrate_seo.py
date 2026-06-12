"""migrate_seo.py — Accessibility + SEO fixes for index.html, dashboard.html, backtest.js"""

import re
import subprocess
from pathlib import Path


def main():
    print("=" * 70)
    print("  A11Y + SEO MIGRATION")
    print("=" * 70)

    print("\n[1/3] Patching index.html...")
    patch_index()

    print("\n[2/3] Patching dashboard.html...")
    patch_dashboard()

    print("\n[3/3] Patching backtest.js...")
    patch_js()

    print("\nStaging changes...")
    subprocess.run(["git", "add", "-A"], capture_output=True)

    print("\n" + "=" * 70)
    print("  MIGRATION COMPLETE")
    print("=" * 70)


def snippet(content, marker, length=80):
    idx = content.find(marker)
    if idx < 0:
        return ""
    return content[idx:idx + length]


def safe_replace(content, old, new, label=""):
    if old in content:
        content = content.replace(old, new)
        if label:
            print("  " + label)
        return content, 1
    return content, 0


# ══════════════════════════════════════════════════════════════
# INDEX.HTML
# ══════════════════════════════════════════════════════════════

def patch_index():
    fp = Path("index.html")
    if not fp.exists():
        print("  ERROR: index.html not found!")
        return

    c = fp.read_text(encoding="utf-8")
    orig = c
    n = 0

    # html lang
    if '<html lang=' not in c:
        c = c.replace('<html>', '<html lang="en">')
        n += 1
        print("  Added lang=en")

    # sr-only CSS
    if '.sr-only' not in c and '</style>' in c:
        sr = ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}\n"
        c = c.replace('</style>', sr + '</style>')
        n += 1
        print("  Added .sr-only CSS")

    # Footer contrast
    c, d = safe_replace(c,
        'padding:16px 24px;font-size:10px;color:var(--text3);text-align:center',
        'padding:16px 24px;font-size:10px;color:var(--text2);text-align:center',
        "Fixed footer contrast")
    n += d

    # Mode desc contrast
    c, d = safe_replace(c,
        '.mode-desc{font-size:10px;color:var(--text3);',
        '.mode-desc{font-size:10px;color:var(--text2);',
        "Fixed mode-desc contrast")
    n += d

    # Ticker search aria
    if 'id="tickerSearch"' in c and 'aria-label' not in snippet(c, 'id="tickerSearch"'):
        c = c.replace('id="tickerSearch"', 'id="tickerSearch" aria-label="Search stock ticker"')
        n += 1
        print("  Added aria to ticker search")

    # Entry threshold
    if 'id="entryThreshold"' in c and 'aria-label' not in snippet(c, 'id="entryThreshold"'):
        c = c.replace('id="entryThreshold"', 'id="entryThreshold" aria-label="Entry threshold"')
        n += 1
        print("  Added aria to entry threshold")

    # Majority N
    if 'id="majorityN"' in c and 'aria-label' not in snippet(c, 'id="majorityN"'):
        c = c.replace('id="majorityN"', 'id="majorityN" aria-label="Majority required count"')
        n += 1
        print("  Added aria to majorityN")

    # Exit rule inputs
    exit_map = [
        ('id="x_sl_val"', 'Stop loss percentage'),
        ('id="x_tp_val"', 'Target profit percentage'),
        ('id="x_trail_val"', 'Trailing stop loss percentage'),
        ('id="x_maxhold_val"', 'Maximum hold days'),
        ('id="x_sl"', 'Enable stop loss'),
        ('id="x_tp"', 'Enable target profit'),
        ('id="x_trail"', 'Enable trailing stop loss'),
        ('id="x_maxhold"', 'Enable maximum hold'),
    ]
    for eid, label in exit_map:
        if eid in c and 'aria-label' not in snippet(c, eid):
            c = c.replace(eid, eid + ' aria-label="' + label + '"')
            n += 1
            print("  Added aria: " + label)

    # Period select
    if 'id="period"' in c and 'aria-label' not in snippet(c, 'id="period"'):
        c = c.replace('id="period"', 'id="period" aria-label="Backtest period"')
        n += 1
        print("  Added aria to period")

    # Chart containers
    if 'id="btChart"' in c and 'role="img"' not in snippet(c, 'id="btChart"'):
        c = c.replace('id="btChart"', 'id="btChart" role="img" aria-label="Price chart with trade markers"')
        n += 1
        print("  Added role=img to price chart")

    if 'id="eqChart"' in c and 'role="img"' not in snippet(c, 'id="eqChart"'):
        c = c.replace('id="eqChart"', 'id="eqChart" role="img" aria-label="Hypothetical equity curve"')
        n += 1
        print("  Added role=img to equity chart")

    # Buttons
    if 'id="btnRun"' in c and 'aria-label' not in snippet(c, 'id="btnRun"'):
        c = c.replace('id="btnRun"', 'id="btnRun" aria-label="Run backtest"')
        n += 1
        print("  Added aria to run button")

    if 'id="btnAddInd"' in c and 'aria-label' not in snippet(c, 'id="btnAddInd"'):
        c = c.replace('id="btnAddInd"', 'id="btnAddInd" aria-label="Add indicator"')
        n += 1
        print("  Added aria to add button")

    # Mode group
    c, d = safe_replace(c,
        '<div class="mode-group">',
        '<div class="mode-group" role="radiogroup" aria-label="Signal mode selection">',
        "Added radiogroup to mode buttons")
    n += d

    # Inline text3 contrast
    count = c.count('font-size:10px;color:var(--text3)')
    if count > 0:
        c = c.replace('font-size:10px;color:var(--text3)', 'font-size:10px;color:var(--text2)')
        n += count
        print("  Fixed " + str(count) + " inline contrast issues")

    # CSS label contrast fixes
    css_pairs = [
        ('.ind-param label{color:var(--text2);', '.ind-param label{color:var(--text);', "param labels"),
        ('.cond-row label{color:var(--text2);font-weight:600;', '.cond-row label{color:var(--text);font-weight:600;', "condition labels"),
        ('.weight-wrap label{font-size:10px;color:var(--text2);', '.weight-wrap label{font-size:10px;color:var(--text);', "weight label"),
        ('.kpi-l{font-size:9px;color:var(--text2);', '.kpi-l{font-size:9px;color:var(--text);', "KPI labels"),
        ('.preset-btn{padding:6px 12px;border:1.5px solid var(--border);border-radius:20px;background:var(--white);color:var(--text2);',
         '.preset-btn{padding:6px 12px;border:1.5px solid var(--border);border-radius:20px;background:var(--white);color:var(--text);', "preset buttons"),
        ('.step-text{font-size:11px;color:var(--text2);', '.step-text{font-size:11px;color:var(--text);', "step text"),
    ]
    for old, new, label in css_pairs:
        c, d = safe_replace(c, old, new, "Fixed contrast: " + label)
        n += d

    if c != orig:
        fp.write_text(c, encoding="utf-8")
        print("\n  index.html patched (" + str(n) + " fixes)")
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

    c = fp.read_text(encoding="utf-8")
    orig = c
    n = 0

    # ── SEO fixes ──

    # html lang
    if '<html lang=' not in c:
        c = c.replace('<html>', '<html lang="en">')
        n += 1
        print("  [SEO] Added lang=en")

    # viewport
    if 'name="viewport"' not in c:
        c = c.replace('<head>', '<head>\n<meta name="viewport" content="width=device-width,initial-scale=1.0">')
        n += 1
        print("  [SEO] Added viewport")

    # charset
    if 'charset' not in c.lower():
        c = c.replace('<head>', '<head>\n<meta charset="UTF-8">')
        n += 1
        print("  [SEO] Added charset")

    # meta description
    if 'name="description"' not in c:
        desc_tag = '<meta name="description" content="Advanced multi-layer stock analytics for Indian equities. Technical indicators, fundamental screening, and market regime analysis. Educational analytical tool. Not SEBI registered. Not investment advice.">'
        title_end = c.find('</title>')
        if title_end > 0:
            pos = title_end + len('</title>')
            c = c[:pos] + '\n' + desc_tag + c[pos:]
            n += 1
            print("  [SEO] Added meta description")

    # canonical
    if 'rel="canonical"' not in c:
        canonical_tag = '<link rel="canonical" href="https://xchart.in/dashboard.html" />'
        c = c.replace('</head>', canonical_tag + '\n</head>')
        n += 1
        print("  [SEO] Added canonical")

    # ── A11Y fixes ──

    # sr-only CSS
    if '.sr-only' not in c and '</style>' in c:
        sr = ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}\n"
        c = c.replace('</style>', sr + '</style>')
        n += 1
        print("  [A11Y] Added .sr-only CSS")

    # Hamburger
    if 'id="hamBtn"' in c and 'aria-label' not in snippet(c, 'id="hamBtn"'):
        c = c.replace('id="hamBtn"', 'id="hamBtn" aria-label="Open navigation menu" aria-expanded="false"')
        n += 1
        print("  [A11Y] Fixed hamburger")

    # Search input
    if 'id="sInput"' in c and 'aria-label' not in snippet(c, 'id="sInput"'):
        c = c.replace('id="sInput"', 'id="sInput" aria-label="Search ticker"')
        n += 1
        print("  [A11Y] Added aria to search")

    # Sort select
    if 'id="sortBy"' in c and 'aria-label' not in snippet(c, 'id="sortBy"'):
        c = c.replace('id="sortBy"', 'id="sortBy" aria-label="Sort stocks by"')
        n += 1
        print("  [A11Y] Added aria to sort")

    # Filter bar role
    c, d = safe_replace(c,
        '<div class="sb-filters" id="filterBar">',
        '<div class="sb-filters" id="filterBar" role="toolbar" aria-label="Stock filters">',
        "[A11Y] Added toolbar role to filters")
    n += d

    # Filter buttons aria-labels
    filter_labels = [
        ('data-f="all"', 'Show all stocks'),
        ('data-f="bull"', 'Show positive momentum'),
        ('data-f="bear"', 'Show negative momentum'),
        ('data-f="neut"', 'Show neutral stocks'),
        ('data-f="hold"', 'Show hold stocks'),
        ('data-f="mega"', 'Show mega cap'),
        ('data-f="large"', 'Show large cap'),
        ('data-f="mid"', 'Show mid cap'),
        ('data-f="small"', 'Show small cap'),
        ('data-f="bbh"', 'Show BB high'),
        ('data-f="bbl"', 'Show BB low'),
        ('data-f="news"', 'Show news stocks'),
    ]
    for attr, label in filter_labels:
        if attr in c and 'aria-label' not in snippet(c, attr):
            c = c.replace(attr, attr + ' aria-label="' + label + '"')
            n += 1
            print("  [A11Y] Filter aria: " + label)

    # Modal
    c, d = safe_replace(c,
        '<div class="mo" id="chartModal">',
        '<div class="mo" id="chartModal" role="dialog" aria-modal="true" aria-label="Stock chart and indicators">',
        "[A11Y] Added dialog role to modal")
    n += d

    # Modal close
    if 'id="mClose"' in c and 'aria-label' not in snippet(c, 'id="mClose"'):
        c = c.replace('id="mClose"', 'id="mClose" aria-label="Close chart modal"')
        n += 1
        print("  [A11Y] Added aria to modal close")

    # Chart containers
    chart_map = [
        ('id="mChart"', 'Stock price chart'),
        ('id="mRsi"', 'RSI indicator chart'),
        ('id="mMacd"', 'MACD indicator chart'),
        ('id="mAdx"', 'ADX indicator chart'),
    ]
    for cid, label in chart_map:
        if cid in c and 'role=' not in snippet(c, cid):
            c = c.replace(cid, cid + ' role="img" aria-label="' + label + '"')
            n += 1
            print("  [A11Y] Chart role: " + label)

    # Indicator toggle buttons
    ind_map = [
        ('data-i="momentum"', 'Toggle momentum readings'),
        ('data-i="volume"', 'Toggle volume'),
        ('data-i="sma9"', 'Toggle SMA 9'),
        ('data-i="sma22"', 'Toggle SMA 22'),
        ('data-i="sma200"', 'Toggle SMA 200'),
        ('data-i="ema9"', 'Toggle EMA 9'),
        ('data-i="ema21"', 'Toggle EMA 21'),
        ('data-i="bb"', 'Toggle Bollinger Bands'),
        ('data-i="supertrend"', 'Toggle SuperTrend'),
        ('data-i="ichimoku"', 'Toggle Ichimoku Cloud'),
        ('data-i="vwap"', 'Toggle VWAP'),
        ('data-i="rsi"', 'Toggle RSI panel'),
        ('data-i="macd"', 'Toggle MACD panel'),
        ('data-i="adx"', 'Toggle ADX panel'),
    ]
    for attr, label in ind_map:
        if attr in c and 'aria-label' not in snippet(c, attr):
            c = c.replace(attr, attr + ' aria-label="' + label + '"')
            n += 1
            print("  [A11Y] Indicator: " + label)

    # Indicator bar role
    c, d = safe_replace(c,
        '<div class="ind-bar" id="indBar">',
        '<div class="ind-bar" id="indBar" role="toolbar" aria-label="Chart indicator toggles">',
        "[A11Y] Added toolbar to indicator bar")
    n += d

    # Sidebar landmark
    c, d = safe_replace(c,
        '<div class="sb" id="sidebar">',
        '<nav class="sb" id="sidebar" aria-label="Stock list navigation">',
        "[A11Y] Sidebar to nav landmark")
    n += d

    # Main content landmark
    c, d = safe_replace(c,
        '<div class="main" id="mainContent">',
        '<main class="main" id="mainContent">',
        "[A11Y] Main content landmark")
    n += d

    # Stock list role
    c, d = safe_replace(c,
        '<div class="sb-list" id="sList">',
        '<div class="sb-list" id="sList" role="listbox" aria-label="Stock list">',
        "[A11Y] Added listbox role to stock list")
    n += d

    # Overlay
    c, d = safe_replace(c,
        '<div class="sb-overlay" id="sbOverlay">',
        '<div class="sb-overlay" id="sbOverlay" aria-hidden="true">',
        "[A11Y] Added aria-hidden to overlay")
    n += d

    # Header date
    if 'id="hDate"' in c and 'aria-label' not in snippet(c, 'id="hDate"'):
        c = c.replace('id="hDate"', 'id="hDate" aria-label="Last updated date"')
        n += 1
        print("  [A11Y] Added aria to date")

    # Skip to content link
    if 'skip-to' not in c and '<body>' in c:
        skip = '<a href="#mainContent" class="sr-only" style="position:absolute;top:-40px;left:0;background:#2563EB;color:#fff;padding:8px 16px;z-index:999" onfocus="this.style.top=\'0\'" onblur="this.style.top=\'-40px\'">Skip to main content</a>'
        c = c.replace('<body>', '<body>\n' + skip)
        n += 1
        print("  [A11Y] Added skip-to-content link")

    # Images without alt
    img_pattern = re.compile(r'<img(?![^>]*alt=)[^>]*>')
    for img_tag in img_pattern.findall(c):
        fixed = img_tag.replace('<img', '<img alt=""')
        c = c.replace(img_tag, fixed)
        n += 1
        print("  [A11Y] Added alt to image")

    if c != orig:
        fp.write_text(c, encoding="utf-8")
        print("\n  dashboard.html patched (" + str(n) + " fixes)")
    else:
        print("  No changes needed")


# ══════════════════════════════════════════════════════════════
# BACKTEST.JS
# ══════════════════════════════════════════════════════════════

def patch_js():
    fp = Path("backtest.js")
    if not fp.exists():
        print("  ERROR: backtest.js not found!")
        return

    c = fp.read_text(encoding="utf-8")
    orig = c
    n = 0

    # Remove button
    old = "'<button class=\"ind-remove\" onclick=\"removeIndicatorSlot(' + idx + ')\" title=\"Remove\">\\u2715</button>'"
    new = "'<button class=\"ind-remove\" onclick=\"removeIndicatorSlot(' + idx + ')\" title=\"Remove indicator\" aria-label=\"Remove indicator ' + (idx + 1) + '\">\\u2715</button>'"
    # Try multiple quote patterns
    patterns = [
        ("'title=\"Remove\">✕</button>'",
         "'title=\"Remove indicator\" aria-label=\"Remove indicator ' + (idx + 1) + '\">✕</button>'"),
        ('title="Remove">✕</button>',
         'title="Remove indicator" aria-label="Remove indicator \' + (idx + 1) + \'">✕</button>'),
    ]
    for old_p, new_p in patterns:
        if old_p in c:
            c = c.replace(old_p, new_p)
            n += 1
            print("  Added aria to remove buttons")
            break

    # Indicator select
    old_sel = "'<select class=\"ind-select\" onchange=\"onIndChange(' + idx + ',this.value)\">'"
    new_sel = "'<select class=\"ind-select\" onchange=\"onIndChange(' + idx + ',this.value)\" aria-label=\"Select indicator ' + (idx + 1) + '\">'"
    if old_sel in c:
        c = c.replace(old_sel, new_sel)
        n += 1
        print("  Added aria to indicator selects")

    # Weight slider
    old_w = "'<input type=\"range\" class=\"weight-slider\" min=\"0\" max=\"100\" value=\"' + slot.weight + '\" '"
    new_w = "'<input type=\"range\" class=\"weight-slider\" min=\"0\" max=\"100\" value=\"' + slot.weight + '\" aria-label=\"Weight for ' + (INDICATORS[slot.indId] ? INDICATORS[slot.indId].name : 'indicator') + '\" '"
    if old_w in c:
        c = c.replace(old_w, new_w)
        n += 1
        print("  Added aria to weight sliders")

    # Entry select
    old_e = "onCondChange(' + idx + ',\\'entry\\',this.value)\">'"
    new_e = "onCondChange(' + idx + ',\\'entry\\',this.value)\" aria-label=\"Entry condition\">'"
    if old_e in c and 'aria-label=\"Entry condition\"' not in c:
        c = c.replace(old_e, new_e)
        n += 1
        print("  Added aria to entry selects")

    # Exit select
    old_x = "onCondChange(' + idx + ',\\'exit\\',this.value)\">'"
    new_x = "onCondChange(' + idx + ',\\'exit\\',this.value)\" aria-label=\"Exit condition\">'"
    if old_x in c and 'aria-label=\"Exit condition\"' not in c:
        c = c.replace(old_x, new_x)
        n += 1
        print("  Added aria to exit selects")

    # Param inputs
    old_pi = "onParamChange(' + idx + ',\\'' + p.id + '\\',this.value)\"></div>'"
    new_pi = "onParamChange(' + idx + ',\\'' + p.id + '\\',this.value)\" aria-label=\"' + p.label + '\"></div>'"
    if old_pi in c:
        c = c.replace(old_pi, new_pi)
        n += 1
        print("  Added aria to param inputs")

    # Mode button aria-pressed
    old_m = "b.classList.toggle('active', b.dataset.mode === mode);"
    new_m = "b.classList.toggle('active', b.dataset.mode === mode);\n      b.setAttribute('aria-pressed', b.dataset.mode === mode);"
    if old_m in c and 'aria-pressed' not in c:
        c = c.replace(old_m, new_m)
        n += 1
        print("  Added aria-pressed to mode buttons")

    if c != orig:
        fp.write_text(c, encoding="utf-8")
        print("\n  backtest.js patched (" + str(n) + " fixes)")
    else:
        print("  No changes needed")


if __name__ == "__main__":
    main()
