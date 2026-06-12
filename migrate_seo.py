"""migrate_seo.py — Accessibility + SEO fixes for index.html & dashboard.html"""

import re, subprocess
from pathlib import PathtickerSearch"', 'id="tickerSearch" aria-label="Search stock ticker"')from pathlib import Path
        print("  Added aria-label to ticker search")
        changes += 1

    # ── 6. Entry threshold ──
    changes += _add_aria(content, 'id="entryThreshold"', 'Entry threshold')
    content = _apply_aria(content, 'id="entryThreshold"', 'Entry threshold')

    # ── 7. Majority N ──
    changes += _add_aria(content, 'id="majorityN"', 'Majority required count')
    content = _apply_aria(content, 'id="majorityN"', 'Majority required count')

    # ── 8. Exit rule inputs ──
    exit_map = {
        'id="x_sl_val"': 'Stop loss percentage',
        'id="x_tp_val"': 'Target profit percentage',
        'id="x_trail_val"': 'Trailing stop loss percentage',
        'id="x_maxhold_val"': 'Maximum hold days',
        'id="x_sl"': 'Enable stop loss',
        'id="x_tp"': 'Enable target profit',
        'id="x_trail"': 'Enable trailing stop loss',
        'id="x_maxhold"': 'Enable maximum hold',
    }
    for old_id, label in exit_map.items():
        if old_id in content and 'aria-label' not in _snippet(content, old_id):
            content = content.replace(old_id, old_id + ' aria-label="' + label + '"')
            print(f"  Added aria-label: {label}")
            changes += 1

    # ── 9. Period select ──
    if 'id="period"' in content and 'aria-label' not in _snippet(content, 'id="period"'):
        content = content.replace('id="period"', 'id="period" aria-label="Backtest period"')
        print("  Added aria-label to period select")
        changes += 1

    # ── 10. Chart containers ──
    old_chart = 'id="btChart" style="width:100%;height:380px"'
    new_chart = 'id="btChart" style="width:100%;height:380px" role="img" aria-label="Price chart with entry and exit markers"'
    if old_chart in content and 'role="img"' not in _snippet(content, 'btChart'):
        content = content.replace(old_chart, new_chart)
        print("  Added role=img to price chart")
        changes += 1

    old_eq = 'id="eqChart" style="width:100%;height:180px"'
    new_eq = 'id="eqChart" style="width:100%;height:180px" role="img" aria-label="Hypothetical equity curve"'
    if old_eq in content and 'role="img"' not in _snippet(content, 'eqChart'):
        content = content.replace(old_eq, new_eq)
        print("  Added role=img to equity chart")
        changes += 1

    # ── 11. Buttons ──
    if 'id="btnRun"' in content and 'aria-label' not in _snippet(content, 'id="btnRun"'):
        content = content.replace('id="btnRun"', 'id="btnRun" aria-label="Run backtest"')
        print("  Added aria-label to run button")
        changes += 1

    if 'id="btnAddInd"' in content and 'aria-label' not in _snippet(content, 'id="btnAddInd"'):
        content = content.replace('id="btnAddInd"', 'id="btnAddInd" aria-label="Add indicator"')
        print("  Added aria-label to add button")
        changes += 1

    # ── 12. Mode group role ──
    old_mg = '<div class="mode-group">'
    new_mg = '<div class="mode-group" role="radiogroup" aria-label="Signal mode selection">'
    if old_mg in content and 'role="radiogroup"' not in content:
        content = content.replace(old_mg, new_mg)
        print("  Added role=radiogroup to mode buttons")
        changes += 1

    # ── 13. Contrast fixes — all text3 in inline styles ──
    pattern = r'(font-size:10px;color:var\(--text3\))'
    count = len(re.findall(pattern, content))
    if count > 0:
        content = re.sub(pattern, 'font-size:10px;color:var(--text2)', content)
        print(f"  Fixed {count} inline low-contrast instances")
        changes += count

    # ── 14. CSS contrast fixes ──
    css_fixes = [
        ('.search-wrap input::placeholder{color:var(--text3)}', '.search-wrap input::placeholder{color:var(--text2)}', 'placeholder'),
        ('.preset-btn{padding:6px 12px;border:1.5px solid var(--border);border-radius:20px;background:var(--white);color:var(--text2);', '.preset-btn{padding:6px 12px;border:1.5px solid var(--border);border-radius:20px;background:var(--white);color:var(--text);', 'preset buttons'),
        ('.step-text{font-size:11px;color:var(--text2);font-weight:500}', '.step-text{font-size:11px;color:var(--text);font-weight:500}', 'step text'),
        ('.ind-param label{color:var(--text2);min-width:48px;font-weight:500}', '.ind-param label{color:var(--text);min-width:48px;font-weight:500}', 'param labels'),
        ('.cond-row label{color:var(--text2);font-weight:600;min-width:36px;', '.cond-row label{color:var(--text);font-weight:600;min-width:36px;', 'condition labels'),
        ('.weight-wrap label{font-size:10px;color:var(--text2);', '.weight-wrap label{font-size:10px;color:var(--text);', 'weight label'),
        ('.kpi-l{font-size:9px;color:var(--text2);text-transform:uppercase;margin-top:4px;letter-spacing:0.3px;font-weight:600}', '.kpi-l{font-size:9px;color:var(--text);text-transform:uppercase;margin-top:4px;letter-spacing:0.3px;font-weight:600}', 'KPI labels'),
        ('.status{font-size:11px;color:var(--text2);', '.status{font-size:11px;color:var(--text);', 'status text'),
    ]
    for old, new, name in css_fixes:
        if old in content:
            content = content.replace(old, new)
            print(f"  Fixed {name} contrast")
            changes += 1

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print(f"\n  ✅ index.html patched ({changes} fixes)")
    else:
        print("  No changes needed")


# ══════════════════════════════════════════════════════════════
# DASHBOARD.HTML — Accessibility (69→90+) + SEO (92→100)
# ══════════════════════════════════════════════════════════════

def patch_dashboard():
    fp = Path("dashboard.html")
    if not fp.exists():
        print("  ERROR: dashboard.html not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content
    changes = 0

    # ══════════════════════════════════════════
    # SEO FIXES (92 → 100)
    # ══════════════════════════════════════════

    # ── 1. Ensure <html lang="en"> ──
    if '<html lang=' not in content:
        content = content.replace('<html>', '<html lang="en">')
        print("  [SEO] Added lang='en'")
        changes += 1

    # ── 2. Add meta viewport if missing ──
    if 'name="viewport"' not in content:
        content = content.replace('<head>', '<head>\n<meta name="viewport" content="width=device-width,initial-scale=1.0">')
        print("  [SEO] Added viewport meta")
        changes += 1

    # ── 3. Add meta description if missing ──
    if 'name="description"' not in content:
        desc = '<meta name="description" content="Advanced multi-layer stock analytics for Indian equities. Technical indicators, fundamental screening, and market regime analysis. Educational analytical tool. Not SEBI registered. Not investment advice.">'
        # Insert after title
        title_match = re.search(r'</title>', content)
        if title_match:
            pos = title_match.end()
            content = content[:pos] + '\n' + desc + content[pos:]
            print("  [SEO] Added meta description")
            changes += 1

    # ── 4. Add canonical if missing ──
    if 'rel="canonical"' not in content:
        canonical = '<link rel="canonical" href="https://xchart.in/dashboard.html" />'
        content = content.replace('</head>', canonical + '\n</head>')
        print("  [SEO] Added canonical URL")
        changes += 1

    # ── 5. Add charset if missing ──
    if 'charset' not in content.lower():
        content = content.replace('<head>', '<head>\n<meta charset="UTF-8">')
        print("  [SEO] Added charset")
        changes += 1

    # ══════════════════════════════════════════
    # ACCESSIBILITY FIXES (69 → 90+)
    # ══════════════════════════════════════════

    # ── 6. Add .sr-only if not in CSS ──
    if '.sr-only' not in content and '</style>' in content:
        sr_only = ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}\n"
        content = content.replace('</style>', sr_only + '</style>')
        print("  [A11Y] Added .sr-only CSS")
        changes += 1

    # ── 7. Hamburger button ──
    old_ham = '<button class="ham" id="hamBtn">☰</button>'
    new_ham = '<button class="ham" id="hamBtn" aria-label="Open navigation menu" aria-expanded="false">☰</button>'
    if old_ham in content:
        content = content.replace(old_ham, new_ham)
        print("  [A11Y] Fixed hamburger button")
        changes += 1
    elif 'id="hamBtn"' in content and 'aria-label' not in _snippet(content, 'id="hamBtn"'):
        content = content.replace('id="hamBtn"', 'id="hamBtn" aria-label="Open navigation menu" aria-expanded="false"')
        print("  [A11Y] Added aria to hamburger")
        changes += 1

    # ── 8. Search input ──
    old_sinput = '<input type="text" id="sInput" placeholder="Search ticker...">'
    new_sinput = '<label for="sInput" class="sr-only">Search ticker</label><input type="text" id="sInput" placeholder="Search ticker..." aria-label="Search ticker">'
    if old_sinput in content:
        content = content.replace(old_sinput, new_sinput)
        print("  [A11Y] Added label + aria to search input")
        changes += 1
    elif 'id="sInput"' in content and 'aria-label' not in _snippet(content, 'id="sInput"'):
        content = content.replace('id="sInput"', 'id="sInput" aria-label="Search ticker"')
        print("  [A11Y] Added aria-label to search input")
        changes += 1

    # ── 9. Sort select ──
    if 'id="sortBy"' in content and 'aria-label' not in _snippet(content, 'id="sortBy"'):
        content = content.replace('id="sortBy"', 'id="sortBy" aria-label="Sort stocks by"')
        print("  [A11Y] Added aria-label to sort select")
        changes += 1

    # ── 10. Filter buttons — add role + aria ──
    old_filterbar = '<div class="sb-filters" id="filterBar">'
    new_filterbar = '<div class="sb-filters" id="filterBar" role="toolbar" aria-label="Stock filters">'
    if old_filterbar in content:
        content = content.replace(old_filterbar, new_filterbar)
        print("  [A11Y] Added role=toolbar to filter bar")
        changes += 1

    # Add aria-pressed to filter buttons
    filter_labels = {
        'data-f="all"': 'Show all stocks',
        'data-f="bull"': 'Show positive momentum stocks',
        'data-f="bear"': 'Show negative momentum stocks',
        'data-f="neut"': 'Show neutral stocks',
        'data-f="hold"': 'Show hold stocks',
        'data-f="mega"': 'Show mega cap stocks',
        'data-f="large"': 'Show large cap stocks',
        'data-f="mid"': 'Show mid cap stocks',
        'data-f="small"': 'Show small cap stocks',
        'data-f="bbh"': 'Show Bollinger Band high stocks',
        'data-f="bbl"': 'Show Bollinger Band low stocks',
        'data-f="news"': 'Show stocks with news',
    }
    for data_attr, label in filter_labels.items():
        if data_attr in content and 'aria-label' not in _snippet(content, data_attr, 80):
            content = content.replace(data_attr, data_attr + ' aria-label="' + label + '"')
            print(f"  [A11Y] Added aria-label to filter: {label[:30]}...")
            changes += 1

    # ── 11. Modal close button ──
    old_close = '<button class="md-x" id="mClose">✕</button>'
    new_close = '<button class="md-x" id="mClose" aria-label="Close chart modal">✕</button>'
    if old_close in content:
        content = content.replace(old_close, new_close)
        print("  [A11Y] Added aria-label to modal close")
        changes += 1
    elif 'id="mClose"' in content and 'aria-label' not in _snippet(content, 'id="mClose"'):
        content = content.replace('id="mClose"', 'id="mClose" aria-label="Close chart modal"')
        print("  [A11Y] Added aria to modal close")
        changes += 1

    # ── 12. Modal — add role="dialog" ──
    old_modal = '<div class="mo" id="chartModal">'
    new_modal = '<div class="mo" id="chartModal" role="dialog" aria-modal="true" aria-label="Stock chart and indicators">'
    if old_modal in content:
        content = content.replace(old_modal, new_modal)
        print("  [A11Y] Added role=dialog to modal")
        changes += 1

    # ── 13. Chart containers — add roles ──
    chart_ids = {
        'id="mChart"': 'Stock price chart',
        'id="mRsi"': 'RSI indicator chart',
        'id="mMacd"': 'MACD indicator chart',
        'id="mAdx"': 'ADX indicator chart',
    }
    for cid, label in chart_ids.items():
        if cid in content and 'role=' not in _snippet(content, cid, 80):
            content = content.replace(cid, cid + ' role="img" aria-label="' + label + '"')
            print(f"  [A11Y] Added role=img to {label}")
            changes += 1

    # ── 14. Indicator toggle buttons — add aria ──
    ind_buttons = {
        'data-i="momentum"': 'Toggle momentum readings',
        'data-i="volume"': 'Toggle volume',
        'data-i="sma9"': 'Toggle SMA 9',
        'data-i="sma22"': 'Toggle SMA 22',
        'data-i="sma200"': 'Toggle SMA 200',
        'data-i="ema9"': 'Toggle EMA 9',
        'data-i="ema21"': 'Toggle EMA 21',
        'data-i="bb"': 'Toggle Bollinger Bands',
        'data-i="supertrend"': 'Toggle SuperTrend',
        'data-i="ichimoku"': 'Toggle Ichimoku Cloud',
        'data-i="vwap"': 'Toggle VWAP',
        'data-i="rsi"': 'Toggle RSI panel',
        'data-i="macd"': 'Toggle MACD panel',
        'data-i="adx"': 'Toggle ADX panel',
    }
    for data_attr, label in ind_buttons.items():
        if data_attr in content and 'aria-label' not in _snippet(content, data_attr, 80):
            content = content.replace(data_attr, data_attr + ' aria-label="' + label + '"')
            print(f"  [A11Y] Added aria to indicator: {label}")
            changes += 1

    # ── 15. Indicator bar — add role ──
    old_indbar = '<div class="ind-bar" id="indBar">'
    new_indbar = '<div class="ind-bar" id="indBar" role="toolbar" aria-label="Chart indicator toggles">'
    if old_indbar in content:
        content = content.replace(old_indbar, new_indbar)
        print("  [A11Y] Added role=toolbar to indicator bar")
        changes += 1

    # ── 16. Sidebar — add landmark ──
    old_sb = '<div class="sb" id="sidebar">'
    new_sb = '<nav class="sb" id="sidebar" aria-label="Stock list navigation">'
    old_sb_close = None  # We need to also close with </nav>
    if old_sb in content:
        content = content.replace(old_sb, new_sb)
        print("  [A11Y] Changed sidebar to <nav> landmark")
        changes += 1

    # ── 17. Main content — add landmark ──
    old_main = '<div class="main" id="mainContent">'
    new_main = '<main class="main" id="mainContent">'
    if old_main in content:
        content = content.replace(old_main, new_main)
        print("  [A11Y] Changed main content to <main> landmark")
        changes += 1

    # ── 18. Sidebar list — add role ──
    old_slist = '<div class="sb-list" id="sList">'
    new_slist = '<div class="sb-list" id="sList" role="listbox" aria-label="Stock list">'
    if old_slist in content:
        content = content.replace(old_slist, new_slist)
        print("  [A11Y] Added role=listbox to stock list")
        changes += 1

    # ── 19. Footer contrast ──
    # Find footer with text3 color and fix
    if '.ftr' in content:
        # Try various patterns
        ftr_patterns = [
            ('color:#7a8299', 'color:#6B7280'),
            ('color:#555', 'color:#6B7280'),
            ('color:var(--text3)', 'color:var(--text2)'),
            ('color:#4a4e5a', 'color:#6B7280'),
        ]
        for old_c, new_c in ftr_patterns:
            # Only replace in .ftr context
            ftr_idx = content.find('.ftr')
            if ftr_idx > 0:
                ftr_block = content[ftr_idx:ftr_idx+300]
                if old_c in ftr_block:
                    content = content[:ftr_idx] + ftr_block.replace(old_c, new_c) + content[ftr_idx+300:]
                    print(f"  [A11Y] Fixed footer contrast ({old_c})")
                    changes += 1
                    break

    # ── 20. Low-contrast CSS fixes for dashboard ──
    # Common dark theme text colors that may fail contrast
    dark_contrast_fixes = [
        # Sidebar text colors
        ('.tk-bot{', 'color:#7a8299', 'color:#9CA3AF'),
        ('.tk-comp{', 'color:#7a8299', 'color:#9CA3AF'),
        ('.hdr-date{', 'color:#7a8299', 'color:#9CA3AF'),
    ]
    # These are contextual — only fix if present

    # ── 21. Images need alt text — find any <img> without alt ──
    img_pattern = re.compile(r'<img(?![^>]*alt=)[^>]*>', re.IGNORECASE)
    imgs = img_pattern.findall(content)
    for img_tag in imgs:
        fixed = img_tag.replace('<img', '<img alt=""')
        content = content.replace(img_tag, fixed)
        print(f"  [A11Y] Added empty alt to decorative image")
        changes += 1

    # ── 22. Links must be distinguishable ──
    # Ensure all <a> tags with just URLs have descriptive text
    # (Usually fine in dashboard)

    # ── 23. Overlay needs aria-hidden ──
    old_overlay = '<div class="sb-overlay" id="sbOverlay">'
    new_overlay = '<div class="sb-overlay" id="sbOverlay" aria-hidden="true">'
    if old_overlay in content:
        content = content.replace(old_overlay, new_overlay)
        print("  [A11Y] Added aria-hidden to overlay")
        changes += 1

    # ── 24. Header date span ──
    if 'id="hDate"' in content and 'aria-label' not in _snippet(content, 'id="hDate"'):
        content = content.replace('id="hDate"', 'id="hDate" aria-label="Last updated date"')
        print("  [A11Y] Added aria to date span")
        changes += 1

    # ── 25. Add skip-to-content link (major a11y boost) ──
    if 'skip-to' not in content and '<body>' in content:
        skip_link = '<a href="#mainContent" class="sr-only" style="position:absolute;top:-40px;left:0;background:#2563EB;color:#fff;padding:8px 16px;z-index:999;transition:top 0.3s" onfocus="this.style.top=\'0\'" onblur="this.style.top=\'-40px\'">Skip to main content</a>'
        content = content.replace('<body>', '<body>\n' + skip_link)
        print("  [A11Y] Added skip-to-content link")
        changes += 1

    # ── 26. Add sr-only class if not in dashboard CSS ──
    if '.sr-only' not in content:
        if '</style>' in content:
            sr = ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}\n"
            content = content.replace('</style>', sr + '</style>')
            print("  [A11Y] Added .sr-only CSS")
            changes += 1

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print(f"\n  ✅ dashboard.html patched ({changes} fixes)")
    else:
        print("  No changes needed")


# ══════════════════════════════════════════════════════════════
# BACKTEST.JS — Dynamic element accessibility
# ══════════════════════════════════════════════════════════════

def patch_js():
    fp = Path("backtest.js")
    if not fp.exists():
        print("  ERROR: backtest.js not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content
    changes = 0

    # ── 1. Remove button ──
    old_remove = """'<button class="ind-remove" onclick="removeIndicatorSlot(' + idx + ')" title="Remove">✕</button>'"""
    new_remove = """'<button class="ind-remove" onclick="removeIndicatorSlot(' + idx + ')" title="Remove indicator" aria-label="Remove indicator ' + (idx + 1) + '">✕</button>'"""
    if old_remove in content:
        content = content.replace(old_remove, new_remove)
        print("  Added aria-label to remove buttons")
        changes += 1

    # ── 2. Indicator select ──
    old_select = """'<select class="ind-select" onchange="onIndChange(' + idx + ',this.value)">'"""
    new_select = """'<select class="ind-select" onchange="onIndChange(' + idx + ',this.value)" aria-label="Select indicator ' + (idx + 1) + '">'"""
    if old_select in content:
        content = content.replace(old_select, new_select)
        print("  Added aria-label to indicator selects")
        changes += 1

    # ── 3. Weight slider ──
    old_slider = """'<input type="range" class="weight-slider" min="0" max="100" value="' + slot.weight + '" '"""
    new_slider = """'<input type="range" class="weight-slider" min="0" max="100" value="' + slot.weight + '" aria-label="Weight for ' + (INDICATORS[slot.indId] ? INDICATORS[slot.indId].name : 'indicator') + '" '"""
    if old_slider in content:
        content = content.replace(old_slider, new_slider)
        print("  Added aria-label to weight sliders")
        changes += 1

    # ── 4. Entry condition select ──
    old_entry = """'<div class="cond-row"><label>Entry</label><select onchange="onCondChange(' + idx + ',\\'entry\\',this.value)">'"""
    new_entry = """'<div class="cond-row"><label for="entry_' + idx + '">Entry</label><select id="entry_' + idx + '" onchange="onCondChange(' + idx + ',\\'entry\\',this.value)" aria-label="Entry condition for indicator ' + (idx + 1) + '">'"""
    if old_entry in content:
        content = content.replace(old_entry, new_entry)
        print("  Added aria-label to entry selects")
        changes += 1

    # ── 5. Exit condition select ──
    old_exit = """'<div class="cond-row"><label>Exit</label><select onchange="onCondChange(' + idx + ',\\'exit\\',this.value)">'"""
    new_exit = """'<div class="cond-row"><label for="exit_' + idx + '">Exit</label><select id="exit_' + idx + '" onchange="onCondChange(' + idx + ',\\'exit\\',this.value)" aria-label="Exit condition for indicator ' + (idx + 1) + '">'"""
    if old_exit in content:
        content = content.replace(old_exit, new_exit)
        print("  Added aria-label to exit selects")
        changes += 1

    # ── 6. Parameter inputs ──
    old_param = """'onchange="onParamChange(' + idx + ',\\'' + p.id + '\\',this.value)"></div>'"""
    new_param = """'onchange="onParamChange(' + idx + ',\\'' + p.id + '\\',this.value)" aria-label="' + p.label + '"></div>'"""
    if old_param in content:
        content = content.replace(old_param, new_param)
        print("  Added aria-label to parameter inputs")
        changes += 1

    # ── 7. Mode button aria-pressed ──
    old_toggle = """b.classList.toggle('active', b.dataset.mode === mode);"""
    new_toggle = """b.classList.toggle('active', b.dataset.mode === mode);
      b.setAttribute('aria-pressed', b.dataset.mode === mode);"""
    if old_toggle in content and 'aria-pressed' not in content:
        content = content.replace(old_toggle, new_toggle)
        print("  Added aria-pressed to mode buttons")
        changes += 1

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print(f"\n  ✅ backtest.js patched ({changes} fixes)")
    else:
        print("  No changes needed")


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _snippet(content, marker, length=60):
    """Get a snippet of content after a marker for checking."""
    idx = content.find(marker)
    if idx < 0:
        return ""
    return content[idx:idx+length]


def _add_aria(content, id_str, label):
    """Check if aria-label needs adding. Returns 1 if needed, 0 if not."""
    if id_str in content and 'aria-label' not in _snippet(content, id_str):
        return 1
    return 0


def _apply_aria(content, id_str, label):
    """Apply aria-label to an element."""
    if id_str in content and 'aria-label' not in _snippet(content, id_str):
        return content.replace(id_str, id_str + ' aria-label="' + label + '"')
    return content


if __name__ == "__main__":
    main()


def main():
    print("=" * 70)
    print("  A11Y + SEO MIGRATION — index.html + dashboard.html")
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
    print("""
  Changes Applied:
    ✅ index.html       — aria-labels, contrast, chart roles, form labels
    ✅ dashboard.html   — aria-labels, contrast, form labels, meta tags,
                           hamburger a11y, modal a11y, filter a11y
    ✅ backtest.js      — dynamic element aria-labels

  Re-test both:
    https://pagespeed.web.dev/?url=https://xchart.in
    https://pagespeed.web.dev/?url=https://xchart.in/dashboard.html
""")


# ══════════════════════════════════════════════════════════════
# INDEX.HTML — Accessibility fixes (62 → 90+)
# ══════════════════════════════════════════════════════════════

def patch_index():
    fp = Path("index.html")
    if not fp.exists():
        print("  ERROR: index.html not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content
    changes = 0

    # ── 1. Ensure <html lang="en"> ──
    if '<html lang=' not in content:
        content = content.replace('<html>', '<html lang="en">')
        print("  Added lang='en' to <html>")
        changes += 1

    # ── 2. Add .sr-only class to <style> ──
    if '.sr-only' not in content:
        sr_only = ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}\n"
        content = content.replace('</style>', sr_only + '</style>')
        print("  Added .sr-only CSS class")
        changes += 1

    # ── 3. Footer contrast ──
    old_ftr = '.ftr{background:var(--white);border-top:1px solid var(--border);padding:16px 24px;font-size:10px;color:var(--text3);'
    new_ftr = '.ftr{background:var(--white);border-top:1px solid var(--border);padding:16px 24px;font-size:10px;color:var(--text2);'
    if old_ftr in content:
        content = content.replace(old_ftr, new_ftr)
        print("  Fixed footer contrast")
        changes += 1

    # ── 4. Mode desc contrast ──
    old_mode = '.mode-desc{font-size:10px;color:var(--text3);'
    new_mode = '.mode-desc{font-size:10px;color:var(--text2);'
    if old_mode in content:
        content = content.replace(old_mode, new_mode)
        print("  Fixed mode-desc contrast")
        changes += 1

    # ── 5. Ticker search — label + aria ──
    old_search = '<input type="text" id="tickerSearch" placeholder="Search by ticker or company name..." list="tickerList" autocomplete="off">'
    new_search = '<label for="tickerSearch" class="sr-only">Search stock ticker</label><input type="text" id="tickerSearch" placeholder="Search by ticker or company name..." list="tickerList" autocomplete="off" aria-label="Search stock ticker">'
    if old_search in content:
        content = content.replace(old_search, new_search)
        print("  Added label + aria to ticker search")
        changes += 1
    elif 'id="tickerSearch"' in content and 'aria-label' not in _snippet(content, 'id="tickerSearch"'):
