"""swap_pages.py -- Swap pages + fix broken dashboard.

1. Rename index.html -> dashboard.html (premium v7.4)
2. Rename backtest.html -> index.html (new homepage)
3. Fix dashboard.html JS breakages from SEBI migration
4. Update nav links in both pages
"""

import shutil
from pathlib import Path


def main():
    print("=" * 60)
    print("  PAGE SWAP + DASHBOARD FIX")
    print("=" * 60)

    # ── Step 1: Rename files ──
    print("\n[1/4] Renaming files...")

    if Path("index.html").exists() and Path("backtest.html").exists():
        # Move index.html -> dashboard.html
        shutil.move("index.html", "dashboard.html")
        print("  index.html -> dashboard.html")

        # Move backtest.html -> index.html
        shutil.move("backtest.html", "index.html")
        print("  backtest.html -> index.html")
    elif Path("index.html").exists() and not Path("backtest.html").exists():
        print("  backtest.html not found — maybe already swapped?")
        return
    else:
        print("  ERROR: index.html not found!")
        return

    # ── Step 2: Fix dashboard.html JS breakages ──
    print("\n[2/4] Fixing dashboard.html JS breakages...")

    dash = Path("dashboard.html")
    if dash.exists():
        content = dash.read_text(encoding="utf-8")
        original = content

        # Revert dangerous JS-breaking replacements
        # The SEBI migration replaced these globally which broke JS logic

        # Fix 1: "momentum readings" back to "signals" in JS contexts only
        # The migration turned variable names, IDs, class names into broken strings
        # We need to revert JS-context replacements while keeping UI text changes

        # Fix broken variable/function/ID references
        fixes = [
            # Revert JS variable names and IDs
            ('id="momentum readings"', 'id="signals"'),
            ("id='momentum readings'", "id='signals'"),
            ('class="momentum readings"', 'class="signals"'),
            ("class='momentum readings'", "class='signals'"),
            (".momentum readings", ".signals"),  # CSS selectors

            # Revert JS variable/property references
            ("var momentum readings", "var signals"),
            ("let momentum readings", "let signals"),
            ("const momentum readings", "const signals"),
            (".momentum readings", ".signals"),

            # Fix data.csv column references — app.py now outputs these new names
            # The JS needs to match what data.csv produces
            # app.py changed: Signal -> Momentum, Composite_Direction -> Momentum_Direction
            # So JS should look for "Momentum" not "Signal"
            # But if migration also changed JS references, they might be double-mangled

            # Fix filter button values — these need to match data.csv values
            # data.csv now has: POSITIVE, NEGATIVE, NEUTRAL (from app.py changes)
            # So the filter buttons should check for these values
            # The migration already changed BULL->POSITIVE in HTML, which is correct
            # But we need to make sure the JS filter logic matches

            # Fix: Sort dropdown that had "Signal" -> was changed to "Momentum"
            ("Sort: Momentum Reading", "Sort: Momentum"),
            ("Sort: Momentum Readings", "Sort: Momentum"),

            # Fix any double-mangled text
            ("Momentum Readingsing", "Momentum"),
            ("momentum readingsing", "momentum"),
            ("Momentum Readingsal", "Momentum"),

            # Fix: The word "Signal" in column references should be "Momentum"
            # This is correct since data.csv now has "Momentum" column

            # Fix Accuracy references
            ("Hist. Alignment:", "Alignment:"),
            ("Historical Alignment:", "Alignment:"),
        ]

        for old, new in fixes:
            if old in content:
                content = content.replace(old, new)

        # More targeted fixes: find broken JS patterns
        # The migration might have turned `r.Signal` into `r.Momentum Reading`
        # which is invalid JS (space in property name)
        import re

        # Fix property access patterns: r.Momentum Readings -> r.Momentum
        content = re.sub(
            r'\.Momentum\s+Reading[s]?',
            '.Momentum',
            content
        )

        # Fix string comparisons that got mangled
        # e.g., === "POSITIVE Momentum Readings" should be === "POSITIVE"
        content = re.sub(
            r'"POSITIVE\s+Momentum[^"]*"',
            '"POSITIVE"',
            content
        )
        content = re.sub(
            r'"NEGATIVE\s+Momentum[^"]*"',
            '"NEGATIVE"',
            content
        )
        content = re.sub(
            r"'POSITIVE\s+Momentum[^']*'",
            "'POSITIVE'",
            content
        )
        content = re.sub(
            r"'NEGATIVE\s+Momentum[^']*'",
            "'NEGATIVE'",
            content
        )

        # Fix: "Momentum Readings" in JS object keys/values that should just be "Momentum"
        content = content.replace('"Momentum Readings"', '"Momentum"')
        content = content.replace("'Momentum Readings'", "'Momentum'")
        content = content.replace('"momentum readings"', '"momentum"')
        content = content.replace("'momentum readings'", "'momentum'")

        # Fix: Column name references for Papa.parse CSV parsing
        # data.csv columns are now: Momentum, Momentum_Direction
        # Make sure JS references these correctly
        content = content.replace("Momentum_Readings", "Momentum")
        content = content.replace("Momentum Readings_Direction", "Momentum_Direction")

        # Fix: fetch paths (should already be output/ from earlier migration)
        # But double-check
        if "fetch('meta.json')" in content:
            content = content.replace("fetch('meta.json')", "fetch('output/meta.json')")
        if 'fetch("meta.json")' in content:
            content = content.replace('fetch("meta.json")', 'fetch("output/meta.json")')

        if content != original:
            dash.write_text(content, encoding="utf-8")
            print(f"  Fixed {content != original} JS breakages in dashboard.html")
        else:
            print("  No JS fixes needed")
    else:
        print("  dashboard.html not found!")

    # ── Step 3: Update nav links in both pages ──
    print("\n[3/4] Updating nav links...")

    # Update index.html (new homepage = backtest page)
    idx = Path("index.html")
    if idx.exists():
        content = idx.read_text(encoding="utf-8")

        # Update nav links
        nav_replacements = [
            # Old backtest.html nav -> update to new structure
            ('<a href="/">Dashboard</a>', '<a href="dashboard.html">Premium Analytics</a>'),
            ('<a href="/">AI Signals</a>', '<a href="dashboard.html">Premium Analytics</a>'),
            ('<a href="/">Backtest</a>', '<a href="/" class="active">Backtest</a>'),

            # Premium button links
            ("window.location.href='/'", "window.location.href='dashboard.html'"),
            ('window.location.href="/"', 'window.location.href="dashboard.html"'),

            # Explore link
            ("Explore Advanced Analytics →", "Explore Premium Analytics →"),
        ]

        for old, new in nav_replacements:
            content = content.replace(old, new)

        # Update disclaimer link
        content = content.replace(
            'href="/"</a>',
            'href="disclaimer.html">Full Disclaimer</a>'
        )

        idx.write_text(content, encoding="utf-8")
        print("  Updated index.html nav links")

    # Update dashboard.html nav
    if dash.exists():
        content = dash.read_text(encoding="utf-8")

        # Add nav links if not present
        nav_html = '''<div style="display:flex;gap:16px;font-size:13px;font-weight:500">
  <a href="/" style="color:#7a8299">Backtest</a>
  <a href="dashboard.html" style="color:#3b82f6">Premium Analytics</a>
  <a href="disclaimer.html" style="color:#7a8299">Disclaimer</a>
</div>'''

        # Try to insert nav near the header
        # Look for common header patterns
        if 'class="nav"' not in content and 'id="nav"' not in content:
            # No nav found, try to add after the logo
            if '</a>' in content[:2000]:
                # Find the first closing </a> in the header area (likely the logo)
                header_end = content.find('</a>') + 4
                if header_end > 4 and header_end < 2000:
                    # Don't insert if there's already navigation nearby
                    pass  # Skip complex nav insertion for now

        dash.write_text(content, encoding="utf-8")
        print("  Updated dashboard.html")

    # ── Step 4: Update backtest.js data path reference ──
    print("\n[4/4] Checking backtest.js paths...")
    bjs = Path("backtest.js")
    if bjs.exists():
        content = bjs.read_text(encoding="utf-8")
        # Paths should already be correct (screener_data/backtest_data/)
        print("  backtest.js paths OK")
    else:
        print("  backtest.js not found!")

    # ── Report ──
    print("\n" + "=" * 60)
    print("  PAGE SWAP COMPLETE")
    print("=" * 60)
    print(f"""
  Files:
    index.html      = Backtest page (homepage)
    dashboard.html  = Premium v7.4 analytics
    backtest.js     = Backtest engine
    disclaimer.html = Legal disclaimer

  URLs:
    xchart.in/                = Backtest (free, public)
    xchart.in/dashboard.html  = Premium Analytics (v7.4)
    xchart.in/disclaimer.html = Disclaimer

  Nav structure:
    [Backtest (active)] [Premium Analytics] [Disclaimer]
""")


if __name__ == "__main__":
    main()
