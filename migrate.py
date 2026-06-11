"""migrate.py -- One-time migration script to clean up repo structure.

Run once:
  python migrate.py

What it does:
  1. Creates output/ directory structure
  2. Moves generated files to output/
  3. Moves create_stock_data.py to engine/
  4. Updates all path references in:
     - app.py
     - engine/news.py
     - engine/create_stock_data.py (after move)
     - engine/data_fetcher.py
     - index.html
     - screener/config.py
     - All workflow YAML files
  5. Updates .gitignore
  6. Runs git add -A

After running, just:
  git commit -m "Restructure: output/ for generated data, engine/ for Python"
  git push
"""

import os
import shutil
import subprocess
from pathlib import Path


def git_mv(src, dst):
    """Move file using git mv (preserves history), fallback to shutil."""
    src_path = Path(src)
    dst_path = Path(dst)
    if not src_path.exists():
        print(f"  SKIP (not found): {src}")
        return False
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "mv", str(src), str(dst)], check=True, capture_output=True)
        print(f"  git mv {src} -> {dst}")
    except subprocess.CalledProcessError:
        shutil.move(str(src), str(dst))
        print(f"  moved  {src} -> {dst}")
    return True


def replace_in_file(filepath, replacements):
    """Replace multiple strings in a file."""
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


def write_file(filepath, content):
    """Write content to file, creating dirs if needed."""
    fp = Path(filepath)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    print(f"  WROTE {filepath}")


def main():
    print("=" * 60)
    print("  MIGRATION SCRIPT — Restructuring xchart-app")
    print("=" * 60)

    # ── Step 1: Create directories ──
    print("\n[1/8] Creating directories...")
    for d in ["output/charts", "screener_data/ohlcv", "screener_data/backtest_data"]:
        Path(d).mkdir(parents=True, exist_ok=True)
        print(f"  mkdir {d}")

    # ── Step 2: Move generated files to output/ ──
    print("\n[2/8] Moving generated files to output/...")
    moves = [
        ("data.csv", "output/data.csv"),
        ("history.csv", "output/history.csv"),
        ("meta.json", "output/meta.json"),
        ("tickers.csv", "output/tickers.csv"),
        ("stock_data.csv", "output/stock_data.csv"),
        ("news_cache.json", "output/news_cache.json"),
    ]
    for src, dst in moves:
        git_mv(src, dst)

    # Move charts/ contents to output/charts/
    if Path("charts").exists() and Path("charts").is_dir():
        chart_files = list(Path("charts").glob("*.json"))
        if chart_files:
            print(f"  Moving {len(chart_files)} chart files to output/charts/...")
            for f in chart_files:
                dst = Path("output/charts") / f.name
                try:
                    subprocess.run(["git", "mv", str(f), str(dst)], check=True, capture_output=True)
                except subprocess.CalledProcessError:
                    shutil.move(str(f), str(dst))
            # Remove empty charts/ dir
            try:
                Path("charts").rmdir()
                print("  Removed empty charts/")
            except OSError:
                pass
        else:
            print("  SKIP charts/ (empty)")
    else:
        print("  SKIP charts/ (not found)")

    # ── Step 3: Move create_stock_data.py to engine/ ──
    print("\n[3/8] Moving create_stock_data.py to engine/...")
    if Path("create_stock_data.py").exists():
        # Check if engine/ already has it
        if Path("engine/create_stock_data.py").exists():
            print("  engine/create_stock_data.py already exists, removing root copy")
            Path("create_stock_data.py").unlink()
        else:
            git_mv("create_stock_data.py", "engine/create_stock_data.py")
    else:
        print("  SKIP (already moved or not found)")

    # ── Step 4: Update Python path references ──
    print("\n[4/8] Updating Python path references...")

    # app.py — main entry point
    replace_in_file("app.py", [
        # Import change
        ("from create_stock_data import", "from engine.create_stock_data import"),
        # Path strings — use various quote styles
        ("'stock_data.csv'", "'output/stock_data.csv'"),
        ('"stock_data.csv"', '"output/stock_data.csv"'),
        ("'tickers.csv'", "'output/tickers.csv'"),
        ('"tickers.csv"', '"output/tickers.csv"'),
        ("'data.csv'", "'output/data.csv'"),
        ('"data.csv"', '"output/data.csv"'),
        ("'history.csv'", "'output/history.csv'"),
        ('"history.csv"', '"output/history.csv"'),
        ("'meta.json'", "'output/meta.json'"),
        ('"meta.json"', '"output/meta.json"'),
        ("'news_cache.json'", "'output/news_cache.json'"),
        ('"news_cache.json"', '"output/news_cache.json"'),
        ("'charts/'", "'output/charts/'"),
        ('"charts/"', '"output/charts/"'),
        ("'charts/'", "'output/charts/'"),
        # Path() style
        ('Path("charts")', 'Path("output/charts")'),
        ("Path('charts')", "Path('output/charts')"),
    ])

    # engine/create_stock_data.py
    replace_in_file("engine/create_stock_data.py", [
        ("DATA_FILE = 'stock_data.csv'", "DATA_FILE = 'output/stock_data.csv'"),
        ('DATA_FILE = "stock_data.csv"', 'DATA_FILE = "output/stock_data.csv"'),
        ("TICKERS_FILE = 'tickers.csv'", "TICKERS_FILE = 'output/tickers.csv'"),
        ('TICKERS_FILE = "tickers.csv"', 'TICKERS_FILE = "output/tickers.csv"'),
    ])

    # engine/news.py
    replace_in_file("engine/news.py", [
        ('Path("news_cache.json")', 'Path("output/news_cache.json")'),
        ("Path('news_cache.json')", "Path('output/news_cache.json')"),
        ('NEWS_CACHE_FILE = Path("news_cache.json")', 'NEWS_CACHE_FILE = Path("output/news_cache.json")'),
    ])

    # engine/data_fetcher.py (if it references stock_data.csv or tickers.csv)
    replace_in_file("engine/data_fetcher.py", [
        ("'stock_data.csv'", "'output/stock_data.csv'"),
        ('"stock_data.csv"', '"output/stock_data.csv"'),
        ("'tickers.csv'", "'output/tickers.csv'"),
        ('"tickers.csv"', '"output/tickers.csv"'),
    ])

    # engine/accuracy.py (if it references any paths)
    replace_in_file("engine/accuracy.py", [
        ("'stock_data.csv'", "'output/stock_data.csv'"),
        ('"stock_data.csv"', '"output/stock_data.csv"'),
    ])

    # screener/config.py
    replace_in_file("screener/config.py", [
        ('PREMIUM_TICKERS_FILE = Path("tickers.csv")', 'PREMIUM_TICKERS_FILE = Path("output/tickers.csv")'),
        ("PREMIUM_TICKERS_FILE = Path('tickers.csv')", "PREMIUM_TICKERS_FILE = Path('output/tickers.csv')"),
    ])

    # ── Step 5: Update index.html JavaScript paths ──
    print("\n[5/8] Updating index.html fetch paths...")
    replace_in_file("index.html", [
        # meta.json fetch
        ("fetch('meta.json')", "fetch('output/meta.json')"),
        ('fetch("meta.json")', 'fetch("output/meta.json")'),
        # Papa.parse CSV paths
        ("Papa.parse('data.csv'", "Papa.parse('output/data.csv'"),
        ('Papa.parse("data.csv"', 'Papa.parse("output/data.csv"'),
        ("Papa.parse('history.csv'", "Papa.parse('output/history.csv'"),
        ('Papa.parse("history.csv"', 'Papa.parse("output/history.csv"'),
        # Chart JSON fetch
        ("fetch('charts/'+", "fetch('output/charts/'+"),
        ('fetch("charts/"+', 'fetch("output/charts/"+'),
        ("'charts/'+tk+'.json'", "'output/charts/'+tk+'.json'"),
    ])

    # ── Step 6: Update .gitignore ──
    print("\n[6/8] Updating .gitignore...")
    gitignore_content = """# Python
__pycache__/
*.pyc
*.pyo
.env

# Screener raw cache (too large for git, ~500 CSV files)
screener_data/ohlcv/

# Large intermediate (uncomment if repo gets too big)
# output/stock_data.csv
# screener_data/nifty500_ohlcv.csv

# OS files
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/

# Migration script (one-time use)
migrate.py
"""
    write_file(".gitignore", gitignore_content)

    # ── Step 7: Skip workflow files (must be updated manually via GitHub UI) ──
    print("\n[7/8] Skipping workflow YAML updates (GitHub blocks automated workflow edits)")
    print("  -> You must manually update these 3 files via GitHub browser:")
    print("     1. .github/workflows/run_engine.yml")
    print("     2. .github/workflows/nifty500_fundamentals.yml")
    print("     3. .github/workflows/nifty500_ohlcv.yml")
    # ── Step 8: Git add all changes ──
    print("\n[8/8] Staging all changes...")
    subprocess.run(["git", "add", "-A"], capture_output=True)
    print("  git add -A done")

    # ── Final Report ──
    print("\n" + "=" * 60)
    print("  MIGRATION COMPLETE")
    print("=" * 60)

    # Count what's in root now
    root_files = [f for f in Path(".").iterdir()
                  if f.is_file() and not f.name.startswith(".")]
    root_dirs = [f for f in Path(".").iterdir()
                 if f.is_dir() and not f.name.startswith(".")]

    print(f"\n  Root files ({len(root_files)}):")
    for f in sorted(root_files):
        print(f"    {f.name}")
    print(f"\n  Root dirs ({len(root_dirs)}):")
    for d in sorted(root_dirs):
        print(f"    {d.name}/")

    print(f"\n  output/ contents:")
    if Path("output").exists():
        for f in sorted(Path("output").iterdir()):
            if f.is_dir():
                count = len(list(f.glob("*")))
                print(f"    {f.name}/ ({count} files)")
            else:
                size = f.stat().st_size / 1024
                print(f"    {f.name} ({size:.0f} KB)")

    print(f"""
  ┌─────────────────────────────────────────────┐
  │  Now run:                                   │
  │                                             │
  │  git status                                 │
  │  git commit -m "Restructure repo layout"    │
  │  git push                                   │
  │                                             │
  │  Then trigger run_engine.yml to verify      │
  └─────────────────────────────────────────────┘
""")

    # ── Sanity checks ──
    warnings = []
    if not Path("app.py").exists():
        warnings.append("app.py not found!")
    if not Path("engine/create_stock_data.py").exists():
        warnings.append("engine/create_stock_data.py not found!")
    if not Path("index.html").exists():
        warnings.append("index.html not found!")
    if not Path("output").is_dir():
        warnings.append("output/ directory not created!")

    # Check if paths were actually updated
    if Path("app.py").exists():
        content = Path("app.py").read_text()
        if "'stock_data.csv'" in content and "'output/stock_data.csv'" not in content:
            warnings.append("app.py still has old paths! Manual fix needed.")
    if Path("index.html").exists():
        content = Path("index.html").read_text()
        if "fetch('meta.json')" in content and "fetch('output/meta.json')" not in content:
            warnings.append("index.html still has old paths! Manual fix needed.")

    if warnings:
        print("  ⚠️ WARNINGS:")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("  ✅ All sanity checks passed!")


if __name__ == "__main__":
    main()
