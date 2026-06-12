"""migrate_sebi.py V4 — Loosen MID/SMALL entry + tighter SL."""

import re, subprocess
from pathlib import Path


def main():
    print("=" * 60)
    print("  MIGRATION V4: MID/SMALL Entry + SL Fix")
    print("=" * 60)

    print("\n[1/3] Patching engine/tech_v8.py...")
    patch_tech_v8()

    print("\n[2/3] Patching engine/accuracy.py (SL 5% -> 3%)...")
    patch_accuracy()

    print("\n[3/3] Staging changes...")
    subprocess.run(["git", "add", "-A"], capture_output=True)

    print("\n" + "=" * 60)
    print("  MIGRATION V4 COMPLETE")
    print("=" * 60)
    print("""
  Changes:
    1. MID/SMALL entry: Close < BB_Lower AND (SMA9 rising OR RSI < 35)
    2. MID/SMALL SL: 3% instead of 5%

  Next: Trigger "Run Trading Engine"
""")


def patch_tech_v8():
    fp = Path("engine/tech_v8.py")
    if not fp.exists():
        print("  ERROR: engine/tech_v8.py not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content

    # Fix 1: Add rsi parameter to score_tech_row signature
    old_sig = "def score_tech_row(close, sma9, sma22, sma200, sma9_prev,\n                   bb_lower, bb_mid, category):"
    new_sig = "def score_tech_row(close, sma9, sma22, sma200, sma9_prev,\n                   bb_lower, bb_mid, category, rsi=50):"

    if "rsi=50" not in content:
        content = content.replace(old_sig, new_sig)
        print("  Added rsi parameter to score_tech_row")

    # Fix 2: Add rsi safe conversion after bb_mid
    old_safe = "    bb_mid = _safe(bb_mid)\n\n    if close <= 0"
    new_safe = "    bb_mid = _safe(bb_mid)\n    rsi = _safe(rsi, 50)\n\n    if close <= 0"

    if "rsi = _safe(rsi" not in content:
        content = content.replace(old_safe, new_safe)
        print("  Added rsi safe conversion")

    # Fix 3: Update MID/SMALL entry condition
    old_entry = "        # ENTRY: Price below lower BB + SMA9 recovering\n        if close < bb_lower and sma9_rising:"
    new_entry = "        # ENTRY: Price below lower BB + (SMA9 recovering OR RSI oversold)\n        if close < bb_lower and (sma9_rising or rsi < 35):"

    if "rsi < 35" not in content:
        content = content.replace(old_entry, new_entry)
        print("  Updated MID/SMALL entry: BB_Lower AND (SMA9 rising OR RSI < 35)")

    # Fix 4: Update compute_tech_scores to pass RSI
    # Find the score_tech_row call in compute_tech_scores
    old_call = """    scores = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        scores[i] = score_tech_row(
            close[i], sma9[i], sma22[i], sma200[i], sma9_prev[i],
            bb_lower[i], bb_mid[i], str(cats[i])
        )"""

    new_call = """    rsi = _col(df, "RSI_14")
    if rsi.sum() == 0:
        rsi = _col(df, "RSI")

    scores = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        scores[i] = score_tech_row(
            close[i], sma9[i], sma22[i], sma200[i], sma9_prev[i],
            bb_lower[i], bb_mid[i], str(cats[i]), rsi[i]
        )"""

    if '"RSI_14"' not in content or 'rsi[i]' not in content:
        if old_call in content:
            content = content.replace(old_call, new_call)
            print("  Updated compute_tech_scores to pass RSI")
        else:
            print("  WARNING: Could not find score_tech_row call block!")

    if content != original:
        fp.write_text(content, encoding="utf-8")
        print("  engine/tech_v8.py patched")
    else:
        print("  No changes needed")


def patch_accuracy():
    fp = Path("engine/accuracy.py")
    if not fp.exists():
        print("  ERROR: engine/accuracy.py not found!")
        return

    content = fp.read_text(encoding="utf-8")
    original = content

    # Find SL_FIXED and change from 0.05 to 0.03
    # Common patterns:
    patterns = [
        ("SL_FIXED = 0.05", "SL_FIXED = 0.03"),
        ("SL_FIXED=0.05", "SL_FIXED=0.03"),
        ("SL_FIXED = 0.050", "SL_FIXED = 0.03"),
        ('SL_FIXED = 5.0', 'SL_FIXED = 3.0'),
    ]

    changed = False
    for old, new in patterns:
        if old in content:
            content = content.replace(old, new)
            changed = True
            print(f"  Changed: {old} -> {new}")
            break

    if not changed:
        # Try regex for any float value
        import re
        match = re.search(r'SL_FIXED\s*=\s*(0\.05|0\.050|5\.0|5)', content)
        if match:
            content = content[:match.start()] + "SL_FIXED = 0.03" + content[match.end():]
            changed = True
            print(f"  Changed SL_FIXED to 0.03 (was: {match.group()})")
        else:
            print("  WARNING: Could not find SL_FIXED in engine/accuracy.py!")
            # Print first few lines that contain SL for debugging
            for line in content.split('\n'):
                if 'SL' in line and '=' in line:
                    print(f"    Found: {line.strip()}")

    if changed:
        fp.write_text(content, encoding="utf-8")
        print("  engine/accuracy.py patched (SL: 5% -> 3%)")


if __name__ == "__main__":
    main()
