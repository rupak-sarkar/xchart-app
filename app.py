"""XChart Predictive Engine v5.2 — Dynamic Horizon + Trend-Following"""
import pandas as pd
import time

from engine.config import (
    TODAY_IST, NEWS_START_DATE, NEWS_CUT raw_dir != adj_dir:    TODAY_IST, NEWS_START_DATE, NEWS_CUTOFF_TIME, DATA_FILE,
            regime_flips += 1
        c_hit = adj_dir == row["Actual_Direction"]
        if adj_dir != 0:
            ctd += 1
            if c_hit:
                chd += 1
        corrected = " <- CORRECTED" if row["Forecast_Direction"] != adj_dir else ""
        bt_tag = ""
        if row.get('BT_1M', 0) > 0:
            bt_tag = f" BT:{row.get('BT_1M', 0):.0f}%/{row.get('BT_Category', '')} {row.get('BT_Forward_Days', 3)}d"
        print(f"  [{scored.index(row)+1:3d}] {row['Ticker']:<14s} Tech:{row['Technical_Score']:+4d} Macro:{row['Macro_Score']:+4d} Fund:{row['Fundamental_Score']:+4d} -> Comp:{adj_score:+6.1f} {dm[adj_dir]} {'HIT' if c_hit else 'MISS'}{corrected}{bt_tag}")

    t_bull = 0
    t_bear = 0
    t_neut = 0
    t_hit = 0
    t_total = 0
    for row in filing + nonews:
        comp = compute_composite_no_news(
            row["Technical_Score"], row["Macro_Score"], row["Fundamental_Score"]
        )
        adj_score, adj_dir = apply_regime_adjustment(comp["score"], regime)
        row["Composite_Score"] = adj_score
        row["Composite_Direction"] = adj_dir
        row["Composite_Severity"] = classify_composite_severity(adj_score) if adj_score != 0 else ""
        row["Forecast_Direction"] = 0
        if adj_dir == 1:
            t_bull += 1
        elif adj_dir == -1:
            t_bear += 1
        else:
            t_neut += 1
        if adj_dir == row["Actual_Direction"]:
            t_hit += 1
        t_total += 1

    for row in all_rows:
        row.pop("_sector", None)

    if t_total > 0:
        print(f"\n  Tech-only: Bull:{t_bull} Bear:{t_bear} Neut:{t_neut} | Hit:{t_hit}/{t_total} = {t_hit/t_total*100:.1f}%")
    print(f"  Regime flips: {regime_flips}")

    # ═══ PHASE 4: STREAKS + SAVE ═══
    print(f"\nPHASE 4: Streaks + save...")
    print("-" * 110)
    hdf = load_history()
    streaks = calculate_streaks(hdf, scored)
    for row in scored:
        s = streaks.get(row["Ticker"], {})
        row["Streak_Days"] = s.get("Streak_Days", 0)
        row["Streak_Return"] = s.get("Streak_Return", 0.0)
        row["Momentum"] = s.get("Momentum", "Neutral")

    pd.DataFrame(all_rows).to_csv(DATA_FILE, index=False)
    save_to_history(scored)

    # ═══ SUMMARY ═══
    sc = len(scored)
    fc = len(filing)
    nc2 = len(nonews)
    hrd = (hd / td2) * 100 if td2 > 0 else 0
    chrd = (chd / ctd) * 100 if ctd > 0 else 0
    comp_bull = sum(1 for r in scored if r.get("Composite_Direction", 0) == 1)
    comp_bear = sum(1 for r in scored if r.get("Composite_Direction", 0) == -1)

    print("\n" + "=" * 110)
    print(f"data.csv | {TODAY_IST} | ENGINE v5.2 DYNAMIC HORIZON + TREND-FOLLOWING")
    print(f"TICKERS: {sc} news | {fc} filing | {nc2} no-news")
    print(f"REGIME: {regime['regime']} ({regime['detail']})")
    print(f"STRATEGY: LC({lc_count}) SMC({smc_count}) | Trend-following | RSI<30")
    print(f"HORIZONS: MEGA=7d(+/-0.3%) LARGE=5d(+/-0.4%) MID=3d(+/-0.5%) SMALL=2d(+/-0.8%)")
    if bt_count > 0:
        print(f"BACKTEST: {bt_count} tickers | {total_bt_preds:,} predictions | 1M:{avg_1m:.1f}% ALL:{avg_all:.1f}%")
    print(f"\nSAME-DAY: Composite {chd}/{ctd} = {chrd:.1f}% | Bull:{comp_bull} Bear:{comp_bear} | Flips:{regime_flips}")
    print("=" * 110)

    # ═══ FULL ACCURACY REPORT ═══
    print_accuracy_report(bt_results, scored, hdf, all_rows)


if __name__ == "__main__":
    run()
    WEIGHTS_NEWS, WEIGHTS_NO_NEWS
)
from engine.tickers import load_tickers
from engine.data_fetcher import ensure_data_exists
from engine.news import build_news_cache, get_all_fresh_news, get_live_price_return
from engine.sentiment import (
    _load_finbert, compute_aggregated_score, classify_severity, classify_impact,
    classify_composite_severity
)
from engine.technical import (
    load_stock_data, detect_mcap_scale, get_technical_score,
    get_sector_from_stock_data
)
from engine.fundamentals import score_fundamentals
from engine.regime import get_nifty_change, compute_market_regime, get_macro_scores
from engine.composite import compute_composite_news, compute_composite_no_news, apply_regime_adjustment
from engine.accuracy import compute_per_ticker_accuracy, print_accuracy_report
from engine.history import load_history, save_to_history, calculate_streaks
from engine.utils import is_bad_str, safe_float
from engine.config import SOURCE_LABELS


def run():
    # ═══ PHASE 0: Ensure 2Y historical data exists ═══
    print("Checking historical data...")
    ensure_data_exists()

    # Init FinBERT
    _load_finbert()

    tl, sm = load_tickers()
    total = len(tl)
    print(f"\nPREDICTIVE Engine v5.2 - {total} tickers | {TODAY_IST}")
    print(f"News: {NEWS_START_DATE} to {NEWS_CUTOFF_TIME.strftime('%I:%M %p')} | CATALYST-ONLY FinBERT")
    print(f"Tech: TREND-FOLLOWING PRIMARY (LC/SMC, RSI<30 threshold)")
    print(f"Horizons: MEGA=7d LARGE=5d MID=3d SMALL=2d (±ADX/Price)")
    print(f"Validation: Dynamic horizon | Per-ticker: Swing/1M/3M/ALL")
    print("=" * 110)

    # ═══ PHASE 1: NEWS ═══
    print("\nPHASE 1: Fetching predictive news...")
    print("-" * 110)
    nc = build_news_cache(tl)
    print("-" * 110)

    # ═══ PHASE 2: FINBERT ═══
    print(f"\nPHASE 2: FinBERT scoring (CATALYST-ONLY)...")
    print("-" * 110)
    scored = []
    filing = []
    nonews = []
    hd = 0
    td2 = 0
    total_catalyst = 0
    total_noise_filtered = 0
    dm = {1: "BULL", -1: "BEAR", 0: "NEUT"}

    for tk in tl:
        ret = get_live_price_return(tk)
        ad = 1 if ret > 0.25 else (-1 if ret < -0.25 else 0)
        entries, cls, fe = get_all_fresh_news(tk, nc, ret)
        base = {
            "Ticker": tk, "Sector": sm.get(tk, ""),
            "Actual_Direction": ad, "Actual_Return_Pct": ret
        }

        if cls == "no_news":
            nonews.append({
                **base, "Latest_Headline": "", "News_Source": "", "News_Time": "",
                "News_URL": "", "Headline_Count": 0, "Forecast_Score": 0.0,
                "Forecast_Direction": 0, "Severity": "No News", "Impact": "",
                "Streak_Days": 0, "Streak_Return": 0.0, "Momentum": "",
                "Signal_Quality": "Tech-Scored"
            })
            continue

        if cls == "filing_only":
            p = fe[0] if fe else {}
            from engine.news import get_source_search_url
            nu = p.get("news_url", "") or get_source_search_url("NSE Official", tk)
            filing.append({
                **base, "Latest_Headline": p.get("headline", ""),
                "News_Source": "NSE Official",
                "News_Time": p.get("pub_time", "").replace(",", ""),
                "News_URL": nu, "Headline_Count": len(fe),
                "Forecast_Score": 0.0, "Forecast_Direction": 0,
                "Severity": "Filing Only", "Impact": "",
                "Streak_Days": 0, "Streak_Return": 0.0, "Momentum": "",
                "Signal_Quality": "Tech-Scored"
            })
            continue

        pe = max(entries, key=lambda e: e["weight"])
        ps = pe["source"]
        pt = pe["pub_time"]
        from engine.news import get_source_search_url
        pu = pe.get("news_url", "") or get_source_search_url(SOURCE_LABELS.get(ps, ""), tk)
        if ps in ("yfinance", "google"):
            time.sleep(0.3)

        score, direction, cat_count, noise_count = compute_aggregated_score(entries)
        total_catalyst += cat_count
        total_noise_filtered += noise_count
        sev = classify_severity(score)
        imp = classify_impact(entries)
        hit = direction == ad
        if direction != 0:
            td2 += 1
            if hit:
                hd += 1
        q = "High" if abs(score) >= 60 else ("Moderate" if abs(score) >= 25 else ("Weak" if abs(score) >= 5 else "Neutral"))
        usrc = list(dict.fromkeys(SOURCE_LABELS.get(e["source"], e["source"]) for e in entries))
        print(f"[{len(scored)+1:3d}] {tk:<14s} {dm.get(direction, '?'):4s} Score:{score:+6.1f} Ret:{ret:+6.2f}% {'HIT' if hit else 'MISS'} [{cat_count}cat/{len(entries)}h]")
        scored.append({
            **base, "Latest_Headline": pe["headline"],
            "News_Source": " | ".join(usrc),
            "News_Time": pt.replace(",", "") if pt else "",
            "News_URL": pu, "Headline_Count": len(entries),
            "Forecast_Score": score, "Forecast_Direction": direction,
            "Severity": sev, "Impact": imp, "Signal_Quality": q
        })

    print(f"\n  Catalysts: {total_catalyst} scored / {total_noise_filtered} noise filtered")

    # ═══ PHASE 3: MULTI-LAYER ANALYSIS ═══
    all_rows = scored + filing + nonews
    print(f"\nPHASE 3: Multi-layer analysis ({len(all_rows)} tickers)...")
    print("-" * 110)

    print("Loading stock data...")
    stock_df = load_stock_data()
    mcap_threshold = detect_mcap_scale(stock_df)
    print(f"  -> MCap threshold: {mcap_threshold:.0f}")

    # Technical
    print("Computing technical scores (v5.2 trend-following)...")
    tech_count = 0
    lc_count = 0
    smc_count = 0
    for i, row in enumerate(all_rows):
        tech = get_technical_score(row["Ticker"], stock_df, mcap_threshold, debug=(i < 3))
        row["Technical_Score"] = tech["score"]
        row["Tech_Signals"] = " | ".join(tech["signals"]) if tech["signals"] else ""
        if tech["score"] != 0:
            tech_count += 1
        if stock_df is not None and not stock_df.empty:
            tk_v = stock_df[stock_df['Ticker'] == row["Ticker"]]
            tk_v = tk_v[tk_v['Close'].notna()]
            if not tk_v.empty:
                mc = safe_float(tk_v.iloc[-1].get('Market_Cap', 0), 0)
                if mc > mcap_threshold:
                    lc_count += 1
                else:
                    smc_count += 1
            else:
                smc_count += 1
        else:
            smc_count += 1
    print(f"  -> {tech_count}/{len(all_rows)} scored | LC:{lc_count} SMC:{smc_count}")

    # Fundamentals
    print("Computing fundamentals...")
    for row in all_rows:
        fund = score_fundamentals(row["Ticker"], stock_df)
        row["Fundamental_Score"] = fund["score"]
        row["Fund_Concern"] = fund.get("concern", "")
    fund_nz = sum(1 for r in all_rows if r["Fundamental_Score"] != 0)
    print(f"  -> {fund_nz}/{len(all_rows)} with non-zero fund score")

    # Sectors
    all_sectors = set()
    sc_count = 0
    for row in all_rows:
        sector = sm.get(row["Ticker"], "")
        if not sector or is_bad_str(sector):
            sector = get_sector_from_stock_data(row["Ticker"], stock_df)
        if is_bad_str(sector):
            sector = ""
        row["_sector"] = sector
        if sector:
            all_sectors.add(sector)
            sc_count += 1
    print(f"  -> {sc_count}/{len(all_rows)} mapped to {len(all_sectors)} sectors")

    # Regime
    print("\nComputing market regime...")
    nifty_chg = get_nifty_change()
    print(f"  -> Nifty 5d: {nifty_chg:+.2f}%")
    regime = compute_market_regime(stock_df, nifty_chg)
    print(f"  -> REGIME: {regime['regime']} ({regime['detail']})")

    # Macro
    print(f"\nComputing sector strength...")
    macro_scores = get_macro_scores(all_sectors, stock_df, regime)
    for row in all_rows:
        macro = macro_scores.get(row.get("_sector", ""), {"score": 0, "context": ""})
        row["Macro_Score"] = macro["score"]
        row["Macro_Context"] = macro.get("context", "")

    # ═══ PHASE 3b: PER-TICKER BACKTEST (dynamic horizons) ═══
    print(f"\nPHASE 3b: Per-ticker backtest (dynamic horizons, 4 accuracy levels)...")
    bt_results = compute_per_ticker_accuracy(stock_df, mcap_threshold)
    bt_count = len(bt_results)
    avg_1m = 0.0
    avg_all = 0.0
    total_bt_preds = 0
    if bt_count > 0:
        avg_1m = sum(r["BT_1M"] for r in bt_results.values()) / bt_count
        avg_all = sum(r["BT_6M"] for r in bt_results.values()) / bt_count
        total_bt_preds = sum(r["BT_Total_Preds"] for r in bt_results.values())
        print(f"  -> {bt_count} tickers | {total_bt_preds:,} predictions")
        print(f"  -> Avg 1M: {avg_1m:.1f}% | Avg ALL: {avg_all:.1f}%")

    # Attach backtest to rows
    for row in all_rows:
        bt = bt_results.get(row["Ticker"], {})
        row["BT_Swing"] = bt.get("BT_Swing", "")
        row["BT_1M"] = bt.get("BT_1M", 0.0)
        row["BT_3M"] = bt.get("BT_3M", 0.0)
        row["BT_6M"] = bt.get("BT_6M", 0.0)
        row["BT_1M_N"] = bt.get("BT_1M_N", 0)
        row["BT_Total_Preds"] = bt.get("BT_Total_Preds", 0)
        row["BT_Forward_Days"] = bt.get("BT_Forward_Days", 3)
        row["BT_Threshold"] = bt.get("BT_Threshold", 0.5)
        row["BT_Category"] = bt.get("BT_Category", "")

    # ═══ COMPOSITE + REGIME ═══
    print(f"\nComputing composite + regime adjustment...")
    if "BEAR" in regime["regime"]:
        rdesc = f"BULL dampened {'60%' if regime['regime'] == 'BEAR' else '80%'}"
    elif "BULL" in regime["regime"]:
        rdesc = f"BEAR dampened {'60%' if regime['regime'] == 'BULL' else '80%'}"
    else:
        rdesc = "no adjustment"
    print(f"  Regime: {regime['regime']} -> {rdesc}")
    print("-" * 110)

    chd = 0
    ctd = 0
    regime_flips = 0
    for row in scored:
        comp = compute_composite_news(
            row["Forecast_Score"], row["Technical_Score"],
            row["Macro_Score"], row["Fundamental_Score"]
        )
        raw_dir = comp["direction"]
        adj_score, adj_dir = apply_regime_adjustment(comp["score"], regime)
        row["Composite_Score"] = adj_score
        row["Composite_Direction"] = adj_dir
        row["Composite_Severity"] = classify_composite_severity(adj_score)
