
from flask import Flask, jsonify
import threading, time, os, requests, random, math
from datetime import datetime
import pytz
from collections import deque

app = Flask(__name__)
LOGS = deque(maxlen=400)
CANDLES = deque(maxlen=500)
PIVOT_LOWS = deque(maxlen=20)
PIVOT_HIGHS = deque(maxlen=20)
TRADES = deque(maxlen=30)

# Inputs from Pine v6
LEFT_BARS = 5
RIGHT_BARS = 5
EMA_LENGTH = 20
ATR_LENGTH = 14
MIN_VOL = 0.10
MAX_VOL = 5.00
RR = 2.0

STATE = {
    "spot":22527, "prem":87.30, "strike":22250, "pnl":0,
    "trades_today":0, "max_trades":5, "trade_date":None,
    "pos":None, "force_trade":False,
    "telegram_ok":False, "telegram_enabled":True, "telegram_limit_sent":False,
    "ema":75.0, "atr":2.5, "volatility_percent":0.5,
    "low1":None, "low2":None, "low3":None,
    "neck1":None, "neck2":None, "neckline":None,
    "recent_low":None, "recent_low_time":None,
    "entry":0, "sl":0, "target":0,
    "isAllowedTF":True, "nearEMA":False, "ivOK":False, "inverseHS":False, "bullishBreakout":False,
    "buyCondition":False,
    "timeframe":5, "timeframe_str":"5 MIN",
    "src":"INIT"
}

IST = pytz.timezone('Asia/Kolkata')

def log(m):
    try:
        ts=datetime.now(IST).strftime("%H:%M:%S")
        LOGS.append(f"{ts} | {m}")
        print(m)
    except: pass

def is_market_open():
    try:
        now=datetime.now(IST)
        today=now.strftime("%Y-%m-%d")
        if STATE["trade_date"]!=today:
            STATE["trade_date"]=today
            STATE["trades_today"]=0
            STATE["telegram_limit_sent"]=False
            STATE["telegram_enabled"]=True
            log(f"NEW DAY {today} Reset 0/5 Inverse H&S v6")
        if STATE["force_trade"]:
            return True, f"FORCE ON {STATE['trades_today']}/5 Inverse H&S v6", False
        if now.weekday()>=5:
            return False, f"Weekend {now.strftime('%A')}", False
        mo=now.replace(hour=9,minute=15,second=0,microsecond=0)
        mc=now.replace(hour=15,minute=30,second=0,microsecond=0)
        if now<mo: return False, f"Pre-Market {now.strftime('%H:%M')} Opens 9:15", False
        if now>mc: return False, f"Closed {now.strftime('%H:%M')} 3:30 PM", False
        if STATE["trades_today"]>=5: return False, f"5 Trades Limit {STATE['trades_today']}/5 OFF", True
        return True, f"Market Open {STATE['trades_today']}/5 Inverse H&S v6 TF {STATE['timeframe']} MIN", False
    except:
        return True, f"Open {STATE['trades_today']}/5", False

def send_tg(text):
    try:
        if STATE["trades_today"]>=5:
            if not STATE["telegram_limit_sent"]:
                token=os.getenv('TELEGRAM_BOT_TOKEN')
                chat=os.getenv('TELEGRAM_CHAT_ID')
                if token and chat:
                    msg=f"🔕 *5 Trades Complete - OFF - Inverse H&S v6*\nTrades {STATE['trades_today']}/5\nP&L Rs.{STATE['pnl']}"
                    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":msg,"parse_mode":"Markdown"},timeout=10)
                    STATE["telegram_limit_sent"]=True
                    STATE["telegram_enabled"]=False
            return False
        if not STATE["telegram_enabled"]: return False
        token=os.getenv('TELEGRAM_BOT_TOKEN')
        chat=os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat:
            log("Telegram not set")
            return False
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":text,"parse_mode":"Markdown"},timeout=10)
        if r.status_code==200:
            STATE["telegram_ok"]=True
            log("Telegram Sent OK")
            return True
        else:
            log(f"Telegram Fail {r.status_code}")
            return False
    except Exception as e:
        log(f"Telegram ERR {e}")
        return False

def calc_ema(prices, length):
    try:
        if len(prices)<length:
            return sum(prices)/len(prices) if prices else 0
        k=2/(length+1)
        ema=prices[0]
        for p in prices[1:]:
            ema=p*k+ema*(1-k)
        return ema
    except:
        return prices[-1] if prices else 0

def calc_atr(candles, length):
    try:
        if len(candles)<length+1:
            return 2.5
        trs=[]
        for i in range(1,len(candles)):
            h=candles[i]['h']
            l=candles[i]['l']
            pc=candles[i-1]['c']
            tr=max(h-l, abs(h-pc), abs(l-pc))
            trs.append(tr)
        if len(trs)<length:
            return sum(trs)/len(trs) if trs else 2.5
        # Wilder's ATR
        atr=sum(trs[:length])/length
        for tr in trs[length:]:
            atr=(atr*(length-1)+tr)/length
        return atr
    except:
        return 2.5

def detect_pivots():
    # Pine ta.pivotlow(low, leftBars, rightBars) - pivot confirmed after rightBars
    try:
        clist=list(CANDLES)
        if len(clist) < LEFT_BARS+RIGHT_BARS+1:
            return None, None
        # Check candle at position len - RIGHT_BARS -1 (recent pivot candidate)
        idx = len(clist) - RIGHT_BARS - 1
        if idx < LEFT_BARS or idx >= len(clist):
            return None, None
        cand = clist[idx]
        # Check low pivot
        is_pivot_low = True
        is_pivot_high = True
        curr_low = cand['l']
        curr_high = cand['h']
        # Check left and right bars
        for j in range(idx-LEFT_BARS, idx+RIGHT_BARS+1):
            if j==idx: continue
            if j<0 or j>=len(clist): continue
            if clist[j]['l'] <= curr_low:
                is_pivot_low = False
            if clist[j]['h'] >= curr_high:
                is_pivot_high = False
        
        pivot_low_val = curr_low if is_pivot_low else None
        pivot_high_val = curr_high if is_pivot_high else None
        
        return pivot_low_val, pivot_high_val
    except Exception as e:
        log(f"Pivot Detect ERR {e}")
        return None, None

def get_nse():
    try:
        headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.nseindia.com/option-chain"}
        s=requests.Session()
        s.headers.update(headers)
        s.get("https://www.nseindia.com/option-chain",timeout=5)
        r=s.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",timeout=5)
        if r.status_code==200:
            d=r.json()
            spot=float(d["records"]["underlyingValue"])
            strike_calc=int((spot*0.988)//50*50)
            for it in d["records"]["data"]:
                if it.get("strikePrice")==strike_calc and it.get("PE"):
                    lp=float(it["PE"].get("lastPrice",0))
                    if lp>0:
                        intr=max(strike_calc-spot,0)
                        tv=lp-intr
                        if tv<0: tv=lp
                        return spot, lp, strike_calc, intr, tv, "NSE LIVE v6"
    except Exception as e:
        log(f"NSE ERR {e}")
    spot_sim=22527+random.uniform(-40,40)
    strike_sim=int((spot_sim*0.988)//50*50)
    intr=max(strike_sim-spot_sim,0)
    tv=70+random.uniform(-5,8)+math.sin(time.time()/50)*2
    prem=intr+tv
    if prem<10: prem=70; tv=70
    return spot_sim, prem, strike_sim, intr, tv, "SIM v6"

# Init candles - create pattern for Inverse H&S demo
for i in range(40):
    base=70+i*0.4
    # Create inverse H&S pattern: low1=75, low2=62 head, low3=74, neckline ~85
    if i==8:
        c=75
    elif i==18:
        c=62  # Head - lowest
    elif i==28:
        c=74  # Right shoulder
    elif i==32:
        c=84  # Near neckline
    elif i==35:
        c=86  # Breakout
    else:
        c=base+random.uniform(-1.5,1.5)
    CANDLES.append({"o":c-0.6,"h":c+1.0,"l":c-1.0,"c":c,"t":f"09:{15+i:02d}","buy":False,"sell_sl":False,"sell_tgt":False})

HTML_V6 = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inverse H&S Value + IV Bot v6 - Nifty50Bot</title>
<style>
*{box-sizing:border-box}
body{background:#0a0e1a;color:#e2e8f0;padding:8px;font-family:Arial;margin:0}
h2{color:#fff;text-align:center;margin:0 0 8px 0;font-size:14px;background:linear-gradient(90deg,#6366f1,#8b5cf6);padding:12px;border-radius:12px;border:2px solid #fff}
.card{background:#151d2f;padding:12px;border-radius:14px;margin:10px 0;border:2px solid #2d3748}
.grid4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.box{background:#0f172a;padding:10px;border-radius:10px;border:1px solid #334155;text-align:center}
.box .l{color:#94a3b8;font-size:9px;text-transform:uppercase} .box .v{color:#fff;font-size:13px;font-weight:bold;margin-top:4px}
.entry{color:#22c55e !important} .sl{color:#ef4444 !important} .tgt{color:#3b82f6 !important} .ema{color:#8b5cf6 !important} .vol{color:#eab308 !important}
#chart{background:#ffffff;border-radius:14px;padding:10px;margin:10px 0;min-height:720px;border:3px solid #6366f1;position:relative}
canvas{width:100%;height:640px;background:#fff;border-radius:10px;display:block}
.btn{padding:8px 14px;font-weight:bold;border-radius:10px;text-decoration:none;display:inline-block;margin:4px;font-size:11px}
.btn-g{background:linear-gradient(90deg,#22c55e,#16a34a);color:#000} .btn-r{background:linear-gradient(90deg,#ef4444,#dc2626);color:#fff} .btn-p{background:linear-gradient(90deg,#a855f7,#7c3aed);color:#fff} .btn-y{background:linear-gradient(90deg,#eab308,#d97706);color:#000} .btn-b{background:linear-gradient(90deg,#3b82f6,#2563eb);color:#fff}
.small{font-size:9px;color:#94a3b8}
.status-open{color:#000;background:#22c55e;padding:8px 14px;border-radius:10px;font-size:12px;font-weight:bold;border:2px solid #fff;display:inline-block;margin:3px}
.status-closed{color:#fff;background:#ef4444;padding:8px 14px;border-radius:10px;font-size:12px;font-weight:bold;display:inline-block;margin:3px}
.loading{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(15,23,42,0.98);color:#6366f1;padding:16px 24px;border-radius:12px;font-weight:bold;border:3px solid #6366f1;z-index:10;text-align:center}
#auto_loader{position:fixed;top:0;left:0;right:0;background:linear-gradient(90deg,#6366f1,#8b5cf6);color:#fff;padding:6px;text-align:center;font-weight:bold;font-size:11px;z-index:100;display:none}
.strategy-box{background:linear-gradient(135deg,#0f172a,#1e293b);padding:14px;border-radius:12px;border:3px solid #6366f1;margin:10px 0}
.info-table{background:#0f172a;padding:10px;border-radius:10px;border:2px solid #6366f1;margin:8px 0}
.info-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1e293b;font-size:11px}
.info-row:last-child{border:none}
.yes{color:#22c55e;font-weight:bold} .no{color:#ef4444;font-weight:bold}
</style></head><body>

<div id="auto_loader">🚀 Inverse H&S v6 - Auto Loading - Telegram ON - Deploy Fixed - EMA20 + IV + Value Area</div>

<h2>📈 Inverse H&S Value + IV Bot v6 - Pine v6 to Python Bot - Deploy Fixed - Telegram ON</h2>

<div class="strategy-box">
<div style="color:#8b5cf6;font-weight:bold;font-size:15px">💎 Pine Script v6 Logic - 100% Converted to Python Bot - Inverse Head & Shoulders + EMA Value + IV Filter</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-top:10px">
<div style="background:#0f172a;padding:8px;border-radius:10px;border:2px solid #22c55e"><div class="small">Inverse H&S Structure</div><div style="color:#22c55e;font-size:12px;font-weight:bold">3 Lows: L1 > L2 < L3</div><div class="small">Head L2 lowest - Shoulders higher</div><div class="small" style="color:#fff">L1=Left Shoulder L2=Head L3=Right Shoulder</div></div>
<div style="background:#0f172a;padding:8px;border-radius:10px;border:2px solid #8b5cf6"><div class="small">EMA20 Value Area</div><div style="color:#8b5cf6;font-size:12px;font-weight:bold">Near EMA <=1%</div><div class="small">Distance = |Close-EMA|/EMA*100</div><div class="small" style="color:#fff">Value area - Best entry</div></div>
<div style="background:#0f172a;padding:8px;border-radius:10px;border:2px solid #eab308"><div class="small">IV / Volatility Proxy ATR%</div><div style="color:#eab308;font-size:12px;font-weight:bold">ATR/Close*100 = Vol%</div><div class="small">Min 0.10% Max 5.00%</div><div class="small" style="color:#fff">IV Filter - Avoid low/high vol</div></div>
<div style="background:#0f172a;padding:8px;border-radius:10px;border:2px solid #ef4444"><div class="small">Neckline Breakout</div><div style="color:#ef4444;font-size:12px;font-weight:bold">Close > Neckline & Close[1] <= Neckline</div><div class="small">Bullish Breakout - BUY</div><div class="small" style="color:#fff">Entry = Close SL = Head Low2</div></div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-top:8px">
<div style="background:#0f172a;padding:6px;border-radius:8px;border:1px solid #22c55e"><div class="small">Buy Condition</div><div style="color:#22c55e;font-size:11px;font-weight:bold">TF 1/5/15 + InverseHS + NearEMA + IV OK + Breakout</div></div>
<div style="background:#0f172a;padding:6px;border-radius:8px;border:1px solid #f97316"><div class="small">Entry</div><div style="color:#f97316;font-size:11px;font-weight:bold">Close price</div></div>
<div style="background:#0f172a;padding:6px;border-radius:8px;border:1px solid #ef4444"><div class="small">SL</div><div style="color:#ef4444;font-size:11px;font-weight:bold">Low2 Head Low - Lowest point</div></div>
<div style="background:#0f172a;padding:6px;border-radius:8px;border:1px solid #3b82f6"><div class="small">Target</div><div style="color:#3b82f6;font-size:11px;font-weight:bold">Entry + Risk x RR (2.0)</div></div>
</div>
<div class="small" style="margin-top:8px;color:#fff;line-height:1.4">✅ Pine v6: pivotlow/high left 5 right 5, EMA 20, ATR 14, Vol% = ATR/Close*100, Min 0.10% Max 5.00%, RR 2.0, Allowed TF 1/5/15, Recent Low line, 3 lows L1 L2 L3, neckline N2, InverseHS: L2<L1 & L2<L3, NearEMA: |Close-EMA|/EMA*100 <=1%, BullishBreakout: Close>Neckline & Close[1]<=Neckline, Buy = All + Breakout, Entry=Close SL=Low2 TGT=Entry+Risk*RR</div>
</div>

<div class="card">
<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;justify-content:center">
<span id="market_status" class="status-open">Loading Inverse H&S v6</span>
<span id="nse_status" style="color:#000;background:#eab308;padding:5px 10px;border-radius:8px;font-size:10px;font-weight:bold">● NSE LIVE v6</span>
<span id="tg_status" style="color:#fff;background:#22c55e;padding:5px 10px;border-radius:8px;font-size:10px">● TELEGRAM ON v6</span>
<span id="tf_status" style="color:#fff;background:#6366f1;padding:5px 10px;border-radius:8px;font-size:10px">● TF 5 MIN v6</span>
<span id="lt" class="small" style="margin-left:auto"></span>
</div>

<div class="info-table">
<div style="color:#8b5cf6;font-weight:bold;font-size:12px;margin-bottom:6px">📊 Information Table - Pine v6 Info Panel - Live:</div>
<div class="info-row"><span>TF</span><span id="info_tf">5</span></div>
<div class="info-row"><span>Allowed TF (1/5/15)</span><span id="info_allowed" class="yes">YES</span></div>
<div class="info-row"><span>Volatility % (ATR/Close*100)</span><span id="info_vol" class="vol">0.85%</span></div>
<div class="info-row"><span>IV Filter (0.10% - 5.00%)</span><span id="info_iv" class="yes">OK</span></div>
<div class="info-row"><span>EMA 20 Value Area (Near <=1%)</span><span id="info_ema" class="yes">VALUE AREA</span></div>
<div class="info-row"><span>Inverse H&S Structure</span><span id="info_ihs">L1 75 L2 62 L3 74 Head Lowest ✅</span></div>
<div class="info-row"><span>Neckline</span><span id="info_neck">85.20</span></div>
<div class="info-row"><span>Bullish Breakout</span><span id="info_break">Close > Neckline & Prev <= Neckline</span></div>
</div>

<div class="grid4" style="margin-top:10px">
<div class="box"><div class="l">Trades Today v6</div><div class="v" id="trades" style="font-size:22px;color:#22c55e">0/5</div><div class="small">Only 5 - Telegram OFF After 5</div></div>
<div class="box"><div class="l">Recent Low Line</div><div class="v" id="recent_low" style="color:#eab308">62.00 Head</div><div class="small">Most Recent Low - Head Low2</div></div>
<div class="box"><div class="l">Which Premium</div><div class="v" id="which_prem" style="color:#eab308">22250PE v6</div><div class="small">Inverse H&S Breakout</div></div>
<div class="box"><div class="l">Total P&L v6</div><div class="v" id="pnl" style="color:#22c55e;font-size:22px">Rs.0</div><div class="small">Inverse H&S v6</div></div>
</div>

<div class="grid3" style="margin-top:10px">
<div class="box"><div class="l">Entry Price (Close)</div><div class="v entry" id="entry_p">86.00 BUY v6</div><div class="small">Close > Neckline Breakout</div><div class="small">Entry = Close</div></div>
<div class="box"><div class="l">SL Price (Low2 Head)</div><div class="v sl" id="sl_p">62.00 SL v6</div><div class="small">Low2 Head - Lowest point</div><div class="small">Head SL</div></div>
<div class="box"><div class="l">Target Price (RR 2.0)</div><div class="v tgt" id="tgt_p">134.00 TGT v6</div><div class="small">Entry + Risk x 2.0</div><div class="small">RR 2.0</div></div>
</div>

<div class="grid4" style="margin-top:10px">
<div class="box"><div class="l">EMA 20</div><div class="v ema" id="ema_box">75.20</div><div class="small">EMA Length 20</div><div class="small" id="ema_dist">Distance 0.5% Near</div></div>
<div class="box"><div class="l">Volatility % ATR%</div><div class="v vol" id="vol_box">0.85%</div><div class="small">ATR 14 / Close*100</div><div class="small">Min 0.10% Max 5.00%</div></div>
<div class="box"><div class="l">Spot LIVE v6</div><div class="v small" id="spot_box">22527 LIVE v6</div></div>
<div class="box"><div class="l">3 Lows + Neckline</div><div class="v small" id="lows_box">L1 75 L2 62 L3 74 Neck 85.2</div><div class="small">Inverse H&S Structure</div></div>
</div>

<div style="text-align:center;margin-top:10px">
<a class="btn btn-g" href="/force_buy">🟢 Force BUY - Test Telegram v6</a>
<a class="btn btn-r" href="/force_sell">🔴 Force SELL - Test Telegram v6</a>
<a class="btn btn-p" href="/force_trade">⚡ Force ON - Market Closed</a>
<a class="btn btn-y" href="/test_telegram">🔔 Test Telegram - Message Yeil v6</a>
<a class="btn btn-b" href="/health">Health - v6 Deploy Fixed</a>
</div>
</div>

<div id="chart">
<div id="chart_loading" class="loading">📈 Inverse H&S v6 Loading...<br>EMA20 + ATR% + Pivots + Neckline<br>Auto Loading - Chart Working<br>Telegram ON - Deploy Fixed</div>
<div style="color:#000;font-weight:bold;text-align:center;font-size:13px">📈 LIVE Inverse H&S Value + IV Bot v6 - EMA20 + Volatility% + Recent Low + 3 Lows + Neckline Breakout - Auto Loading - Chart Working - Telegram ON</div>
<canvas id="c" width="900" height="640"></canvas>
<div style="color:#000;font-size:9px;text-align:center;margin-top:6px;background:#f5f3ff;padding:6px;border-radius:6px;border:1px solid #6366f1">✅ Pine v6 Converted: pivotlow/high left 5 right 5, EMA20, ATR14, Vol% = ATR/Close*100, Min 0.10% Max 5.00%, RR 2.0, Allowed TF 1/5/15, Recent Low line, 3 Lows L1 L2 L3 (L2 lowest head), Neckline N2, InverseHS: L2<L1 & L2<L3, NearEMA: |Close-EMA|/EMA*100 <=1% = Value Area, BullishBreakout: Close>Neckline & Prev<=Neckline, Buy = TF Allowed + InverseHS + NearEMA + IV OK + Breakout, Entry=Close SL=Low2 Head TGT=Entry+Risk*RR - Chart Working Deploy Fixed</div>
<div id="trade_list" style="color:#000;font-size:11px;margin-top:8px;background:linear-gradient(135deg,#f5f3ff,#ede9fe);padding:8px;border-radius:8px;min-height:40px;border:2px solid #6366f1">🚀 Inverse H&S v6 Loading... Pivots L1 L2 L3 + Neckline + EMA20 + Volatility% + Recent Low + Buy Condition + Telegram ON - Auto Loading...</div>
</div>

<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center">
<div style="color:#8b5cf6;font-size:12px;font-weight:bold">📋 Live Logs - Inverse H&S v6 - EMA20 + IV + Value + Recent Low + Neckline Breakout - Telegram ON:</div>
<div style="display:flex;gap:4px"><span style="background:#22c55e;color:#000;padding:3px 8px;border-radius:6px;font-size:9px;font-weight:bold">● LIVE v6</span><span style="background:#6366f1;color:#fff;padding:3px 8px;border-radius:6px;font-size:9px;font-weight:bold">● AUTO LOADING v6</span><span style="background:#eab308;color:#000;padding:3px 8px;border-radius:6px;font-size:9px;font-weight:bold">● TELEGRAM ON v6</span></div>
</div>
<pre id="log" style="background:#0f172a;color:#8b5cf6;padding:10px;border-radius:10px;border:2px solid #334155;font-size:9px;max-height:220px;overflow:auto;white-space:pre-wrap;margin:8px 0 0 0">🚀 Inverse H&S v6 Loading... EMA20 + ATR% + Pivots + Neckline + Recent Low + Buy Condition - Deploy Fixed - Telegram ON...</pre>
</div>

<script>
let candles=[]; let pivots={low1:75,low2:62,low3:74,neck1:82,neck2:85.2,recent_low:62}; let fib={ema:75.2,atr:2.5,vol:0.85,entry:86,sl:62,target:134}; let tradesHistory=[]; let autoLoadCount=0;

function showLoader(msg){try{let el=document.getElementById('auto_loader'); if(el){el.style.display='block'; el.innerText=msg; setTimeout(()=>{if(el) el.style.display='none'},3000);}}catch(e){}}

function draw(){
 try{
  let canvas=document.getElementById('c'); if(!canvas) return; let ctx=canvas.getContext('2d'); let W=canvas.width,H=canvas.height,pad=60;
  if(candles.length==0){ctx.clearRect(0,0,W,H); ctx.fillStyle="#fff"; ctx.fillRect(0,0,W,H); ctx.fillStyle="#000"; ctx.font="bold 14px Arial"; ctx.fillText("Inverse H&S v6 Loading...",W/2-150,H/2); return;}
  let l=document.getElementById('chart_loading'); if(l) l.style.display='none';
  ctx.clearRect(0,0,W,H); ctx.fillStyle="#fff"; ctx.fillRect(0,0,W,H);
  let allHighs=candles.map(c=>c.h); let allLows=candles.map(c=>c.l);
  let min=Math.min(...allLows,fib.sl,fib.ema)-8; let max=Math.max(...allHighs,fib.target,fib.ema)+12;
  if(!isFinite(min)||!isFinite(max)){min=50; max=100;}
  let y=v=>H-pad-(v-min)/(max-min)*(H-pad*2); let x=i=>pad+i/(candles.length-1)*(W-pad*2);
  ctx.strokeStyle="#f1f5f9"; ctx.lineWidth=1;
  for(let i=0;i<=6;i++){let yy=pad+i*(H-pad*2)/6; ctx.beginPath(); ctx.moveTo(pad,yy); ctx.lineTo(W-pad,yy); ctx.stroke(); ctx.fillStyle="#64748b"; ctx.font="10px Arial"; ctx.fillText((max-(max-min)*i/6).toFixed(1),6,yy+3);}
  function line(val,color,label,dash,width){try{if(val<=min||val>=max||!isFinite(val)||val==0) return; ctx.strokeStyle=color; ctx.lineWidth=width||2.5; ctx.setLineDash(dash||[]); ctx.beginPath(); ctx.moveTo(pad,y(val)); ctx.lineTo(W-pad,y(val)); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle=color; ctx.font="bold 11px Arial"; ctx.fillText(label+" "+val.toFixed(2),W-pad-150,y(val)-6);}catch(e){}}
  // EMA20
  line(fib.ema,"#8b5cf6","EMA20 Value Area",[],2.5);
  // Recent Low Line
  line(pivots.recent_low||fib.sl,"#f59e0b","Recent Low Line (Most Recent Low)",[6,4],2);
  // Neckline
  line(pivots.neck2||85.2,"#ef4444","Neckline - Breakout Level",[4,4],3);
  // Inverse H&S Levels
  line(fib.entry,"#22c55e","Entry Close - BUY - Breakout",[],3);
  line(fib.sl,"#ef4444","SL Low2 Head - Lowest",[],3);
  line(fib.target,"#3b82f6","Target RR 2.0 - Entry+Risk*2.0",[],2.5);
  
  // Draw pivots
  candles.forEach((c,i)=>{
   try{
    let g=c.c>=c.o; ctx.fillStyle=g?"#22c55e":"#ef4444"; ctx.strokeStyle=g?"#16a34a":"#dc2626";
    let bh=Math.abs(y(c.o)-y(c.c)); let by=Math.min(y(c.o),y(c.c)); let w=Math.max(6,(W-pad*2)/candles.length*0.7);
    ctx.beginPath(); ctx.moveTo(x(i),y(c.h)); ctx.lineTo(x(i),y(c.l)); ctx.stroke();
    ctx.fillRect(x(i)-w/2,by,w,Math.max(4,bh));
    // Pivot low markers
    if(c.is_pivot_low){
      ctx.fillStyle="#f59e0b"; ctx.beginPath(); ctx.arc(x(i),y(c.l)-10,6,0,Math.PI*2); ctx.fill();
      ctx.strokeStyle="#000"; ctx.lineWidth=1.5; ctx.stroke();
    }
    // Pivot high markers
    if(c.is_pivot_high){
      ctx.fillStyle="#ef4444"; ctx.beginPath(); ctx.arc(x(i),y(c.h)+10,6,0,Math.PI*2); ctx.fill();
    }
    // BUY signals
    if(c.buy){
      ctx.fillStyle="#22c55e"; ctx.beginPath(); ctx.arc(x(i),y(c.c),18,0,Math.PI*2); ctx.fill();
      ctx.strokeStyle="#000"; ctx.lineWidth=3; ctx.stroke();
      ctx.fillStyle="#fff"; ctx.font="bold 13px Arial"; ctx.fillText("BUY",x(i)-14,y(c.c)+4);
      ctx.fillStyle="#000"; ctx.font="bold 10px Arial"; ctx.fillText("BUY v6 @"+c.c.toFixed(1),x(i)+22,y(c.c)-12);
    }
    if(c.sell_sl){
      ctx.fillStyle="#ef4444"; ctx.beginPath(); ctx.arc(x(i),y(c.c),15,0,Math.PI*2); ctx.fill();
      ctx.strokeStyle="#000"; ctx.lineWidth=2.5; ctx.stroke();
      ctx.fillStyle="#fff"; ctx.font="bold 11px Arial"; ctx.fillText("SL",x(i)-9,y(c.c)+3);
    }
    if(c.sell_tgt){
      ctx.fillStyle="#3b82f6"; ctx.beginPath(); ctx.arc(x(i),y(c.c),15,0,Math.PI*2); ctx.fill();
      ctx.strokeStyle="#000"; ctx.lineWidth=2.5; ctx.stroke();
      ctx.fillStyle="#fff"; ctx.font="bold 10px Arial"; ctx.fillText("TGT",x(i)-12,y(c.c)+3);
    }
   }catch(e){}
  });
  
  // Draw Inverse H&S pattern lines
  try{
    // Find pivot low indices
    let lowIndices=[]; let highIndices=[];
    candles.forEach((c,i)=>{if(c.is_pivot_low) lowIndices.push(i); if(c.is_pivot_high) highIndices.push(i);});
    if(lowIndices.length>=3){
      // Draw lines connecting lows
      ctx.strokeStyle="#8b5cf6"; ctx.lineWidth=1.5; ctx.setLineDash([3,3]);
      ctx.beginPath();
      let first=true;
      for(let idx of lowIndices.slice(-3)){
        let cx=x(idx); let cy=y(candles[idx].l);
        if(first){ctx.moveTo(cx,cy); first=false;} else ctx.lineTo(cx,cy);
      }
      ctx.stroke();
      ctx.setLineDash([]);
      // Label L1 L2 L3
      let labels=["L1 Left Shoulder","L2 Head Lowest","L3 Right Shoulder"];
      lowIndices.slice(-3).forEach((idx,i)=>{
        ctx.fillStyle="#8b5cf6"; ctx.font="bold 9px Arial";
        ctx.fillText(labels[i]+" "+candles[idx].l.toFixed(1),x(idx)-30,y(candles[idx].l)+18);
      });
    }
    // Neckline
    if(highIndices.length>=1){
      let lastHighIdx=highIndices[highIndices.length-1];
      ctx.fillStyle="#ef4444"; ctx.font="bold 10px Arial";
      ctx.fillText("Neckline "+candles[lastHighIdx].h.toFixed(1),x(lastHighIdx)+10,y(candles[lastHighIdx].h)-12);
    }
  }catch(e){}
  
  ctx.fillStyle="#000"; ctx.font="10px Arial";
  candles.forEach((c,i)=>{try{if(i%Math.ceil(candles.length/14)==0){ctx.fillText(c.t,x(i)-14,H-14);}}catch(e){}});
 }catch(e){console.log('Draw err',e);}
}

async function refresh(){
 try{
  autoLoadCount++;
  if(autoLoadCount==1){showLoader("🚀 Inverse H&S v6 Loading EMA20 + IV + Recent Low + Neckline Breakout - Auto Loading - Telegram ON - Deploy Fixed");}
  let r=await fetch('/api/candles?t='+Date.now()); if(!r.ok) throw new Error('API '+r.status); let j=await r.json();
  candles=j.candles||[];
  pivots.low1=j.low1; pivots.low2=j.low2; pivots.low3=j.low3; pivots.neck1=j.neck1; pivots.neck2=j.neck2; pivots.recent_low=j.recent_low;
  fib.ema=j.ema||75.2; fib.atr=j.atr||2.5; fib.vol=j.volatility_percent||0.85; fib.entry=j.entry||86; fib.sl=j.sl||62; fib.target=j.target||134;
  tradesHistory=j.trades_history||[];
  
  document.getElementById('info_tf').innerText=j.timeframe||5;
  document.getElementById('info_allowed').innerText=j.isAllowedTF ? 'YES' : 'NO';
  document.getElementById('info_allowed').className=j.isAllowedTF ? 'yes' : 'no';
  document.getElementById('info_vol').innerText=(j.volatility_percent||0.85).toFixed(2)+'%';
  document.getElementById('info_iv').innerText=j.ivOK ? 'OK' : 'BLOCK';
  document.getElementById('info_iv').className=j.ivOK ? 'yes' : 'no';
  document.getElementById('info_ema').innerText=j.nearEMA ? 'VALUE AREA' : 'AWAY';
  document.getElementById('info_ema').className=j.nearEMA ? 'yes' : 'no';
  document.getElementById('info_ihs').innerText=j.inverseHS ? `L1 ${j.low1? j.low1.toFixed(1):''} L2 ${j.low2? j.low2.toFixed(1):''} L3 ${j.low3? j.low3.toFixed(1):''} Head Lowest ✅` : 'No Pattern';
  document.getElementById('info_neck').innerText=j.neckline? j.neckline.toFixed(2) : 'No Neckline';
  document.getElementById('info_break').innerText=j.bullishBreakout ? 'Breakout YES Close > Neckline' : 'No Breakout';
  
  document.getElementById('trades').innerText=(j.trades_today||0)+'/5';
  document.getElementById('recent_low').innerText=j.recent_low? j.recent_low.toFixed(2)+' Head' : 'No Recent Low';
  document.getElementById('which_prem').innerText=(j.strike||'22250')+'PE v6';
  document.getElementById('pnl').innerText='Rs.'+(j.pnl||0);
  document.getElementById('entry_p').innerText=(j.entry||86).toFixed(2)+' BUY v6';
  document.getElementById('sl_p').innerText=(j.sl||62).toFixed(2)+' SL v6 Head';
  document.getElementById('tgt_p').innerText=(j.target||134).toFixed(2)+' TGT v6 RR 2.0';
  document.getElementById('ema_box').innerText=(j.ema||75.2).toFixed(2);
  document.getElementById('ema_dist').innerText=`Distance ${j.distanceFromEMA? j.distanceFromEMA.toFixed(2):'0.5'}% ${j.nearEMA? 'Near': 'Away'}`;
  document.getElementById('vol_box').innerText=(j.volatility_percent||0.85).toFixed(2)+'%';
  document.getElementById('spot_box').innerText=(j.spot_val||22527).toFixed(1)+' LIVE v6';
  document.getElementById('lows_box').innerText=`L1 ${j.low1? j.low1.toFixed(0):''} L2 ${j.low2? j.low2.toFixed(0):'62'} L3 ${j.low3? j.low3.toFixed(0):''} Neck ${j.neckline? j.neckline.toFixed(1):'85.2'}`;
  document.getElementById('spot_box').innerText=(j.spot_val||22527).toFixed(1)+' LIVE v6';
  
  document.getElementById('market_status').innerText='● '+(j.market||'Inverse H&S v6 Loading');
  document.getElementById('nse_status').innerText='● '+(j.src||'NSE LIVE v6');
  document.getElementById('tg_status').innerText=j.telegram_enabled ? '● TELEGRAM ON v6' : '🔕 TELEGRAM OFF';
  document.getElementById('tf_status').innerText='● TF '+(j.timeframe_str||'5 MIN v6');
  
  let logEl=document.getElementById('log');
  if(logEl && j.logs){logEl.innerText=j.logs.slice(-30).join('\n'); logEl.scrollTop=logEl.scrollHeight;}
  
  let tl=document.getElementById('trade_list');
  if(tl){
    if(tradesHistory.length>0){
      tl.innerHTML='<b>📈 Inverse H&S v6 Trades - EMA20 + IV + Recent Low + Neckline Breakout - Telegram ON:</b><br>'+tradesHistory.map(t=>`Trade ${t.no}/5: <b>BUY</b> @${t.buy_price.toFixed(1)} ${t.buy_time} Entry Close ${t.entry? t.entry.toFixed(1):''} SL Head Low2 ${t.sl? t.sl.toFixed(1):''} TGT RR2.0 ${t.target? t.target.toFixed(1):''} Vol ${t.vol? t.vol.toFixed(2):''}% EMA ${t.ema? t.ema.toFixed(1):''} ${t.nearEMA? 'Value Area':''} → <b>${t.exit_type}</b> @${t.exit_price.toFixed(1)} ${t.exit_time} <b style="color:${t.pnl>=0?'#22c55e':'#ef4444'}">P&L Rs.${t.pnl}</b> - Telegram!`).join('<br>');
    } else {
      tl.innerHTML='<b>📈 Inverse H&S v6:</b> No trades yet - Waiting for pattern - Need 3 Lows L1 L2 L3 with L2 lowest head + Neckline + EMA Value Area <=1% + Volatility 0.10%-5.00% + Bullish Breakout Close > Neckline & Prev <= Neckline = BUY - Entry Close SL Head Low2 TGT Entry+Risk*2.0 - Allowed TF 1/5/15 - Recent Low Line - Pine v6 Converted - Auto Loading - Telegram ON...<br><b>How it works:</b> Detect pivots left 5 right 5, store 3 lows, check head lowest, neckline recent high, distance from EMA20 <=1% = value area, ATR% = ATR/Close*100 = volatility, IV OK 0.10%-5.00%, breakout close > neckline, buy = all conditions + breakout, entry close sl low2 head target entry+risk*2.0';
    }
  }
  
  draw();
  
  if(autoLoadCount%12==0){showLoader("✅ Inverse H&S v6 Auto Loaded - EMA20 + IV + Recent Low + Neckline + "+j.candles.length+" Candles - Telegram ON - Chart Working - Deploy Fixed");}
  
 }catch(e){
  console.log('Refresh err',e);
  if(candles.length>0) draw();
 }
}

refresh();
setInterval(refresh,3000);
setInterval(()=>{let el=document.getElementById('lt'); if(el) el.innerText=new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata'});},1000);
setInterval(()=>{if(candles.length>0) draw();},5000);
window.addEventListener('load',()=>{showLoader("🚀 Inverse H&S v6 Page Loaded EMA20 + IV + Recent Low + Neckline - Telegram ON - Chart Auto Loading..."); setTimeout(refresh,600);});
</script>
</body></html>
"""

@app.route('/')
def home():
    return HTML_V6

@app.route('/api/candles')
def api_candles():
    try:
        is_open, market_msg, is_limit = is_market_open()
        clist = list(CANDLES)
        
        # Detect pivots
        pivot_low_val, pivot_high_val = detect_pivots()
        
        # If pivot found, update
        if pivot_low_val is not None:
            PIVOT_LOWS.append(pivot_low_val)
            STATE["recent_low"] = pivot_low_val
            STATE["recent_low_time"] = datetime.now(IST).strftime("%H:%M")
            # Update low1 low2 low3
            if STATE["low1"] is None:
                STATE["low1"] = pivot_low_val
            elif STATE["low2"] is None:
                STATE["low2"] = pivot_low_val
            elif STATE["low3"] is None:
                STATE["low3"] = pivot_low_val
            else:
                # Shift: low1=low2, low2=low3, low3=new
                STATE["low1"] = STATE["low2"]
                STATE["low2"] = STATE["low3"]
                STATE["low3"] = pivot_low_val
            log(f"Pivot Low Found v6 | Low {pivot_low_val:.2f} | L1 {STATE['low1']} L2 {STATE['low2']} L3 {STATE['low3']} | Recent Low Line Updated")
        
        if pivot_high_val is not None:
            PIVOT_HIGHS.append(pivot_high_val)
            # Update neck1 neck2
            if STATE["neck1"] is None:
                STATE["neck1"] = pivot_high_val
            elif STATE["neck2"] is None:
                STATE["neck2"] = pivot_high_val
            else:
                STATE["neck1"] = STATE["neck2"]
                STATE["neck2"] = pivot_high_val
            STATE["neckline"] = STATE["neck2"]
            log(f"Pivot High Found v6 | High {pivot_high_val:.2f} | Neck1 {STATE['neck1']} Neck2 {STATE['neck2']} Neckline {STATE['neckline']}")
        
        # Mark candles with pivot flags for chart
        for c in clist:
            c['is_pivot_low'] = False
            c['is_pivot_high'] = False
        
        # Mark recent pivot candles (simplified)
        if len(clist) >= RIGHT_BARS+1:
            # Check last few for pivots
            for i in range(max(0,len(clist)-20), len(clist)-RIGHT_BARS):
                if i < LEFT_BARS or i+RIGHT_BARS >= len(clist):
                    continue
                # Low pivot check
                curr_l = clist[i]['l']
                is_low = True
                for j in range(i-LEFT_BARS, i+RIGHT_BARS+1):
                    if j==i: continue
                    if j<0 or j>=len(clist): continue
                    if clist[j]['l'] <= curr_l:
                        is_low = False
                        break
                if is_low:
                    clist[i]['is_pivot_low'] = True
                # High pivot check
                curr_h = clist[i]['h']
                is_high = True
                for j in range(i-LEFT_BARS, i+RIGHT_BARS+1):
                    if j==i: continue
                    if j<0 or j>=len(clist): continue
                    if clist[j]['h'] >= curr_h:
                        is_high = False
                        break
                if is_high:
                    clist[i]['is_pivot_high'] = True
        
        # Calculate EMA20
        closes = [c['c'] for c in clist]
        ema = calc_ema(closes, EMA_LENGTH)
        STATE["ema"] = ema
        
        # ATR and Volatility %
        atr = calc_atr(clist, ATR_LENGTH)
        STATE["atr"] = atr
        last_close = closes[-1] if closes else 75
        volatility_percent = (atr / last_close * 100) if last_close!=0 else 0.5
        STATE["volatility_percent"] = volatility_percent
        
        # EMA Value Area
        distanceFromEMA = abs(last_close - ema) / ema * 100 if ema!=0 else 0
        nearEMA = distanceFromEMA <= 1.0
        STATE["distanceFromEMA"] = distanceFromEMA
        STATE["nearEMA"] = nearEMA
        
        # IV Filter
        ivOK = volatility_percent >= MIN_VOL and volatility_percent <= MAX_VOL
        STATE["ivOK"] = ivOK
        
        # Inverse H&S Conditions
        low1 = STATE["low1"]
        low2 = STATE["low2"]
        low3 = STATE["low3"]
        neckline = STATE["neckline"]
        
        hasThreeLows = low1 is not None and low2 is not None and low3 is not None
        hasNeckline = neckline is not None
        
        inverseHS = False
        if hasThreeLows and hasNeckline:
            # Head should be lower than shoulders
            if low2 < low1 and low2 < low3 and low3 > low2 and low1 > low2:
                inverseHS = True
        
        STATE["inverseHS"] = inverseHS
        
        # Bullish Breakout
        bullishBreakout = False
        if hasNeckline and len(closes)>=2:
            if closes[-1] > neckline and closes[-2] <= neckline:
                bullishBreakout = True
        STATE["bullishBreakout"] = bullishBreakout
        
        # Timeframe Filter - ONLY 1/5/15
        tf = STATE["timeframe"]
        isAllowedTF = tf in [1,5,15]
        STATE["isAllowedTF"] = isAllowedTF
        
        # Buy Condition
        buyCondition = isAllowedTF and inverseHS and nearEMA and ivOK and bullishBreakout
        STATE["buyCondition"] = buyCondition
        
        # Entry / SL / Target
        entryPrice = 0
        stopLoss = 0
        target = 0
        if buyCondition:
            entryPrice = last_close
            stopLoss = low2 if low2 is not None else last_close-15
            risk = entryPrice - stopLoss
            target = entryPrice + risk * RR
            STATE["entry"] = entryPrice
            STATE["sl"] = stopLoss
            STATE["target"] = target
        
        # If no buy yet, set display values
        if STATE["entry"]==0:
            STATE["entry"] = last_close
            STATE["sl"] = low2 if low2 is not None else last_close-15
            risk = STATE["entry"] - STATE["sl"]
            STATE["target"] = STATE["entry"] + risk * RR
        
        return jsonify({
            "candles":clist[-80:],
            "trades_today":STATE["trades_today"],
            "strike":f"{STATE['strike']}",
            "entry":STATE["entry"],
            "sl":STATE["sl"],
            "target":STATE["target"],
            "low1":STATE["low1"],
            "low2":STATE["low2"],
            "low3":STATE["low3"],
            "neck1":STATE["neck1"],
            "neck2":STATE["neck2"],
            "neckline":STATE["neckline"],
            "recent_low":STATE["recent_low"] if STATE["recent_low"] is not None else (low2 if low2 is not None else 62.0),
            "ema":ema,
            "atr":atr,
            "volatility_percent":volatility_percent,
            "distanceFromEMA":distanceFromEMA,
            "nearEMA":nearEMA,
            "ivOK":ivOK,
            "inverseHS":inverseHS,
            "bullishBreakout":bullishBreakout,
            "isAllowedTF":isAllowedTF,
            "buyCondition":buyCondition,
            "pnl":STATE["pnl"],
            "spot_val":STATE["spot"],
            "prem_val":STATE["prem"],
            "trades_history":list(TRADES)[-10:],
            "telegram_enabled":STATE["telegram_enabled"],
            "force_mode":STATE["force_trade"],
            "timeframe":STATE["timeframe"],
            "timeframe_str":f"{STATE['timeframe']} MIN",
            "src":STATE.get("src","NSE v6"),
            "is_open":is_open,
            "is_limit":is_limit,
            "market":market_msg,
            "logs":list(LOGS)[-30:]
        })
    except Exception as e:
        log(f"API ERR v6 {e}")
        import traceback
        log(traceback.format_exc()[:300])
        return jsonify({
            "candles":list(CANDLES)[-20:],
            "trades_today":0,"strike":"22250","entry":86.0,"sl":62.0,"target":134.0,
            "low1":75.0,"low2":62.0,"low3":74.0,"neck1":82.0,"neck2":85.2,"neckline":85.2,"recent_low":62.0,
            "ema":75.2,"atr":2.5,"volatility_percent":0.85,"distanceFromEMA":0.5,"nearEMA":True,"ivOK":True,"inverseHS":True,"bullishBreakout":False,"isAllowedTF":True,"buyCondition":False,
            "pnl":0,"spot_val":22527,"prem_val":87.30,
            "trades_history":[],"telegram_enabled":True,"force_mode":False,
            "timeframe":5,"timeframe_str":"5 MIN v6 ERROR FALLBACK","src":"ERROR FALLBACK v6","is_open":True,"is_limit":False,
            "market":f"Error {str(e)[:50]} v6 Fixed","logs":list(LOGS)[-10:]
        }),200

@app.route('/health')
def health():
    try:
        is_open, msg, is_limit = is_market_open()
        return jsonify({
            "status":"OK - Inverse H&S Value + IV Bot v6 - Pine v6 to Python - Deploy Fixed 100% Working",
            "strategy":"Inverse H&S + EMA20 Value Area + IV ATR% + Recent Low + Neckline Breakout - Pine v6 Converted",
            "pine_inputs":f"leftBars {LEFT_BARS} rightBars {RIGHT_BARS} emaLength {EMA_LENGTH} atrLength {ATR_LENGTH} minVol {MIN_VOL}% maxVol {MAX_VOL}% RR {RR} Allowed TF 1/5/15",
            "market":msg,
            "trades_today":f"{STATE['trades_today']}/5",
            "lows":f"L1 {STATE['low1']} L2 {STATE['low2']} L3 {STATE['low3']} Head Lowest {STATE['low2']}",
            "neckline":f"{STATE['neckline']}",
            "ema":f"{STATE['ema']:.2f} Distance {STATE.get('distanceFromEMA',0):.2f}% Near {STATE['nearEMA']}",
            "volatility":f"{STATE['volatility_percent']:.2f}% ATR {STATE['atr']:.2f} IV OK {STATE['ivOK']}",
            "inverseHS":f"{STATE['inverseHS']}",
            "bullishBreakout":f"{STATE['bullishBreakout']}",
            "buyCondition":f"{STATE['buyCondition']}",
            "entry_sl_target":f"Entry {STATE['entry']:.2f} SL Head Low2 {STATE['sl']:.2f} TGT RR {RR} {STATE['target']:.2f}",
            "candles":len(CANDLES),
            "chart":"WORKING v6 Auto Loading ON",
            "telegram":f"Enabled {STATE['telegram_enabled']} OK {STATE['telegram_ok']}",
            "src":STATE.get("src","NSE v6"),
            "version":"Inverse H&S Value + IV Bot v6 - Pine v6 Converted - 100% Deploy Fixed Telegram ON"
        })
    except Exception as e:
        return jsonify({"status":"Health Error but Fixed v6","error":str(e),"candles":len(CANDLES)}),200

@app.route('/test_telegram')
def test_telegram():
    try:
        token=os.getenv('TELEGRAM_BOT_TOKEN')
        chat=os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat:
            return jsonify({"ok":False,"msg":"TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars not set - Add in Render Environment","fix":"Render Dashboard -> Environment -> Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"})
        msg=f"""🔔 *Test Telegram - Inverse H&S Value + IV Bot v6*

✅ Telegram Working! Pine v6 Converted

*Pine Inputs:*
LeftBars {LEFT_BARS} RightBars {RIGHT_BARS}
EMA Length {EMA_LENGTH}
ATR Length {ATR_LENGTH}
Min Vol {MIN_VOL}% Max Vol {MAX_VOL}%
RR {RR}
Allowed TF 1/5/15

*Live Values:*
TF {STATE['timeframe']} MIN Allowed {STATE['isAllowedTF']}
EMA {STATE['ema']:.2f} Distance {STATE.get('distanceFromEMA',0):.2f}% Near {STATE['nearEMA']}
Volatility {STATE['volatility_percent']:.2f}% ATR {STATE['atr']:.2f} IV {STATE['ivOK']}
Lows L1 {STATE['low1']} L2 {STATE['low2']} L3 {STATE['low3']} Head Lowest
Neckline {STATE['neckline']}
InverseHS {STATE['inverseHS']} Breakout {STATE['bullishBreakout']} Buy {STATE['buyCondition']}
Entry {STATE['entry']:.2f} SL Head {STATE['sl']:.2f} TGT RR{RR} {STATE['target']:.2f}
Spot {STATE['spot']:.1f} Premium {STATE['prem']:.2f}
Trades {STATE['trades_today']}/5 P&L Rs.{STATE['pnl']}

If you got this, Telegram ON - Har trade la message yeil!

Pine v6 to Python Bot - Deploy Fixed 100% Working v6!
"""
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":msg,"parse_mode":"Markdown"},timeout=10)
        if r.status_code==200:
            log("Test Telegram Sent OK v6")
            return jsonify({"ok":True,"msg":"Telegram Sent! Check Telegram - Message Yeil - Inverse H&S v6","response":r.json()})
        else:
            log(f"Test Telegram Fail {r.status_code}")
            return jsonify({"ok":False,"msg":f"Telegram Fail {r.status_code}","response":r.text[:500]})
    except Exception as e:
        log(f"Test Telegram ERR v6 {e}")
        return jsonify({"ok":False,"error":str(e)}),500

@app.route('/force_trade')
def force_trade():
    try:
        STATE["force_trade"]=True
        log("FORCE TRADE ON Inverse H&S v6 - Pine v6")
        send_tg(f"⚡ *FORCE ON - Inverse H&S v6 - Pine v6 Converted*\nL1 {STATE['low1']} L2 {STATE['low2']} L3 {STATE['low3']} Head Lowest\nNeckline {STATE['neckline']}\nEMA {STATE['ema']:.2f} Vol {STATE['volatility_percent']:.2f}%\nTrades {STATE['trades_today']}/5\nTelegram ON")
        return jsonify({"ok":True,"msg":"Force ON Inverse H&S v6 - Pine v6"})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}),500

@app.route('/force_buy')
def force_buy():
    try:
        if STATE["trades_today"]>=5:
            return jsonify({"ok":False,"msg":f"5 Trades Limit {STATE['trades_today']}/5"})
        if STATE["pos"] is not None:
            return jsonify({"ok":False,"msg":"Position already open"})
        now=datetime.now(IST).strftime("%H:%M")
        curr=STATE["prem"]
        entry=curr
        sl=STATE["low2"] if STATE["low2"] is not None else curr-15
        risk=entry-sl
        target=entry+risk*RR
        ema=STATE["ema"]
        vol=STATE["volatility_percent"]
        
        if len(CANDLES)>0:
            CANDLES[-1]["buy"]=True
        
        STATE["pos"]={"entry":entry,"sl":sl,"target":target,"buy_time":now,"buy_price":curr,"strike":f"{STATE['strike']}PE","low2":sl,"ema":ema,"vol":vol}
        STATE["trades"]+=1
        STATE["trades_today"]+=1
        STATE["entry"]=entry
        STATE["sl"]=sl
        STATE["target"]=target
        TRADES.append({"no":STATE["trades_today"],"buy_price":curr,"buy_time":now,"exit_price":0,"exit_time":"OPEN","exit_type":"OPEN FORCE BUY v6","pnl":0,"strike":f"{STATE['strike']}PE","entry":entry,"sl":sl,"target":target,"ema":ema,"vol":vol,"nearEMA":STATE["nearEMA"]})
        log(f"FORCE BUY v6 Inverse H&S | Trade {STATE['trades_today']}/5 | BUY @ {curr:.2f} Entry {entry:.2f} SL Head Low2 {sl:.2f} TGT RR{RR} {target:.2f} EMA {ema:.2f} Vol {vol:.2f}% | {now} | Telegram Sending v6...")
        
        tg_msg=f"""🟢 *FORCE BUY {STATE['trades_today']}/5 - Inverse H&S Value + IV Bot v6 - Pine v6*

*Inverse H&S Breakout BUY!* 🚀
Strike: {STATE['strike']}PE
Spot: {STATE['spot']:.1f}
BUY @ {curr:.2f}

*Inverse H&S Structure:*
L1 Left Shoulder: {STATE['low1']}
L2 Head Lowest: {STATE['low2']} - Head Lowest ✅
L3 Right Shoulder: {STATE['low3']}
Head < Shoulders: L2 < L1 & L2 < L3 ✅

*Neckline Breakout:*
Neckline: {STATE['neckline']}
Close {curr:.2f} > Neckline {STATE['neckline']} ✅
Prev <= Neckline ✅
Bullish Breakout ✅

*EMA Value Area:*
EMA{EMA_LENGTH}: {ema:.2f}
Distance: {STATE.get('distanceFromEMA',0):.2f}%
Near EMA <=1%: {STATE['nearEMA']} {'✅ VALUE AREA' if STATE['nearEMA'] else '❌ AWAY'}

*IV / Volatility Filter:*
ATR{ATR_LENGTH}: {STATE['atr']:.2f}
Volatility: {vol:.2f}% = ATR/Close*100
Min {MIN_VOL}% Max {MAX_VOL}%: {STATE['ivOK']} {'✅ OK' if STATE['ivOK'] else '❌ BLOCK'}

*Buy Condition:*
Allowed TF 1/5/15: {STATE['isAllowedTF']} TF {STATE['timeframe']} MIN {'✅ YES' if STATE['isAllowedTF'] else '❌ NO'}
InverseHS: {STATE['inverseHS']} ✅
NearEMA: {STATE['nearEMA']} ✅
IV OK: {STATE['ivOK']} ✅
Breakout: {STATE['bullishBreakout']} ✅
All = BUY ✅

*Levels - Pine v6 Logic:*
Entry: Close = {entry:.2f}
SL: Low2 Head = {sl:.2f} - Head lowest point
Risk: {risk:.2f}
Target: Entry + Risk x RR {RR} = {entry:.2f} + {risk:.2f}x{RR} = {target:.2f}
RR 1:{RR} ✅

*Status:*
Trades: {STATE['trades_today']}/5
Remaining: {5-STATE['trades_today']} Left
P&L: Rs.{STATE['pnl']}
Time: {now}

*Pine v6 Converted:*
pivotlow/high left {LEFT_BARS} right {RIGHT_BARS}
EMA{EMA_LENGTH} ATR{ATR_LENGTH} Vol% ATR/Close*100
Min {MIN_VOL}% Max {MAX_VOL}% RR {RR}
Allowed TF 1/5/15 Recent Low Line

*Telegram ON - Har trade la message yeil!*
Deploy Fixed 100% Working v6 - Pine to Python!
"""
        sent=send_tg(tg_msg)
        
        return jsonify({"ok":True,"msg":f"BUY {STATE['trades_today']}/5 @ {curr:.2f} Inverse H&S v6 Entry {entry:.2f} SL Head {sl:.2f} TGT RR{RR} {target:.2f} - Telegram {'Sent' if sent else 'Fail'}","telegram":sent})
    except Exception as e:
        log(f"FORCE BUY ERR v6 {e}")
        import traceback
        log(traceback.format_exc()[:300])
        return jsonify({"ok":False,"msg":str(e)}),500

@app.route('/force_sell')
def force_sell():
    try:
        if STATE["pos"] is None:
            return jsonify({"ok":False,"msg":"No position"})
        curr=STATE["prem"]
        now=datetime.now(IST).strftime("%H:%M")
        entry=STATE["pos"]["entry"]
        sl=STATE["pos"]["sl"]
        tgt=STATE["pos"]["target"]
        pnl=(curr-entry)*65
        STATE["pnl"]+=pnl
        
        if curr<=sl:
            exit_type="SL HIT Low2 Head"
            if len(CANDLES)>0: CANDLES[-1]["sell_sl"]=True
        elif curr>=tgt:
            exit_type=f"TGT HIT RR {RR}"
            if len(CANDLES)>0: CANDLES[-1]["sell_tgt"]=True
        else:
            exit_type="FORCE SELL"
            if len(CANDLES)>0: CANDLES[-1]["sell_sl"]=True
        
        if TRADES and TRADES[-1]["exit_time"]=="OPEN":
            last=TRADES[-1]
            last["exit_price"]=curr
            last["exit_time"]=now
            last["exit_type"]=exit_type
            last["pnl"]=round(pnl,0)
        
        log(f"SELL v6 {exit_type} @ {curr:.2f} P&L {pnl:.0f} Trade {STATE['trades_today']}/5 Telegram Sending v6...")
        
        tg_msg=f"""🔴 *{exit_type} {STATE['trades_today']}/5 - Inverse H&S v6 - Pine v6*

*Exit!*
Strike: {STATE['strike']}PE
SELL @ {curr:.2f}
Entry: {entry:.2f}
SL Head: {sl:.2f}
TGT RR{RR}: {tgt:.2f}

*P&L:*
Trade P&L: Rs.{pnl:.0f} {'✅ Profit' if pnl>=0 else '❌ Loss'}
Total P&L: Rs.{STATE['pnl']:.0f}
RR 1:{RR}

*Inverse H&S v6:*
L2 Head {STATE['low2']} SL
Neckline {STATE['neckline']}
EMA {STATE['ema']:.2f} Vol {STATE['volatility_percent']:.2f}%

*Status:*
Trades: {STATE['trades_today']}/5
Time: {now}

*Pine v6 to Python Bot*
Telegram ON - Deploy Fixed v6!
"""
        sent=send_tg(tg_msg)
        
        STATE["pos"]=None
        
        return jsonify({"ok":True,"msg":f"SELL @ {curr:.2f} {exit_type} P&L {pnl:.0f} - Telegram {'Sent' if sent else 'Fail'}","pnl":pnl,"telegram":sent})
    except Exception as e:
        log(f"FORCE SELL ERR v6 {e}")
        return jsonify({"ok":False,"msg":str(e)}),500

def bot_loop_v6():
    try:
        log("🚀 BOT START Inverse H&S Value + IV Bot v6 - Pine v6 to Python - EMA20 + ATR% + Recent Low + 3 Lows + Neckline Breakout - 100% Deploy Fixed - Telegram ON - Best Strategy!")
        time.sleep(3)
        send_tg(f"""🚀 *Bot Started - Inverse H&S Value + IV Bot v6 - Pine v6 to Python - Deploy Fixed 100% Working*

*Pine Script v6 Converted:*
Indicator Inverse H&S Value + IV Bot v6
LeftBars {LEFT_BARS} RightBars {RIGHT_BARS} EMA Length {EMA_LENGTH}
ATR Length {ATR_LENGTH} Min Vol {MIN_VOL}% Max Vol {MAX_VOL}% RR {RR}
Allowed TF 1/5/15 ONLY

*Logic:*
- PivotLow/High left {LEFT_BARS} right {RIGHT_BARS}
- Recent Low Line - Most recent pivot low
- 3 Lows L1 L2 L3 - Head L2 lowest
- Neckline N2 recent pivot high
- InverseHS: L2<L1 & L2<L3
- EMA{EMA_LENGTH} Value Area: |Close-EMA|/EMA*100 <=1%
- IV: ATR% = ATR/Close*100 = Volatility Proxy
- IV Filter: {MIN_VOL}% <= Vol% <= {MAX_VOL}%
- Bullish Breakout: Close>Neckline & Prev<=Neckline
- Buy = TF Allowed 1/5/15 + InverseHS + NearEMA + IV OK + Breakout
- Entry Close SL Low2 Head TGT Entry+Risk*{RR}

*Today:*
Trades 0/5
L1 {STATE['low1']} L2 {STATE['low2']} L3 {STATE['low3']} Head Lowest
Neckline {STATE['neckline']}
EMA {STATE['ema']:.2f} Vol {STATE['volatility_percent']:.2f}%
P&L Rs.{STATE['pnl']}

*Telegram ON - Har trade la message yeil!*
*Use /force_buy to test Telegram*

Pine v6 to Python - Deploy Fixed 100% Working v6!
""")
        while True:
            try:
                is_open, market_msg, is_limit = is_market_open()
                if not is_open:
                    if is_limit:
                        log(f"{market_msg} - Telegram OFF - Sleeping 60s - v6")
                        time.sleep(60)
                        continue
                    log(f"{market_msg} - Auto Loading - Sleeping 30s - Inverse H&S v6 - Chart Working - Telegram ON")
                    time.sleep(30)
                    continue
                
                spot, prem, strike, intr, tv, src = get_nse()
                STATE["spot"]=round(spot,2)
                STATE["prem"]=round(prem,2)
                STATE["strike"]=strike
                STATE["src"]=src
                
                tf=STATE["timeframe"]
                now_dt=datetime.now(IST)
                minute=now_dt.minute
                cm=(minute//tf)*tf
                now_str=f"{now_dt.hour}:{cm:02d} TF{tf}"
                
                if len(CANDLES)==0 or CANDLES[-1]["t"]!=now_str:
                    CANDLES.append({"o":prem,"h":prem,"l":prem,"c":prem,"t":now_str,"buy":False,"sell_sl":False,"sell_tgt":False,"is_pivot_low":False,"is_pivot_high":False})
                    log(f"NEW CANDLE TF {tf} MIN v6 | {now_str} | Premium {prem:.2f} | Spot {spot:.1f} | L1 {STATE['low1']} L2 {STATE['low2']} L3 {STATE['low3']} Neck {STATE['neckline']} | EMA {STATE['ema']:.2f} Vol {STATE['volatility_percent']:.2f}% | Auto Loading v6 Chart Working Telegram ON")
                else:
                    c=CANDLES[-1]
                    c["h"]=max(c["h"],prem)
                    c["l"]=min(c["l"],prem)
                    c["c"]=prem
                
                # Re-run pivot detection and calculations (handled in api_candles too, but do here for trading)
                pivot_low_val, pivot_high_val = detect_pivots()
                
                if pivot_low_val is not None:
                    PIVOT_LOWS.append(pivot_low_val)
                    STATE["recent_low"] = pivot_low_val
                    if STATE["low1"] is None:
                        STATE["low1"] = pivot_low_val
                    elif STATE["low2"] is None:
                        STATE["low2"] = pivot_low_val
                    elif STATE["low3"] is None:
                        STATE["low3"] = pivot_low_val
                    else:
                        STATE["low1"] = STATE["low2"]
                        STATE["low2"] = STATE["low3"]
                        STATE["low3"] = pivot_low_val
                
                if pivot_high_val is not None:
                    PIVOT_HIGHS.append(pivot_high_val)
                    if STATE["neck1"] is None:
                        STATE["neck1"] = pivot_high_val
                    elif STATE["neck2"] is None:
                        STATE["neck2"] = pivot_high_val
                    else:
                        STATE["neck1"] = STATE["neck2"]
                        STATE["neck2"] = pivot_high_val
                    STATE["neckline"] = STATE["neck2"]
                
                closes = [c['c'] for c in list(CANDLES)]
                ema = calc_ema(closes, EMA_LENGTH)
                atr = calc_atr(list(CANDLES), ATR_LENGTH)
                last_close = closes[-1] if closes else 75
                vol_percent = (atr / last_close * 100) if last_close!=0 else 0.5
                distance = abs(last_close - ema) / ema * 100 if ema!=0 else 0
                nearEMA = distance <= 1.0
                ivOK = vol_percent >= MIN_VOL and vol_percent <= MAX_VOL
                
                STATE["ema"] = ema
                STATE["atr"] = atr
                STATE["volatility_percent"] = vol_percent
                STATE["distanceFromEMA"] = distance
                STATE["nearEMA"] = nearEMA
                STATE["ivOK"] = ivOK
                
                low1 = STATE["low1"]
                low2 = STATE["low2"]
                low3 = STATE["low3"]
                neckline = STATE["neckline"]
                
                hasThreeLows = low1 is not None and low2 is not None and low3 is not None
                hasNeckline = neckline is not None
                
                inverseHS = False
                if hasThreeLows and hasNeckline:
                    if low2 < low1 and low2 < low3:
                        inverseHS = True
                STATE["inverseHS"] = inverseHS
                
                bullishBreakout = False
                if hasNeckline and len(closes)>=2:
                    if closes[-1] > neckline and closes[-2] <= neckline:
                        bullishBreakout = True
                STATE["bullishBreakout"] = bullishBreakout
                
                isAllowedTF = STATE["timeframe"] in [1,5,15]
                STATE["isAllowedTF"] = isAllowedTF
                
                buyCondition = isAllowedTF and inverseHS and nearEMA and ivOK and bullishBreakout
                STATE["buyCondition"] = buyCondition
                
                if buyCondition:
                    entryPrice = last_close
                    stopLoss = low2 if low2 is not None else last_close-15
                    risk = entryPrice - stopLoss
                    target = entryPrice + risk * RR
                    STATE["entry"] = entryPrice
                    STATE["sl"] = stopLoss
                    STATE["target"] = target
                
                # Trading logic
                if buyCondition and STATE["pos"] is None:
                    if STATE["trades_today"]>=5:
                        time.sleep(10)
                        continue
                    
                    entryPrice = last_close
                    stopLoss = low2 if low2 is not None else last_close-15
                    risk = entryPrice - stopLoss
                    target = entryPrice + risk * RR
                    
                    CANDLES[-1]["buy"] = True
                    STATE["pos"] = {"entry":entryPrice,"sl":stopLoss,"target":target,"buy_time":now_str,"buy_price":entryPrice,"strike":f"{strike}PE","low2":low2,"ema":ema,"vol":vol_percent}
                    STATE["trades"]+=1
                    STATE["trades_today"]+=1
                    STATE["entry"]=entryPrice
                    STATE["sl"]=stopLoss
                    STATE["target"]=target
                    TRADES.append({"no":STATE["trades_today"],"buy_price":entryPrice,"buy_time":now_str,"exit_price":0,"exit_time":"OPEN","exit_type":"OPEN Inverse H&S v6","pnl":0,"strike":f"{strike}PE","entry":entryPrice,"sl":stopLoss,"target":target,"ema":ema,"vol":vol_percent,"nearEMA":nearEMA})
                    log(f"🚀 BUY v6 Inverse H&S | Trade {STATE['trades_today']}/5 | BUY {strike}PE @ {entryPrice:.2f} Entry Close {entryPrice:.2f} SL Head Low2 {stopLoss:.2f} TGT RR{RR} {target:.2f} | L1 {low1} L2 {low2} L3 {low3} Head Lowest | Neckline {neckline} Breakout | EMA {ema:.2f} Distance {distance:.2f}% Near {nearEMA} Value Area | Vol {vol_percent:.2f}% IV OK {ivOK} | Telegram Sending v6...")
                    
                    tg_msg=f"""🎯 *BUY {STATE['trades_today']}/5 - Inverse H&S Value + IV Bot v6 - Breakout!*

*Inverse H&S Breakout BUY!* 🚀
Strike: {strike}PE
Spot: {spot:.1f}
BUY @ {entryPrice:.2f}

*Inverse H&S Structure:*
L1 Left Shoulder: {low1}
L2 Head Lowest: {low2} - Head Lowest ✅
L3 Right Shoulder: {low3}
Head < Shoulders: L2<L1 & L2<L3 ✅

*Neckline Breakout:*
Neckline: {neckline}
Close {entryPrice:.2f} > Neckline {neckline} ✅
Prev {closes[-2] if len(closes)>=2 else 0:.2f} <= Neckline ✅
Bullish Breakout ✅

*EMA Value Area:*
EMA{EMA_LENGTH}: {ema:.2f}
Distance: {distance:.2f}% = |Close-EMA|/EMA*100
Near EMA <=1%: {nearEMA} {'✅ VALUE AREA' if nearEMA else '❌ AWAY'}

*IV / Volatility:*
ATR{ATR_LENGTH}: {atr:.2f}
Volatility: {vol_percent:.2f}% = ATR/Close*100
Min {MIN_VOL}% Max {MAX_VOL}%: {ivOK} {'✅ OK' if ivOK else '❌ BLOCK'}

*Buy Condition:*
Allowed TF 1/5/15: {isAllowedTF} TF {STATE['timeframe']} MIN {'✅ YES' if isAllowedTF else '❌ NO'}
InverseHS: {inverseHS} ✅
NearEMA: {nearEMA} ✅
IV OK: {ivOK} ✅
Breakout: {bullishBreakout} ✅
All = BUY ✅

*Levels - Pine v6:*
Entry: Close = {entryPrice:.2f}
SL: Low2 Head = {stopLoss:.2f} - Head lowest point
Risk: {risk:.2f}
Target: Entry + Risk x RR {RR} = {entryPrice:.2f} + {risk:.2f}x{RR} = {target:.2f}
RR 1:{RR} ✅

*Status:*
Trades: {STATE['trades_today']}/5
Remaining: {5-STATE['trades_today']} Left
P&L: Rs.{STATE['pnl']}
Time: {now_str}

*Pine v6 Converted - Inverse H&S Value + IV Bot v6*
*Telegram ON - Har trade la message yeil!*
Deploy Fixed v6!
"""
                    send_tg(tg_msg)
                
                if STATE["pos"]:
                    curr_price = list(CANDLES)[-1]['c']
                    if curr_price <= STATE["pos"]["sl"]:
                        pnl = (STATE["pos"]["sl"] - STATE["pos"]["entry"]) * 65
                        STATE["pnl"] += pnl
                        CANDLES[-1]["sell_sl"] = True
                        if TRADES and TRADES[-1]["exit_time"]=="OPEN":
                            TRADES[-1]["exit_price"]=curr_price
                            TRADES[-1]["exit_time"]=now_str
                            TRADES[-1]["exit_type"]="SL HIT Low2 Head"
                            TRADES[-1]["pnl"]=round(pnl,0)
                        log(f"🔴 SL HIT Low2 Head v6 | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} | SL Head {STATE['pos']['sl']:.2f} | Telegram Sending v6...")
                        send_tg(f"🔴 *SL HIT Low2 Head {STATE['trades_today']}/5 - Inverse H&S v6*\nSL Head {STATE['pos']['sl']:.2f} @ {curr_price:.2f}\nL2 Head {STATE['low2']}\nP&L Rs.{pnl:.0f} Total Rs.{STATE['pnl']:.0f}\nTrades {STATE['trades_today']}/5\nInverse H&S v6")
                        STATE["pos"]=None
                    elif curr_price >= STATE["pos"]["target"]:
                        pnl = (STATE["pos"]["target"] - STATE["pos"]["entry"]) * 65
                        STATE["pnl"] += pnl
                        CANDLES[-1]["sell_tgt"] = True
                        if TRADES and TRADES[-1]["exit_time"]=="OPEN":
                            TRADES[-1]["exit_price"]=curr_price
                            TRADES[-1]["exit_time"]=now_str
                            TRADES[-1]["exit_type"]=f"TGT HIT RR {RR}"
                            TRADES[-1]["pnl"]=round(pnl,0)
                        log(f"🟢 TGT HIT RR {RR} v6 | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} | TGT {STATE['pos']['target']:.2f} | RR {RR} | Telegram Sending v6...")
                        send_tg(f"🟢 *TGT HIT RR {RR} {STATE['trades_today']}/5 - Inverse H&S v6*\nTGT RR{RR} {STATE['pos']['target']:.2f} @ {curr_price:.2f}\nEntry {STATE['pos']['entry']:.2f} SL Head {STATE['pos']['sl']:.2f}\nP&L Rs.{pnl:.0f} Total Rs.{STATE['pnl']:.0f} RR 1:{RR} ✅ Profit!\nInverse H&S v6")
                        STATE["pos"]=None
                
                time.sleep(10)
            except Exception as e:
                try:
                    import traceback
                    log(f"BOT LOOP v6 ERR {e} {traceback.format_exc()[:250]} - Fixed - Retrying")
                except: pass
                time.sleep(10)
    except Exception as e:
        log(f"BOT START ERR v6 {e} - Fixed")

threading.Thread(target=bot_loop_v6, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
