/**
 * backtest.js — xchart.in Backtest Engine V2
 * 20 indicators, 3 signal modes, per-indicator breakdown
 * All computation runs client-side on OHLCV JSON
 */

// ═══════════════════════════════════════════════════════════
// GLOBALS
// ═══════════════════════════════════════════════════════════
var BT = {
  tickers: [], tickerMap: {}, fundamentals: {},
  ohlcv: null, ticker: null,
  slots: [], mode: 'weighted', majorityN: 3,
  mainChart: null, eqChart: null,
  colors: ['#2563EB','#7C3AED','#059669','#D97706','#DC2626']
};

// ═══════════════════════════════════════════════════════════
// MATH HELPERS
// ═══════════════════════════════════════════════════════════
function sma(arr, period) {
  var r = new Array(arr.length).fill(NaN);
  for (var i = period - 1; i < arr.length; i++) {
    var s = 0;
    for (var j = i - period + 1; j <= i; j++) s += arr[j];
    r[i] = s / period;
  }
  return r;
}

function ema(arr, period) {
  var r = new Array(arr.length).fill(NaN);
  var k = 2 / (period + 1);
  var first = 0;
  for (var i = 0; i < period; i++) first += arr[i];
  r[period - 1] = first / period;
  for (var i = period; i < arr.length; i++) {
    r[i] = arr[i] * k + r[i - 1] * (1 - k);
  }
  return r;
}

function trueRange(high, low, close) {
  var tr = [high[0] - low[0]];
  for (var i = 1; i < high.length; i++) {
    tr.push(Math.max(high[i] - low[i], Math.abs(high[i] - close[i-1]), Math.abs(low[i] - close[i-1])));
  }
  return tr;
}

function atr(high, low, close, period) {
  var tr = trueRange(high, low, close);
  return sma(tr, period);
}

function stdDev(arr, period) {
  var m = sma(arr, period);
  var r = new Array(arr.length).fill(NaN);
  for (var i = period - 1; i < arr.length; i++) {
    var sum = 0;
    for (var j = i - period + 1; j <= i; j++) {
      sum += (arr[j] - m[i]) * (arr[j] - m[i]);
    }
    r[i] = Math.sqrt(sum / period);
  }
  return r;
}

function highest(arr, period) {
  var r = new Array(arr.length).fill(NaN);
  for (var i = period - 1; i < arr.length; i++) {
    var mx = -Infinity;
    for (var j = i - period + 1; j <= i; j++) mx = Math.max(mx, arr[j]);
    r[i] = mx;
  }
  return r;
}

function lowest(arr, period) {
  var r = new Array(arr.length).fill(NaN);
  for (var i = period - 1; i < arr.length; i++) {
    var mn = Infinity;
    for (var j = i - period + 1; j <= i; j++) mn = Math.min(mn, arr[j]);
    r[i] = mn;
  }
  return r;
}

function crossAbove(a, b, i) {
  return i > 0 && a[i] > b[i] && a[i-1] <= b[i-1];
}

function crossBelow(a, b, i) {
  return i > 0 && a[i] < b[i] && a[i-1] >= b[i-1];
}

function fillConst(len, val) {
  var r = [];
  for (var i = 0; i < len; i++) r.push(val);
  return r;
}

// ═══════════════════════════════════════════════════════════
// INDICATOR COMPUTATION FUNCTIONS
// ═══════════════════════════════════════════════════════════

function calcRSI(close, period) {
  var r = new Array(close.length).fill(NaN);
  var gains = [], losses = [];
  for (var i = 1; i < close.length; i++) {
    var d = close[i] - close[i-1];
    gains.push(d > 0 ? d : 0);
    losses.push(d < 0 ? -d : 0);
  }
  if (gains.length < period) return r;
  var avgG = 0, avgL = 0;
  for (var i = 0; i < period; i++) { avgG += gains[i]; avgL += losses[i]; }
  avgG /= period; avgL /= period;
  r[period] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
  for (var i = period; i < gains.length; i++) {
    avgG = (avgG * (period - 1) + gains[i]) / period;
    avgL = (avgL * (period - 1) + losses[i]) / period;
    r[i + 1] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
  }
  return r;
}

function calcStochRSI(close, rsiPeriod, stochPeriod, kSmooth, dSmooth) {
  var rsi = calcRSI(close, rsiPeriod);
  var rsiClean = rsi.map(function(v) { return isNaN(v) ? 0 : v; });
  var hi = highest(rsiClean, stochPeriod);
  var lo = lowest(rsiClean, stochPeriod);
  var stochRaw = rsiClean.map(function(v, i) {
    var range = hi[i] - lo[i];
    return range > 0 ? ((v - lo[i]) / range) * 100 : 50;
  });
  var k = sma(stochRaw, kSmooth);
  var d = sma(k.map(function(v) { return isNaN(v) ? 0 : v; }), dSmooth);
  return { k: k, d: d };
}

function calcMACD(close, fast, slow, signal) {
  var emaF = ema(close, fast);
  var emaS = ema(close, slow);
  var macdLine = emaF.map(function(v, i) { return v - emaS[i]; });
  var macdClean = macdLine.map(function(v) { return isNaN(v) ? 0 : v; });
  var signalLine = ema(macdClean, signal);
  var hist = macdClean.map(function(v, i) { return v - (isNaN(signalLine[i]) ? 0 : signalLine[i]); });
  return { line: macdLine, signal: signalLine, hist: hist };
}

function calcCCI(high, low, close, period) {
  var tp = close.map(function(v, i) { return (high[i] + low[i] + v) / 3; });
  var tpSMA = sma(tp, period);
  var r = new Array(close.length).fill(NaN);
  for (var i = period - 1; i < close.length; i++) {
    var md = 0;
    for (var j = i - period + 1; j <= i; j++) md += Math.abs(tp[j] - tpSMA[i]);
    md /= period;
    r[i] = md === 0 ? 0 : (tp[i] - tpSMA[i]) / (0.015 * md);
  }
  return r;
}

function calcWilliamsR(high, low, close, period) {
  var hh = highest(high, period);
  var ll = lowest(low, period);
  return close.map(function(v, i) {
    var range = hh[i] - ll[i];
    return range > 0 ? ((hh[i] - v) / range) * -100 : -50;
  });
}

function calcBB(close, period, upperSigma, lowerSigma) {
  var mid = sma(close, period);
  var sd = stdDev(close, period);
  return {
    upper: mid.map(function(v, i) { return v + upperSigma * (isNaN(sd[i]) ? 0 : sd[i]); }),
    mid: mid,
    lower: mid.map(function(v, i) { return v - lowerSigma * (isNaN(sd[i]) ? 0 : sd[i]); }),
    width: mid.map(function(v, i) { return v > 0 ? (4 * (isNaN(sd[i]) ? 0 : sd[i])) / v * 100 : 0; })
  };
}

function calcKeltner(close, high, low, emaPeriod, atrPeriod, mult) {
  var mid = ema(close, emaPeriod);
  var atrVal = atr(high, low, close, atrPeriod);
  return {
    upper: mid.map(function(v, i) { return v + mult * (isNaN(atrVal[i]) ? 0 : atrVal[i]); }),
    mid: mid,
    lower: mid.map(function(v, i) { return v - mult * (isNaN(atrVal[i]) ? 0 : atrVal[i]); })
  };
}

function calcSuperTrend(high, low, close, atrPeriod, mult) {
  var atrVal = atr(high, low, close, atrPeriod);
  var upperBand = [], lowerBand = [], st = [], dir = [];
  for (var i = 0; i < close.length; i++) {
    var hl2 = (high[i] + low[i]) / 2;
    var a = isNaN(atrVal[i]) ? 0 : atrVal[i];
    var ub = hl2 + mult * a;
    var lb = hl2 - mult * a;
    if (i > 0) {
      lb = Math.max(lb, lowerBand[i-1] || lb);
      ub = Math.min(ub, upperBand[i-1] || ub);
      if (close[i-1] <= (upperBand[i-1] || ub)) ub = Math.min(ub, upperBand[i-1] || ub);
      if (close[i-1] >= (lowerBand[i-1] || lb)) lb = Math.max(lb, lowerBand[i-1] || lb);
    }
    upperBand.push(ub);
    lowerBand.push(lb);
    if (i === 0) { dir.push(1); st.push(lb); }
    else if (dir[i-1] === 1 && close[i] < lowerBand[i]) { dir.push(-1); st.push(ub); }
    else if (dir[i-1] === -1 && close[i] > upperBand[i]) { dir.push(1); st.push(lb); }
    else { dir.push(dir[i-1]); st.push(dir[i-1] === 1 ? lb : ub); }
  }
  return { value: st, direction: dir };
}

function calcADX(high, low, close, period) {
  var pDI = new Array(close.length).fill(NaN);
  var nDI = new Array(close.length).fill(NaN);
  var adx = new Array(close.length).fill(NaN);
  if (close.length < period * 2) return { adx: adx, pDI: pDI, nDI: nDI };
  var tr = trueRange(high, low, close);
  var pDM = [0], nDM = [0];
  for (var i = 1; i < close.length; i++) {
    var upMove = high[i] - high[i-1];
    var downMove = low[i-1] - low[i];
    pDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
    nDM.push(downMove > upMove && downMove > 0 ? downMove : 0);
  }
  var smaTR = sma(tr, period);
  var smaPDM = sma(pDM, period);
  var smaNDM = sma(nDM, period);
  var dx = [];
  for (var i = 0; i < close.length; i++) {
    if (isNaN(smaTR[i]) || smaTR[i] === 0) { dx.push(NaN); continue; }
    var p = (smaPDM[i] / smaTR[i]) * 100;
    var n = (smaNDM[i] / smaTR[i]) * 100;
    pDI[i] = p; nDI[i] = n;
    var sum = p + n;
    dx.push(sum === 0 ? 0 : Math.abs(p - n) / sum * 100);
  }
  var dxClean = dx.map(function(v) { return isNaN(v) ? 0 : v; });
  adx = sma(dxClean, period);
  return { adx: adx, pDI: pDI, nDI: nDI };
}

function calcIchimoku(high, low, tenkan, kijun, senkou) {
  var tenkanSen = high.map(function(v, i) {
    if (i < tenkan - 1) return NaN;
    var h = -Infinity, l = Infinity;
    for (var j = i - tenkan + 1; j <= i; j++) { h = Math.max(h, high[j]); l = Math.min(l, low[j]); }
    return (h + l) / 2;
  });
  var kijunSen = high.map(function(v, i) {
    if (i < kijun - 1) return NaN;
    var h = -Infinity, l = Infinity;
    for (var j = i - kijun + 1; j <= i; j++) { h = Math.max(h, high[j]); l = Math.min(l, low[j]); }
    return (h + l) / 2;
  });
  var spanA = tenkanSen.map(function(v, i) { return isNaN(v) || isNaN(kijunSen[i]) ? NaN : (v + kijunSen[i]) / 2; });
  var spanB = high.map(function(v, i) {
    if (i < senkou - 1) return NaN;
    var h = -Infinity, l = Infinity;
    for (var j = i - senkou + 1; j <= i; j++) { h = Math.max(h, high[j]); l = Math.min(l, low[j]); }
    return (h + l) / 2;
  });
  return { tenkan: tenkanSen, kijun: kijunSen, spanA: spanA, spanB: spanB };
}

function calcVWAP(high, low, close, volume) {
  var tp = close.map(function(v, i) { return (high[i] + low[i] + v) / 3; });
  var cumTPV = 0, cumVol = 0;
  return tp.map(function(v, i) {
    cumTPV += v * volume[i];
    cumVol += volume[i];
    return cumVol > 0 ? cumTPV / cumVol : v;
  });
}

function calcOBV(close, volume) {
  var obv = [0];
  for (var i = 1; i < close.length; i++) {
    if (close[i] > close[i-1]) obv.push(obv[i-1] + volume[i]);
    else if (close[i] < close[i-1]) obv.push(obv[i-1] - volume[i]);
    else obv.push(obv[i-1]);
  }
  return obv;
}

function calcDonchian(high, low, period) {
  return {
    upper: highest(high, period),
    lower: lowest(low, period),
    mid: highest(high, period).map(function(v, i) { return (v + lowest(low, period)[i]) / 2; })
  };
}

function calcPivots(high, low, close) {
  // Standard pivot points from previous bar
  var pp = [], s1 = [], s2 = [], r1 = [], r2 = [];
  for (var i = 0; i < close.length; i++) {
    if (i === 0) { pp.push(NaN); s1.push(NaN); s2.push(NaN); r1.push(NaN); r2.push(NaN); continue; }
    var p = (high[i-1] + low[i-1] + close[i-1]) / 3;
    pp.push(p);
    r1.push(2 * p - low[i-1]);
    s1.push(2 * p - high[i-1]);
    r2.push(p + (high[i-1] - low[i-1]));
    s2.push(p - (high[i-1] - low[i-1]));
  }
  return { pp: pp, r1: r1, r2: r2, s1: s1, s2: s2 };
}

function calcATRBreakout(close, high, low, period, mult) {
  var atrVal = atr(high, low, close, period);
  var basis = sma(close, period);
  return {
    upper: basis.map(function(v, i) { return v + mult * (isNaN(atrVal[i]) ? 0 : atrVal[i]); }),
    lower: basis.map(function(v, i) { return v - mult * (isNaN(atrVal[i]) ? 0 : atrVal[i]); }),
    atr: atrVal
  };
}

// ═══════════════════════════════════════════════════════════
// INDICATOR REGISTRY — All 20 indicators
// ═══════════════════════════════════════════════════════════

var INDICATORS = {
  rsi: {
    id:'rsi', name:'RSI', cat:'Momentum',
    params: [
      {id:'period', label:'Period', def:14, min:2, max:50},
      {id:'oversold', label:'Oversold', def:30, min:10, max:45},
      {id:'overbought', label:'Overbought', def:70, min:55, max:90}
    ],
    entry: [
      {id:'cross_above_os', label:'RSI crosses ABOVE oversold (recovery)'},
      {id:'below_os', label:'RSI is BELOW oversold (deep oversold)'},
      {id:'cross_above_50', label:'RSI crosses ABOVE 50 (bullish)'}
    ],
    exit: [
      {id:'cross_above_ob', label:'RSI crosses ABOVE overbought'},
      {id:'below_50', label:'RSI drops BELOW 50'},
      {id:'below_os', label:'RSI drops BELOW oversold (stop)'}
    ]
  },
  stochRsi: {
    id:'stochRsi', name:'Stochastic RSI', cat:'Momentum',
    params: [
      {id:'rsiPeriod', label:'RSI Period', def:14, min:2, max:50},
      {id:'stochPeriod', label:'Stoch Period', def:14, min:2, max:50},
      {id:'kSmooth', label:'K Smooth', def:3, min:1, max:10},
      {id:'dSmooth', label:'D Smooth', def:3, min:1, max:10},
      {id:'oversold', label:'Oversold', def:20, min:5, max:40},
      {id:'overbought', label:'Overbought', def:80, min:60, max:95}
    ],
    entry: [
      {id:'k_cross_above_d', label:'K crosses ABOVE D (bullish cross)'},
      {id:'below_os', label:'K below oversold level'},
      {id:'cross_above_os', label:'K crosses ABOVE oversold'}
    ],
    exit: [
      {id:'k_cross_below_d', label:'K crosses BELOW D'},
      {id:'above_ob', label:'K above overbought level'},
      {id:'cross_below_ob', label:'K crosses BELOW overbought'}
    ]
  },
  macd: {
    id:'macd', name:'MACD', cat:'Momentum',
    params: [
      {id:'fast', label:'Fast', def:12, min:2, max:50},
      {id:'slow', label:'Slow', def:26, min:5, max:100},
      {id:'signal', label:'Signal', def:9, min:2, max:30}
    ],
    entry: [
      {id:'cross_above_signal', label:'MACD crosses ABOVE signal line'},
      {id:'hist_positive', label:'Histogram turns positive'},
      {id:'cross_above_zero', label:'MACD crosses ABOVE zero'}
    ],
    exit: [
      {id:'cross_below_signal', label:'MACD crosses BELOW signal line'},
      {id:'hist_negative', label:'Histogram turns negative'},
      {id:'cross_below_zero', label:'MACD crosses BELOW zero'}
    ]
  },
  cci: {
    id:'cci', name:'CCI', cat:'Momentum',
    params: [
      {id:'period', label:'Period', def:20, min:5, max:50},
      {id:'oversold', label:'Oversold', def:-100, min:-200, max:-50},
      {id:'overbought', label:'Overbought', def:100, min:50, max:200}
    ],
    entry: [
      {id:'cross_above_os', label:'CCI crosses ABOVE oversold'},
      {id:'below_os', label:'CCI below oversold'},
      {id:'cross_above_zero', label:'CCI crosses ABOVE zero'}
    ],
    exit: [
      {id:'cross_above_ob', label:'CCI crosses ABOVE overbought'},
      {id:'cross_below_zero', label:'CCI crosses BELOW zero'},
      {id:'cross_below_ob', label:'CCI crosses BELOW overbought'}
    ]
  },
  williamsR: {
    id:'williamsR', name:'Williams %R', cat:'Momentum',
    params: [
      {id:'period', label:'Period', def:14, min:2, max:50},
      {id:'oversold', label:'Oversold', def:-80, min:-95, max:-60},
      {id:'overbought', label:'Overbought', def:-20, min:-40, max:-5}
    ],
    entry: [
      {id:'cross_above_os', label:'%R crosses ABOVE oversold (recovery)'},
      {id:'below_os', label:'%R is BELOW oversold'}
    ],
    exit: [
      {id:'cross_above_ob', label:'%R crosses ABOVE overbought'},
      {id:'cross_below_ob', label:'%R crosses BELOW overbought'}
    ]
  },
  smaCross: {
    id:'smaCross', name:'SMA Crossover', cat:'Trend',
    params: [
      {id:'fast', label:'Fast SMA', def:9, min:2, max:100},
      {id:'slow', label:'Slow SMA', def:22, min:5, max:200}
    ],
    entry: [
      {id:'fast_cross_above_slow', label:'Fast SMA crosses ABOVE slow SMA'},
      {id:'price_above_both', label:'Price above both SMAs'}
    ],
    exit: [
      {id:'fast_cross_below_slow', label:'Fast SMA crosses BELOW slow SMA'},
      {id:'price_below_fast', label:'Price drops below fast SMA'}
    ]
  },
  emaCross: {
    id:'emaCross', name:'EMA Crossover', cat:'Trend',
    params: [
      {id:'fast', label:'Fast EMA', def:9, min:2, max:100},
      {id:'slow', label:'Slow EMA', def:21, min:5, max:200}
    ],
    entry: [
      {id:'fast_cross_above_slow', label:'Fast EMA crosses ABOVE slow EMA'},
      {id:'price_above_both', label:'Price above both EMAs'}
    ],
    exit: [
      {id:'fast_cross_below_slow', label:'Fast EMA crosses BELOW slow EMA'},
      {id:'price_below_fast', label:'Price drops below fast EMA'}
    ]
  },
  supertrend: {
    id:'supertrend', name:'SuperTrend', cat:'Trend',
    params: [
      {id:'atrPeriod', label:'ATR Period', def:10, min:5, max:30},
      {id:'multiplier', label:'Multiplier', def:3, min:1, max:6}
    ],
    entry: [
      {id:'turns_bullish', label:'SuperTrend turns bullish (price > ST)'},
      {id:'price_above', label:'Price is above SuperTrend'}
    ],
    exit: [
      {id:'turns_bearish', label:'SuperTrend turns bearish (price < ST)'},
      {id:'price_below', label:'Price is below SuperTrend'}
    ]
  },
  adx: {
    id:'adx', name:'ADX + DI', cat:'Trend',
    params: [
      {id:'period', label:'Period', def:14, min:5, max:30},
      {id:'threshold', label:'ADX Threshold', def:25, min:15, max:40}
    ],
    entry: [
      {id:'pdi_cross_above_ndi', label:'+DI crosses ABOVE -DI (with ADX > threshold)'},
      {id:'adx_rising', label:'ADX rising above threshold (trend strengthening)'}
    ],
    exit: [
      {id:'ndi_cross_above_pdi', label:'-DI crosses ABOVE +DI'},
      {id:'adx_below_threshold', label:'ADX drops below threshold (trend weakening)'}
    ]
  },
  ichimoku: {
    id:'ichimoku', name:'Ichimoku Cloud', cat:'Trend',
    params: [
      {id:'tenkan', label:'Tenkan', def:9, min:5, max:20},
      {id:'kijun', label:'Kijun', def:26, min:10, max:60},
      {id:'senkou', label:'Senkou B', def:52, min:20, max:120}
    ],
    entry: [
      {id:'tenkan_cross_above_kijun', label:'Tenkan crosses ABOVE Kijun (TK cross)'},
      {id:'price_above_cloud', label:'Price above cloud (bullish)'}
    ],
    exit: [
      {id:'tenkan_cross_below_kijun', label:'Tenkan crosses BELOW Kijun'},
      {id:'price_below_cloud', label:'Price below cloud'}
    ]
  },
  bb: {
    id:'bb', name:'Bollinger Bands', cat:'Volatility',
    params: [
      {id:'period', label:'SMA Period', def:20, min:5, max:50},
      {id:'upperSigma', label:'Upper σ', def:2, min:0.5, max:4},
      {id:'lowerSigma', label:'Lower σ', def:2, min:0.5, max:4}
    ],
    entry: [
      {id:'cross_below_lower', label:'Price crosses BELOW lower band (oversold)'},
      {id:'bounce_from_lower', label:'Price bounces FROM lower band (reversal)'},
      {id:'cross_above_upper', label:'Price crosses ABOVE upper band (breakout)'},
      {id:'between_mid_lower', label:'Price between mid and lower (weakness)'}
    ],
    exit: [
      {id:'cross_above_mid', label:'Price crosses ABOVE mid line (target)'},
      {id:'cross_above_upper', label:'Price crosses ABOVE upper band (overbought)'},
      {id:'cross_below_mid', label:'Price drops BELOW mid line'}
    ]
  },
  keltner: {
    id:'keltner', name:'Keltner Channel', cat:'Volatility',
    params: [
      {id:'emaPeriod', label:'EMA Period', def:20, min:5, max:50},
      {id:'atrPeriod', label:'ATR Period', def:10, min:5, max:30},
      {id:'multiplier', label:'Multiplier', def:2, min:1, max:4}
    ],
    entry: [
      {id:'cross_below_lower', label:'Price crosses BELOW lower channel'},
      {id:'bounce_from_lower', label:'Price bounces from lower channel'}
    ],
    exit: [
      {id:'cross_above_mid', label:'Price crosses ABOVE mid line'},
      {id:'cross_above_upper', label:'Price crosses ABOVE upper channel'}
    ]
  },
  atrBreakout: {
    id:'atrBreakout', name:'ATR Breakout', cat:'Volatility',
    params: [
      {id:'period', label:'Period', def:14, min:5, max:30},
      {id:'multiplier', label:'Multiplier', def:2, min:1, max:4}
    ],
    entry: [
      {id:'cross_above_upper', label:'Price breaks ABOVE upper band (expansion)'},
      {id:'cross_below_lower', label:'Price breaks BELOW lower band'}
    ],
    exit: [
      {id:'returns_to_basis', label:'Price returns to basis (SMA)'},
      {id:'opposite_break', label:'Price breaks opposite band'}
    ]
  },
  priceSMA: {
    id:'priceSMA', name:'Price vs SMA', cat:'Trend',
    params: [
      {id:'period', label:'SMA Period', def:200, min:5, max:500}
    ],
    entry: [
      {id:'cross_above', label:'Price crosses ABOVE SMA'},
      {id:'is_above', label:'Price is ABOVE SMA'}
    ],
    exit: [
      {id:'cross_below', label:'Price crosses BELOW SMA'},
      {id:'is_below', label:'Price is BELOW SMA'}
    ]
  },
  priceEMA: {
    id:'priceEMA', name:'Price vs EMA', cat:'Trend',
    params: [
      {id:'period', label:'EMA Period', def:50, min:5, max:500}
    ],
    entry: [
      {id:'cross_above', label:'Price crosses ABOVE EMA'},
      {id:'is_above', label:'Price is ABOVE EMA'}
    ],
    exit: [
      {id:'cross_below', label:'Price crosses BELOW EMA'},
      {id:'is_below', label:'Price is BELOW EMA'}
    ]
  },
  vwap: {
    id:'vwap', name:'VWAP', cat:'Volume',
    params: [],
    entry: [
      {id:'cross_above', label:'Price crosses ABOVE VWAP'},
      {id:'is_below', label:'Price is BELOW VWAP (value zone)'}
    ],
    exit: [
      {id:'cross_below', label:'Price crosses BELOW VWAP'},
      {id:'is_above', label:'Price is ABOVE VWAP'}
    ]
  },
  volumeSpike: {
    id:'volumeSpike', name:'Volume Spike', cat:'Volume',
    params: [
      {id:'lookback', label:'Lookback', def:20, min:5, max:50},
      {id:'threshold', label:'Multiplier', def:2, min:1.5, max:5}
    ],
    entry: [
      {id:'spike_with_up', label:'Volume spike + price up (accumulation)'},
      {id:'spike_any', label:'Volume spike (any direction)'}
    ],
    exit: [
      {id:'spike_with_down', label:'Volume spike + price down (distribution)'},
      {id:'volume_dries', label:'Volume drops below average'}
    ]
  },
  obv: {
    id:'obv', name:'OBV Trend', cat:'Volume',
    params: [
      {id:'lookback', label:'SMA Lookback', def:20, min:5, max:50}
    ],
    entry: [
      {id:'obv_above_sma', label:'OBV crosses ABOVE its SMA (accumulation)'},
      {id:'obv_rising', label:'OBV is rising'}
    ],
    exit: [
      {id:'obv_below_sma', label:'OBV crosses BELOW its SMA (distribution)'},
      {id:'obv_falling', label:'OBV is falling'}
    ]
  },
  pivots: {
    id:'pivots', name:'Pivot Points', cat:'Support/Resistance',
    params: [],
    entry: [
      {id:'bounce_s1', label:'Price bounces from S1 support'},
      {id:'break_above_pp', label:'Price breaks ABOVE pivot point'},
      {id:'near_s2', label:'Price near S2 (deep support)'}
    ],
    exit: [
      {id:'reaches_r1', label:'Price reaches R1 resistance'},
      {id:'break_below_pp', label:'Price breaks BELOW pivot point'},
      {id:'reaches_r2', label:'Price reaches R2'}
    ]
  },
  donchian: {
    id:'donchian', name:'Donchian Channel', cat:'Breakout',
    params: [
      {id:'period', label:'Period', def:20, min:5, max:100}
    ],
    entry: [
      {id:'break_above_upper', label:'Price breaks ABOVE upper channel (breakout)'},
      {id:'bounce_from_lower', label:'Price bounces from lower channel'}
    ],
    exit: [
      {id:'break_below_lower', label:'Price breaks BELOW lower channel'},
      {id:'returns_to_mid', label:'Price returns to mid line'}
    ]
  }
};

// ═══════════════════════════════════════════════════════════
// SIGNAL EVALUATION — Evaluates entry/exit conditions per bar
// ═══════════════════════════════════════════════════════════

function evalCondition(indId, condId, type, data, params, i) {
  // Returns true/false for whether condition fires at bar i
  if (i < 1) return false;
  var close = data.close, high = data.high, low = data.low, volume = data.volume;
  var n = close.length;

  // Helper: get computed indicator values from data.computed[indId]
  var comp = data.computed[indId];
  if (!comp) return false;

  switch (indId) {
    case 'rsi': {
      var rsi = comp.rsi;
      var os = params.oversold, ob = params.overbought;
      if (type === 'entry') {
        if (condId === 'cross_above_os') return i > 0 && rsi[i] > os && rsi[i-1] <= os;
        if (condId === 'below_os') return rsi[i] < os;
        if (condId === 'cross_above_50') return crossAbove(rsi, fillConst(n, 50), i);
      } else {
        if (condId === 'cross_above_ob') return i > 0 && rsi[i] > ob && rsi[i-1] <= ob;
        if (condId === 'below_50') return i > 0 && rsi[i] < 50 && rsi[i-1] >= 50;
        if (condId === 'below_os') return rsi[i] < os;
      }
      break;
    }
    case 'stochRsi': {
      var k = comp.k, d = comp.d;
      var os = params.oversold, ob = params.overbought;
      if (type === 'entry') {
        if (condId === 'k_cross_above_d') return crossAbove(k, d, i);
        if (condId === 'below_os') return k[i] < os;
        if (condId === 'cross_above_os') return i > 0 && k[i] > os && k[i-1] <= os;
      } else {
        if (condId === 'k_cross_below_d') return crossBelow(k, d, i);
        if (condId === 'above_ob') return k[i] > ob;
        if (condId === 'cross_below_ob') return i > 0 && k[i] < ob && k[i-1] >= ob;
      }
      break;
    }
    case 'macd': {
      var line = comp.line, sig = comp.signal, hist = comp.hist;
      if (type === 'entry') {
        if (condId === 'cross_above_signal') return crossAbove(line, sig, i);
        if (condId === 'hist_positive') return i > 0 && hist[i] > 0 && hist[i-1] <= 0;
        if (condId === 'cross_above_zero') return crossAbove(line, fillConst(n, 0), i);
      } else {
        if (condId === 'cross_below_signal') return crossBelow(line, sig, i);
        if (condId === 'hist_negative') return i > 0 && hist[i] < 0 && hist[i-1] >= 0;
        if (condId === 'cross_below_zero') return crossBelow(line, fillConst(n, 0), i);
      }
      break;
    }
    case 'cci': {
      var cci = comp.cci;
      var os = params.oversold, ob = params.overbought;
      if (type === 'entry') {
        if (condId === 'cross_above_os') return i > 0 && cci[i] > os && cci[i-1] <= os;
        if (condId === 'below_os') return cci[i] < os;
        if (condId === 'cross_above_zero') return crossAbove(cci, fillConst(n, 0), i);
      } else {
        if (condId === 'cross_above_ob') return i > 0 && cci[i] > ob && cci[i-1] <= ob;
        if (condId === 'cross_below_zero') return crossBelow(cci, fillConst(n, 0), i);
        if (condId === 'cross_below_ob') return i > 0 && cci[i] < ob && cci[i-1] >= ob;
      }
      break;
    }
    case 'williamsR': {
      var wr = comp.wr;
      var os = params.oversold, ob = params.overbought;
      if (type === 'entry') {
        if (condId === 'cross_above_os') return i > 0 && wr[i] > os && wr[i-1] <= os;
        if (condId === 'below_os') return wr[i] < os;
      } else {
        if (condId === 'cross_above_ob') return i > 0 && wr[i] > ob && wr[i-1] <= ob;
        if (condId === 'cross_below_ob') return i > 0 && wr[i] < ob && wr[i-1] >= ob;
      }
      break;
    }
    case 'smaCross': {
      var fast = comp.fast, slow = comp.slow;
      if (type === 'entry') {
        if (condId === 'fast_cross_above_slow') return crossAbove(fast, slow, i);
        if (condId === 'price_above_both') return close[i] > fast[i] && close[i] > slow[i];
      } else {
        if (condId === 'fast_cross_below_slow') return crossBelow(fast, slow, i);
        if (condId === 'price_below_fast') return close[i] < fast[i];
      }
      break;
    }
    case 'emaCross': {
      var fast = comp.fast, slow = comp.slow;
      if (type === 'entry') {
        if (condId === 'fast_cross_above_slow') return crossAbove(fast, slow, i);
        if (condId === 'price_above_both') return close[i] > fast[i] && close[i] > slow[i];
      } else {
        if (condId === 'fast_cross_below_slow') return crossBelow(fast, slow, i);
        if (condId === 'price_below_fast') return close[i] < fast[i];
      }
      break;
    }
    case 'supertrend': {
      var dir = comp.direction, val = comp.value;
      if (type === 'entry') {
        if (condId === 'turns_bullish') return i > 0 && dir[i] === 1 && dir[i-1] === -1;
        if (condId === 'price_above') return close[i] > val[i];
      } else {
        if (condId === 'turns_bearish') return i > 0 && dir[i] === -1 && dir[i-1] === 1;
        if (condId === 'price_below') return close[i] < val[i];
      }
      break;
    }
    case 'adx': {
      var adxVal = comp.adx, pDI = comp.pDI, nDI = comp.nDI;
      var thresh = params.threshold;
      if (type === 'entry') {
        if (condId === 'pdi_cross_above_ndi') return crossAbove(pDI, nDI, i) && adxVal[i] > thresh;
        if (condId === 'adx_rising') return i > 0 && adxVal[i] > thresh && adxVal[i] > adxVal[i-1];
      } else {
        if (condId === 'ndi_cross_above_pdi') return crossAbove(nDI, pDI, i);
        if (condId === 'adx_below_threshold') return adxVal[i] < thresh;
      }
      break;
    }
    case 'ichimoku': {
      var tenkan = comp.tenkan, kijun = comp.kijun, spanA = comp.spanA, spanB = comp.spanB;
      var cloudTop = spanA.map(function(v, j) { return Math.max(isNaN(v)?0:v, isNaN(spanB[j])?0:spanB[j]); });
      var cloudBot = spanA.map(function(v, j) { return Math.min(isNaN(v)?0:v, isNaN(spanB[j])?0:spanB[j]); });
      if (type === 'entry') {
        if (condId === 'tenkan_cross_above_kijun') return crossAbove(tenkan, kijun, i);
        if (condId === 'price_above_cloud') return close[i] > cloudTop[i];
      } else {
        if (condId === 'tenkan_cross_below_kijun') return crossBelow(tenkan, kijun, i);
        if (condId === 'price_below_cloud') return close[i] < cloudBot[i];
      }
      break;
    }
    case 'bb': {
      var upper = comp.upper, mid = comp.mid, lower = comp.lower;
      if (type === 'entry') {
        if (condId === 'cross_below_lower') return crossBelow(close, lower, i);
        if (condId === 'bounce_from_lower') return i > 0 && close[i-1] < lower[i-1] && close[i] > lower[i];
        if (condId === 'cross_above_upper') return crossAbove(close, upper, i);
        if (condId === 'between_mid_lower') return close[i] < mid[i] && close[i] > lower[i];
      } else {
        if (condId === 'cross_above_mid') return crossAbove(close, mid, i);
        if (condId === 'cross_above_upper') return crossAbove(close, upper, i);
        if (condId === 'cross_below_mid') return crossBelow(close, mid, i);
      }
      break;
    }
    case 'keltner': {
      var upper = comp.upper, mid = comp.mid, lower = comp.lower;
      if (type === 'entry') {
        if (condId === 'cross_below_lower') return crossBelow(close, lower, i);
        if (condId === 'bounce_from_lower') return i > 0 && close[i-1] < lower[i-1] && close[i] > lower[i];
      } else {
        if (condId === 'cross_above_mid') return crossAbove(close, mid, i);
        if (condId === 'cross_above_upper') return crossAbove(close, upper, i);
      }
      break;
    }
    case 'atrBreakout': {
      var upper = comp.upper, lower = comp.lower, basis = sma(close, params.period);
      if (type === 'entry') {
        if (condId === 'cross_above_upper') return crossAbove(close, upper, i);
        if (condId === 'cross_below_lower') return crossBelow(close, lower, i);
      } else {
        if (condId === 'returns_to_basis') return i > 0 && ((close[i-1] > basis[i-1] && close[i] <= basis[i]) || (close[i-1] < basis[i-1] && close[i] >= basis[i]));
        if (condId === 'opposite_break') return crossBelow(close, lower, i);
      }
      break;
    }
    case 'priceSMA': {
      var smaVal = comp.sma;
      if (type === 'entry') {
        if (condId === 'cross_above') return crossAbove(close, smaVal, i);
        if (condId === 'is_above') return close[i] > smaVal[i];
      } else {
        if (condId === 'cross_below') return crossBelow(close, smaVal, i);
        if (condId === 'is_below') return close[i] < smaVal[i];
      }
      break;
    }
    case 'priceEMA': {
      var emaVal = comp.ema;
      if (type === 'entry') {
        if (condId === 'cross_above') return crossAbove(close, emaVal, i);
        if (condId === 'is_above') return close[i] > emaVal[i];
      } else {
        if (condId === 'cross_below') return crossBelow(close, emaVal, i);
        if (condId === 'is_below') return close[i] < emaVal[i];
      }
      break;
    }
    case 'vwap': {
      var vwapVal = comp.vwap;
      if (type === 'entry') {
        if (condId === 'cross_above') return crossAbove(close, vwapVal, i);
        if (condId === 'is_below') return close[i] < vwapVal[i];
      } else {
        if (condId === 'cross_below') return crossBelow(close, vwapVal, i);
        if (condId === 'is_above') return close[i] > vwapVal[i];
      }
      break;
    }
    case 'volumeSpike': {
      var avgVol = comp.avgVol;
      var thresh = params.threshold;
      if (type === 'entry') {
        if (condId === 'spike_with_up') return volume[i] > avgVol[i] * thresh && close[i] > close[i-1];
        if (condId === 'spike_any') return volume[i] > avgVol[i] * thresh;
      } else {
        if (condId === 'spike_with_down') return volume[i] > avgVol[i] * thresh && close[i] < close[i-1];
        if (condId === 'volume_dries') return volume[i] < avgVol[i] * 0.5;
      }
      break;
    }
    case 'obv': {
      var obvVal = comp.obv, obvSMA = comp.obvSMA;
      if (type === 'entry') {
        if (condId === 'obv_above_sma') return crossAbove(obvVal, obvSMA, i);
        if (condId === 'obv_rising') return i > 0 && obvVal[i] > obvVal[i-1];
      } else {
        if (condId === 'obv_below_sma') return crossBelow(obvVal, obvSMA, i);
        if (condId === 'obv_falling') return i > 0 && obvVal[i] < obvVal[i-1];
      }
      break;
    }
    case 'pivots': {
      var pp = comp.pp, r1 = comp.r1, r2 = comp.r2, s1 = comp.s1, s2 = comp.s2;
      if (type === 'entry') {
        if (condId === 'bounce_s1') return i > 0 && close[i-1] <= s1[i] && close[i] > s1[i];
        if (condId === 'break_above_pp') return crossAbove(close, pp, i);
        if (condId === 'near_s2') return close[i] <= s2[i] * 1.005 && close[i] >= s2[i] * 0.995;
      } else {
        if (condId === 'reaches_r1') return close[i] >= r1[i];
        if (condId === 'break_below_pp') return crossBelow(close, pp, i);
        if (condId === 'reaches_r2') return close[i] >= r2[i];
      }
      break;
    }
    case 'donchian': {
      var upper = comp.upper, lower = comp.lower, mid = comp.mid;
      if (type === 'entry') {
        if (condId === 'break_above_upper') return crossAbove(close, upper, i);
        if (condId === 'bounce_from_lower') return i > 0 && close[i-1] <= lower[i-1] && close[i] > lower[i];
      } else {
        if (condId === 'break_below_lower') return crossBelow(close, lower, i);
        if (condId === 'returns_to_mid') return i > 0 && close[i-1] > mid[i-1] && close[i] <= mid[i];
      }
      break;
    }
  }
  return false;
}


// ═══════════════════════════════════════════════════════════
// COMPUTE ALL INDICATORS FOR OHLCV DATA
// ═══════════════════════════════════════════════════════════

function computeIndicators(data, slots) {
  var close = data.close, high = data.high, low = data.low, volume = data.volume;
  data.computed = {};

  slots.forEach(function(slot) {
    if (!slot.indId) return;
    var p = slot.params;

    switch (slot.indId) {
      case 'rsi':
        data.computed.rsi = { rsi: calcRSI(close, p.period) };
        break;
      case 'stochRsi':
        data.computed.stochRsi = calcStochRSI(close, p.rsiPeriod, p.stochPeriod, p.kSmooth, p.dSmooth);
        break;
      case 'macd':
        data.computed.macd = calcMACD(close, p.fast, p.slow, p.signal);
        break;
      case 'cci':
        data.computed.cci = { cci: calcCCI(high, low, close, p.period) };
        break;
      case 'williamsR':
        data.computed.williamsR = { wr: calcWilliamsR(high, low, close, p.period) };
        break;
      case 'smaCross':
        data.computed.smaCross = { fast: sma(close, p.fast), slow: sma(close, p.slow) };
        break;
      case 'emaCross':
        data.computed.emaCross = { fast: ema(close, p.fast), slow: ema(close, p.slow) };
        break;
      case 'supertrend':
        data.computed.supertrend = calcSuperTrend(high, low, close, p.atrPeriod, p.multiplier);
        break;
      case 'adx':
        data.computed.adx = calcADX(high, low, close, p.period);
        break;
      case 'ichimoku':
        data.computed.ichimoku = calcIchimoku(high, low, p.tenkan, p.kijun, p.senkou);
        break;
      case 'bb':
        data.computed.bb = calcBB(close, p.period, p.upperSigma, p.lowerSigma);
        break;
      case 'keltner':
        data.computed.keltner = calcKeltner(close, high, low, p.emaPeriod, p.atrPeriod, p.multiplier);
        break;
      case 'atrBreakout':
        data.computed.atrBreakout = calcATRBreakout(close, high, low, p.period, p.multiplier);
        break;
      case 'priceSMA':
        data.computed.priceSMA = { sma: sma(close, p.period) };
        break;
      case 'priceEMA':
        data.computed.priceEMA = { ema: ema(close, p.period) };
        break;
      case 'vwap':
        data.computed.vwap = { vwap: calcVWAP(high, low, close, volume) };
        break;
      case 'volumeSpike':
        data.computed.volumeSpike = { avgVol: sma(volume, p.lookback) };
        break;
      case 'obv': {
        var o = calcOBV(close, volume);
        data.computed.obv = { obv: o, obvSMA: sma(o, p.lookback) };
        break;
      }
      case 'pivots':
        data.computed.pivots = calcPivots(high, low, close);
        break;
      case 'donchian':
        data.computed.donchian = calcDonchian(high, low, p.period);
        break;
    }
  });
}


// ═══════════════════════════════════════════════════════════
// SIGNAL GENERATION — Per bar, per mode
// ═══════════════════════════════════════════════════════════

function generateSignals(data, slots, mode, majorityN, threshold) {
  var n = data.close.length;
  var signals = new Array(n).fill(0); // 1=entry, -1=exit, 0=none
  var perInd = {}; // per-indicator signals for breakdown

  slots.forEach(function(slot) {
    if (!slot.indId) return;
    perInd[slot.indId] = { entries: 0, exits: 0, entryBars: [], exitBars: [] };
  });

  for (var i = 1; i < n; i++) {
    var entrySignals = [];
    var exitSignals = [];
    var entryScoreSum = 0;
    var exitScoreSum = 0;
    var totalWeight = 0;

    for (var s = 0; s < slots.length; s++) {
      var slot = slots[s];
      if (!slot.indId) continue;
      var w = slot.weight / 100;
      totalWeight += w;

      var entryFired = evalCondition(slot.indId, slot.entryCond, 'entry', data, slot.params, i);
      var exitFired = evalCondition(slot.indId, slot.exitCond, 'exit', data, slot.params, i);

      entrySignals.push(entryFired);
      exitSignals.push(exitFired);

      if (entryFired) {
        entryScoreSum += 100 * w;
        perInd[slot.indId].entries++;
        perInd[slot.indId].entryBars.push(i);
      }
      if (exitFired) {
        exitScoreSum += 100 * w;
        perInd[slot.indId].exits++;
        perInd[slot.indId].exitBars.push(i);
      }
    }

    if (mode === 'weighted') {
      if (totalWeight > 0) {
        var netScore = (entryScoreSum - exitScoreSum) / totalWeight;
        if (netScore >= threshold) signals[i] = 1;
        else if (netScore <= -threshold) signals[i] = -1;
      }
    } else if (mode === 'and') {
      var allEntry = entrySignals.length > 0 && entrySignals.every(function(v) { return v; });
      var allExit = exitSignals.length > 0 && exitSignals.every(function(v) { return v; });
      if (allEntry) signals[i] = 1;
      else if (allExit) signals[i] = -1;
    } else if (mode === 'majority') {
      var entryCount = entrySignals.filter(function(v) { return v; }).length;
      var exitCount = exitSignals.filter(function(v) { return v; }).length;
      var required = Math.min(majorityN, slots.length);
      if (entryCount >= required) signals[i] = 1;
      else if (exitCount >= required) signals[i] = -1;
    }
  }

  return { signals: signals, perInd: perInd };
}


// ═══════════════════════════════════════════════════════════
// BACKTEST ENGINE — BUY-only simulation
// ═══════════════════════════════════════════════════════════

function runBacktest(data, signals, settings) {
  var close = data.close, dates = data.dates;
  var n = close.length;
  var trades = [];
  var equity = [100];
  var equityDates = [dates[0]];
  var inTrade = false;
  var entryPrice = 0, entryIdx = 0, peakPrice = 0;

  var slEnabled = settings.sl.enabled;
  var slPct = settings.sl.value / 100;
  var tpEnabled = settings.tp.enabled;
  var tpPct = settings.tp.value / 100;
  var trailEnabled = settings.trail.enabled;
  var trailPct = settings.trail.value / 100;
  var maxHoldEnabled = settings.maxHold.enabled;
  var maxHoldDays = settings.maxHold.value;

  for (var i = 1; i < n; i++) {
    if (inTrade) {
      peakPrice = Math.max(peakPrice, close[i]);
      var holdDays = i - entryIdx;
      var pctChange = (close[i] - entryPrice) / entryPrice;
      var exitType = null;

      // Check exit conditions
      if (slEnabled && pctChange <= -slPct) {
        exitType = 'Stop Loss';
      } else if (tpEnabled && pctChange >= tpPct) {
        exitType = 'Target';
      } else if (trailEnabled && peakPrice > 0) {
        var trailDrop = (peakPrice - close[i]) / peakPrice;
        if (trailDrop >= trailPct) exitType = 'Trailing SL';
      }
      if (maxHoldEnabled && holdDays >= maxHoldDays && !exitType) {
        exitType = 'Max Hold';
      }
      if (signals[i] === -1 && !exitType) {
        exitType = 'Signal Exit';
      }

      if (exitType) {
        var exitPrice = close[i];
        var result = (exitPrice - entryPrice) / entryPrice * 100;
        trades.push({
          entryDate: dates[entryIdx], entryPrice: entryPrice, entryIdx: entryIdx,
          exitDate: dates[i], exitPrice: exitPrice, exitIdx: i,
          days: holdDays, result: result, exitType: exitType
        });
        inTrade = false;
        var lastEq = equity[equity.length - 1];
        equity.push(lastEq * (1 + result / 100));
        equityDates.push(dates[i]);
      }
    } else {
      if (signals[i] === 1) {
        entryPrice = close[i];
        entryIdx = i;
        peakPrice = close[i];
        inTrade = true;
      }
    }
  }

  // Close open trade at last bar
  if (inTrade) {
    var exitPrice = close[n - 1];
    var result = (exitPrice - entryPrice) / entryPrice * 100;
    trades.push({
      entryDate: dates[entryIdx], entryPrice: entryPrice, entryIdx: entryIdx,
      exitDate: dates[n-1], exitPrice: exitPrice, exitIdx: n-1,
      days: n - 1 - entryIdx, result: result, exitType: 'Open'
    });
    var lastEq = equity[equity.length - 1];
    equity.push(lastEq * (1 + result / 100));
    equityDates.push(dates[n-1]);
  }

  return { trades: trades, equity: equity, equityDates: equityDates };
}


// ═══════════════════════════════════════════════════════════
// COMPUTE KPIs FROM TRADES
// ═══════════════════════════════════════════════════════════

function computeKPIs(trades) {
  if (!trades.length) return {
    totalTrades:0, wins:0, losses:0, winRate:0, avgWin:0, avgLoss:0,
    profitFactor:0, totalReturn:0, avgHold:0, maxDrawdown:0, slExits:0
  };

  var wins = trades.filter(function(t) { return t.result > 0; });
  var losses = trades.filter(function(t) { return t.result <= 0; });
  var grossWin = wins.reduce(function(s, t) { return s + t.result; }, 0);
  var grossLoss = Math.abs(losses.reduce(function(s, t) { return s + t.result; }, 0));
  var totalReturn = trades.reduce(function(s, t) { return s + t.result; }, 0);
  var avgHold = trades.reduce(function(s, t) { return s + t.days; }, 0) / trades.length;
  var slExits = trades.filter(function(t) { return t.exitType === 'Stop Loss'; }).length;

  // Max drawdown from equity curve
  var eq = 100;
  var peak = 100;
  var maxDD = 0;
  trades.forEach(function(t) {
    eq *= (1 + t.result / 100);
    peak = Math.max(peak, eq);
    var dd = (peak - eq) / peak * 100;
    maxDD = Math.max(maxDD, dd);
  });

  return {
    totalTrades: trades.length,
    wins: wins.length,
    losses: losses.length,
    winRate: (wins.length / trades.length * 100),
    avgWin: wins.length ? grossWin / wins.length : 0,
    avgLoss: losses.length ? grossLoss / losses.length : 0,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? 99.9 : 0),
    totalReturn: totalReturn,
    avgHold: avgHold,
    maxDrawdown: maxDD,
    slExits: slExits
  };
}


// ═══════════════════════════════════════════════════════════
// PER-INDICATOR CONTRIBUTION ANALYSIS
// ═══════════════════════════════════════════════════════════

function analyzeIndicatorContribution(perInd, trades, data) {
  var results = [];
  var indIds = Object.keys(perInd);

  indIds.forEach(function(indId) {
    var info = perInd[indId];
    var ind = INDICATORS[indId];
    if (!ind) return;

    // Count how many of this indicator's entry signals led to winning trades
    var hitCount = 0;
    var totalEntries = info.entryBars.length;

    info.entryBars.forEach(function(bar) {
      // Find trade that started at or near this bar
      var trade = trades.find(function(t) { return Math.abs(t.entryIdx - bar) <= 1; });
      if (trade && trade.result > 0) hitCount++;
    });

    var accuracy = totalEntries > 0 ? (hitCount / totalEntries * 100) : 0;
    var impact = totalEntries > 0 ? accuracy - 50 : 0; // impact vs random (50%)

    results.push({
      id: indId,
      name: ind.name,
      triggers: totalEntries,
      correct: hitCount,
      accuracy: accuracy,
      impact: impact
    });
  });

  results.sort(function(a, b) { return b.accuracy - a.accuracy; });
  return results;
}
// ═══════════════════════════════════════════════════════════
// UI — INDICATOR SLOTS
// ═══════════════════════════════════════════════════════════

function addIndicatorSlot() {
  if (BT.slots.length >= 5) return;
  var idx = BT.slots.length;
  BT.slots.push({ indId: null, params: {}, entryCond: null, exitCond: null, weight: Math.round(100 / (idx + 1)) });
  rebalanceWeights();
  renderSlots();
}

function removeIndicatorSlot(idx) {
  BT.slots.splice(idx, 1);
  rebalanceWeights();
  renderSlots();
  updateRunButton();
}

function rebalanceWeights() {
  var n = BT.slots.length;
  if (n === 0) return;
  var each = Math.floor(100 / n);
  var rem = 100 - each * n;
  BT.slots.forEach(function(s, i) { s.weight = each + (i < rem ? 1 : 0); });
}

function renderSlots() {
  var container = document.getElementById('indSlots');
  container.innerHTML = '';

  BT.slots.forEach(function(slot, idx) {
    var div = document.createElement('div');
    div.className = 'ind-slot' + (slot.indId ? ' active' : '');
    div.innerHTML = buildSlotHTML(slot, idx);
    container.appendChild(div);
  });

  document.getElementById('btnAddInd').disabled = BT.slots.length >= 5;
  document.getElementById('btnAddInd').textContent = BT.slots.length >= 5 ? 'Maximum 5 indicators' : '+ Add Indicator';
  document.getElementById('majorityTotal').textContent = BT.slots.length;
  updateWeightBar();
  updateRunButton();
}

function buildSlotHTML(slot, idx) {
  var indKeys = Object.keys(INDICATORS);
  var optionsHTML = '<option value="">— Select indicator —</option>';

  // Group by category
  var cats = {};
  indKeys.forEach(function(k) {
    var ind = INDICATORS[k];
    if (!cats[ind.cat]) cats[ind.cat] = [];
    cats[ind.cat].push(ind);
  });

  Object.keys(cats).forEach(function(cat) {
    optionsHTML += '<optgroup label="' + cat + '">';
    cats[cat].forEach(function(ind) {
      var sel = slot.indId === ind.id ? ' selected' : '';
      optionsHTML += '<option value="' + ind.id + '"' + sel + '>' + ind.name + '</option>';
    });
    optionsHTML += '</optgroup>';
  });

  var html = '<div class="ind-slot-hdr">';
  html += '<div class="ind-slot-num ' + (slot.indId ? '' : 'empty') + '">' + (idx + 1) + '</div>';
  html += '<select class="ind-select" onchange="onIndChange(' + idx + ',this.value)">' + optionsHTML + '</select>';
  html += '<button class="ind-remove" onclick="removeIndicatorSlot(' + idx + ')" title="Remove">✕</button>';
  html += '</div>';

  if (slot.indId) {
    var ind = INDICATORS[slot.indId];
    if (!ind) return html;

    // Parameters
    if (ind.params.length > 0) {
      html += '<div class="ind-config"><div class="ind-params">';
      ind.params.forEach(function(p) {
        var val = slot.params[p.id] !== undefined ? slot.params[p.id] : p.def;
        html += '<div class="ind-param"><label>' + p.label + '</label>';
        html += '<input type="number" value="' + val + '" min="' + p.min + '" max="' + p.max + '" ';
        html += 'step="' + (p.max <= 6 ? '0.5' : '1') + '" ';
        html += 'onchange="onParamChange(' + idx + ',\'' + p.id + '\',this.value)"></div>';
      });
      html += '</div>';
    } else {
      html += '<div class="ind-config">';
    }

    // Entry condition
    html += '<div class="ind-conditions">';
    html += '<div class="cond-row"><label>Entry</label><select onchange="onCondChange(' + idx + ',\'entry\',this.value)">';
    ind.entry.forEach(function(e, ei) {
      var sel = (slot.entryCond === e.id || (!slot.entryCond && ei === 0)) ? ' selected' : '';
      html += '<option value="' + e.id + '"' + sel + '>' + e.label + '</option>';
    });
    html += '</select></div>';

    // Exit condition
    html += '<div class="cond-row"><label>Exit</label><select onchange="onCondChange(' + idx + ',\'exit\',this.value)">';
    ind.exit.forEach(function(e, ei) {
      var sel = (slot.exitCond === e.id || (!slot.exitCond && ei === 0)) ? ' selected' : '';
      html += '<option value="' + e.id + '"' + sel + '>' + e.label + '</option>';
    });
    html += '</select></div></div>';

    // Weight slider
    html += '<div class="weight-wrap"><label>Weight</label>';
    html += '<input type="range" class="weight-slider" min="0" max="100" value="' + slot.weight + '" ';
    html += 'oninput="onWeightChange(' + idx + ',this.value)">';
    html += '<span class="weight-val">' + slot.weight + '%</span></div>';

    html += '</div>'; // close ind-config
  }

  return html;
}

function onIndChange(idx, indId) {
  var slot = BT.slots[idx];
  slot.indId = indId || null;
  slot.params = {};

  if (indId && INDICATORS[indId]) {
    var ind = INDICATORS[indId];
    ind.params.forEach(function(p) { slot.params[p.id] = p.def; });
    slot.entryCond = ind.entry[0].id;
    slot.exitCond = ind.exit[0].id;
  } else {
    slot.entryCond = null;
    slot.exitCond = null;
  }
  renderSlots();
}

function onParamChange(idx, paramId, val) {
  BT.slots[idx].params[paramId] = parseFloat(val) || 0;
}

function onCondChange(idx, type, condId) {
  if (type === 'entry') BT.slots[idx].entryCond = condId;
  else BT.slots[idx].exitCond = condId;
}

function onWeightChange(idx, val) {
  BT.slots[idx].weight = parseInt(val);
  // Update display
  var slotEls = document.querySelectorAll('.ind-slot');
  if (slotEls[idx]) {
    var wv = slotEls[idx].querySelector('.weight-val');
    if (wv) wv.textContent = val + '%';
  }
  updateWeightBar();
}

function updateWeightBar() {
  var bar = document.getElementById('weightBar');
  var totalEl = document.getElementById('weightTotal');
  var total = BT.slots.reduce(function(s, sl) { return s + (sl.indId ? sl.weight : 0); }, 0);
  var html = '';
  BT.slots.forEach(function(sl, i) {
    if (!sl.indId) return;
    html += '<div class="seg" style="width:' + sl.weight + '%;background:' + BT.colors[i % BT.colors.length] + '"></div>';
  });
  bar.innerHTML = html;
  totalEl.textContent = total + '%';
  totalEl.className = (total >= 95 && total <= 105) ? 'wt-ok' : 'wt-err';
}


// ═══════════════════════════════════════════════════════════
// UI — SIGNAL MODE
// ═══════════════════════════════════════════════════════════

function setMode(mode) {
  BT.mode = mode;
  document.querySelectorAll('.mode-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
  var desc = document.getElementById('modeDesc');
  var majCfg = document.getElementById('majorityConfig');

  if (mode === 'weighted') {
    desc.textContent = 'Each indicator scores ±100, weighted by priority. Entry when composite exceeds threshold.';
    majCfg.style.display = 'none';
  } else if (mode === 'and') {
    desc.textContent = 'ALL indicator entry conditions must fire simultaneously. Strictest mode — fewest signals.';
    majCfg.style.display = 'none';
  } else {
    desc.textContent = 'Entry when a minimum number of indicators agree. Balance between strict and flexible.';
    majCfg.style.display = 'flex';
  }
}


// ═══════════════════════════════════════════════════════════
// PRESETS
// ═══════════════════════════════════════════════════════════

var PRESETS = {
  meanReversion: {
    name: 'RSI Mean Reversion',
    mode: 'weighted',
    slots: [
      { indId:'rsi', params:{period:14,oversold:30,overbought:70}, entryCond:'cross_above_os', exitCond:'cross_above_ob', weight:40 },
      { indId:'bb', params:{period:20,upperSigma:2,lowerSigma:2}, entryCond:'bounce_from_lower', exitCond:'cross_above_mid', weight:35 },
      { indId:'volumeSpike', params:{lookback:20,threshold:2}, entryCond:'spike_with_up', exitCond:'volume_dries', weight:25 }
    ]
  },
  macdMomentum: {
    name: 'MACD Momentum',
    mode: 'weighted',
    slots: [
      { indId:'macd', params:{fast:12,slow:26,signal:9}, entryCond:'cross_above_signal', exitCond:'cross_below_signal', weight:40 },
      { indId:'adx', params:{period:14,threshold:25}, entryCond:'adx_rising', exitCond:'adx_below_threshold', weight:30 },
      { indId:'priceSMA', params:{period:200}, entryCond:'is_above', exitCond:'cross_below', weight:30 }
    ]
  },
  bbSqueeze: {
    name: 'BB Squeeze',
    mode: 'weighted',
    slots: [
      { indId:'bb', params:{period:20,upperSigma:2,lowerSigma:2}, entryCond:'cross_below_lower', exitCond:'cross_above_upper', weight:40 },
      { indId:'rsi', params:{period:14,oversold:30,overbought:70}, entryCond:'below_os', exitCond:'cross_above_ob', weight:35 },
      { indId:'obv', params:{lookback:20}, entryCond:'obv_above_sma', exitCond:'obv_below_sma', weight:25 }
    ]
  },
  trendFollowing: {
    name: 'Trend Following',
    mode: 'and',
    slots: [
      { indId:'smaCross', params:{fast:50,slow:200}, entryCond:'fast_cross_above_slow', exitCond:'fast_cross_below_slow', weight:35 },
      { indId:'supertrend', params:{atrPeriod:10,multiplier:3}, entryCond:'turns_bullish', exitCond:'turns_bearish', weight:35 },
      { indId:'adx', params:{period:14,threshold:20}, entryCond:'adx_rising', exitCond:'adx_below_threshold', weight:30 }
    ]
  },
  swingTrading: {
    name: 'Swing Trading',
    mode: 'majority',
    slots: [
      { indId:'rsi', params:{period:14,oversold:35,overbought:65}, entryCond:'cross_above_os', exitCond:'cross_above_ob', weight:25 },
      { indId:'bb', params:{period:20,upperSigma:2,lowerSigma:2}, entryCond:'bounce_from_lower', exitCond:'cross_above_mid', weight:25 },
      { indId:'macd', params:{fast:12,slow:26,signal:9}, entryCond:'cross_above_signal', exitCond:'cross_below_signal', weight:25 },
      { indId:'emaCross', params:{fast:9,slow:21}, entryCond:'fast_cross_above_slow', exitCond:'fast_cross_below_slow', weight:25 }
    ]
  }
};

function loadPreset(presetId) {
  var preset = PRESETS[presetId];
  if (!preset) return;

  BT.slots = preset.slots.map(function(s) {
    return { indId: s.indId, params: Object.assign({}, s.params), entryCond: s.entryCond, exitCond: s.exitCond, weight: s.weight };
  });
  setMode(preset.mode);
  if (preset.mode === 'majority') {
    document.getElementById('majorityN').value = 3;
    BT.majorityN = 3;
  }
  renderSlots();
}


// ═══════════════════════════════════════════════════════════
// DATA LOADING
// ═══════════════════════════════════════════════════════════

function loadTickerList() {
  Papa.parse('screener_data/nifty500_tickers.csv', {
    download: true, header: true,
    complete: function(r) {
      var rows = r.data.filter(function(r) { return r.Ticker && String(r.Ticker).trim(); });
      if (rows.length > 0) {
        populateTickers(rows);
        return;
      }
      // Fallback to output/tickers.csv
      Papa.parse('output/tickers.csv', {
        download: true, header: true,
        complete: function(r2) {
          var rows2 = r2.data.filter(function(r) { return r.Ticker && String(r.Ticker).trim(); });
          if (rows2.length > 0) {
            populateTickers(rows2);
          } else {
            setStatus('dot-err', 'No ticker data found');
          }
        },
        error: function() { setStatus('dot-err', 'Failed to load tickers'); }
      });
    },
    error: function() {
      // Try fallback
      Papa.parse('output/tickers.csv', {
        download: true, header: true,
        complete: function(r2) {
          var rows2 = r2.data.filter(function(r) { return r.Ticker && String(r.Ticker).trim(); });
          populateTickers(rows2);
        },
        error: function() { setStatus('dot-err', 'Failed to load tickers'); }
      });
    }
  });
}

function populateTickers(rows) {
  BT.tickers = [];
  var dl = document.getElementById('tickerList');
  dl.innerHTML = '';
  rows.forEach(function(r) {
    var tk = String(r.Ticker).trim().toUpperCase().replace('.NS', '');
    if (!tk) return;
    BT.tickers.push(tk);
    BT.tickerMap[tk] = { sector: r.Sector || '', name: r.Company || r.Name || tk };
    var opt = document.createElement('option');
    opt.value = tk;
    opt.textContent = tk + (r.Sector ? ' · ' + r.Sector : '');
    dl.appendChild(opt);
  });
  document.getElementById('hsTickers').textContent = BT.tickers.length;
  setStatus('dot-ok', BT.tickers.length + ' stocks loaded. Search to begin.');
}

function setStatus(dotClass, text) {
  var el = document.getElementById('dataStatus');
  el.innerHTML = '<span class="dot ' + dotClass + '"></span> ' + text;
}

function loadOHLCV(ticker) {
  setStatus('dot-load', 'Loading ' + ticker + ' data...');

  var paths = [
    'screener_data/backtest_data/' + ticker + '.json',
    'charts/' + ticker + '.json',
    'output/charts/' + ticker + '.json'
  ];

  function tryPath(idx) {
    if (idx >= paths.length) {
      setStatus('dot-load', 'Loading ' + ticker + ' from CSV...');
      loadFromCSV(ticker);
      return;
    }
    fetch(paths[idx])
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(chartData) {
        // Support both formats: ohlcv (screener) and ohlc (engine)
        var rows = chartData.ohlcv || chartData.ohlc || [];
        if (rows.length > 20) {
          parseChartJSON(ticker, chartData);
        } else {
          throw new Error('insufficient data: ' + rows.length);
        }
      })
      .catch(function() { tryPath(idx + 1); });
  }
  tryPath(0);
}
function parseChartJSON(ticker, chartData) {
  // Support both formats
  var raw = chartData.ohlcv || chartData.ohlc || [];
  
  // Detect format: short keys (d,o,h,l,c,v) vs long keys (time,open,high,low,close)
  var isShort = raw.length > 0 && raw[0].d !== undefined;
  
  // Normalize to standard format
  var ohlc = raw.map(function(r) {
    if (isShort) {
      return { time: r.d, open: r.o, high: r.h, low: r.l, close: r.c, volume: r.v || 0 };
    } else {
      return { time: r.time, open: r.open, high: r.high, low: r.low, close: r.close, volume: r.volume || 0 };
    }
  });

  // Apply period filter
  var period = document.getElementById('period').value;
  var lastDate = ohlc[ohlc.length - 1].time;
  var cutoff = getPeriodCutoff(period, lastDate);
  var filtered = ohlc.filter(function(d) { return d.time >= cutoff; });

  // If filter removes too much, use all data
  if (filtered.length < 20) {
    filtered = ohlc;
  }

  // Build volume map from separate array if exists (engine format)
  var volMap = {};
  if (chartData.volume && !isShort) {
    chartData.volume.forEach(function(v) { volMap[v.time] = v.value; });
  }

  BT.ohlcv = {
    dates: filtered.map(function(d) { return d.time; }),
    open: filtered.map(function(d) { return d.open || 0; }),
    high: filtered.map(function(d) { return d.high || 0; }),
    low: filtered.map(function(d) { return d.low || 0; }),
    close: filtered.map(function(d) { return d.close || 0; }),
    volume: filtered.map(function(d) {
      // Short format has volume inline, long format may have separate array
      return d.volume || volMap[d.time] || 0;
    }),
    computed: {}
  };
  BT.ticker = ticker;

  var info = BT.tickerMap[ticker] || {};
  document.getElementById('tkName').textContent = ticker;
  document.getElementById('tkSector').textContent = info.sector || 'Unknown';
  document.getElementById('tickerInfo').style.display = 'block';

  var msg = ticker + ': ' + BT.ohlcv.dates.length + ' trading days';
  if (BT.ohlcv.dates.length > 0) {
    msg += ' (' + BT.ohlcv.dates[0] + ' to ' + BT.ohlcv.dates[BT.ohlcv.dates.length - 1] + ')';
  }
  setStatus('dot-ok', msg);
  updateRunButton();
}

function loadFromCSV(ticker) {
  Papa.parse('output/stock_data.csv', {
    download: true, header: true,
    complete: function(r) {
      var rows = r.data.filter(function(d) {
        return String(d.Ticker).trim().toUpperCase() === ticker;
      }).sort(function(a, b) { return (a.Date || '').localeCompare(b.Date || ''); });

      if (rows.length < 30) {
        setStatus('dot-err', 'Not enough data for ' + ticker + ' (' + rows.length + ' rows)');
        return;
      }

      var period = document.getElementById('period').value;
      var cutoff = getPeriodCutoff(period, rows[rows.length - 1].Date);
      rows = rows.filter(function(d) { return (d.Date || '') >= cutoff; });

      BT.ohlcv = {
        dates: rows.map(function(d) { return String(d.Date).substring(0, 10); }),
        open: rows.map(function(d) { return parseFloat(d.Open) || 0; }),
        high: rows.map(function(d) { return parseFloat(d.High) || 0; }),
        low: rows.map(function(d) { return parseFloat(d.Low) || 0; }),
        close: rows.map(function(d) { return parseFloat(d.Close) || 0; }),
        volume: rows.map(function(d) { return parseFloat(d.Volume) || 0; }),
        computed: {}
      };
      BT.ticker = ticker;

      var info = BT.tickerMap[ticker] || {};
      document.getElementById('tkName').textContent = ticker;
      document.getElementById('tkSector').textContent = info.sector || 'Unknown';
      document.getElementById('tickerInfo').style.display = 'block';
      setStatus('dot-ok', ticker + ': ' + BT.ohlcv.dates.length + ' trading days loaded');
      updateRunButton();
    },
    error: function() { setStatus('dot-err', 'Failed to load stock data'); }
  });
}

function getPeriodCutoff(period, lastDate) {
  var d = new Date(lastDate);
  if (period === '6m') d.setMonth(d.getMonth() - 6);
  else if (period === '1y') d.setFullYear(d.getFullYear() - 1);
  else if (period === '2y') d.setFullYear(d.getFullYear() - 2);
  else if (period === '3y') d.setFullYear(d.getFullYear() - 3);
  return d.toISOString().substring(0, 10);
}


// ═══════════════════════════════════════════════════════════
// RUN BUTTON + ORCHESTRATION
// ═══════════════════════════════════════════════════════════

function updateRunButton() {
  var btn = document.getElementById('btnRun');
  var activeSlots = BT.slots.filter(function(s) { return s.indId; });

  if (!BT.ticker || !BT.ohlcv) {
    btn.disabled = true;
    btn.className = 'btn-run';
    btn.textContent = '▶  Select a stock first';
  } else if (activeSlots.length === 0) {
    btn.disabled = true;
    btn.className = 'btn-run';
    btn.textContent = '▶  Add at least one indicator';
  } else {
    btn.disabled = false;
    btn.className = 'btn-run ready';
    btn.textContent = '▶  Run Backtest on ' + BT.ticker;
  }
}

function runFullBacktest() {
  if (!BT.ohlcv || !BT.ticker) return;
  var activeSlots = BT.slots.filter(function(s) { return s.indId; });
  if (activeSlots.length === 0) return;

  var btn = document.getElementById('btnRun');
  btn.disabled = true;
  btn.textContent = '⏳ Running...';

  // Small delay for UI update
  setTimeout(function() {
    try {
      // 1. Compute indicators
      computeIndicators(BT.ohlcv, activeSlots);

      // 2. Generate signals
      var threshold = parseInt(document.getElementById('entryThreshold').value) || 20;
      BT.majorityN = parseInt(document.getElementById('majorityN').value) || 3;
      var sigResult = generateSignals(BT.ohlcv, activeSlots, BT.mode, BT.majorityN, threshold);

      // 3. Get exit settings
      var settings = {
        sl: { enabled: document.getElementById('x_sl').checked, value: parseFloat(document.getElementById('x_sl_val').value) || 3 },
        tp: { enabled: document.getElementById('x_tp').checked, value: parseFloat(document.getElementById('x_tp_val').value) || 8 },
        trail: { enabled: document.getElementById('x_trail').checked, value: parseFloat(document.getElementById('x_trail_val').value) || 2 },
        maxHold: { enabled: document.getElementById('x_maxhold').checked, value: parseInt(document.getElementById('x_maxhold_val').value) || 14 }
      };

      // 4. Run backtest
      var btResult = runBacktest(BT.ohlcv, sigResult.signals, settings);

      // 5. Compute KPIs
      var kpis = computeKPIs(btResult.trades);

      // 6. Per-indicator analysis
      var indContrib = analyzeIndicatorContribution(sigResult.perInd, btResult.trades, BT.ohlcv);

      // 7. Render everything
      renderResults(kpis, btResult, sigResult, indContrib);

    } catch (e) {
      console.error('Backtest error:', e);
      setStatus('dot-err', 'Error: ' + e.message);
    }

    btn.disabled = false;
    btn.className = 'btn-run ready';
    btn.textContent = '▶  Run Backtest on ' + BT.ticker;
  }, 50);
}


// ═══════════════════════════════════════════════════════════
// RENDER RESULTS
// ═══════════════════════════════════════════════════════════

function renderResults(kpis, btResult, sigResult, indContrib) {
  // Hide placeholder
  document.getElementById('placeholder').style.display = 'none';

  // Show result sections
  ['kpiCard', 'chartWrap', 'equityWrap', 'indBreakdownCard', 'profileCard', 'premiumCard', 'tradeCard'].forEach(function(id) {
    document.getElementById(id).style.display = '';
  });

  document.getElementById('resultTicker').textContent = BT.ticker;

  // KPIs
  var kpiGrid = document.getElementById('kpiGrid');
  var pfColor = kpis.profitFactor >= 1.1 ? 'var(--bull)' : kpis.profitFactor < 0.9 ? 'var(--bear)' : 'var(--text)';
  var retColor = kpis.totalReturn >= 0 ? 'var(--bull)' : 'var(--bear)';
  var wrColor = kpis.winRate >= 50 ? 'var(--bull)' : 'var(--bear)';

  kpiGrid.innerHTML =
    kpiHTML(kpis.totalTrades, 'Trades', '') +
    kpiHTML(kpis.winRate.toFixed(1) + '%', 'Win Rate', wrColor) +
    kpiHTML(kpis.profitFactor.toFixed(2), 'Profit Factor', pfColor) +
    kpiHTML((kpis.totalReturn >= 0 ? '+' : '') + kpis.totalReturn.toFixed(1) + '%', 'Total Return', retColor) +
    kpiHTML('+' + kpis.avgWin.toFixed(1) + '%', 'Avg Win', 'var(--bull)') +
    kpiHTML('-' + kpis.avgLoss.toFixed(1) + '%', 'Avg Loss', 'var(--bear)') +
    kpiHTML(kpis.avgHold.toFixed(0) + 'd', 'Avg Hold', '') +
    kpiHTML(kpis.maxDrawdown.toFixed(1) + '%', 'Max Drawdown', 'var(--bear)') +
    kpiHTML(kpis.slExits, 'SL Exits', '') +
    kpiHTML(BT.mode.toUpperCase(), 'Signal Mode', 'var(--accent)');

  // Price chart with markers
  renderPriceChart(btResult);

  // Equity curve
  renderEquityCurve(btResult);

  // Per-indicator breakdown
  renderIndBreakdown(indContrib);

  // Stock profile
  renderStockProfile();

  // Trade table
  renderTradeTable(btResult.trades);
  addDownloadButton(kpis, btResult, sigResult, indContrib);
  // Scroll to results
  document.getElementById('kpiCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function kpiHTML(value, label, color) {
  var style = color ? ' style="color:' + color + '"' : '';
  return '<div class="kpi"><div class="kpi-v"' + style + '>' + value + '</div><div class="kpi-l">' + label + '</div></div>';
}


// ═══════════════════════════════════════════════════════════
// CHARTS
// ═══════════════════════════════════════════════════════════

function renderPriceChart(btResult) {
  var container = document.getElementById('btChart');
  container.innerHTML = '';
  if (BT.mainChart) { try { BT.mainChart.remove(); } catch(e) {} }

  BT.mainChart = LightweightCharts.createChart(container, {
    width: container.clientWidth, height: 380,
    layout: { background: { type: 'solid', color: '#FFFFFF' }, textColor: '#6B7280', fontSize: 11 },
    grid: { vertLines: { color: '#F3F4F6' }, horzLines: { color: '#F3F4F6' } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#E5E7EB' },
    timeScale: { borderColor: '#E5E7EB', timeVisible: false }
  });

  var cs = BT.mainChart.addCandlestickSeries({
    upColor: '#16A34A', downColor: '#DC2626',
    borderUpColor: '#16A34A', borderDownColor: '#DC2626',
    wickUpColor: '#16A34A88', wickDownColor: '#DC262688'
  });

  var ohlcData = BT.ohlcv.dates.map(function(d, i) {
    return { time: d, open: BT.ohlcv.open[i], high: BT.ohlcv.high[i], low: BT.ohlcv.low[i], close: BT.ohlcv.close[i] };
  });
  cs.setData(ohlcData);

  // Volume
  if (BT.ohlcv.volume.some(function(v) { return v > 0; })) {
    var vs = BT.mainChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol' });
    BT.mainChart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    vs.setData(BT.ohlcv.dates.map(function(d, i) {
      return { time: d, value: BT.ohlcv.volume[i], color: BT.ohlcv.close[i] >= BT.ohlcv.open[i] ? '#16A34A44' : '#DC262644' };
    }));
  }

  // Trade markers
  var markers = [];
  btResult.trades.forEach(function(t) {
    markers.push({
      time: t.entryDate, position: 'belowBar', color: '#2563EB',
      shape: 'arrowUp', text: 'BUY ' + t.entryPrice.toFixed(0)
    });
    markers.push({
      time: t.exitDate, position: 'aboveBar',
      color: t.result >= 0 ? '#16A34A' : '#DC2626',
      shape: 'arrowDown',
      text: (t.result >= 0 ? '+' : '') + t.result.toFixed(1) + '%'
    });
  });
  markers.sort(function(a, b) { return a.time.localeCompare(b.time); });
  if (markers.length) cs.setMarkers(markers);

  BT.mainChart.timeScale().fitContent();
  new ResizeObserver(function() { if (BT.mainChart) BT.mainChart.applyOptions({ width: container.clientWidth }); }).observe(container);
}

function renderEquityCurve(btResult) {
  var container = document.getElementById('eqChart');
  container.innerHTML = '';
  if (BT.eqChart) { try { BT.eqChart.remove(); } catch(e) {} }

  if (btResult.equity.length < 2) {
    container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3)">No trades to plot</div>';
    return;
  }

  BT.eqChart = LightweightCharts.createChart(container, {
    width: container.clientWidth, height: 180,
    layout: { background: { type: 'solid', color: '#FFFFFF' }, textColor: '#6B7280', fontSize: 10 },
    grid: { vertLines: { color: '#F3F4F6' }, horzLines: { color: '#F3F4F6' } },
    rightPriceScale: { borderColor: '#E5E7EB' },
    timeScale: { borderColor: '#E5E7EB', visible: true }
  });

  var lastEq = btResult.equity[btResult.equity.length - 1];
  var lineColor = lastEq >= 100 ? '#16A34A' : '#DC2626';

  var areaSeries = BT.eqChart.addAreaSeries({
    lineColor: lineColor, lineWidth: 2,
    topColor: lineColor + '33', bottomColor: lineColor + '05',
    priceLineVisible: false, lastValueVisible: true
  });

  var eqData = btResult.equityDates.map(function(d, i) {
    return { time: d, value: btResult.equity[i] };
  });
  areaSeries.setData(eqData);

  // Baseline at 100
  BT.eqChart.addLineSeries({
    color: '#9CA3AF', lineWidth: 1, lineStyle: 2,
    priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false
  }).setData([
    { time: btResult.equityDates[0], value: 100 },
    { time: btResult.equityDates[btResult.equityDates.length - 1], value: 100 }
  ]);

  BT.eqChart.timeScale().fitContent();
  new ResizeObserver(function() { if (BT.eqChart) BT.eqChart.applyOptions({ width: container.clientWidth }); }).observe(container);
}


// ═══════════════════════════════════════════════════════════
// PER-INDICATOR BREAKDOWN
// ═══════════════════════════════════════════════════════════

function renderIndBreakdown(contribs) {
  var el = document.getElementById('indBreakdown');
  if (!contribs.length) { el.innerHTML = '<div style="color:var(--text3);font-size:12px;padding:8px">No indicator data</div>'; return; }

  var html = '';
  contribs.forEach(function(c) {
    var color = c.accuracy >= 55 ? 'var(--bull)' : c.accuracy < 45 ? 'var(--bear)' : 'var(--neut)';
    var barWidth = Math.min(c.accuracy, 100);
    html += '<div class="ind-breakdown-row">';
    html += '<div class="ind-breakdown-name">' + c.name + '</div>';
    html += '<div style="min-width:50px;font-size:11px;color:var(--text2)">' + c.triggers + ' triggers</div>';
    html += '<div class="ind-breakdown-bar"><div class="ind-breakdown-fill" style="width:' + barWidth + '%;background:' + color + '"></div></div>';
    html += '<div class="ind-breakdown-val" style="color:' + color + '">' + c.accuracy.toFixed(0) + '%</div>';
    html += '</div>';
  });
  el.innerHTML = html;
}


// ═══════════════════════════════════════════════════════════
// STOCK PROFILE
// ═══════════════════════════════════════════════════════════

function renderStockProfile() {
  var el = document.getElementById('stockProfile');
  if (!BT.ohlcv || !BT.ohlcv.close.length) { el.innerHTML = ''; return; }

  var close = BT.ohlcv.close;
  var high = BT.ohlcv.high;
  var low = BT.ohlcv.low;
  var n = close.length;
  var last = close[n - 1];
  var hi52 = Math.max.apply(null, high);
  var lo52 = Math.min.apply(null, low);
  var avgVol = BT.ohlcv.volume.reduce(function(s, v) { return s + v; }, 0) / n;
  var ret1m = n > 22 ? ((last - close[n - 22]) / close[n - 22] * 100) : 0;
  var ret3m = n > 66 ? ((last - close[n - 66]) / close[n - 66] * 100) : 0;
  var retTotal = ((last - close[0]) / close[0] * 100);

  var info = BT.tickerMap[BT.ticker] || {};

  el.innerHTML =
    spItem('₹' + last.toFixed(0), 'Last Close') +
    spItem('₹' + hi52.toFixed(0), '52W High') +
    spItem('₹' + lo52.toFixed(0), '52W Low') +
    spItem(formatVol(avgVol), 'Avg Volume') +
    spItem((ret1m >= 0 ? '+' : '') + ret1m.toFixed(1) + '%', '1M Return', ret1m >= 0 ? 'var(--bull)' : 'var(--bear)') +
    spItem((ret3m >= 0 ? '+' : '') + ret3m.toFixed(1) + '%', '3M Return', ret3m >= 0 ? 'var(--bull)' : 'var(--bear)') +
    spItem((retTotal >= 0 ? '+' : '') + retTotal.toFixed(1) + '%', 'Period Return', retTotal >= 0 ? 'var(--bull)' : 'var(--bear)') +
    spItem(info.sector || '—', 'Sector');
}

function spItem(val, label, color) {
  var style = color ? ' style="color:' + color + '"' : '';
  return '<div class="sp-item"><div class="sp-v"' + style + '>' + val + '</div><div class="sp-l">' + label + '</div></div>';
}

function formatVol(v) {
  if (v >= 1e7) return (v / 1e7).toFixed(1) + 'Cr';
  if (v >= 1e5) return (v / 1e5).toFixed(1) + 'L';
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return v.toFixed(0);
}


// ═══════════════════════════════════════════════════════════
// TRADE TABLE
// ═══════════════════════════════════════════════════════════

function renderTradeTable(trades) {
  var countEl = document.getElementById('tradeCount');
  countEl.textContent = '(' + trades.length + ' trades)';
  var tbody = document.getElementById('tradeBody');
  tbody.innerHTML = '';

  trades.forEach(function(t, i) {
    var cls = t.result >= 0 ? 'win' : 'loss';
    var resText = (t.result >= 0 ? '+' : '') + t.result.toFixed(2) + '%';
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td>' + (i + 1) + '</td>' +
      '<td>' + t.entryDate + '</td>' +
      '<td>₹' + t.entryPrice.toFixed(2) + '</td>' +
      '<td>' + t.exitDate + '</td>' +
      '<td>₹' + t.exitPrice.toFixed(2) + '</td>' +
      '<td>' + t.days + 'd</td>' +
      '<td class="' + cls + '">' + resText + '</td>' +
      '<td>' + t.exitType + '</td>';
    tbody.appendChild(tr);
  });
}


// ═══════════════════════════════════════════════════════════
// EVENT LISTENERS + INIT
// ═══════════════════════════════════════════════════════════

// Ticker search
document.getElementById('tickerSearch').addEventListener('input', function(e) {
  var val = this.value.trim().toUpperCase();
  if (BT.tickers.indexOf(val) >= 0) {
    loadOHLCV(val);
  }
});

document.getElementById('tickerSearch').addEventListener('change', function(e) {
  var val = this.value.trim().toUpperCase();
  if (BT.tickers.indexOf(val) >= 0) {
    loadOHLCV(val);
  }
});

// Run button
document.getElementById('btnRun').addEventListener('click', runFullBacktest);

// Majority N
document.getElementById('majorityN').addEventListener('change', function() {
  BT.majorityN = parseInt(this.value) || 3;
});

// Keyboard shortcut: Enter to run
document.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !document.getElementById('btnRun').disabled) {
    if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'SELECT') {
      runFullBacktest();
    }
  }
});
// ═══════════════════════════════════════════════════════════
// BACKTEST REPORT — Single HTML download
// ═══════════════════════════════════════════════════════════

function addDownloadButton(kpis, btResult, sigResult, indContrib) {
  var existing = document.getElementById('downloadWrap');
  if (existing) existing.remove();

  var wrap = document.createElement('div');
  wrap.id = 'downloadWrap';
  wrap.style.cssText = 'display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;align-items:center';

  var btn = document.createElement('button');
  btn.textContent = '📄 Download Backtest Report';
  btn.style.cssText = 'padding:10px 20px;background:var(--accent);color:#fff;border:none;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;transition:all 0.2s;box-shadow:0 2px 8px rgba(37,99,235,0.25)';
  btn.onmouseenter = function() { btn.style.transform = 'translateY(-1px)'; };
  btn.onmouseleave = function() { btn.style.transform = 'none'; };
  btn.onclick = function() { generateReport(kpis, btResult, sigResult, indContrib); };
  wrap.appendChild(btn);

  var hint = document.createElement('span');
  hint.style.cssText = 'font-size:10px;color:var(--text3)';
  hint.textContent = 'Self-contained HTML — works offline, printable, shareable';
  wrap.appendChild(hint);

  document.getElementById('kpiCard').appendChild(wrap);
}

function generateReport(kpis, btResult, sigResult, indContrib) {
  var tk = BT.ticker;
  var now = new Date();
  var dateStr = now.toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' });
  var timeStr = now.toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit' });

  // Gather config
  var activeSlots = BT.slots.filter(function(s) { return s.indId; });
  var threshold = parseInt(document.getElementById('entryThreshold').value) || 20;
  var periodLabel = document.getElementById('period').value.toUpperCase();
  var dataRange = BT.ohlcv.dates[0] + ' to ' + BT.ohlcv.dates[BT.ohlcv.dates.length - 1];
  var info = BT.tickerMap[tk] || {};

  // Build signal activity per bar (for validation table)
  var signalBars = [];
  for (var i = 0; i < BT.ohlcv.dates.length; i++) {
    var barInfo = { date: BT.ohlcv.dates[i], close: BT.ohlcv.close[i], signal: sigResult.signals[i], indSignals: {} };
    var hasActivity = sigResult.signals[i] !== 0;
    Object.keys(sigResult.perInd).forEach(function(indId) {
      var pInd = sigResult.perInd[indId];
      var eF = pInd.entryBars.indexOf(i) >= 0;
      var xF = pInd.exitBars.indexOf(i) >= 0;
      barInfo.indSignals[indId] = { entry: eF, exit: xF };
      if (eF || xF) hasActivity = true;
    });
    if (hasActivity) signalBars.push(barInfo);
  }

  // Count signals
  var totalEntry = sigResult.signals.filter(function(s) { return s === 1; }).length;
  var totalExit = sigResult.signals.filter(function(s) { return s === -1; }).length;

  // Color helpers
  function pnlColor(v) { return v > 0 ? '#16A34A' : v < 0 ? '#DC2626' : '#6B7280'; }
  function pnlSign(v) { return v > 0 ? '+' : ''; }

  // ── Build HTML ──
  var h = '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">';
  h += '<title>Backtest Report — ' + tk + ' | xchart.in</title>';
  h += '<style>';
  h += '*{margin:0;padding:0;box-sizing:border-box}';
  h += 'body{font-family:system-ui,-apple-system,sans-serif;background:#F8F9FB;color:#1F2937;padding:24px;max-width:1100px;margin:0 auto;-webkit-print-color-adjust:exact;print-color-adjust:exact}';
  h += 'a{color:#2563EB;text-decoration:none}';
  h += '.hdr{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #2563EB;padding-bottom:16px;margin-bottom:24px}';
  h += '.hdr h1{font-size:24px;font-weight:800;color:#1F2937}.hdr h1 em{font-style:normal;color:#2563EB}';
  h += '.hdr-right{text-align:right;font-size:11px;color:#6B7280;line-height:1.8}';
  h += '.section{margin-bottom:24px}.section h2{font-size:14px;font-weight:700;color:#1F2937;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #E5E7EB;display:flex;align-items:center;gap:6px}';
  h += '.kpi-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}';
  h += '.kpi{background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:12px;text-align:center}';
  h += '.kpi-v{font-size:18px;font-weight:700}.kpi-l{font-size:9px;color:#6B7280;text-transform:uppercase;margin-top:2px;font-weight:600}';
  h += '.config-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}';
  h += '.config-card{background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:14px}';
  h += '.config-card h3{font-size:12px;font-weight:700;color:#2563EB;margin-bottom:8px}';
  h += '.config-row{display:flex;justify-content:space-between;font-size:11px;padding:3px 0;border-bottom:1px solid #F3F4F6}';
  h += '.config-row:last-child{border:none}.config-label{color:#6B7280}.config-val{font-weight:600;color:#1F2937}';
  h += '.ind-card{background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:14px;margin-bottom:8px}';
  h += '.ind-hdr{display:flex;align-items:center;gap:8px;margin-bottom:6px}';
  h += '.ind-num{width:22px;height:22px;border-radius:50%;background:#2563EB;color:#fff;font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center}';
  h += '.ind-name{font-size:13px;font-weight:700;color:#1F2937}.ind-cat{font-size:9px;color:#6B7280;background:#F3F4F6;padding:2px 6px;border-radius:4px}';
  h += '.ind-detail{font-size:11px;color:#4B5563;line-height:1.8}';
  h += '.ind-detail span{font-weight:600;color:#1F2937}';
  h += 'table{width:100%;border-collapse:collapse;font-size:11px}';
  h += 'th{background:#F8F9FB;color:#6B7280;font-weight:600;text-align:left;padding:8px;border-bottom:2px solid #E5E7EB;font-size:10px;text-transform:uppercase;letter-spacing:0.3px}';
  h += 'td{padding:6px 8px;border-bottom:1px solid #F3F4F6;color:#1F2937}';
  h += 'tr:hover{background:#F8F9FB}.win{color:#16A34A;font-weight:600}.loss{color:#DC2626;font-weight:600}';
  h += '.bar-wrap{width:60px;height:6px;background:#E5E7EB;border-radius:3px;display:inline-block;vertical-align:middle;margin-left:4px}';
  h += '.bar-fill{height:100%;border-radius:3px}';
  h += '.sig-entry{background:#DCFCE7;color:#16A34A;font-weight:700;padding:1px 5px;border-radius:3px;font-size:9px}';
  h += '.sig-exit{background:#FEE2E2;color:#DC2626;font-weight:700;padding:1px 5px;border-radius:3px;font-size:9px}';
  h += '.sig-dot{width:8px;height:8px;border-radius:50%;display:inline-block}';
  h += '.dot-e{background:#16A34A}.dot-x{background:#DC2626}';
  h += '.summary-box{background:linear-gradient(135deg,rgba(37,99,235,0.04),rgba(79,70,229,0.04));border:1px solid rgba(37,99,235,0.12);border-radius:8px;padding:16px;margin-top:12px;font-size:11px;color:#4B5563;line-height:1.8}';
  h += '.ftr{margin-top:30px;padding-top:16px;border-top:1px solid #E5E7EB;font-size:9px;color:#9CA3AF;text-align:center;line-height:1.8}';
  h += '.chip{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;margin:0 2px}';
  h += '.chip-blue{background:rgba(37,99,235,0.08);color:#2563EB}.chip-green{background:rgba(22,163,74,0.08);color:#16A34A}.chip-red{background:rgba(220,38,38,0.08);color:#DC2626}.chip-gray{background:#F3F4F6;color:#6B7280}';
  h += '@media print{body{padding:12px;font-size:10px}.kpi-grid{grid-template-columns:repeat(5,1fr)}.section{break-inside:avoid}}';
  h += '@media(max-width:700px){.kpi-grid{grid-template-columns:repeat(3,1fr)}.config-grid{grid-template-columns:1fr}}';
  h += '</style></head><body>';

  // ── Header ──
  h += '<div class="hdr">';
  h += '<div><h1>x<em>chart</em>.in — Backtest Report</h1>';
  h += '<div style="font-size:12px;color:#6B7280;margin-top:4px">Analytical backtest results for <strong>' + tk + '</strong></div></div>';
  h += '<div class="hdr-right">Generated: ' + dateStr + ' ' + timeStr + '<br>';
  h += 'Data: ' + dataRange + ' (' + BT.ohlcv.dates.length + ' bars)<br>';
  h += 'Sector: ' + (info.sector || 'N/A') + '</div></div>';

  // ── KPIs ──
  h += '<div class="section"><h2>📊 Performance Summary</h2>';
  h += '<div class="kpi-grid">';
  h += kpiCell(kpis.totalTrades, 'Total Trades', '#1F2937');
  h += kpiCell(kpis.winRate.toFixed(1) + '%', 'Win Rate', pnlColor(kpis.winRate - 50));
  h += kpiCell(kpis.profitFactor.toFixed(2), 'Profit Factor', pnlColor(kpis.profitFactor - 1));
  h += kpiCell(pnlSign(kpis.totalReturn) + kpis.totalReturn.toFixed(1) + '%', 'Total Return', pnlColor(kpis.totalReturn));
  h += kpiCell(kpis.maxDrawdown.toFixed(1) + '%', 'Max Drawdown', '#DC2626');
  h += kpiCell('+' + kpis.avgWin.toFixed(1) + '%', 'Avg Win', '#16A34A');
  h += kpiCell('-' + kpis.avgLoss.toFixed(1) + '%', 'Avg Loss', '#DC2626');
  h += kpiCell(kpis.avgHold.toFixed(0) + 'd', 'Avg Hold', '#1F2937');
  h += kpiCell(kpis.slExits, 'SL Exits', '#1F2937');
  h += kpiCell(BT.mode.toUpperCase(), 'Signal Mode', '#2563EB');
  h += '</div>';

  // Verdict
  var verdict = kpis.profitFactor >= 1.2 ? '✅ Strategy shows positive edge' :
                kpis.profitFactor >= 0.9 ? '⚠️ Marginal — needs refinement' :
                '❌ Strategy underperforms — review conditions';
  h += '<div class="summary-box"><strong>Assessment:</strong> ' + verdict + ' — ';
  h += 'PF ' + kpis.profitFactor.toFixed(2) + ' with ' + kpis.totalTrades + ' trades over ' + periodLabel + '. ';
  h += 'Win rate ' + kpis.winRate.toFixed(1) + '% (avg win ' + kpis.avgWin.toFixed(1) + '% vs avg loss ' + kpis.avgLoss.toFixed(1) + '%). ';
  h += 'Max drawdown ' + kpis.maxDrawdown.toFixed(1) + '%.</div>';
  h += '</div>';

  // ── Configuration ──
  h += '<div class="section"><h2>⚙️ Configuration</h2>';
  h += '<div class="config-grid">';

  // Signal settings
  h += '<div class="config-card"><h3>Signal Settings</h3>';
  h += cfgRow('Mode', BT.mode.toUpperCase());
  if (BT.mode === 'majority') h += cfgRow('Majority Required', BT.majorityN + ' of ' + activeSlots.length);
  h += cfgRow('Entry Threshold', '±' + threshold);
  h += cfgRow('Backtest Period', periodLabel);
  h += cfgRow('Data Points', BT.ohlcv.dates.length + ' bars');
  h += '</div>';

  // Exit rules
  h += '<div class="config-card"><h3>Exit Rules</h3>';
  h += cfgRow('Stop Loss', document.getElementById('x_sl').checked ? document.getElementById('x_sl_val').value + '%' : 'OFF');
  h += cfgRow('Target', document.getElementById('x_tp').checked ? document.getElementById('x_tp_val').value + '%' : 'OFF');
  h += cfgRow('Trailing SL', document.getElementById('x_trail').checked ? document.getElementById('x_trail_val').value + '%' : 'OFF');
  h += cfgRow('Max Hold', document.getElementById('x_maxhold').checked ? document.getElementById('x_maxhold_val').value + ' days' : 'OFF');
  h += '</div>';
  h += '</div>';

  // ── Indicators ──
  h += '<div class="section"><h2>📐 Indicators (' + activeSlots.length + ')</h2>';
  activeSlots.forEach(function(slot, idx) {
    var ind = INDICATORS[slot.indId];
    if (!ind) return;
    h += '<div class="ind-card"><div class="ind-hdr">';
    h += '<div class="ind-num">' + (idx + 1) + '</div>';
    h += '<div class="ind-name">' + ind.name + '</div>';
    h += '<div class="ind-cat">' + ind.cat + '</div>';
    h += '<div style="margin-left:auto;font-size:12px;font-weight:700;color:#2563EB">' + slot.weight + '%</div>';
    h += '</div><div class="ind-detail">';

    // Params
    if (ind.params.length > 0) {
      h += '<strong>Parameters:</strong> ';
      h += ind.params.map(function(p) {
        var v = slot.params[p.id] !== undefined ? slot.params[p.id] : p.def;
        return p.label + '=<span>' + v + '</span>';
      }).join(', ');
      h += '<br>';
    }

    // Conditions
    var entryLabel = ind.entry.find(function(e) { return e.id === slot.entryCond; });
    var exitLabel = ind.exit.find(function(e) { return e.id === slot.exitCond; });
    h += '<strong>Entry:</strong> ' + (entryLabel ? entryLabel.label : slot.entryCond) + '<br>';
    h += '<strong>Exit:</strong> ' + (exitLabel ? exitLabel.label : slot.exitCond);
    h += '</div></div>';
  });
  h += '</div>';

  // ── Per-Indicator Breakdown ──
  if (indContrib.length > 0) {
    h += '<div class="section"><h2>🎯 Indicator Contribution Analysis</h2>';
    h += '<table><thead><tr><th>Indicator</th><th>Entry Triggers</th><th>Led to Wins</th><th>Accuracy</th><th>Impact vs Random</th><th>Visual</th></tr></thead><tbody>';
    indContrib.forEach(function(c) {
      var accColor = pnlColor(c.accuracy - 50);
      h += '<tr><td><strong>' + c.name + '</strong></td>';
      h += '<td>' + c.triggers + '</td>';
      h += '<td>' + c.correct + '</td>';
      h += '<td style="color:' + accColor + ';font-weight:600">' + c.accuracy.toFixed(1) + '%</td>';
      h += '<td style="color:' + pnlColor(c.impact) + ';font-weight:600">' + pnlSign(c.impact) + c.impact.toFixed(1) + '%</td>';
      h += '<td><div class="bar-wrap"><div class="bar-fill" style="width:' + Math.min(c.accuracy, 100) + '%;background:' + accColor + '"></div></div></td>';
      h += '</tr>';
    });
    h += '</tbody></table>';
    h += '<div style="font-size:10px;color:#9CA3AF;margin-top:6px">💡 Accuracy > 55% = positive contribution. Impact = accuracy minus 50% (random baseline).</div>';
    h += '</div>';
  }

  // ── Trade Log ──
  h += '<div class="section"><h2>📋 Complete Trade Log (' + btResult.trades.length + ' trades)</h2>';
  if (btResult.trades.length > 0) {
    h += '<table><thead><tr><th>#</th><th>Entry Date</th><th>Entry ₹</th><th>Exit Date</th><th>Exit ₹</th><th>Days</th><th>Result</th><th>Exit Type</th><th>Cumulative</th></tr></thead><tbody>';
    var cumReturn = 0;
    btResult.trades.forEach(function(t, i) {
      cumReturn += t.result;
      var cls = t.result >= 0 ? 'win' : 'loss';
      h += '<tr>';
      h += '<td>' + (i + 1) + '</td>';
      h += '<td>' + t.entryDate + '</td>';
      h += '<td>₹' + t.entryPrice.toFixed(2) + '</td>';
      h += '<td>' + t.exitDate + '</td>';
      h += '<td>₹' + t.exitPrice.toFixed(2) + '</td>';
      h += '<td>' + t.days + 'd</td>';
      h += '<td class="' + cls + '">' + pnlSign(t.result) + t.result.toFixed(2) + '%</td>';
      h += '<td><span class="chip ' + (t.exitType === 'Stop Loss' ? 'chip-red' : t.exitType === 'Target' ? 'chip-green' : 'chip-gray') + '">' + t.exitType + '</span></td>';
      h += '<td style="color:' + pnlColor(cumReturn) + ';font-weight:600">' + pnlSign(cumReturn) + cumReturn.toFixed(1) + '%</td>';
      h += '</tr>';
    });
    h += '</tbody></table>';
  } else {
    h += '<div style="text-align:center;padding:20px;color:#9CA3AF">No trades generated. Review indicator conditions and signal mode.</div>';
  }
  h += '</div>';

  // ── Signal Validation Log ──
  h += '<div class="section"><h2>🔍 Signal Validation Log</h2>';
  h += '<div style="font-size:10px;color:#6B7280;margin-bottom:8px">';
  h += 'Shows every bar where at least one indicator fired. Use this to verify entry/exit logic. ';
  h += 'Total: <span class="chip chip-green">' + totalEntry + ' entry signals</span> <span class="chip chip-red">' + totalExit + ' exit signals</span>';
  h += '</div>';

  if (signalBars.length > 0) {
    var indIds = Object.keys(sigResult.perInd);
    h += '<div style="overflow-x:auto"><table><thead><tr><th>Date</th><th>Close</th><th>Signal</th>';
    indIds.forEach(function(id) {
      var name = INDICATORS[id] ? INDICATORS[id].name : id;
      h += '<th>' + name + '</th>';
    });
    h += '</tr></thead><tbody>';

    // Show max 100 rows to keep file size reasonable
    var showBars = signalBars.length > 100 ? signalBars.slice(0, 50).concat([null]).concat(signalBars.slice(-50)) : signalBars;
    showBars.forEach(function(bar) {
      if (!bar) {
        h += '<tr><td colspan="' + (3 + indIds.length) + '" style="text-align:center;color:#9CA3AF;font-style:italic">... ' + (signalBars.length - 100) + ' more rows ...</td></tr>';
        return;
      }
      h += '<tr>';
      h += '<td>' + bar.date + '</td>';
      h += '<td>₹' + bar.close.toFixed(2) + '</td>';
      h += '<td>';
      if (bar.signal === 1) h += '<span class="sig-entry">▲ ENTRY</span>';
      else if (bar.signal === -1) h += '<span class="sig-exit">▼ EXIT</span>';
      h += '</td>';
      indIds.forEach(function(id) {
        var s = bar.indSignals[id];
        h += '<td>';
        if (s.entry) h += '<span class="sig-dot dot-e" title="Entry fired"></span> ';
        if (s.exit) h += '<span class="sig-dot dot-x" title="Exit fired"></span>';
        h += '</td>';
      });
      h += '</tr>';
    });
    h += '</tbody></table></div>';
  } else {
    h += '<div style="text-align:center;padding:20px;color:#9CA3AF">No signals generated.</div>';
  }
  h += '</div>';

  // ── Footer ──
  h += '<div class="ftr">';
  h += '<strong>⚠️ Disclaimer:</strong> This report is generated by xchart.in, an analytical tool for educational purposes. ';
  h += 'All results are based on historical data and user-configured rules. Past performance does not guarantee future results. ';
  h += 'This is not investment advice. Not SEBI registered.<br>';
  h += '© 2026 xchart.in · Generated on ' + dateStr + ' ' + timeStr + ' · <a href="https://xchart.in">xchart.in</a>';
  h += '</div></body></html>';

  // Download
  var blob = new Blob([h], { type: 'text/html' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = tk + '_backtest_report_' + now.toISOString().slice(0,10) + '.html';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function kpiCell(val, label, color) {
  return '<div class="kpi"><div class="kpi-v" style="color:' + color + '">' + val + '</div><div class="kpi-l">' + label + '</div></div>';
}

function cfgRow(label, val) {
  return '<div class="config-row"><span class="config-label">' + label + '</span><span class="config-val">' + val + '</span></div>';
}
// Init
(function() {
  loadTickerList();
  // Add one empty slot by default
  addIndicatorSlot();
})();
