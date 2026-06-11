/**
 * backtest.js — Client-side backtesting engine for xchart.in
 *
 * Loads per-ticker JSON from screener_data/backtest_data/
 * Computes indicators on the fly (or uses pre-computed)
 * Runs walk-forward backtest based on user-configured rules
 * Displays results: KPIs, chart with markers, equity curve, trade log
 */

(function () {
  "use strict";

  // ── State ──
  var TICKERS = [];
  var TICKER_DATA = null;   // Current loaded ticker data
  var SCORES = {};          // Quality scores (optional)
  var mainChart = null;
  var eqChart = null;

  var DATA_BASE = "screener_data/backtest_data/";
  var SCORES_CSV = "screener_data/nifty500_scores.csv";
  var TICKERS_CSV = "screener_data/nifty500_tickers.csv";

  // ── Helpers ──
  var pf = function (v) { return parseFloat(v) || 0; };
  var round2 = function (v) { return Math.round(v * 100) / 100; };

  // ── Indicator Computations (for browser) ──

  function computeSMA(closes, period) {
    var result = new Array(closes.length).fill(null);
    for (var i = period - 1; i < closes.length; i++) {
      var sum = 0;
      for (var j = i - period + 1; j <= i; j++) sum += closes[j];
      result[i] = sum / period;
    }
    return result;
  }

  function computeEMA(closes, period) {
    var result = new Array(closes.length).fill(null);
    var k = 2 / (period + 1);
    // Initialize with SMA
    var sum = 0;
    for (var i = 0; i < period; i++) sum += closes[i];
    result[period - 1] = sum / period;
    for (var i = period; i < closes.length; i++) {
      result[i] = closes[i] * k + result[i - 1] * (1 - k);
    }
    return result;
  }

  function computeRSI(closes, period) {
    var result = new Array(closes.length).fill(null);
    if (closes.length < period + 1) return result;

    var gains = [], losses = [];
    for (var i = 1; i < closes.length; i++) {
      var delta = closes[i] - closes[i - 1];
      gains.push(delta > 0 ? delta : 0);
      losses.push(delta < 0 ? -delta : 0);
    }

    // Wilder's smoothing
    var avgGain = 0, avgLoss = 0;
    for (var i = 0; i < period; i++) {
      avgGain += gains[i];
      avgLoss += losses[i];
    }
    avgGain /= period;
    avgLoss /= period;

    result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

    for (var i = period; i < gains.length; i++) {
      avgGain = (avgGain * (period - 1) + gains[i]) / period;
      avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
      result[i + 1] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
    return result;
  }

  function computeMACD(closes) {
    var ema12 = computeEMA(closes, 12);
    var ema26 = computeEMA(closes, 26);
    var line = new Array(closes.length).fill(null);
    var signal = new Array(closes.length).fill(null);

    for (var i = 0; i < closes.length; i++) {
      if (ema12[i] !== null && ema26[i] !== null) {
        line[i] = ema12[i] - ema26[i];
      }
    }

    // Signal line (9-EMA of MACD line)
    var validLine = [];
    var validIdx = [];
    for (var i = 0; i < line.length; i++) {
      if (line[i] !== null) { validLine.push(line[i]); validIdx.push(i); }
    }
    if (validLine.length >= 9) {
      var sigEma = computeEMA(validLine, 9);
      for (var i = 0; i < sigEma.length; i++) {
        if (sigEma[i] !== null) signal[validIdx[i]] = sigEma[i];
      }
    }

    return { line: line, signal: signal };
  }

  function computeBB(closes, period, stdMult) {
    period = period || 20;
    stdMult = stdMult || 2;
    var upper = new Array(closes.length).fill(null);
    var lower = new Array(closes.length).fill(null);

    for (var i = period - 1; i < closes.length; i++) {
      var slice = closes.slice(i - period + 1, i + 1);
      var mean = slice.reduce(function (a, b) { return a + b; }, 0) / period;
      var variance = slice.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / period;
      var std = Math.sqrt(variance);
      upper[i] = mean + stdMult * std;
      lower[i] = mean - stdMult * std;
    }
    return { upper: upper, lower: lower };
  }

  function computeADX(highs, lows, closes, period) {
    period = period || 14;
    var n = closes.length;
    var result = new Array(n).fill(null);
    if (n < period + 1) return result;

    // True Range
    var tr = [0];
    for (var i = 1; i < n; i++) {
      tr.push(Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1])));
    }

    var plusDM = [0], minusDM = [0];
    for (var i = 1; i < n; i++) {
      var up = highs[i] - highs[i - 1];
      var down = lows[i - 1] - lows[i];
      plusDM.push(up > down && up > 0 ? up : 0);
      minusDM.push(down > up && down > 0 ? down : 0);
    }

    // Wilder's smoothing
    var alpha = 1 / period;
    var atr = tr[0], sp = plusDM[0], sm = minusDM[0];
    for (var i = 1; i < Math.min(period, n); i++) {
      atr += tr[i]; sp += plusDM[i]; sm += minusDM[i];
    }
    atr /= period; sp /= period; sm /= period;

    var dxArr = [];
    for (var i = period; i < n; i++) {
      atr = atr * (1 - alpha) + tr[i] * alpha;
      sp = sp * (1 - alpha) + plusDM[i] * alpha;
      sm = sm * (1 - alpha) + minusDM[i] * alpha;

      var pdi = atr > 0 ? 100 * sp / atr : 0;
      var mdi = atr > 0 ? 100 * sm / atr : 0;
      var diSum = pdi + mdi;
      var dx = diSum > 0 ? 100 * Math.abs(pdi - mdi) / diSum : 0;
      dxArr.push(dx);

      if (dxArr.length >= period) {
        var adxVal = dxArr.slice(-period).reduce(function (a, b) { return a + b; }, 0) / period;
        result[i] = adxVal;
      }
    }
    return result;
  }

  function computeSuperTrend(highs, lows, closes, period, multiplier) {
    period = period || 10;
    multiplier = multiplier || 3;
    var n = closes.length;
    var direction = new Array(n).fill(0);
    var stValue = new Array(n).fill(null);

    // ATR
    var tr = [0];
    for (var i = 1; i < n; i++) {
      tr.push(Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1])));
    }
    var atrArr = new Array(n).fill(null);
    for (var i = period - 1; i < n; i++) {
      var sum = 0;
      for (var j = i - period + 1; j <= i; j++) sum += tr[j];
      atrArr[i] = sum / period;
    }

    // Find first valid
    var fv = -1;
    for (var i = 0; i < n; i++) { if (atrArr[i] !== null) { fv = i; break; } }
    if (fv < 0) return { direction: direction, value: stValue };

    var hl2, ub, lb;
    hl2 = (highs[fv] + lows[fv]) / 2;
    var fu = hl2 + multiplier * atrArr[fv];
    var fl = hl2 - multiplier * atrArr[fv];
    direction[fv] = closes[fv] > fu ? -1 : 1;

    for (var i = fv + 1; i < n; i++) {
      if (atrArr[i] === null) {
        direction[i] = direction[i - 1];
        continue;
      }
      hl2 = (highs[i] + lows[i]) / 2;
      lb = hl2 - multiplier * atrArr[i];
      ub = hl2 + multiplier * atrArr[i];

      fl = (lb > fl || closes[i - 1] < fl) ? lb : fl;
      fu = (ub < fu || closes[i - 1] > fu) ? ub : fu;

      if (direction[i - 1] <= 0 && closes[i] > fu) direction[i] = -1;
      else if (direction[i - 1] >= 0 && closes[i] < fl) direction[i] = 1;
      else direction[i] = direction[i - 1];
    }

    for (var i = 0; i < n; i++) {
      stValue[i] = direction[i] === -1 ? fl : (direction[i] === 1 ? fu : null);
    }

    return { direction: direction, value: stValue };
  }


  // ── Data Loading ──

  function loadTickerList() {
    Papa.parse(TICKERS_CSV, {
      download: true, header: true,
      complete: function (r) {
        TICKERS = r.data
          .map(function (row) { return (row.Ticker || row.Symbol || "").trim(); })
          .filter(function (t) { return t && t !== "nan"; });

        var dl = document.getElementById("tickerList");
        dl.innerHTML = "";
        TICKERS.forEach(function (t) {
          var opt = document.createElement("option");
          opt.value = t;
          dl.appendChild(opt);
        });

        document.getElementById("hsTickers").textContent = TICKERS.length;
        updateStatus("load", TICKERS.length + " stocks loaded. Search above.");
      },
      error: function () {
        updateStatus("err", "Could not load ticker list. Run the OHLCV pipeline first.");
      }
    });
  }

  function loadTickerData(ticker) {
    updateStatus("load", "Loading " + ticker + "...");
    document.getElementById("btnRun").disabled = true;

    fetch(DATA_BASE + ticker + ".json")
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then(function (data) {
        TICKER_DATA = data;
        updateStatus("ok", ticker + " loaded: " + data.rows + " days (" + data.first_date + " to " + data.last_date + ")");
        document.getElementById("btnRun").disabled = false;
      })
      .catch(function () {
        TICKER_DATA = null;
        updateStatus("err", ticker + " not found. Run OHLCV pipeline for this ticker.");
        document.getElementById("btnRun").disabled = true;
      });
  }

  function updateStatus(type, msg) {
    var el = document.getElementById("dataStatus");
    var dotClass = type === "ok" ? "dot-ok" : type === "err" ? "dot-err" : "dot-load";
    el.innerHTML = '<span class="dot ' + dotClass + '"></span> ' + msg;
  }


  // ── Backtest Engine ──

  function runBacktest() {
    if (!TICKER_DATA || !TICKER_DATA.ohlcv || TICKER_DATA.ohlcv.length < 20) {
      updateStatus("err", "Not enough data to backtest.");
      return;
    }

    var ticker = TICKER_DATA.ticker;
    var ohlcv = TICKER_DATA.ohlcv;

    // Filter by period
    var period = document.getElementById("period").value;
    var cutoffDays = { "6m": 130, "1y": 260, "2y": 520, "3y": 9999 }[period] || 260;
    if (ohlcv.length > cutoffDays) {
      ohlcv = ohlcv.slice(-cutoffDays);
    }

    var n = ohlcv.length;
    var dates = ohlcv.map(function (r) { return r.d; });
    var opens = ohlcv.map(function (r) { return r.o; });
    var highs = ohlcv.map(function (r) { return r.h; });
    var lows = ohlcv.map(function (r) { return r.l; });
    var closes = ohlcv.map(function (r) { return r.c; });
    var volumes = ohlcv.map(function (r) { return r.v; });

    // ── Compute indicators ──
    var rsiArr = computeRSI(closes, 14);
    var macdData = computeMACD(closes);
    var bb = computeBB(closes, 20, 2);
    var adxArr = computeADX(highs, lows, closes, 14);
    var st = computeSuperTrend(highs, lows, closes, 10, 3);

    // Dynamic SMAs/EMAs based on user settings
    var smaFast = computeSMA(closes, parseInt(document.getElementById("e_sma_fast").value) || 9);
    var smaSlow = computeSMA(closes, parseInt(document.getElementById("e_sma_slow").value) || 22);
    var emaFast = computeEMA(closes, parseInt(document.getElementById("e_ema_fast").value) || 9);
    var emaSlow = computeEMA(closes, parseInt(document.getElementById("e_ema_slow").value) || 21);
    var priceSMAPeriod = parseInt(document.getElementById("e_price_sma_val").value) || 200;
    var priceSMA = computeSMA(closes, priceSMAPeriod);

    // ── Read rules ──
    var entryLogic = document.getElementById("entryLogic").value; // "all" or "any"

    var entryRules = [];
    if (document.getElementById("e_rsi").checked) {
      var threshold = pf(document.getElementById("e_rsi_val").value);
      entryRules.push(function (i) { return rsiArr[i] !== null && rsiArr[i] < threshold; });
    }
    if (document.getElementById("e_sma_cross").checked) {
      entryRules.push(function (i) {
        return smaFast[i] !== null && smaSlow[i] !== null && smaFast[i] > smaSlow[i] &&
               (smaFast[i - 1] === null || smaSlow[i - 1] === null || smaFast[i - 1] <= smaSlow[i - 1]);
      });
    }
    if (document.getElementById("e_macd").checked) {
      entryRules.push(function (i) {
        return macdData.line[i] !== null && macdData.signal[i] !== null &&
               macdData.line[i] > macdData.signal[i] &&
               (macdData.line[i - 1] === null || macdData.signal[i - 1] === null || macdData.line[i - 1] <= macdData.signal[i - 1]);
      });
    }
    if (document.getElementById("e_supertrend").checked) {
      entryRules.push(function (i) { return st.direction[i] === -1; });
    }
    if (document.getElementById("e_bb_low").checked) {
      var bbThreshold = pf(document.getElementById("e_bb_val").value);
      entryRules.push(function (i) {
        if (bb.upper[i] === null || bb.lower[i] === null) return false;
        var range = bb.upper[i] - bb.lower[i];
        if (range <= 0) return false;
        return (closes[i] - bb.lower[i]) / range < bbThreshold;
      });
    }
    if (document.getElementById("e_adx").checked) {
      var adxThreshold = pf(document.getElementById("e_adx_val").value);
      entryRules.push(function (i) { return adxArr[i] !== null && adxArr[i] > adxThreshold; });
    }
    if (document.getElementById("e_ema_cross").checked) {
      entryRules.push(function (i) {
        return emaFast[i] !== null && emaSlow[i] !== null && emaFast[i] > emaSlow[i] &&
               (emaFast[i - 1] === null || emaSlow[i - 1] === null || emaFast[i - 1] <= emaSlow[i - 1]);
      });
    }
    if (document.getElementById("e_price_sma200").checked) {
      entryRules.push(function (i) { return priceSMA[i] !== null && closes[i] > priceSMA[i]; });
    }

    // Default rule if none selected
    if (entryRules.length === 0) {
      entryRules.push(function (i) { return rsiArr[i] !== null && rsiArr[i] < 30; });
    }

    // Exit rules
    var exitRsiEnabled = document.getElementById("x_rsi").checked;
    var exitRsiVal = pf(document.getElementById("x_rsi_val").value);
    var exitSLEnabled = document.getElementById("x_sl").checked;
    var exitSLVal = pf(document.getElementById("x_sl_val").value) / 100;
    var exitTPEnabled = document.getElementById("x_tp").checked;
    var exitTPVal = pf(document.getElementById("x_tp_val").value) / 100;
    var exitTrailEnabled = document.getElementById("x_trail").checked;
    var exitTrailVal = pf(document.getElementById("x_trail_val").value) / 100;
    var exitMaxHoldEnabled = document.getElementById("x_maxhold").checked;
    var exitMaxHoldVal = parseInt(document.getElementById("x_maxhold_val").value) || 14;
    var exitFlipEnabled = document.getElementById("x_signal_flip").checked;

    // ── Walk-forward backtest ──
    var trades = [];
    var inTrade = false;
    var entryPrice = 0, entryIdx = 0, peakPrice = 0;
    var markers = [];

    // Need at least 30 rows of warmup for indicators
    var warmup = 30;

    for (var i = warmup; i < n; i++) {
      if (!inTrade) {
        // Check entry
        var entryMatch;
        if (entryLogic === "any") {
          entryMatch = entryRules.some(function (fn) { try { return fn(i); } catch (e) { return false; } });
        } else {
          entryMatch = entryRules.every(function (fn) { try { return fn(i); } catch (e) { return false; } });
        }

        if (entryMatch) {
          inTrade = true;
          entryPrice = closes[i];
          entryIdx = i;
          peakPrice = closes[i];
          markers.push({
            time: dates[i],
            position: "belowBar",
            color: "#22c55e",
            shape: "arrowUp",
            text: "BUY"
          });
        }
      } else {
        // Track peak for trailing SL
        if (closes[i] > peakPrice) peakPrice = closes[i];

        var exitReason = null;
        var holdDays = i - entryIdx;
        var returnPct = (closes[i] - entryPrice) / entryPrice;

        // Check exit conditions
        if (exitSLEnabled && returnPct <= -exitSLVal) {
          exitReason = "SL";
        } else if (exitTPEnabled && returnPct >= exitTPVal) {
          exitReason = "TP";
        } else if (exitTrailEnabled && peakPrice > entryPrice) {
          var trailLevel = peakPrice * (1 - exitTrailVal);
          if (closes[i] < trailLevel) exitReason = "Trail";
        }

        if (!exitReason && exitRsiEnabled && rsiArr[i] !== null && rsiArr[i] > exitRsiVal) {
          exitReason = "RSI";
        }
        if (!exitReason && exitMaxHoldEnabled && holdDays >= exitMaxHoldVal) {
          exitReason = "MaxHold";
        }
        if (!exitReason && exitFlipEnabled) {
          // Check if entry conditions now fail
          var stillValid;
          if (entryLogic === "any") {
            stillValid = entryRules.some(function (fn) { try { return fn(i); } catch (e) { return false; } });
          } else {
            stillValid = entryRules.every(function (fn) { try { return fn(i); } catch (e) { return false; } });
          }
          if (!stillValid) exitReason = "Flip";
        }

        if (exitReason) {
          var retPct = round2((closes[i] - entryPrice) / entryPrice * 100);
          trades.push({
            entry_date: dates[entryIdx],
            exit_date: dates[i],
            entry_price: round2(entryPrice),
            exit_price: round2(closes[i]),
            return_pct: retPct,
            hold_days: holdDays,
            exit_reason: exitReason,
            win: retPct > 0
          });
          markers.push({
            time: dates[i],
            position: "aboveBar",
            color: retPct > 0 ? "#22c55e" : "#ef4444",
            shape: "arrowDown",
            text: (retPct > 0 ? "+" : "") + retPct.toFixed(1) + "%"
          });
          inTrade = false;
        }
      }
    }

    // Close any open trade
    if (inTrade) {
      var retPct = round2((closes[n - 1] - entryPrice) / entryPrice * 100);
      trades.push({
        entry_date: dates[entryIdx],
        exit_date: dates[n - 1],
        entry_price: round2(entryPrice),
        exit_price: round2(closes[n - 1]),
        return_pct: retPct,
        hold_days: n - 1 - entryIdx,
        exit_reason: "Open",
        win: retPct > 0
      });
    }

    // ── Compute KPIs ──
    var totalTrades = trades.length;
    var wins = trades.filter(function (t) { return t.win; });
    var losses = trades.filter(function (t) { return !t.win; });
    var winRate = totalTrades > 0 ? round2(wins.length / totalTrades * 100) : 0;
    var avgWin = wins.length > 0 ? round2(wins.reduce(function (s, t) { return s + t.return_pct; }, 0) / wins.length) : 0;
    var avgLoss = losses.length > 0 ? round2(losses.reduce(function (s, t) { return s + Math.abs(t.return_pct); }, 0) / losses.length) : 0;
    var totalReturn = round2(trades.reduce(function (s, t) { return s + t.return_pct; }, 0));
    var profitFactor = 0;
    var grossWin = wins.reduce(function (s, t) { return s + t.return_pct; }, 0);
    var grossLoss = losses.reduce(function (s, t) { return s + Math.abs(t.return_pct); }, 0);
    profitFactor = grossLoss > 0 ? round2(grossWin / grossLoss) : (grossWin > 0 ? 999 : 0);
    var avgHold = totalTrades > 0 ? round2(trades.reduce(function (s, t) { return s + t.hold_days; }, 0) / totalTrades) : 0;
    var maxDD = computeMaxDrawdown(trades);
    var slExits = trades.filter(function (t) { return t.exit_reason === "SL"; }).length;

    // ── Display Results ──
    displayKPIs(ticker, {
      trades: totalTrades, winRate: winRate, avgWin: avgWin, avgLoss: avgLoss,
      totalReturn: totalReturn, profitFactor: profitFactor, avgHold: avgHold,
      maxDD: maxDD, slExits: slExits, period: period
    });
    displayChart(ticker, ohlcv, markers);
    displayEquityCurve(trades, dates);
    displayTradeLog(trades);

    document.getElementById("placeholder").style.display = "none";
    updateStatus("ok", ticker + ": " + totalTrades + " trades, PF=" + profitFactor + ", WR=" + winRate + "%");
  }

  function computeMaxDrawdown(trades) {
    if (!trades.length) return 0;
    var equity = 100;
    var peak = 100;
    var maxDD = 0;
    for (var i = 0; i < trades.length; i++) {
      equity *= (1 + trades[i].return_pct / 100);
      if (equity > peak) peak = equity;
      var dd = (peak - equity) / peak * 100;
      if (dd > maxDD) maxDD = dd;
    }
    return round2(maxDD);
  }


  // ── Display Functions ──

  function displayKPIs(ticker, kpi) {
    document.getElementById("kpiCard").style.display = "block";
    document.getElementById("resultTicker").textContent = ticker + " (" + kpi.period.toUpperCase() + ")";

    var pfColor = kpi.profitFactor >= 1.2 ? "var(--bull)" : kpi.profitFactor < 0.9 ? "var(--bear)" : "var(--white)";
    var retColor = kpi.totalReturn > 0 ? "var(--bull)" : "var(--bear)";

    document.getElementById("kpiGrid").innerHTML =
      mkKPI(kpi.trades, "Trades", "var(--white)") +
      mkKPI(kpi.winRate + "%", "Win Rate", kpi.winRate >= 50 ? "var(--bull)" : "var(--bear)") +
      mkKPI(kpi.profitFactor, "Profit Factor", pfColor) +
      mkKPI((kpi.totalReturn > 0 ? "+" : "") + kpi.totalReturn + "%", "Total Return", retColor) +
      mkKPI("+" + kpi.avgWin + "%", "Avg Win", "var(--bull)") +
      mkKPI("-" + kpi.avgLoss + "%", "Avg Loss", "var(--bear)") +
      mkKPI(kpi.avgHold + "d", "Avg Hold", "var(--white)") +
      mkKPI(kpi.maxDD + "%", "Max DD", "var(--bear)") +
      mkKPI(kpi.slExits, "SL Exits", "var(--neut)");
  }

  function mkKPI(value, label, color) {
    return '<div class="kpi"><div class="kpi-v" style="color:' + (color || "var(--white)") + '">' + value + '</div><div class="kpi-l">' + label + '</div></div>';
  }

  function displayChart(ticker, ohlcv, markers) {
    document.getElementById("chartWrap").style.display = "block";
    var container = document.getElementById("btChart");
    container.innerHTML = "";

    if (mainChart) { try { mainChart.remove(); } catch (e) { } }

    mainChart = LightweightCharts.createChart(container, {
      width: container.clientWidth,
      height: 350,
      layout: { background: { type: "solid", color: "#151823" }, textColor: "#8b949e", fontSize: 10 },
      grid: { vertLines: { color: "#1a1d29" }, horzLines: { color: "#1a1d29" } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#2a2e3d" },
      timeScale: { borderColor: "#2a2e3d", timeVisible: false }
    });

    var cs = mainChart.addCandlestickSeries({
      upColor: "#22c55e", downColor: "#ef4444",
      borderUpColor: "#22c55e", borderDownColor: "#ef4444",
      wickUpColor: "#22c55e88", wickDownColor: "#ef444488"
    });

    var ohlcData = ohlcv.map(function (r) {
      return { time: r.d, open: r.o, high: r.h, low: r.l, close: r.c };
    });
    cs.setData(ohlcData);

    if (markers && markers.length) {
      markers.sort(function (a, b) { return a.time.localeCompare(b.time); });
      cs.setMarkers(markers);
    }

    mainChart.timeScale().fitContent();

    new ResizeObserver(function () {
      if (mainChart) mainChart.applyOptions({ width: container.clientWidth });
    }).observe(container);
  }

  function displayEquityCurve(trades, allDates) {
    if (!trades.length) {
      document.getElementById("equityWrap").style.display = "none";
      return;
    }

    document.getElementById("equityWrap").style.display = "block";
    var container = document.getElementById("eqChart");
    container.innerHTML = "";

    if (eqChart) { try { eqChart.remove(); } catch (e) { } }

    eqChart = LightweightCharts.createChart(container, {
      width: container.clientWidth,
      height: 180,
      layout: { background: { type: "solid", color: "#151823" }, textColor: "#8b949e", fontSize: 10 },
      grid: { vertLines: { color: "#1a1d29" }, horzLines: { color: "#1a1d29" } },
      rightPriceScale: { borderColor: "#2a2e3d" },
      timeScale: { borderColor: "#2a2e3d", visible: true }
    });

    var equity = 100;
    var eqData = [{ time: trades[0].entry_date, value: 100 }];

    for (var i = 0; i < trades.length; i++) {
      equity *= (1 + trades[i].return_pct / 100);
      eqData.push({ time: trades[i].exit_date, value: round2(equity) });
    }

    var color = equity >= 100 ? "#22c55e" : "#ef4444";
    var eqSeries = eqChart.addAreaSeries({
      lineColor: color, topColor: color + "40", bottomColor: color + "05",
      lineWidth: 2, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: true
    });
    eqSeries.setData(eqData);

    // Baseline at 100
    var baseSeries = eqChart.addLineSeries({
      color: "#8b949e44", lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false
    });
    baseSeries.setData([
      { time: eqData[0].time, value: 100 },
      { time: eqData[eqData.length - 1].time, value: 100 }
    ]);

    eqChart.timeScale().fitContent();

    new ResizeObserver(function () {
      if (eqChart) eqChart.applyOptions({ width: container.clientWidth });
    }).observe(container);
  }

  function displayTradeLog(trades) {
    document.getElementById("tradeCard").style.display = "block";
    document.getElementById("tradeCount").textContent = "(" + trades.length + " trades)";

    var tbody = document.getElementById("tradeBody");
    tbody.innerHTML = "";

    trades.forEach(function (t, idx) {
      var retColor = t.return_pct > 0 ? "var(--bull)" : "var(--bear)";
      var retStr = (t.return_pct > 0 ? "+" : "") + t.return_pct.toFixed(1) + "%";
      var icon = t.win ? "✅" : "❌";

      var tr = document.createElement("tr");
      tr.innerHTML =
        '<td style="color:var(--text2)">' + (idx + 1) + '</td>' +
        '<td>' + t.entry_date + ' <span style="color:var(--text2)">@' + t.entry_price + '</span></td>' +
        '<td>' + t.exit_date + ' <span style="color:var(--text2)">@' + t.exit_price + '</span></td>' +
        '<td>' + t.hold_days + 'd</td>' +
        '<td style="color:' + retColor + ';font-weight:600">' + icon + ' ' + retStr + '</td>' +
        '<td style="color:var(--text2)">' + t.exit_reason + '</td>';
      tbody.appendChild(tr);
    });
  }


  // ── Event Handlers ──

  document.getElementById("tickerSearch").addEventListener("change", function () {
    var val = this.value.toUpperCase().trim();
    if (val && TICKERS.indexOf(val) >= 0) {
      loadTickerData(val);
    }
  });

  document.getElementById("tickerSearch").addEventListener("input", function () {
    var val = this.value.toUpperCase().trim();
    if (val && TICKERS.indexOf(val) >= 0) {
      loadTickerData(val);
    }
  });

  document.getElementById("btnRun").addEventListener("click", function () {
    this.disabled = true;
    this.textContent = "⏳ Running...";
    setTimeout(function () {
      try {
        runBacktest();
      } catch (e) {
        updateStatus("err", "Backtest error: " + e.message);
        console.error(e);
      }
      document.getElementById("btnRun").disabled = false;
      document.getElementById("btnRun").textContent = "▶ Run Backtest";
    }, 50);
  });

  // Keyboard shortcut: Enter to run
  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !document.getElementById("btnRun").disabled) {
      document.getElementById("btnRun").click();
    }
  });


  // ── Init ──
  loadTickerList();

})();
