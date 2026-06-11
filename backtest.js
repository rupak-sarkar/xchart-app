/**
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
})();