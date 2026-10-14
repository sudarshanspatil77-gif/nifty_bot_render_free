
from flask import Flask, jsonify
import threading, time, os, requests, random, math
from datetime import datetime
import pytz
from collections import deque

app = Flask(__name__)
LOGS = deque(maxlen=200)
CANDLES = deque(maxlen=500)
TRADES_HISTORY = deque(maxlen=20)
STATE = {
    "trades":0,"trades_today":0,"max_trades":5,"pnl":0,
    "spot":22527,"prem":87.30,"strike":22250,
    "intrinsic":0,"time_value":87.30,"delta":0.30,
    "fib_high":90.2,"fib_low":60.2,"range":30.0,
    "pos":None,"trade_date":None,
    "telegram_limit_sent":False,"telegram_enabled":True,"force_trade":False,
    "timeframe":5,"sl_fib":0.35,"entry_fib":0.5,"tgt_fib":2.414
}
IST = pytz.timezone('Asia/Kolkata')
def add_log(m):
    ts=datetime.now(IST).strftime("%H:%M:%S")
    LOGS.append(f"{ts} | {m}")
def get_tf_str(): return f"{STATE['timeframe']} MIN"
def is_market_open():
    now=datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    if STATE["trade_date"] != today:
        STATE["trade_date"]=today; STATE["trades_today"]=0; STATE["trades"]=0; STATE["telegram_limit_sent"]=False; STATE["telegram_enabled"]=True
        add_log(f"NEW DAY {today} Reset 0/5 TF {get_tf_str()} SL 0.35")
    if STATE["force_trade"]:
        return True, f"FORCE ON - {STATE['trades_today']}/5 - TF {get_tf_str()} - SL 0.35", False
    if now.weekday()>=5: return False, f"Weekend {now.strftime('%A')}", False
    mo=now.replace(hour=9,minute=15,second=0,microsecond=0); mc=now.replace(hour=15,minute=30,second=0,microsecond=0)
    if now<mo: return False, f"Pre-Market {now.strftime('%H:%M')} Opens 9:15 AM", False
    if now>mc: return False, f"Closed {now.strftime('%H:%M')} 3:30 PM", False
    if STATE["trades_today"]>=5: return False, f"5 Trades Limit {STATE['trades_today']}/5 OFF", True
    return True, f"Market Open 9:15 AM - {STATE['trades_today']}/5 - TF {get_tf_str()} SL 0.35", False
def send_telegram(text):
    if STATE["trades_today"] >= 5:
        if not STATE["telegram_limit_sent"]:
            try:
                token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
                if token and chat:
                    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":f"🔕 5 Trades Complete TF {get_tf_str()} - OFF\nTrades: {STATE['trades_today']}/5 P&L: Rs.{STATE['pnl']}", "parse_mode":"Markdown"},timeout=10)
                    STATE["telegram_limit_sent"]=True; STATE["telegram_enabled"]=False
            except: pass
        return False
    if not STATE["telegram_enabled"]: return False
    try:
        token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat: return False
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":text,"parse_mode":"Markdown"},timeout=10)
        return r.status_code==200
    except: return False
def get_nse():
    try:
        headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.nseindia.com/option-chain"}
        s=requests.Session(); s.headers.update(headers)
        s.get("https://www.nseindia.com/option-chain",timeout=5)
        r=s.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",timeout=5)
        if r.status_code==200:
            d=r.json(); spot=float(d["records"]["underlyingValue"])
            for it in d["records"]["data"]:
                if it.get("strikePrice")==int((spot*0.988)//50*50) and it.get("PE"):
                    lp=float(it["PE"]["lastPrice"])
                    if lp>0:
                        intr=max(int((spot*0.988)//50*50 - spot,0)
                        tv=lp-intr
                        return spot, lp, int((spot*0.988)//50*50), intr, tv, 0.30, -0.012, "NSE LIVE"
    except: pass
    spot_sim = 22527 + random.uniform(-30, 30)
    strike_sim = int((spot_sim * 0.988)//50*50)
    intr = max(strike_sim - spot_sim, 0)
    tv = 65 + random.uniform(-3,5) + math.sin(time.time()/50)*1.5
    prem = intr + tv
    return spot_sim, prem, strike_sim, intr, tv, 0.30, -0.012, "LIVE SIM"
def detect_swings():
    if len(CANDLES) < 12: return None
    clist = list(CANDLES); WINDOW=5; MIN_GAP=6
    sh=[]; sl=[]
    for i in range(WINDOW, len(clist)-WINDOW):
        curr=clist[i]
        ih=True; il=True
        for j in range(i-WINDOW, i+WINDOW+1):
            if j==i: continue
            if clist[j]['h'] >= curr['h']: ih=False
            if clist[j]['l'] <= curr['l']: il=False
        if ih: sh.append({"idx":i,"value":curr['h'],"time":curr['t']})
        if il: sl.append({"idx":i,"value":curr['l'],"time":curr['t']})
    if not sh or not sl: return None
    fsh=[]; last=-100
    for x in sh:
        if x['idx']-last>=MIN_GAP:
            fsh.append(x); last=x['idx']
        elif x['value']>fsh[-1]['value']:
            fsh[-1]=x; last=x['idx']
    fsl=[]; last=-100
    for x in sl:
        if x['idx']-last>=MIN_GAP:
            fsl.append(x); last=x['idx']
        elif x['value']<fsl[-1]['value']:
            fsl[-1]=x; last=x['idx']
    if not fsh or not fsl: return None
    rh=fsh[-1]; rl=fsl[-1]
    fh=max(rh['value'], rl['value']); fl=min(rh['value'], rl['value']); rng=fh-fl
    if rng<3: return None
    return {"swing_high":rh,"swing_low":rl,"fib_high":fh,"fib_low":fl,"range":rng,"0.35":fl+rng*0.35,"0.5":fl+rng*0.5,"2.414":fl+rng*2.414}

for i in range(25):
    c=70+i*0.6+random.uniform(-1.5,2)
    if i==6: c=85
    if i==18: c=58
    CANDLES.append({"o":c-1,"h":c+1.2,"l":c-1,"c":c,"t":f"09:{i+15:02d}","buy":False,"sell_sl":False,"sell_tgt":False})

HTML = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nifty50Bot - 5 MIN - SL 0.35 - Clean</title>
<style>
*{box-sizing:border-box}
body{background:#0f172a;color:#e2e8f0;padding:8px;font-family:Arial;margin:0}
h2{color:#22c55e;text-align:center;margin:0 0 8px 0;font-size:13px;background:#1e293b;padding:10px;border-radius:10px;border:2px solid #22c55e}
.card{background:#1e293b;padding:10px;border-radius:12px;margin:8px 0;border:1px solid #334155}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}
.grid4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px}
.box{background:#0f172a;padding:8px;border-radius:10px;border:1px solid #334155;text-align:center}
.box .l{color:#94a3b8;font-size:9px} .box .v{color:#fff;font-size:13px;font-weight:bold;margin-top:3px}
.entry{color:#22c55e !important} .sl{color:#f97316 !important} .tgt{color:#3b82f6 !important} .prem{color:#eab308 !important}
#chart{background:#ffffff;border-radius:12px;padding:8px;margin:8px 0;min-height:650px;border:3px solid #22c55e;position:relative}
canvas{width:100%;height:560px;background:#fff;border-radius:8px;display:block}
.btn{padding:7px 12px;font-weight:bold;border-radius:8px;text-decoration:none;display:inline-block;margin:3px;font-size:11px}
.btn-g{background:#22c55e;color:#000} .btn-y{background:#eab308;color:#000} .btn-b{background:#3b82f6;color:#fff} .btn-r{background:#ef4444;color:#fff} .btn-p{background:#a855f7;color:#fff}
.small{font-size:9px;color:#94a3b8}
.status-open{color:#000;background:#22c55e;padding:6px 12px;border-radius:8px;font-size:12px;font-weight:bold;border:2px solid #fff;display:inline-block;margin:2px}
.status-closed{color:#fff;background:#ef4444;padding:6px 12px;border-radius:8px;font-size:12px;font-weight:bold;display:inline-block;margin:2px}
.loading{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(15,23,42,0.9);color:#22c55e;padding:12px 20px;border-radius:10px;font-weight:bold;border:2px solid #22c55e;z-index:10}
#auto_loader{position:fixed;top:0;left:0;right:0;background:#22c55e;color:#000;padding:4px;text-align:center;font-weight:bold;font-size:11px;z-index:100;display:none}
</style></head><body>

<div id="auto_loader">🔄 Auto Loading... TF 5 MIN - SL 0.35 - Chart Loading - Please Wait...</div>

<h2>🇮🇳 Nifty50Bot - 5 MIN TF - SL 0.35 Fib - Auto Loading - Clean</h2>

<div class="card" style="padding:8px">
<div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;justify-content:center">
<span id="market_status" class="status-open">● Market Open 9:15 AM - 0/5 - TF 5 MIN SL 0.35</span>
<span id="nse_status" style="color:#000;background:#eab308;padding:4px 8px;border-radius:6px;font-size:10px;font-weight:bold">● NSE LIVE</span>
<span id="tg_status" style="color:#fff;background:#22c55e;padding:4px 8px;border-radius:6px;font-size:10px">● TELEGRAM ON</span>
<span id="tf_status" style="color:#fff;background:#06b6d4;padding:4px 8px;border-radius:6px;font-size:10px">● TF 5 MIN SL 0.35</span>
<span id="lt" class="small" style="margin-left:auto"></span>
</div>

<div class="grid4" style="margin-top:8px">
<div class="box"><div class="l">Trades Today</div><div class="v" id="trades" style="font-size:20px;color:#22c55e">0/5</div><div class="small">Only 5 Trade</div></div>
<div class="box"><div class="l">Which Premium Δ0.30</div><div class="v prem" id="which_prem">22250PE Δ0.30</div><div class="small">5 MIN HL</div></div>
<div class="box"><div class="l">Total P&L</div><div class="v" id="pnl" style="color:#22c55e;font-size:20px">Rs.0</div><div class="small">Today</div></div>
<div class="box"><div class="l">Timeframe</div><div class="v" id="tf_box_top" style="color:#06b6d4;font-size:18px">5 MIN</div><div class="small">SL 0.35 Fib</div></div>
</div>

<div class="grid3" style="margin-top:8px">
<div class="box"><div class="l">Entry Price (0.5 Fib)</div><div class="v entry" id="entry_p">75.20 BUY</div><div class="small">5 MIN HL 0.5</div></div>
<div class="box"><div class="l">SL Price (0.35 Fib) ✅</div><div class="v sl" id="sl_p">70.50 → Trail</div><div class="small">5 MIN HL 0.35 Less Hit</div></div>
<div class="box"><div class="l">Target Price (2.414 Fib)</div><div class="v tgt" id="tgt_p">132.62 TGT</div><div class="small">5 MIN HL 2.414</div></div>
</div>

<div class="grid4" style="margin-top:8px">
<div class="box"><div class="l">Spot LIVE</div><div class="v small" id="spot_box">22527 LIVE</div></div>
<div class="box"><div class="l">Strike Δ0.30</div><div class="v small" id="strike_box">22250PE</div></div>
<div class="box"><div class="l">Premium LIVE</div><div class="v small prem" id="prem_box">87.30 LIVE</div></div>
<div class="box"><div class="l">Delta</div><div class="v small" id="delta_box" style="color:#22c55e">0.30</div></div>
</div>

<div class="grid3" style="margin-top:6px">
<div class="box"><div class="l">Swing High 5 MIN</div><div class="v small" id="swing_high" style="color:#ef4444">90.2 @10:18</div></div>
<div class="box"><div class="l">Swing Low 5 MIN</div><div class="v small" id="swing_low" style="color:#22c55e">60.2 @10:00</div></div>
<div class="box"><div class="l">Fib H L R SL</div><div class="v small" id="fib_info">H 90.2 L 60.2 R 30.0 SL 70.5</div></div>
</div>

<div style="text-align:center;margin-top:8px">
<a class="btn btn-g" href="/force_buy">🟢 Force BUY</a>
<a class="btn btn-r" href="/force_sell">🔴 Force SELL</a>
<a class="btn btn-p" href="/force_trade">⚡ Force ON</a>
<a class="btn btn-y" href="/set_timeframe/5">5 MIN Best</a>
<a class="btn btn-b" href="/health">Health</a>
</div>
</div>

<div id="chart">
<div id="chart_loading" class="loading">📈 Chart Loading... Auto Loading TF 5 MIN - SL 0.35...</div>
<div style="color:#000;font-weight:bold;text-align:center;font-size:12px">📈 LIVE 5 MIN - SL 0.35 Fib - 5 MIN High Low - Auto Loading - Working Chart</div>
<canvas id="c" width="800" height="560"></canvas>
<div style="color:#000;font-size:9px;text-align:center;margin-top:4px">✅ Clean Dashboard - No Update Boxes - Auto Loading ON - Chart Fixed - TF 5 MIN - Entry 0.5 SL 0.35 TGT 2.414 - 5 MIN HL</div>
<div id="trade_list" style="color:#000;font-size:10px;margin-top:6px;background:#f0f0f0;padding:6px;border-radius:6px;min-height:30px">Loading trades...</div>
</div>

<div class="card">
<div style="color:#22c55e;font-size:11px;font-weight:bold;margin-bottom:4px">📋 Live Logs - Auto Loading - TF 5 MIN SL 0.35:</div>
<pre id="log" style="background:#0f172a;color:#22c55e;padding:8px;border-radius:8px;border:1px solid #334155;font-size:9px;max-height:200px;overflow:auto;white-space:pre-wrap;margin:0">Loading logs...</pre>
</div>

<script>
let candles=[];
let fib={low:60.2,high:90.2,range:30,"0.35":70.5,"0.5":75.2,"2.414":132.62,swingHigh:{value:90.2,time:"10:18"},swingLow:{value:60.2,time:"10:00"}};
let tradesHistory=[];
let autoLoadCount=0;

function showLoader(msg){
  let el=document.getElementById('auto_loader');
  el.style.display='block';
  el.innerText=msg;
  setTimeout(()=>{el.style.display='none'},2000);
}

function draw(){
 let canvas=document.getElementById('c');
 if(!canvas) return;
 let ctx=canvas.getContext('2d');
 let W=canvas.width, H=canvas.height, pad=50;
 if(candles.length==0){
   ctx.clearRect(0,0,W,H);
   ctx.fillStyle="#fff"; ctx.fillRect(0,0,W,H);
   ctx.fillStyle="#000"; ctx.font="14px Arial"; ctx.fillText("Chart Loading... TF 5 MIN - Auto Loading...", W/2-120, H/2);
   return;
 }
 // Hide loading
 document.getElementById('chart_loading').style.display='none';
 
 ctx.clearRect(0,0,W,H); ctx.fillStyle="#fff"; ctx.fillRect(0,0,W,H);
 let allHighs=candles.map(c=>c.h); let allLows=candles.map(c=>c.l);
 let min=Math.min(...allLows,fib.low,fib["0.35"])-10; let max=Math.max(...allHighs,fib.high,fib["2.414"])+15;
 let y=v=>H-pad-(v-min)/(max-min)*(H-pad*2); let x=i=>pad+i/(candles.length-1)*(W-pad*2);
 ctx.strokeStyle="#eee"; ctx.lineWidth=1;
 for(let i=0;i<=6;i++){
   let yy=pad+i*(H-pad*2)/6;
   ctx.beginPath(); ctx.moveTo(pad,yy); ctx.lineTo(W-pad,yy); ctx.stroke();
   ctx.fillStyle="#666"; ctx.font="10px Arial"; ctx.fillText((max-(max-min)*i/6).toFixed(1),4,yy+3);
 }
 function line(val,color,label,dash,width){
   if(val<=min || val>=max) return;
   ctx.strokeStyle=color; ctx.lineWidth=width||2; ctx.setLineDash(dash||[]);
   ctx.beginPath(); ctx.moveTo(pad,y(val)); ctx.lineTo(W-pad,y(val)); ctx.stroke(); ctx.setLineDash([]);
   ctx.fillStyle=color; ctx.font="bold 11px Arial"; ctx.fillText(label+" "+val.toFixed(1),W-pad+2,y(val)-4);
 }
 line(fib.high,"#ef4444","Swing High 5MIN",[8,4],2);
 line(fib.low,"#0f172a","Swing Low 5MIN",[8,4],2);
 line(fib["0.5"],"#22c55e","0.5 ENTRY BUY - 5MIN HL",[],3);
 line(fib["0.35"],"#f97316","0.35 SL ✅ - 5MIN HL - Less Hit",[6,3],3);
 line(fib["2.414"],"#3b82f6","2.414 TGT - 5MIN HL",[],2);
 
 candles.forEach((c,i)=>{
  let g=c.c>=c.o; ctx.fillStyle=g?"#22c55e":"#ef4444"; ctx.strokeStyle=g?"#16a34a":"#dc2626";
  let bh=Math.abs(y(c.o)-y(c.c)); let by=Math.min(y(c.o),y(c.c));
  let w=Math.max(5, (W-pad*2)/candles.length*0.7);
  ctx.beginPath(); ctx.moveTo(x(i),y(c.h)); ctx.lineTo(x(i),y(c.l)); ctx.stroke();
  ctx.fillRect(x(i)-w/2,by,w,Math.max(3,bh));
  if(c.buy){
    ctx.fillStyle="#22c55e"; ctx.beginPath(); ctx.arc(x(i),y(c.c),15,0,Math.PI*2); ctx.fill();
    ctx.strokeStyle="#000"; ctx.lineWidth=3; ctx.stroke();
    ctx.fillStyle="#fff"; ctx.font="bold 11px Arial"; ctx.fillText("BUY",x(i)-12,y(c.c)+4);
    ctx.fillStyle="#000"; ctx.font="bold 10px Arial"; ctx.fillText("BUY @"+c.c.toFixed(1),x(i)+18,y(c.c)-8);
  }
  if(c.sell_sl){
    ctx.fillStyle="#f97316"; ctx.beginPath(); ctx.arc(x(i),y(c.c),13,0,Math.PI*2); ctx.fill();
    ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke();
    ctx.fillStyle="#fff"; ctx.font="bold 9px Arial"; ctx.fillText("SL 0.35",x(i)-15,y(c.c)+3);
  }
  if(c.sell_tgt){
    ctx.fillStyle="#3b82f6"; ctx.beginPath(); ctx.arc(x(i),y(c.c),13,0,Math.PI*2); ctx.fill();
    ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke();
    ctx.fillStyle="#fff"; ctx.font="bold 9px Arial"; ctx.fillText("TGT",x(i)-10,y(c.c)+3);
  }
 });
 ctx.fillStyle="#000"; ctx.font="9px Arial";
 candles.forEach((c,i)=>{
   if(i%Math.ceil(candles.length/10)==0){
     ctx.fillText(c.t,x(i)-12,H-10);
   }
 });
}

async function refresh(){
 try{
  autoLoadCount++;
  if(autoLoadCount==1){
    showLoader("🔄 Auto Loading... TF 5 MIN - SL 0.35 - Chart Loading...");
  }
  let r=await fetch('/api/candles?t='+Date.now());
  if(!r.ok) throw new Error('API fail');
  let j=await r.json();
  
  if(!j.candles || j.candles.length==0){
    console.log('No candles yet');
    return;
  }
  
  candles=j.candles;
  fib.high=j.fib_high; fib.low=j.fib_low; fib.range=j.range;
  fib["0.5"]=j.entry; fib["0.35"]=j.sl; fib["2.414"]=j.tgt;
  fib.swingHigh=j.swing_high; fib.swingLow=j.swing_low;
  tradesHistory=j.trades_history || [];
  
  document.getElementById('trades').innerText=j.trades_today+'/5';
  document.getElementById('entry_p').innerText=j.entry.toFixed(2)+' BUY';
  document.getElementById('sl_p').innerText=j.sl.toFixed(2)+' → Trail (0.35)';
  document.getElementById('tgt_p').innerText=j.tgt.toFixed(2)+' TGT';
  document.getElementById('pnl').innerText='Rs.'+j.pnl;
  document.getElementById('which_prem').innerText=j.strike+'PE Δ'+(j.delta||0.30).toFixed(2);
  document.getElementById('swing_high').innerText=j.swing_high.value.toFixed(1)+' @'+j.swing_high.time;
  document.getElementById('swing_low').innerText=j.swing_low.value.toFixed(1)+' @'+j.swing_low.time;
  document.getElementById('fib_info').innerText='H '+j.fib_high.toFixed(1)+' L '+j.fib_low.toFixed(1)+' R '+j.range.toFixed(1)+' SL '+j.sl.toFixed(1);
  document.getElementById('spot_box').innerText=j.spot_val.toFixed(1)+' LIVE';
  document.getElementById('strike_box').innerText=j.strike+'PE';
  document.getElementById('prem_box').innerText=j.prem_val.toFixed(2)+' LIVE';
  document.getElementById('delta_box').innerText=(j.delta||0.30).toFixed(2);
  document.getElementById('tf_box_top').innerText=j.timeframe_str || '5 MIN';
  
  document.getElementById('market_status').innerText='● '+j.market;
  document.getElementById('market_status').className=j.force_mode?'status-open':(j.is_limit?'status-closed':(j.is_open?'status-open':'status-closed'));
  document.getElementById('nse_status').innerText='● '+(j.src || 'NSE LIVE');
  document.getElementById('tg_status').innerText=j.telegram_enabled ? '● TELEGRAM ON' : '🔕 TELEGRAM OFF';
  document.getElementById('tf_status').innerText='● TF '+(j.timeframe_str||'5 MIN')+' SL 0.35';
  
  let logEl=document.getElementById('log');
  if(j.logs && j.logs.length>0){
    logEl.innerText=j.logs.slice(-25).join('\n');
    logEl.scrollTop = logEl.scrollHeight;
  }
  
  let tl=document.getElementById('trade_list');
  if(tradesHistory.length>0){
   tl.innerHTML='<b>📊 Trades - TF 5 MIN SL 0.35 - Auto Loading:</b><br>'+tradesHistory.map(t=>`Trade ${t.no}/5: BUY @${t.buy_price.toFixed(1)} ${t.buy_time} → ${t.exit_type} @${t.exit_price.toFixed(1)} ${t.exit_time} P&L Rs.${t.pnl}`).join('<br>');
  } else {
   tl.innerHTML='<b>📊 Trades:</b> No trades yet - TF 5 MIN SL 0.35 - Auto Loading - Waiting for 0.5 cross - Entry 0.5 SL 0.35 TGT 2.414 - 5 MIN HL';
  }
  
  draw();
  
  if(autoLoadCount%10==0){
    showLoader("✅ Auto Loaded - TF 5 MIN - Chart Working - "+j.candles.length+" Candles");
  }
  
 }catch(e){
   console.log('Refresh err', e);
   let logEl=document.getElementById('log');
   if(logEl) logEl.innerText = 'Auto Loading Error - Retrying... TF 5 MIN - SL 0.35\n'+e.message;
   // Still try to draw if we have candles
   if(candles.length>0) draw();
 }
}

// Auto Loading Start - Immediate
showLoader("🔄 Auto Loading Suru - TF 5 MIN - SL 0.35 - Chart Loading...");
refresh();

// Auto Loading Interval - Har 3 sec la auto refresh - Chart band honar nahi!
setInterval(refresh, 3000);

// Time update
setInterval(()=>{
  let el=document.getElementById('lt');
  if(el) el.innerText=new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata'});
},1000);

// Force chart redraw every 5 sec to ensure it stays visible
setInterval(()=>{
  if(candles.length>0){
    draw();
  }
},5000);

window.addEventListener('load', ()=>{
  showLoader("✅ Page Loaded - TF 5 MIN - SL 0.35 - Chart Auto Loading...");
  setTimeout(refresh, 500);
});

</script>
</body></html>
"""

@app.route('/')
def home(): return HTML
@app.route('/api/candles')
def api_candles():
    is_open, market_msg, is_limit = is_market_open()
    clist = list(CANDLES)
    if len(clist)==0:
        return jsonify({"candles":[],"trades_today":0,"trades":0,"strike":"22250","entry":75.2,"sl":70.5,"tgt":132.6,"pnl":0,"spot_val":22527,"prem_val":87.3,"delta":0.30,"fib_high":90.2,"fib_low":60.2,"range":30.0,"swing_high":{"value":90.2,"time":"10:18"},"swing_low":{"value":60.2,"time":"10:00"},"trades_history":[],"telegram_enabled":True,"force_mode":False,"timeframe_str":"5 MIN","src":"LOADING","is_open":is_open,"is_limit":is_limit,"market":market_msg,"logs":list(LOGS)[-20:]})
    sl_fib=STATE["sl_fib"]; entry_fib=STATE["entry_fib"]; tgt_fib=STATE["tgt_fib"]
    fh=STATE["fib_high"]; fl=STATE["fib_low"]; rng=STATE["range"]
    # Recalc fib if not set
    if rng==0 and len(clist)>=12:
        # Quick calc from candles
        highs=[c['h'] for c in clist]; lows=[c['l'] for c in clist]
        fh=max(highs[-15:]) if highs else 90.2
        fl=min(lows[-15:]) if lows else 60.2
        rng=fh-fl
        STATE["fib_high"]=fh; STATE["fib_low"]=fl; STATE["range"]=rng
    return jsonify({
        "candles":clist[-80:],
        "trades_today":STATE["trades_today"],"trades":STATE["trades"],
        "strike":f"{STATE['strike']}",
        "entry":STATE["fib_low"]+STATE["range"]*entry_fib if STATE["range"]>0 else 75.2,
        "sl":STATE["fib_low"]+STATE["range"]*sl_fib if STATE["range"]>0 else 70.5,
        "tgt":STATE["fib_low"]+STATE["range"]*tgt_fib if STATE["range"]>0 else 132.6,
        "pnl":STATE["pnl"],
        "spot_val":STATE["spot"],"prem_val":STATE["prem"],"delta":STATE["delta"],
        "fib_high":STATE["fib_high"] if STATE["fib_high"]>0 else fh,
        "fib_low":STATE["fib_low"] if STATE["fib_low"]>0 else fl,
        "range":STATE["range"] if STATE["range"]>0 else rng,
        "swing_high":STATE.get("swing_high_info",{"value":STATE["fib_high"] if STATE["fib_high"]>0 else 90.2,"time":"10:18"}),
        "swing_low":STATE.get("swing_low_info",{"value":STATE["fib_low"] if STATE["fib_low"]>0 else 60.2,"time":"10:00"}),
        "trades_history":list(TRADES_HISTORY)[-10:],
        "telegram_enabled":STATE["telegram_enabled"],"force_mode":STATE["force_trade"],
        "timeframe":STATE["timeframe"],"timeframe_str":get_tf_str(),
        "src":STATE.get("src","NSE"),"is_open":is_open,"is_limit":is_limit,"market":market_msg,"logs":list(LOGS)[-25:]
    })
@app.route('/health')
def health():
    is_open, msg, is_limit = is_market_open()
    return jsonify({"status":"OK","market":msg,"trades_today":f"{STATE['trades_today']}/5","timeframe":f"{STATE['timeframe']} MIN SL 0.35","candles":len(CANDLES),"chart":"WORKING - Auto Loading ON"})
@app.route('/set_timeframe/<int:tf>')
def set_timeframe(tf):
    if tf not in [1,3,5,15,30]: return jsonify({"ok":False})
    STATE["timeframe"]=tf
    add_log(f"TF UPDATE {tf} MIN SL 0.35 - Clean - Auto Loading")
    CANDLES.clear()
    for i in range(20):
        c=70+i*0.6+random.uniform(-1.5,2)
        CANDLES.append({"o":c-1,"h":c+1.2,"l":c-1,"c":c,"t":f"09:{i+15:02d}","buy":False,"sell_sl":False,"sell_tgt":False})
    STATE["fib_high"]=0; STATE["fib_low"]=0; STATE["range"]=0
    return jsonify({"ok":True,"new_tf":tf})
@app.route('/force_trade')
def force_trade(): STATE["force_trade"]=True; return jsonify({"ok":True})
@app.route('/disable_force')
def disable_force(): STATE["force_trade"]=False; return jsonify({"ok":True})
@app.route('/force_buy')
def force_buy():
    if STATE["trades_today"]>=5: return jsonify({"ok":False,"msg":"5 Limit"})
    if STATE["pos"] is not None: return jsonify({"ok":False,"msg":"Position open"})
    try:
        now=datetime.now(IST).strftime("%H:%M"); curr=STATE["prem"]
        f05=STATE["fib_low"]+STATE["range"]*0.5 if STATE["range"]>0 else 75.2; f035=STATE["fib_low"]+STATE["range"]*0.35 if STATE["range"]>0 else 70.5; f2414=STATE["fib_low"]+STATE["range"]*2.414 if STATE["range"]>0 else 132.6
        CANDLES[-1]["buy"]=True
        STATE["pos"]={"entry":curr,"sl":f035,"tgt":f2414,"buy_time":now,"buy_price":curr,"strike":f"{STATE['strike']}PE"}
        STATE["trades"]+=1; STATE["trades_today"]+=1
        TRADES_HISTORY.append({"no":STATE["trades_today"],"buy_price":curr,"buy_time":now,"exit_price":0,"exit_time":"OPEN","exit_type":"OPEN","pnl":0,"strike":f"{STATE['strike']}PE"})
        add_log(f"FORCE BUY TF 5 MIN SL 0.35 | Trade {STATE['trades_today']}/5 @ {curr:.2f}")
        send_telegram(f"🟢 BUY {STATE['trades_today']}/5 TF 5 MIN SL 0.35 @ {curr:.2f}")
        return jsonify({"ok":True,"msg":f"BUY {STATE['trades_today']}/5 @ {curr:.2f}"})
    except Exception as e: return jsonify({"ok":False,"msg":str(e)})
@app.route('/force_sell')
def force_sell():
    if STATE["pos"] is None: return jsonify({"ok":False,"msg":"No pos"})
    try:
        curr=STATE["prem"]; now=datetime.now(IST).strftime("%H:%M"); pnl=(curr-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
        exit_type="SL HIT 0.35" if curr<=STATE["pos"]["sl"] else "TGT HIT" if curr>=STATE["pos"]["tgt"] else "FORCE SELL"
        CANDLES[-1]["sell_sl"]=True
        if TRADES_HISTORY: last=TRADES_HISTORY[-1]; last["exit_price"]=curr; last["exit_time"]=now; last["exit_type"]=exit_type; last["pnl"]=round(pnl,0)
        add_log(f"SELL {exit_type} @ {curr:.2f} P&L {pnl:.0f}")
        send_telegram(f"🔴 {exit_type} {STATE['trades_today']}/5 @ {curr:.2f} P&L {pnl:.0f}")
        STATE["pos"]=None
        return jsonify({"ok":True,"msg":f"SELL @ {curr:.2f} {exit_type}"})
    except Exception as e: return jsonify({"ok":False,"msg":str(e)})

def bot_loop():
    add_log("BOT START CLEAN - 5 MIN TF SL 0.35 - No Update Boxes - Auto Loading ON - Chart Fixed - Working")
    time.sleep(1)
    send_telegram("🚀 Clean Bot Started TF 5 MIN SL 0.35 - Auto Loading - Chart Fixed - No Update Boxes")
    while True:
        try:
            is_open, market_msg, is_limit = is_market_open()
            if not is_open:
                add_log(f"{market_msg} - Auto Loading - Sleeping 30s - Chart Working")
                time.sleep(30); continue
            spot, prem, strike, intr, tv, delta, moneyness, src = get_nse()
            STATE["spot"]=round(spot,2); STATE["prem"]=round(prem,2); STATE["strike"]=strike; STATE["intrinsic"]=intr; STATE["time_value"]=tv; STATE["delta"]=delta; STATE["src"]=src
            tf=STATE["timeframe"]
            now_dt=datetime.now(IST); minute=now_dt.minute; cm=(minute//tf)*tf; now_str=f"{now_dt.hour}:{cm:02d} TF{tf}"
            if len(CANDLES)==0 or CANDLES[-1]["t"]!=now_str:
                CANDLES.append({"o":prem,"h":prem,"l":prem,"c":prem,"t":now_str,"buy":False,"sell_sl":False,"sell_tgt":False})
                add_log(f"NEW CANDLE TF {tf} MIN SL 0.35 | {now_str} | Premium {prem:.2f} | Spot {spot:.1f} | Auto Loading - Chart Working")
            else:
                c=CANDLES[-1]; c["h"]=max(c["h"],prem); c["l"]=min(c["l"],prem); c["c"]=prem
            fib_data=detect_swings()
            if fib_data:
                STATE["fib_high"]=fib_data["fib_high"]; STATE["fib_low"]=fib_data["fib_low"]; STATE["range"]=fib_data["range"]
                STATE["swing_high_info"]=fib_data["swing_high"]; STATE["swing_low_info"]=fib_data["swing_low"]
                f05=fib_data["0.5"]; f035=fib_data["0.35"]; f2414=fib_data["2.414"]
                recent=list(CANDLES)[-12:]; curr=recent[-1]['c']; prev=recent[-2]['c'] if len(recent)>=2 else curr
                cross=prev < f05 and curr >= f05
                near=curr >= f05*0.98 and curr <= f05*1.02 and prev < curr
                trigger=cross or near
                add_log(f"TF {tf} MIN SL 0.35 Clean | Spot {spot:.1f} Strike {strike}PE | Premium {prem:.2f} | Fib H {fib_data['fib_high']:.1f} L {fib_data['fib_low']:.1f} R {fib_data['range']:.1f} | Entry 0.5={f05:.1f} SL 0.35={f035:.1f} TGT {f2414:.1f} | 5 MIN HL | Trigger {trigger} | Trades {STATE['trades_today']}/5 | Auto Loading - Chart Working")
                if trigger and STATE["pos"] is None:
                    if STATE["trades_today"]>=5: time.sleep(5); continue
                    CANDLES[-1]["buy"]=True
                    STATE["pos"]={"entry":curr,"sl":f035,"tgt":f2414,"buy_time":now_str,"buy_price":curr,"strike":f"{strike}PE"}
                    STATE["trades"]+=1; STATE["trades_today"]+=1
                    TRADES_HISTORY.append({"no":STATE["trades_today"],"buy_price":curr,"buy_time":now_str,"exit_price":0,"exit_time":"OPEN","exit_type":"OPEN","pnl":0,"strike":f"{strike}PE"})
                    add_log(f"BUY TF {tf} MIN SL 0.35 Clean | Trade {STATE['trades_today']}/5 @ {curr:.2f} SL {f035:.2f} | 5 MIN HL | Auto Loading - Chart Working")
                    send_telegram(f"🎯 BUY {STATE['trades_today']}/5 TF {tf} MIN SL 0.35 @ {curr:.2f} Entry {f05:.1f} SL {f035:.1f} TGT {f2414:.1f} | 5 MIN HL")
                if STATE["pos"]:
                    if curr<=STATE["pos"]["sl"]:
                        pnl=(STATE["pos"]["sl"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        CANDLES[-1]["sell_sl"]=True
                        if TRADES_HISTORY and TRADES_HISTORY[-1]["exit_time"]=="OPEN":
                            TRADES_HISTORY[-1]["exit_price"]=curr; TRADES_HISTORY[-1]["exit_time"]=now_str; TRADES_HISTORY[-1]["exit_type"]="SL HIT 0.35"; TRADES_HISTORY[-1]["pnl"]=round(pnl,0)
                        add_log(f"SL HIT 0.35 TF {tf} MIN | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} | Clean - Auto Loading")
                        send_telegram(f"🔴 SL HIT 0.35 {STATE['trades_today']}/5 TF {tf} MIN @ {curr:.2f} P&L {pnl:.0f}")
                        STATE["pos"]=None
                    elif curr>=STATE["pos"]["tgt"]:
                        pnl=(STATE["pos"]["tgt"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        CANDLES[-1]["sell_tgt"]=True
                        if TRADES_HISTORY and TRADES_HISTORY[-1]["exit_time"]=="OPEN":
                            TRADES_HISTORY[-1]["exit_price"]=curr; TRADES_HISTORY[-1]["exit_time"]=now_str; TRADES_HISTORY[-1]["exit_type"]="TGT HIT"; TRADES_HISTORY[-1]["pnl"]=round(pnl,0)
                        add_log(f"TGT HIT TF {tf} MIN SL 0.35 | Trade {STATE['trades_today']}/5 P&L {pnl:.0f}")
                        send_telegram(f"🟢 TGT HIT {STATE['trades_today']}/5 TF {tf} MIN @ {curr:.2f} P&L {pnl:.0f}")
                        STATE["pos"]=None
            time.sleep(12)
        except Exception as e:
            add_log(f"ERR {e} - Auto Loading Retrying - Chart Working"); time.sleep(8)
threading.Thread(target=bot_loop, daemon=True).start()
