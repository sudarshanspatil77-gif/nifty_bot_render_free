
from flask import Flask, jsonify
import threading, time, os, requests, random
from datetime import datetime
import pytz
from collections import deque

app = Flask(__name__)
LOGS = deque(maxlen=500)
CANDLES = deque(maxlen=500)
TRADES_HISTORY = deque(maxlen=20)
STATE = {"trades":0,"trades_today":0,"max_trades":5,"pnl":0,"spot":22527,"prem":87.30,"strike":22250,"fib_high":90.2,"fib_low":60.2,"range":30.0,"pos":None,"telegram_ok":False,"trade_date":None,"telegram_limit_sent":False,"telegram_enabled":True}

IST = pytz.timezone('Asia/Kolkata')

def add_log(m):
    ts=datetime.now(IST).strftime("%H:%M:%S")
    LOGS.append(f"{ts} | {m}")

def is_market_open():
    now=datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    if STATE["trade_date"] != today:
        if STATE["trade_date"] is not None:
            add_log(f"NEW DAY {today} Reset 0/5 - Telegram ON")
        STATE["trade_date"]=today; STATE["trades_today"]=0; STATE["trades"]=0; STATE["telegram_limit_sent"]=False; STATE["telegram_enabled"]=True
    if now.weekday()>=5: return False, f"Closed Weekend {now.strftime('%A')}", False
    mo=now.replace(hour=9,minute=15,second=0,microsecond=0); mc=now.replace(hour=15,minute=30,second=0,microsecond=0)
    if now<mo: return False, f"Closed Pre-Market {now.strftime('%H:%M')} Opens 9:15 AM", False
    if now>mc: return False, f"Closed Post-Market {now.strftime('%H:%M')} Closed 3:30 PM", False
    if STATE["trades_today"]>=5: return False, f"5 Trades Limit {STATE['trades_today']}/5 No More Trading - Telegram OFF", True
    return True, f"Market Open 9:15 AM Trading ON - {STATE['trades_today']}/5 - Swing 15+ Candle", False

def send_telegram(text):
    # 5 Trade complete zale nantar telegram band - Check
    if STATE["trades_today"] >= STATE["max_trades"]:
        if not STATE["telegram_limit_sent"]:
            # Fakt ekda last message pathav - Mag band
            try:
                token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
                if not token or not chat: return False
                last_msg = f"🔕 *5 Trades Complete - Telegram OFF*\nTrades Today: {STATE['trades_today']}/5\nNo More Telegram Messages Today\nBot Band - Udya 9:15 AM Parat ON\nP&L Today: Rs.{STATE['pnl']}"
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":last_msg,"parse_mode":"Markdown"},timeout=10)
                STATE["telegram_limit_sent"]=True
                STATE["telegram_enabled"]=False
                add_log(f"TELEGRAM OFF | 5 Trades Complete {STATE['trades_today']}/5 - Last Telegram Sent - Aata Telegram Band - No More Messages Today")
            except:
                pass
        return False  # Aata pudhe kuthla pan telegram nahi
    
    if not STATE["telegram_enabled"]:
        return False
    
    try:
        token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat: return False
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":text,"parse_mode":"Markdown"},timeout=10)
        if r.status_code==200: STATE["telegram_ok"]=True; return True
        return False
    except: return False

def get_real_nse():
    try:
        headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.nseindia.com/option-chain"}
        s=requests.Session(); s.headers.update(headers)
        s.get("https://www.nseindia.com/option-chain",timeout=8)
        r=s.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",timeout=8)
        if r.status_code==200:
            d=r.json(); spot=float(d["records"]["underlyingValue"])
            strike=int((spot*0.988)//50*50); prem=None
            for it in d["records"]["data"]:
                if it.get("strikePrice")==strike and it.get("PE"): prem=float(it["PE"]["lastPrice"]); break
            if prem and prem>0: return spot, prem, strike, "NSE_LIVE_REAL"
    except: pass
    return 22527+random.uniform(-15,15), 87.3+random.uniform(-3,3), 22250, "LIVE_SIM"

def detect_swings_15_candle():
    if len(CANDLES) < 20: return None
    clist = list(CANDLES)
    WINDOW = 7
    MIN_GAP = 15
    swing_highs = []
    swing_lows = []
    for i in range(WINDOW, len(clist)-WINDOW):
        curr = clist[i]
        is_high = True
        is_low = True
        for j in range(i-WINDOW, i+WINDOW+1):
            if j == i: continue
            if clist[j]['h'] >= curr['h']: is_high = False
            if clist[j]['l'] <= curr['l']: is_low = False
        if is_high: swing_highs.append({"idx":i,"value":curr['h'],"time":curr['t'],"candle":curr})
        if is_low: swing_lows.append({"idx":i,"value":curr['l'],"time":curr['t'],"candle":curr})
    if not swing_highs or not swing_lows: return None
    filtered_highs = []
    last_idx = -100
    for sh in swing_highs:
        if sh['idx'] - last_idx >= MIN_GAP:
            filtered_highs.append(sh); last_idx = sh['idx']
        else:
            if sh['value'] > filtered_highs[-1]['value']:
                filtered_highs[-1] = sh; last_idx = sh['idx']
    filtered_lows = []
    last_idx = -100
    for sl in swing_lows:
        if sl['idx'] - last_idx >= MIN_GAP:
            filtered_lows.append(sl); last_idx = sl['idx']
        else:
            if sl['value'] < filtered_lows[-1]['value']:
                filtered_lows[-1] = sl; last_idx = sl['idx']
    if not filtered_highs or not filtered_lows: return None
    recent_high = filtered_highs[-1]
    recent_low = filtered_lows[-1]
    if abs(recent_high['idx'] - recent_low['idx']) < 5:
        if len(filtered_highs) >=2 and recent_high['idx'] > recent_low['idx']:
            recent_high = filtered_highs[-2]
        elif len(filtered_lows) >=2 and recent_low['idx'] > recent_high['idx']:
            recent_low = filtered_lows[-2]
    fib_high_actual = max(recent_high['value'], recent_low['value'])
    fib_low_actual = min(recent_high['value'], recent_low['value'])
    rng = fib_high_actual - fib_low_actual
    if rng < 5: return None
    return {"swing_high":recent_high,"swing_low":recent_low,"fib_high":fib_high_actual,"fib_low":fib_low_actual,"range":rng,"0.36":fib_low_actual+rng*0.36,"0.5":fib_low_actual+rng*0.5,"2.414":fib_low_actual+rng*2.414,"all_highs":filtered_highs[-5:],"all_lows":filtered_lows[-5:],"total_swings_high":len(filtered_highs),"total_swings_low":len(filtered_lows),"window":15}

def is_marubozu(c):
    body=abs(c['c']-c['o']); rng=c['h']-c['l']
    return rng>0 and c['c']>c['o'] and body/rng>=0.70

for i in range(30):
    c=60+i*1.2+random.uniform(-1,2)
    if i==5: c=85
    if i==22: c=58
    CANDLES.append({"o":c-1,"h":c+1.5,"l":c-1.2,"c":c,"t":f"10:{i:02d}","maru":False,"buy":False,"sell_sl":False,"sell_tgt":False})

HTML = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{background:#0f172a;color:#e2e8f0;padding:10px;font-family:Arial;margin:0}
h2{color:#22c55e;text-align:center;margin:6px 0;font-size:12px;background:#1e293b;padding:8px;border-radius:10px;border:2px solid #22c55e}
.card{background:#1e293b;padding:12px;border-radius:12px;margin:8px 0;border:1px solid #334155}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.box{background:#0f172a;padding:10px;border-radius:10px;border:1px solid #334155;text-align:center}
.box .l{color:#94a3b8;font-size:10px} .box .v{color:#fff;font-size:15px;font-weight:bold;margin-top:3px}
.entry{color:#22c55e !important} .sl{color:#f97316 !important} .tgt{color:#3b82f6 !important} .prem{color:#eab308 !important}
#chart{background:#ffffff;border-radius:12px;padding:10px;margin:8px 0;min-height:600px;border:3px solid #22c55e}
canvas{width:100%;height:520px;background:#fff;border-radius:8px}
.btn{padding:7px 12px;font-weight:bold;border-radius:8px;text-decoration:none;display:inline-block;margin:3px;font-size:11px}
.btn-g{background:#22c55e;color:#000} .btn-y{background:#eab308;color:#000} .btn-b{background:#3b82f6;color:#fff} .btn-r{background:#ef4444;color:#fff}
.small{font-size:10px;color:#94a3b8}
.status-open{color:#000;background:#22c55e;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:bold;border:2px solid #fff}
.status-closed{color:#fff;background:#ef4444;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:bold}
.status-limit{color:#fff;background:#6b7280;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:bold;border:2px solid #eab308}
.limit-box{background:#1a1a00;padding:10px;border-radius:10px;border:3px solid #eab308;margin:8px 0;text-align:center}
.swing-box{background:#1a0a0a;padding:10px;border-radius:10px;border:3px solid #ef4444;margin:8px 0;text-align:center}
.telegram-box{background:#1a0a1a;padding:10px;border-radius:10px;border:3px solid #ec4899;margin:8px 0;text-align:center}
.live-dot{animation:blink 1s infinite;width:10px;height:10px;background:#22c55e;border-radius:50%;display:inline-block}
@keyframes blink{0%{opacity:1}50%{opacity:0.3}100%{opacity:1}}
</style></head><body>
<h2>🇮🇳 5 Trade Complete - Telegram OFF - 15+ Candle Swing - Market Open 9:15 AM</h2>

<div class="telegram-box">
<div style="color:#ec4899;font-weight:bold;font-size:14px">🔕 5 Trade Complete Zale Nantar Telegram Message Pan Band!</div>
<div style="display:flex;gap:10px;justify-content:center;margin-top:8px;flex-wrap:wrap">
<div style="background:#0f172a;padding:8px 16px;border-radius:8px;border:2px solid #22c55e"><div class="small">Trades Today</div><div id="trades_today_top" style="color:#22c55e;font-size:22px;font-weight:bold">0/5</div></div>
<div style="background:#0f172a;padding:8px 16px;border-radius:8px;border:2px solid #ec4899"><div class="small">Telegram Status</div><div id="tg_status_top" style="color:#ec4899;font-size:14px;font-weight:bold">● ON - Active</div></div>
<div style="background:#0f172a;padding:8px 16px;border-radius:8px;border:2px solid #eab308"><div class="small">Remaining</div><div id="trades_remain_top" style="color:#eab308;font-size:22px;font-weight:bold">5 Left</div></div>
</div>
<div class="small" style="margin-top:6px;color:#94a3b8">5 Trade complete zale ki Telegram OFF hoil - Last message: "5 Trades Complete - Telegram OFF" - Mag kuthla pan message nahi - Udya 9:15 AM la parat ON</div>
</div>

<div class="swing-box">
<div style="color:#ef4444;font-weight:bold;font-size:13px">📊 1 MIN - More Than 15 Candle Cha Swing - Strong Swing</div>
<div style="display:flex;gap:10px;justify-content:center;margin-top:6px;flex-wrap:wrap">
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #ef4444"><div class="small">Swing Window</div><div style="color:#ef4444;font-size:16px;font-weight:bold">15+ Candle</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #22c55e"><div class="small">Min Gap</div><div style="color:#22c55e;font-size:16px;font-weight:bold">15 Candle</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #eab308"><div class="small">Total Swing</div><div id="total_swings" style="color:#eab308;font-size:14px;font-weight:bold">H:0 L:0</div></div>
</div>
</div>

<div class="limit-box">
<div style="color:#eab308;font-weight:bold;font-size:13px">⏰ Only 5 Trade in a Day - Chart Auto Upload - Telegram Auto OFF After 5</div>
<div style="display:flex;gap:10px;justify-content:center;margin-top:6px;flex-wrap:wrap">
<div style="background:#0f172a;padding:8px 16px;border-radius:8px;border:2px solid #22c55e"><div class="small">Trades Today</div><div id="trades_today" style="color:#22c55e;font-size:22px;font-weight:bold">0/5</div></div>
<div style="background:#0f172a;padding:8px 16px;border-radius:8px;border:2px solid #eab308"><div class="small">Remaining</div><div id="trades_remain" style="color:#eab308;font-size:22px;font-weight:bold">5 Left</div></div>
<div style="background:#0f172a;padding:8px 16px;border-radius:8px;border:2px solid #ec4899"><div class="small">Telegram</div><div id="telegram_box" style="color:#ec4899;font-size:12px;font-weight:bold">ON</div></div>
</div>
</div>

<div class="card">
<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
<span id="market_status" class="status-open">● Market Open 9:15 AM - 0/5 - Swing 15+ Candle</span>
<span id="nse_status" style="color:#000;background:#eab308;padding:4px 8px;border-radius:6px;font-size:10px">● NSE LIVE</span>
<span id="tg_status" style="color:#fff;background:#22c55e;padding:4px 8px;border-radius:6px;font-size:10px">● TELEGRAM ON</span>
<span id="lt" class="small"></span>
</div>

<div class="grid" style="margin-top:8px">
<div class="box"><div class="l">No. Of Trade (Today)</div><div class="v" id="trades" style="font-size:20px">0/5</div></div>
<div class="box"><div class="l">Which Premium</div><div class="v prem" id="which_prem">22250PE Δ0.30</div></div>
<div class="box"><div class="l">Entry Price (0.5)</div><div class="v entry" id="entry_p">75.20 BUY</div></div>
<div class="box"><div class="l">SL Price (0.36 Trail)</div><div class="v sl" id="sl_p">71.00 → Trail</div></div>
<div class="box"><div class="l">Target Price (2.414)</div><div class="v tgt" id="tgt_p">132.62 TGT</div></div>
<div class="box"><div class="l">Total P&L</div><div class="v" id="pnl" style="color:#22c55e;font-size:20px">Rs.0</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1fr;gap:6px;margin-top:8px">
<div class="box"><div class="l">Swing High 15+</div><div class="v" id="swing_high" style="color:#ef4444">90.2 @10:18</div></div>
<div class="box"><div class="l">Swing Low 15+</div><div class="v" id="swing_low" style="color:#22c55e">60.2 @10:00</div></div>
<div class="box"><div class="l">Fib H L R</div><div class="v small" id="fib_info">H 90.2 L 60.2 R 30.0</div></div>
<div class="box"><div class="l">Spot / Prem</div><div class="v small" id="spot_prem">22527 / 87.30 REAL</div></div>
<div class="box"><div class="l">Telegram</div><div class="v small" id="telegram_info">ON - 5 nantar OFF</div></div>
</div>

<div style="margin-top:10px">
<a class="btn btn-g" href="/test_telegram">🔔 Test Telegram</a>
<a class="btn btn-y" href="/health">Health</a>
<a class="btn btn-b" href="/api/data">API</a>
<a class="btn btn-b" href="/api/candles">Candles</a>
<a class="btn btn-r" href="/disable_telegram">🔕 Disable TG</a>
</div>
</div>

<div id="chart">
<div style="color:#000;font-weight:bold;text-align:center;font-size:12px">📈 LIVE 1 MIN - 15+ Candle Swing + Telegram OFF After 5 Trade - Market Open 9:15 AM</div>
<canvas id="c" width="800" height="520"></canvas>
<div style="color:#000;font-size:9px;text-align:center;margin-top:4px">✅ 1 MIN - 15+ Candle Swing + 5 Trade Complete = Telegram OFF - Last message "5 Trades Complete - Telegram OFF" - Mag kuthla pan message nahi - Udya 9:15 AM parat ON</div>
<div id="trade_list" style="color:#000;font-size:10px;margin-top:8px;background:#f0f0f0;padding:6px;border-radius:6px"></div>
</div>

<div class="card">
<pre id="log" style="background:#0f172a;color:#22c55e;padding:8px;border-radius:8px;border:1px solid #334155;font-size:9px;max-height:250px;overflow:auto;white-space:pre-wrap"></pre>
</div>

<script>
let candles=[];
let fib={low:60.2,high:90.2,range:30,"0.36":71.0,"0.5":75.2,"2.414":132.62,swingHigh:{value:90.2,time:"10:18",idx:0},swingLow:{value:60.2,time:"10:00",idx:0}};
let tradesHistory=[];

function draw(){
 let canvas=document.getElementById('c'); let ctx=canvas.getContext('2d');
 let W=canvas.width, H=canvas.height, pad=50;
 if(candles.length==0) return;
 ctx.clearRect(0,0,W,H); ctx.fillStyle="#fff"; ctx.fillRect(0,0,W,H);
 let allHighs=candles.map(c=>c.h); let allLows=candles.map(c=>c.l);
 let min=Math.min(...allLows,fib.low,fib["0.36"])-8; let max=Math.max(...allHighs,fib.high,fib["2.414"])+12;
 let y=v=>H-pad-(v-min)/(max-min)*(H-pad*2); let x=i=>pad+i/(candles.length-1)*(W-pad*2);
 ctx.strokeStyle="#eee"; ctx.lineWidth=1;
 for(let i=0;i<=5;i++){let yy=pad+i*(H-pad*2)/5; ctx.beginPath(); ctx.moveTo(pad,yy); ctx.lineTo(W-pad,yy); ctx.stroke(); ctx.fillStyle="#666"; ctx.font="10px Arial"; ctx.fillText((max-(max-min)*i/5).toFixed(0),5,yy);}
 function line(val,color,label,dash,width){ctx.strokeStyle=color; ctx.lineWidth=width||2; ctx.setLineDash(dash||[]); ctx.beginPath(); ctx.moveTo(pad,y(val)); ctx.lineTo(W-pad,y(val)); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle=color; ctx.font="bold 11px Arial"; ctx.fillText(label+" "+val.toFixed(1),W-pad+5,y(val)-2);}
 line(fib.high,"#ef4444","15+C Swing High",[8,4],3);
 line(fib.low,"#000","15+C Swing Low",[8,4],3);
 line(fib["0.5"],"#22c55e","0.5 ENTRY BUY",[],3);
 line(fib["0.36"],"#f97316","0.36 SL Trail",[4,4],2);
 line(fib["2.414"],"#3b82f6","2.414 TGT",[],3);
 candles.forEach((c,i)=>{
  let g=c.c>=c.o; ctx.fillStyle=g?"#22c55e":"#ef4444"; ctx.strokeStyle=g?"#16a34a":"#dc2626";
  let bh=Math.abs(y(c.o)-y(c.c)); let by=Math.min(y(c.o),y(c.c)); let w=Math.max(4, (W-pad*2)/candles.length*0.6);
  ctx.beginPath(); ctx.moveTo(x(i),y(c.h)); ctx.lineTo(x(i),y(c.l)); ctx.stroke();
  ctx.fillRect(x(i)-w/2,by,w,Math.max(2,bh));
  if(c.swingHigh){ctx.fillStyle="#ef4444"; ctx.beginPath(); ctx.moveTo(x(i),y(c.h)-16); ctx.lineTo(x(i)-10,y(c.h)-4); ctx.lineTo(x(i)+10,y(c.h)-4); ctx.closePath(); ctx.fill(); ctx.fillStyle="#ef4444"; ctx.font="bold 10px Arial"; ctx.fillText("▲ 15C SH "+c.h.toFixed(1)+" @"+c.t,x(i)-35,y(c.h)-20);}
  if(c.swingLow){ctx.fillStyle="#22c55e"; ctx.beginPath(); ctx.moveTo(x(i),y(c.l)+16); ctx.lineTo(x(i)-10,y(c.l)+4); ctx.lineTo(x(i)+10,y(c.l)+4); ctx.closePath(); ctx.fill(); ctx.fillStyle="#22c55e"; ctx.font="bold 10px Arial"; ctx.fillText("▼ 15C SL "+c.l.toFixed(1)+" @"+c.t,x(i)-35,y(c.l)+32);}
  if(c.buy){ctx.fillStyle="#22c55e"; ctx.beginPath(); ctx.arc(x(i),y(c.c),14,0,Math.PI*2); ctx.fill(); ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle="#fff"; ctx.font="bold 10px Arial"; ctx.fillText("BUY",x(i)-11,y(c.c)+3);}
  if(c.sell_sl){ctx.fillStyle="#ef4444"; ctx.beginPath(); ctx.arc(x(i),y(c.c),12,0,Math.PI*2); ctx.fill(); ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle="#fff"; ctx.font="bold 9px Arial"; ctx.fillText("SL",x(i)-7,y(c.c)+3);}
  if(c.sell_tgt){ctx.fillStyle="#3b82f6"; ctx.beginPath(); ctx.arc(x(i),y(c.c),12,0,Math.PI*2); ctx.fill(); ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle="#fff"; ctx.font="bold 9px Arial"; ctx.fillText("TGT",x(i)-10,y(c.c)+3);}
 });
 ctx.fillStyle="#000"; ctx.font="9px Arial";
 candles.forEach((c,i)=>{if(i%Math.ceil(candles.length/12)==0){ctx.fillText(c.t,x(i)-10,H-12);}});
}

async function refresh(){
 try{
  let r=await fetch('/api/candles?t='+Date.now()); let j=await r.json();
  candles=j.candles;
  fib.high=j.fib_high; fib.low=j.fib_low; fib.range=j.range; fib["0.5"]=j.entry; fib["0.36"]=j.sl; fib["2.414"]=j.tgt;
  fib.swingHigh=j.swing_high; fib.swingLow=j.swing_low;
  tradesHistory=j.trades_history;
  document.getElementById('trades').innerText=j.trades_today+'/5';
  document.getElementById('trades_today').innerText=j.trades_today+'/5';
  document.getElementById('trades_today_top').innerText=j.trades_today+'/5';
  document.getElementById('trades_remain').innerText=(5-j.trades_today)+' Left';
  document.getElementById('trades_remain_top').innerText=(5-j.trades_today)+' Left';
  document.getElementById('which_prem').innerText=j.strike;
  document.getElementById('entry_p').innerText=j.entry.toFixed(2)+' BUY';
  document.getElementById('sl_p').innerText=j.sl.toFixed(2)+' → Trail';
  document.getElementById('tgt_p').innerText=j.tgt.toFixed(2)+' TGT';
  document.getElementById('pnl').innerText='Rs.'+j.pnl;
  document.getElementById('swing_high').innerText=j.swing_high.value.toFixed(1)+' @'+j.swing_high.time;
  document.getElementById('swing_low').innerText=j.swing_low.value.toFixed(1)+' @'+j.swing_low.time;
  document.getElementById('fib_info').innerText='H '+j.fib_high.toFixed(1)+' L '+j.fib_low.toFixed(1)+' R '+j.range.toFixed(1);
  document.getElementById('spot_prem').innerText=j.spot+' / '+j.prem;
  document.getElementById('total_swings').innerText='H:'+j.total_swings_high+' L:'+j.total_swings_low;
  document.getElementById('market_status').innerText='● '+j.market;
  document.getElementById('market_status').className=j.is_limit?'status-limit':(j.is_open?'status-open':'status-closed');
  
  let tg_on = j.telegram_enabled;
  let tg_text = tg_on ? '● TELEGRAM ON' : '🔕 TELEGRAM OFF';
  let tg_top_text = tg_on ? '● ON - Active' : '🔕 OFF - 5 Done';
  let tg_box_text = tg_on ? 'ON' : '🔕 OFF';
  let tg_info_text = tg_on ? 'ON - 5 nantar OFF' : '🔕 OFF - 5 Done';
  let tg_class = tg_on ? 'status-open' : 'status-limit';
  
  document.getElementById('tg_status').innerText=tg_text;
  document.getElementById('tg_status_top').innerText=tg_top_text;
  document.getElementById('telegram_box').innerText=tg_box_text;
  document.getElementById('telegram_info').innerText=tg_info_text;
  document.getElementById('tg_status').className=tg_on ? 'status-open' : 'status-limit';
  
  if(!tg_on){
   document.getElementById('tg_status').style.background='#6b7280';
   document.getElementById('tg_status').style.color='#fff';
   document.getElementById('tg_status_top').style.color='#6b7280';
  } else {
   document.getElementById('tg_status').style.background='#22c55e';
   document.getElementById('tg_status_top').style.color='#22c55e';
  }
  
  document.getElementById('log').innerText=j.logs.slice(-25).join('\n');
  let tl=document.getElementById('trade_list');
  if(tradesHistory.length>0){
   tl.innerHTML='<b>📊 Trades History - Telegram '+(tg_on?'ON':'OFF after 5')+':</b><br>'+tradesHistory.map(t=>`Trade ${t.no}/5: BUY @${t.buy_price.toFixed(1)} ${t.buy_time} → ${t.exit_type} @${t.exit_price.toFixed(1)} ${t.exit_time} P&L Rs.${t.pnl}`).join('<br>');
  } else {
   tl.innerHTML='<b>📊 Trades History:</b> No trades yet - 5 Trade nantar Telegram OFF hoil';
  }
  draw();
 }catch(e){console.log(e);}
}
setInterval(refresh,4000); refresh();
setInterval(()=>{document.getElementById('lt').innerText=new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})},1000);
</script>
</body></html>
"""

@app.route('/')
def home(): return HTML

@app.route('/api/candles')
def api_candles():
    is_open, market_msg, is_limit = is_market_open()
    clist = list(CANDLES)
    return jsonify({
        "candles":clist[-100:],
        "trades_today":STATE["trades_today"],"trades":STATE["trades"],"max_trades":5,"trade_date":STATE["trade_date"],
        "strike":f"{STATE['strike']}PE Δ0.30",
        "entry":STATE["fib_low"]+STATE["range"]*0.5,"sl":STATE["fib_low"]+STATE["range"]*0.36,"tgt":STATE["fib_low"]+STATE["range"]*2.414,
        "pnl":STATE["pnl"],"spot":f"{STATE['spot']} LIVE","prem":f"{STATE['prem']} REAL",
        "fib_high":STATE["fib_high"],"fib_low":STATE["fib_low"],"range":STATE["range"],
        "swing_high":STATE.get("swing_high_info",{"value":STATE["fib_high"],"time":"10:18","idx":0}),
        "swing_low":STATE.get("swing_low_info",{"value":STATE["fib_low"],"time":"10:00","idx":0}),
        "total_swings_high":STATE.get("total_swings_high",0),
        "total_swings_low":STATE.get("total_swings_low",0),
        "window":15,"min_gap":15,
        "trades_history":list(TRADES_HISTORY)[-10:],
        "telegram_enabled":STATE["telegram_enabled"],
        "telegram_limit_sent":STATE["telegram_limit_sent"],
        "src":STATE.get("src","NSE_LIVE"),"telegram_ok":STATE["telegram_ok"],"is_open":is_open,"is_limit":is_limit,"market":market_msg,"logs":list(LOGS)[-30:]
    })

@app.route('/api/data')
def api_data():
    is_open, market_msg, is_limit = is_market_open()
    return jsonify({
        "trades_today":STATE["trades_today"],"trades":STATE["trades"],
        "strike":f"{STATE['strike']}PE Δ0.30",
        "entry":STATE["fib_low"]+STATE["range"]*0.5,"sl":STATE["fib_low"]+STATE["range"]*0.36,"tgt":STATE["fib_low"]+STATE["range"]*2.414,
        "pnl":STATE["pnl"],"spot":f"{STATE['spot']} LIVE","prem":f"{STATE['prem']} REAL",
        "fib_high":STATE["fib_high"],"fib_low":STATE["fib_low"],"range":STATE["range"],
        "swing_high":STATE.get("swing_high_info",{"value":STATE["fib_high"],"time":"10:18"}),
        "swing_low":STATE.get("swing_low_info",{"value":STATE["fib_low"],"time":"10:00"}),
        "telegram_enabled":STATE["telegram_enabled"],
        "src":STATE.get("src","NSE_LIVE"),"telegram_ok":STATE["telegram_ok"],"is_open":is_open,"is_limit":is_limit,"market":market_msg,"logs":list(LOGS)[-30:]
    })

@app.route('/health')
def health():
    is_open, msg, is_limit = is_market_open()
    return jsonify({"status":"OK","market":msg,"trades_today":f"{STATE['trades_today']}/5","telegram": "ON" if STATE["telegram_enabled"] else "OFF - 5 Done","swing":"15+ Candle","is_limit":is_limit})

@app.route('/test_telegram')
def test():
    if not STATE["telegram_enabled"]:
        return jsonify({"ok":False,"msg":"Telegram OFF - 5 Trades Complete - No More Messages Today - Udya 9:15 AM ON"})
    token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat: return jsonify({"ok":False})
    try:
        txt=f"Telegram ON Test - Trades Today: {STATE['trades_today']}/5 - 5 nantar OFF hoil"
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":txt,"parse_mode":"Markdown"},timeout=10)
        return jsonify({"ok":r.status_code==200})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})

@app.route('/disable_telegram')
def disable_tg():
    STATE["telegram_enabled"]=False
    STATE["telegram_limit_sent"]=True
    add_log("TELEGRAM MANUALLY OFF | User ne band kela")
    return jsonify({"ok":True,"msg":"Telegram OFF - No More Messages Today - Udya 9:15 AM ON"})

def bot_loop():
    add_log("BOT | 5 Trade Complete -> Telegram OFF - 15+ Candle Swing")
    time.sleep(3)
    send_telegram("🚀 Bot Started\n5 Trade Complete Zale Nantar Telegram OFF\nSwing: 15+ Candle Strong\nMarket Open 9:15 AM")
    while True:
        try:
            is_open, market_msg, is_limit = is_market_open()
            if not is_open:
                # Telegram band asel tar sleep log madhe telegram off dakhav
                if is_limit:
                    if STATE["telegram_enabled"]:
                        # Send final off message via send_telegram (it will send last msg and disable)
                        send_telegram(f"5 Trades Done - Telegram OFF trigger")
                    add_log(f"{market_msg} - Telegram OFF - Sleeping 60s - No More Telegram Today")
                else:
                    add_log(f"{market_msg} - Sleeping 60s")
                time.sleep(60); continue
            spot, prem, strike, src = get_real_nse()
            STATE["spot"]=round(spot,2); STATE["prem"]=round(prem,2); STATE["strike"]=strike; STATE["src"]=src
            now=datetime.now(IST).strftime("%H:%M")
            if len(CANDLES)==0 or CANDLES[-1]["t"]!=now:
                CANDLES.append({"o":prem,"h":prem,"l":prem,"c":prem,"t":now,"maru":False,"buy":False,"sell_sl":False,"sell_tgt":False})
            else:
                c=CANDLES[-1]; c["h"]=max(c["h"],prem); c["l"]=min(c["l"],prem); c["c"]=prem; c["maru"]=is_marubozu(c)
            fib_data = detect_swings_15_candle()
            if fib_data:
                STATE["fib_high"]=fib_data["fib_high"]; STATE["fib_low"]=fib_data["fib_low"]; STATE["range"]=fib_data["range"]
                STATE["swing_high_info"]=fib_data["swing_high"]; STATE["swing_low_info"]=fib_data["swing_low"]
                STATE["total_swings_high"]=fib_data["total_swings_high"]; STATE["total_swings_low"]=fib_data["total_swings_low"]
                f05=fib_data["0.5"]; f036=fib_data["0.36"]; f2414=fib_data["2.414"]
                recent=list(CANDLES)[-25:]; curr=recent[-1]['c']; prev=recent[-2]['c'] if len(recent)>=2 else curr
                closes=[r['c'] for r in recent]; ema=sum(closes)/len(closes) if closes else curr
                cross=prev<f05 and curr>=f05; above=curr>ema
                add_log(f"15+C SWING | H {fib_data['swing_high']['value']:.1f} L {fib_data['swing_low']['value']:.1f} | Gap 15 OK | Window 15 | Total H:{fib_data['total_swings_high']} L:{fib_data['total_swings_low']} | Fib 0.5 {f05:.1f} | Cross {cross} | Trades {STATE['trades_today']}/5 | Telegram {'ON' if STATE['telegram_enabled'] else 'OFF'}")
                if cross and above and STATE["pos"] is None:
                    if STATE["trades_today"]>=5: 
                        add_log(f"5 Trade Limit {STATE['trades_today']}/5 No BUY - Telegram OFF")
                        time.sleep(20); continue
                    CANDLES[-1]["buy"]=True
                    STATE["pos"]={"entry":curr,"sl":f036,"tgt":f2414,"buy_time":now,"buy_price":curr,"strike":f"{strike}PE"}
                    STATE["trades"]+=1; STATE["trades_today"]+=1
                    add_log(f"BUY 15+C | Trade {STATE['trades_today']}/5 | BUY {strike}PE @ {curr:.1f} {now} | Telegram {'ON' if STATE['telegram_enabled'] else 'OFF'} | Remaining {5-STATE['trades_today']}")
                    send_telegram(f"🎯 *BUY {STATE['trades_today']}/5 - 15+ Candle*\nPremium: {strike}PE\nBUY @ {curr:.2f} {now}\nEntry 0.5: {f05:.2f} SL: {f036:.2f} TGT: {f2414:.2f}\nRemaining: {5-STATE['trades_today']} Left\nTelegram: {'ON' if STATE['trades_today']<5 else 'OFF after this'}")
                    if STATE["trades_today"]>=5:
                        # 5th trade - Send final and turn off
                        time.sleep(1)
                        send_telegram(f"🔕 *5 Trades Complete - Telegram OFF*\n{STATE['trades_today']}/5 Done\nNo More Telegram Today\nBot Band - Udya 9:15 AM ON")
                        add_log(f"5 TRADE COMPLETE | Telegram OFF - No More Messages Today - Udya 9:15 AM ON")
                if STATE["pos"]:
                    if CANDLES[-1]["maru"]:
                        new_low=CANDLES[-1]["l"]; new_rng=STATE["fib_high"]-new_low; new_sl=new_low+new_rng*0.36
                        if new_sl>STATE["pos"]["sl"]: STATE["pos"]["sl"]=new_sl
                    if curr<=STATE["pos"]["sl"]:
                        pnl=(STATE["pos"]["sl"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        CANDLES[-1]["sell_sl"]=True
                        TRADES_HISTORY.append({"no":STATE["trades_today"],"buy_price":STATE["pos"]["buy_price"],"buy_time":STATE["pos"]["buy_time"],"exit_price":curr,"exit_time":now,"exit_type":"SL HIT","pnl":round(pnl,0),"strike":STATE["pos"]["strike"]})
                        add_log(f"SL HIT | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} | Telegram {'ON' if STATE['telegram_enabled'] else 'OFF'}")
                        send_telegram(f"🔴 *SL HIT {STATE['trades_today']}/5*\nSL @ {curr:.2f} {now}\nP&L {pnl:.0f} Total {STATE['pnl']:.0f}\nTelegram {'ON' if STATE['trades_today']<5 else 'OFF after 5'}")
                        STATE["pos"]=None
                        if STATE["trades_today"]>=5:
                            time.sleep(1)
                            send_telegram(f"🔕 *5 Trades Done - Telegram OFF*\nP&L Today: Rs.{STATE['pnl']}\nNo More Telegram Today")
                    elif curr>=STATE["pos"]["tgt"]:
                        pnl=(STATE["pos"]["tgt"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        CANDLES[-1]["sell_tgt"]=True
                        TRADES_HISTORY.append({"no":STATE["trades_today"],"buy_price":STATE["pos"]["buy_price"],"buy_time":STATE["pos"]["buy_time"],"exit_price":curr,"exit_time":now,"exit_type":"TGT HIT 2.414","pnl":round(pnl,0),"strike":STATE["pos"]["strike"]})
                        add_log(f"TGT HIT | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} | Telegram {'ON' if STATE['telegram_enabled'] else 'OFF'}")
                        send_telegram(f"🟢 *TGT HIT {STATE['trades_today']}/5*\nTGT @ {curr:.2f} {now}\nP&L {pnl:.0f} Total {STATE['pnl']:.0f}\nTelegram {'ON' if STATE['trades_today']<5 else 'OFF after 5'}")
                        STATE["pos"]=None
                        if STATE["trades_today"]>=5:
                            time.sleep(1)
                            send_telegram(f"🔕 *5 Trades Done - Telegram OFF*\nP&L Today: Rs.{STATE['pnl']}\nNo More Telegram Today")
            time.sleep(20)
        except Exception as e:
            import traceback; add_log(f"ERR {e}"); time.sleep(10)

threading.Thread(target=bot_loop, daemon=True).start()
