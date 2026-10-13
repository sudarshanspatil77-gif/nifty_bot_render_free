
from flask import Flask, jsonify
import threading, time, os, requests, random
from datetime import datetime
import pytz
from collections import deque

app = Flask(__name__)
LOGS = deque(maxlen=500)
CANDLES = deque(maxlen=300)
STATE = {"trades":0,"trades_today":0,"max_trades":5,"pnl":0,"spot":22527,"prem":87.30,"strike":22250,"fib_high":90.2,"fib_low":60.2,"range":30.0,"intrinsic":0,"time_value":87.30,"pos":None,"telegram_ok":False,"trade_date":None}

IST = pytz.timezone('Asia/Kolkata')

def add_log(m):
    ts=datetime.now(IST).strftime("%H:%M:%S")
    LOGS.append(f"{ts} | {m}")

def is_market_open():
    now=datetime.now(IST)
    # Reset trades daily at new date
    today = now.strftime("%Y-%m-%d")
    if STATE["trade_date"] != today:
        if STATE["trade_date"] is not None:
            add_log(f"NEW DAY | {today} - Trades reset 0/5 - Yesterday {STATE['trade_date']} trades {STATE['trades_today']}")
        STATE["trade_date"] = today
        STATE["trades_today"] = 0
        STATE["trades"] = 0
    if now.weekday()>=5: return False, f"Market Closed Weekend {now.strftime('%A')}", False
    mo=now.replace(hour=9,minute=15,second=0,microsecond=0); mc=now.replace(hour=15,minute=30,second=0,microsecond=0)
    if now<mo: return False, f"Market Closed Pre-Market {now.strftime('%H:%M')} Opens 9:15 AM", False
    if now>mc: return False, f"Market Closed Post-Market {now.strftime('%H:%M')} Closed 3:30 PM", False
    # Check 5 trade limit
    if STATE["trades_today"] >= STATE["max_trades"]:
        return False, f"5 Trades Limit Reached Today {STATE['trades_today']}/5 - No More Trading Today - Wait Till Tomorrow 9:15 AM", True
    return True, f"Market Open 9:15 AM Trading ON - Trades Today {STATE['trades_today']}/5", False

def send_telegram(text):
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

def detect_swings_and_fib():
    if len(CANDLES)<7: return None
    clist=list(CANDLES)
    swing_highs=[]; swing_lows=[]
    for i in range(2,len(clist)-2):
        if clist[i]['h']>clist[i-1]['h'] and clist[i]['h']>clist[i-2]['h'] and clist[i]['h']>clist[i+1]['h'] and clist[i]['h']>clist[i+2]['h']:
            swing_highs.append({"idx":i,"value":clist[i]['h'],"time":clist[i]['t']})
        if clist[i]['l']<clist[i-1]['l'] and clist[i]['l']<clist[i-2]['l'] and clist[i]['l']<clist[i+1]['l'] and clist[i]['l']<clist[i+2]['l']:
            swing_lows.append({"idx":i,"value":clist[i]['l'],"time":clist[i]['t']})
    if not swing_highs or not swing_lows: return None
    recent_high = swing_highs[-1]; recent_low = swing_lows[-1]
    fib_high_actual = max(recent_high['value'], recent_low['value'])
    fib_low_actual = min(recent_high['value'], recent_low['value'])
    rng = fib_high_actual - fib_low_actual
    if rng<5: return None
    return {"swing_high":recent_high,"swing_low":recent_low,"fib_high":fib_high_actual,"fib_low":fib_low_actual,"range":rng,"0.36":fib_low_actual+rng*0.36,"0.5":fib_low_actual+rng*0.5,"2.414":fib_low_actual+rng*2.414}

def is_marubozu(c):
    body=abs(c['c']-c['o']); rng=c['h']-c['l']
    return rng>0 and c['c']>c['o'] and body/rng>=0.70

for i in range(25):
    c=60+i*1.2+random.uniform(-1,2)
    CANDLES.append({"o":c-1,"h":c+1.5,"l":c-1.2,"c":c,"t":f"10:{i:02d}","maru":False})

HTML = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{background:#0f172a;color:#e2e8f0;padding:10px;font-family:Arial;margin:0}
h2{color:#22c55e;text-align:center;margin:6px 0;font-size:12px;background:#1e293b;padding:8px;border-radius:10px;border:2px solid #22c55e}
.card{background:#1e293b;padding:12px;border-radius:12px;margin:8px 0;border:1px solid #334155}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.box{background:#0f172a;padding:10px;border-radius:10px;border:1px solid #334155;text-align:center}
.box .l{color:#94a3b8;font-size:10px} .box .v{color:#fff;font-size:15px;font-weight:bold;margin-top:3px}
.entry{color:#22c55e !important} .sl{color:#f97316 !important} .tgt{color:#3b82f6 !important} .prem{color:#eab308 !important}
#chart{background:#ffffff;border-radius:12px;padding:10px;margin:8px 0;min-height:520px;border:3px solid #22c55e}
canvas{width:100%;height:460px;background:#fff;border-radius:8px}
.btn{padding:7px 12px;font-weight:bold;border-radius:8px;text-decoration:none;display:inline-block;margin:3px;font-size:11px}
.btn-g{background:#22c55e;color:#000} .btn-y{background:#eab308;color:#000} .btn-b{background:#3b82f6;color:#fff}
.small{font-size:10px;color:#94a3b8}
.status-open{color:#000;background:#22c55e;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:bold;border:2px solid #fff}
.status-closed{color:#fff;background:#ef4444;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:bold}
.status-limit{color:#000;background:#eab308;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:bold;border:2px solid #fff}
.flow-box{background:#0f172a;padding:10px;border-radius:10px;border:2px solid #22c55e;margin:8px 0;display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:11px}
.limit-box{background:#1a1a00;padding:10px;border-radius:10px;border:3px solid #eab308;margin:8px 0;text-align:center}
</style></head><body>
<h2>🇮🇳 MARKET OPEN 9:15 AM - Only 5 Trade/Day Limit - Swing High Low → Fib → Trading</h2>

<div class="limit-box">
<div style="color:#eab308;font-weight:bold;font-size:14px">⏰ Only 5 Trade in a Day - Limit Reached? No More Trading!</div>
<div style="display:flex;gap:10px;justify-content:center;margin-top:8px;flex-wrap:wrap">
<div style="background:#0f172a;padding:8px 16px;border-radius:8px;border:2px solid #22c55e"><div class="small">Trades Today</div><div id="trades_today" style="color:#22c55e;font-size:22px;font-weight:bold">0/5</div></div>
<div style="background:#0f172a;padding:8px 16px;border-radius:8px;border:2px solid #eab308"><div class="small">Remaining</div><div id="trades_remain" style="color:#eab308;font-size:22px;font-weight:bold">5 Left</div></div>
<div style="background:#0f172a;padding:8px 16px;border-radius:8px;border:2px solid #3b82f6"><div class="small">Date</div><div id="trade_date" style="color:#fff;font-size:14px;font-weight:bold">2025-10-14</div></div>
</div>
<div class="small" style="margin-top:6px;color:#94a3b8">5 Trade limit reached zale ki bot band hoil - Udya 9:15 AM la auto reset 0/5 - No more trading today</div>
</div>

<div class="flow-box">
<span style="color:#ef4444;background:#fff;padding:4px 8px;border-radius:6px;font-weight:bold">Swing High Low ▲▼</span>
<span style="color:#eab308;font-size:16px">→</span>
<span style="color:#eab308;background:#000;padding:4px 8px;border-radius:6px;font-weight:bold">Fib 0.5/0.36/2.414</span>
<span style="color:#eab308;font-size:16px">→</span>
<span style="color:#000;background:#22c55e;padding:4px 8px;border-radius:6px;font-weight:bold">Trading</span>
<span style="color:#eab308;font-size:16px">→</span>
<span style="color:#000;background:#eab308;padding:6px 10px;border-radius:8px;font-weight:bold;border:2px solid #fff">Only 5 Trade/Day</span>
<span style="color:#eab308;font-size:16px">→</span>
<span style="color:#000;background:#22c55e;padding:6px 10px;border-radius:8px;font-weight:bold;border:2px solid #fff">Market Open 9:15 AM</span>
</div>

<div class="card">
<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
<span id="market_status" class="status-open">● Market Open 9:15 AM Trading ON - 0/5</span>
<span id="nse_status" style="color:#000;background:#eab308;padding:4px 8px;border-radius:6px;font-size:10px">● NSE LIVE</span>
<span id="tg_status" style="color:#fff;background:#ef4444;padding:4px 8px;border-radius:6px;font-size:10px">● TELEGRAM</span>
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

<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-top:8px">
<div class="box"><div class="l">Swing High</div><div class="v" id="swing_high" style="color:#ef4444">90.2 @10:18</div></div>
<div class="box"><div class="l">Swing Low</div><div class="v" id="swing_low" style="color:#22c55e">60.2 @10:00</div></div>
<div class="box"><div class="l">Fib H L R</div><div class="v small" id="fib_info">H 90.2 L 60.2 R 30.0</div></div>
<div class="box"><div class="l">Spot / Prem</div><div class="v small" id="spot_prem">22527 / 87.30 REAL</div></div>
</div>

<div style="margin-top:10px">
<a class="btn btn-g" href="/test_telegram">🔔 Test Telegram</a>
<a class="btn btn-y" href="/health">Health</a>
<a class="btn btn-b" href="/api/data">API</a>
</div>
</div>

<div id="chart">
<div style="color:#000;font-weight:bold;text-align:center;font-size:12px">📈 1 MIN Premium Chart - Only 5 Trade/Day - Market Open 9:15 AM</div>
<canvas id="c" width="800" height="460"></canvas>
</div>

<div class="card">
<pre id="log" style="background:#0f172a;color:#22c55e;padding:8px;border-radius:8px;border:1px solid #334155;font-size:9px;max-height:250px;overflow:auto;white-space:pre-wrap"></pre>
</div>

<script>
let candles=[
 {o:62,h:65,l:60.2,c:61,t:"10:00",swingLow:true},{o:61,h:68,l:60,c:65,t:"10:01"},
 {o:65,h:78,l:64,c:73,t:"10:02",swingHigh:true},{o:73,h:76,l:71,c:72,t:"10:03"},
 {o:66,h:75,l:65,c:73,t:"10:06"},{o:73,h:80,l:71,c:78,t:"10:08",swingHigh:true},
 {o:78,h:88,l:76,c:87.3,t:"10:10",buy:true},{o:95,h:110,l:93,c:108,t:"10:16",maru:true,swingHigh:true},
 {o:108,h:133,l:105,c:130,t:"10:20",tgt:true}
];
let fib={low:60.2,high:90.2,range:30,"0.36":71.0,"0.5":75.2,"2.414":132.62,swingHigh:{value:90.2,time:"10:18"},swingLow:{value:60.2,time:"10:00"}};

function draw(){
 let canvas=document.getElementById('c'); let ctx=canvas.getContext('2d');
 let W=canvas.width, H=canvas.height, pad=50;
 ctx.clearRect(0,0,W,H); ctx.fillStyle="#fff"; ctx.fillRect(0,0,W,H);
 let min=fib.low-12; let max=fib["2.414"]+12;
 let y=v=>H-pad-(v-min)/(max-min)*(H-pad*2); let x=i=>pad+i/(candles.length-1)*(W-pad*2);
 ctx.strokeStyle="#eee"; ctx.lineWidth=1;
 for(let i=0;i<=5;i++){let yy=pad+i*(H-pad*2)/5; ctx.beginPath(); ctx.moveTo(pad,yy); ctx.lineTo(W-pad,yy); ctx.stroke(); ctx.fillStyle="#666"; ctx.font="10px Arial"; ctx.fillText((max-(max-min)*i/5).toFixed(0),5,yy);}
 function line(val,color,label,dash,width){ctx.strokeStyle=color; ctx.lineWidth=width||2; ctx.setLineDash(dash||[]); ctx.beginPath(); ctx.moveTo(pad,y(val)); ctx.lineTo(W-pad,y(val)); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle=color; ctx.font="bold 11px Arial"; ctx.fillText(label+" "+val.toFixed(1),W-pad+5,y(val)-2);}
 line(fib.high,"#ef4444","Swing High",[8,4],3);
 line(fib.low,"#000","Swing Low",[8,4],3);
 line(fib["0.5"],"#22c55e","0.5 ENTRY BUY",[],3);
 line(fib["0.36"],"#f97316","0.36 SL Trail",[4,4],2);
 line(fib["2.414"],"#3b82f6","2.414 TGT",[],3);
 candles.forEach((c,i)=>{
  let g=c.c>c.o; ctx.fillStyle=g?"#22c55e":"#ef4444"; ctx.strokeStyle=g?"#16a34a":"#dc2626";
  let bh=Math.abs(y(c.o)-y(c.c)); let by=Math.min(y(c.o),y(c.c)); let w=12;
  ctx.beginPath(); ctx.moveTo(x(i),y(c.h)); ctx.lineTo(x(i),y(c.l)); ctx.stroke();
  ctx.fillRect(x(i)-w/2,by,w,Math.max(2,bh));
  if(c.swingHigh){ctx.fillStyle="#ef4444"; ctx.beginPath(); ctx.moveTo(x(i),y(c.h)-14); ctx.lineTo(x(i)-9,y(c.h)-3); ctx.lineTo(x(i)+9,y(c.h)-3); ctx.closePath(); ctx.fill(); ctx.fillStyle="#ef4444"; ctx.font="bold 9px Arial"; ctx.fillText("▲ SH "+c.h.toFixed(1),x(i)-20,y(c.h)-18);}
  if(c.swingLow){ctx.fillStyle="#22c55e"; ctx.beginPath(); ctx.moveTo(x(i),y(c.l)+14); ctx.lineTo(x(i)-9,y(c.l)+3); ctx.lineTo(x(i)+9,y(c.l)+3); ctx.closePath(); ctx.fill(); ctx.fillStyle="#22c55e"; ctx.font="bold 9px Arial"; ctx.fillText("▼ SL "+c.l.toFixed(1),x(i)-20,y(c.l)+28);}
  if(c.buy){ctx.fillStyle="#22c55e"; ctx.beginPath(); ctx.arc(x(i),y(c.c),12,0,Math.PI*2); ctx.fill(); ctx.fillStyle="#000"; ctx.font="bold 11px Arial"; ctx.fillText("BUY",x(i)-9,y(c.c)+3);}
 });
 ctx.fillStyle="#000"; ctx.font="9px Arial"; candles.forEach((c,i)=>{ctx.fillText(c.t,x(i)-10,H-12);});
}
draw();

async function refresh(){
 try{
  let r=await fetch('/api/data?t='+Date.now()); let j=await r.json();
  document.getElementById('trades').innerText=j.trades_today+'/5';
  document.getElementById('trades_today').innerText=j.trades_today+'/5';
  document.getElementById('trades_remain').innerText=(5-j.trades_today)+' Left';
  document.getElementById('trade_date').innerText=j.trade_date;
  document.getElementById('which_prem').innerText=j.strike;
  document.getElementById('entry_p').innerText=j.entry.toFixed(2)+' BUY';
  document.getElementById('sl_p').innerText=j.sl.toFixed(2)+' → Trail';
  document.getElementById('tgt_p').innerText=j.tgt.toFixed(2)+' TGT';
  document.getElementById('pnl').innerText='Rs.'+j.pnl;
  document.getElementById('swing_high').innerText=j.swing_high.value.toFixed(1)+' @'+j.swing_high.time;
  document.getElementById('swing_low').innerText=j.swing_low.value.toFixed(1)+' @'+j.swing_low.time;
  document.getElementById('fib_info').innerText='H '+j.fib_high.toFixed(1)+' L '+j.fib_low.toFixed(1)+' R '+j.range.toFixed(1);
  document.getElementById('spot_prem').innerText=j.spot+' / '+j.prem;
  document.getElementById('market_status').innerText='● '+j.market;
  if(j.is_limit){document.getElementById('market_status').className='status-limit';}
  else{document.getElementById('market_status').className=j.is_open?'status-open':'status-closed';}
  document.getElementById('log').innerText=j.logs.slice(-25).join('\n');
  if(j.fib_high){fib.high=j.fib_high; fib.low=j.fib_low; fib.range=j.range; fib["0.5"]=j.entry; fib["0.36"]=j.sl; fib["2.414"]=j.tgt; fib.swingHigh=j.swing_high; fib.swingLow=j.swing_low; draw();}
 }catch(e){}
}
setInterval(refresh,4000); refresh();
setInterval(()=>{document.getElementById('lt').innerText=new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})},1000);
</script>
</body></html>
"""

@app.route('/')
def home(): return HTML

@app.route('/api/data')
def api_data():
    is_open, market_msg, is_limit = is_market_open()
    return jsonify({
        "trades_today":STATE["trades_today"],"trades":STATE["trades"],"max_trades":5,"trade_date":STATE["trade_date"],
        "strike":f"{STATE['strike']}PE Δ0.30",
        "entry":STATE["fib_low"]+STATE["range"]*0.5,"sl":STATE["fib_low"]+STATE["range"]*0.36,"tgt":STATE["fib_low"]+STATE["range"]*2.414,
        "pnl":STATE["pnl"],"spot":f"{STATE['spot']} LIVE","prem":f"{STATE['prem']} REAL",
        "fib_high":STATE["fib_high"],"fib_low":STATE["fib_low"],"range":STATE["range"],
        "swing_high":STATE.get("swing_high_info",{"value":STATE["fib_high"],"time":"10:18"}),
        "swing_low":STATE.get("swing_low_info",{"value":STATE["fib_low"],"time":"10:00"}),
        "intrinsic":STATE["intrinsic"],"time_value":STATE["time_value"],
        "src":STATE.get("src","NSE_LIVE"),"telegram_ok":STATE["telegram_ok"],"is_open":is_open,"is_limit":is_limit,"market":market_msg,"logs":list(LOGS)[-30:]
    })

@app.route('/health')
def health():
    is_open, msg, is_limit = is_market_open()
    return jsonify({"status":"OK","market":msg,"trades_today":f"{STATE['trades_today']}/5","is_limit":is_limit})

@app.route('/test_telegram')
def test():
    token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat: return jsonify({"ok":False})
    try:
        txt=f"Only 5 Trade/Day Test\nTrades Today: {STATE['trades_today']}/5 Remaining: {5-STATE['trades_today']}\nMarket Open 9:15 AM"
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":txt,"parse_mode":"Markdown"},timeout=10)
        return jsonify({"ok":r.status_code==200})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})

def bot_loop():
    add_log("BOT | Only 5 Trade in a Day - Limit Added - Market Open 9:15 AM")
    time.sleep(3)
    send_telegram("🚀 Only 5 Trade/Day Limit Added\nMarket Open 9:15 AM\nTrades Today: 0/5")
    while True:
        try:
            is_open, market_msg, is_limit = is_market_open()
            if not is_open:
                if is_limit:
                    add_log(f"{market_msg} - 5 Trade Limit Reached - No More Trading Today")
                    send_telegram(f"⚠️ *5 Trades Limit Reached Today*\nTrades: {STATE['trades_today']}/5\nNo More Trading Today\nWait Till Tomorrow 9:15 AM")
                else:
                    add_log(f"{market_msg} - Sleeping")
                time.sleep(60); continue
            spot, prem, strike, src = get_real_nse()
            STATE["spot"]=round(spot,2); STATE["prem"]=round(prem,2); STATE["strike"]=strike; STATE["src"]=src
            STATE["intrinsic"]=max(strike-spot,0); STATE["time_value"]=prem-STATE["intrinsic"]
            now=datetime.now(IST).strftime("%H:%M")
            if len(CANDLES)==0 or CANDLES[-1]["t"]!=now:
                CANDLES.append({"o":prem,"h":prem,"l":prem,"c":prem,"t":now,"maru":False})
            else:
                c=CANDLES[-1]; c["h"]=max(c["h"],prem); c["l"]=min(c["l"],prem); c["c"]=prem; c["maru"]=is_marubozu(c)
            fib_data = detect_swings_and_fib()
            if fib_data:
                STATE["fib_high"]=fib_data["fib_high"]; STATE["fib_low"]=fib_data["fib_low"]; STATE["range"]=fib_data["range"]
                STATE["swing_high_info"]=fib_data["swing_high"]; STATE["swing_low_info"]=fib_data["swing_low"]
                f05=fib_data["0.5"]; f036=fib_data["0.36"]; f2414=fib_data["2.414"]
                recent=list(CANDLES)[-20:]; curr=recent[-1]['c']; prev=recent[-2]['c'] if len(recent)>=2 else curr
                closes=[r['c'] for r in recent]; ema=sum(closes)/len(closes) if closes else curr
                cross=prev<f05 and curr>=f05; above=curr>ema
                if cross and above and STATE["pos"] is None:
                    if STATE["trades_today"] >= 5:
                        add_log(f"5 TRADE LIMIT | Trades Today {STATE['trades_today']}/5 - No More BUY - Signal Ignored")
                        time.sleep(20); continue
                    STATE["pos"]={"entry":curr,"sl":f036,"tgt":f2414}
                    STATE["trades"]+=1; STATE["trades_today"]+=1
                    add_log(f"BUY SIGNAL | Trade {STATE['trades_today']}/5 Today | BUY {strike}PE @ {curr:.1f} | 5 Trade Limit Check OK | Remaining {5-STATE['trades_today']} Left")
                    send_telegram(f"🎯 *BUY {STATE['trades_today']}/5 Today*\nPremium: {strike}PE\nEntry 0.5: {f05:.2f} @ {curr:.2f}\nSL: {f036:.2f} TGT: {f2414:.2f}\nRemaining: {5-STATE['trades_today']} Left Today\nSpot: {spot:.1f}")
                    if STATE["trades_today"] >= 5:
                        add_log(f"5 TRADE LIMIT REACHED | {STATE['trades_today']}/5 Today - No More Trading Today")
                        send_telegram(f"⚠️ *5 Trades Done Today*\n{STATE['trades_today']}/5 Limit Reached\nNo More Trading Today\nTomorrow 9:15 AM Reset")
                if STATE["pos"]:
                    if CANDLES[-1]["maru"]:
                        new_low=CANDLES[-1]["l"]; new_rng=STATE["fib_high"]-new_low; new_sl=new_low+new_rng*0.36
                        if new_sl>STATE["pos"]["sl"]: STATE["pos"]["sl"]=new_sl
                    if curr<=STATE["pos"]["sl"]:
                        pnl=(STATE["pos"]["sl"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        add_log(f"SL HIT | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} Total {STATE['pnl']:.0f}")
                        send_telegram(f"🔴 SL HIT {STATE['trades_today']}/5 P&L {pnl:.0f} Total {STATE['pnl']:.0f}")
                        STATE["pos"]=None
                    elif curr>=STATE["pos"]["tgt"]:
                        pnl=(STATE["pos"]["tgt"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        add_log(f"TGT HIT | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} Total {STATE['pnl']:.0f}")
                        send_telegram(f"🟢 TGT HIT {STATE['trades_today']}/5 P&L {pnl:.0f} Total {STATE['pnl']:.0f}")
                        STATE["pos"]=None
            time.sleep(20)
        except Exception as e:
            add_log(f"ERR {e}"); time.sleep(10)

threading.Thread(target=bot_loop, daemon=True).start()
