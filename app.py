
from flask import Flask, jsonify, request
import threading, time, os, requests, random, math
from datetime import datetime
import pytz
from collections import deque

app = Flask(__name__)
LOGS = deque(maxlen=500)
CANDLES = deque(maxlen=500)
TRADES_HISTORY = deque(maxlen=20)
STATE = {
    "trades":0,"trades_today":0,"max_trades":5,"pnl":0,
    "spot":22527,"prem":0,"strike":0,
    "intrinsic":0,"time_value":0,"delta":0.30,
    "fib_high":0,"fib_low":0,"range":0,
    "pos":None,"telegram_ok":False,"trade_date":None,
    "telegram_limit_sent":False,"telegram_enabled":True,"force_trade":False,
    "timeframe":5,
    "timeframe_str":"5 MIN",
    "sl_fib":0.35,
    "entry_fib":0.5,
    "tgt_fib":2.414
}
IST = pytz.timezone('Asia/Kolkata')
def add_log(m):
    ts=datetime.now(IST).strftime("%H:%M:%S")
    LOGS.append(f"{ts} | {m}")
def get_timeframe(): return STATE["timeframe"]
def get_timeframe_str(): return f"{STATE['timeframe']} MIN"
def is_market_open():
    now=datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    if STATE["trade_date"] != today:
        if STATE["trade_date"] is not None:
            add_log(f"NEW DAY {today} Reset 0/5 - TF {get_timeframe_str()} - SL Fib 0.35 Updated")
        STATE["trade_date"]=today; STATE["trades_today"]=0; STATE["trades"]=0; STATE["telegram_limit_sent"]=False; STATE["telegram_enabled"]=True
    if STATE["force_trade"]:
        return True, f"FORCE MODE ON - {STATE['trades_today']}/5 - TF {get_timeframe_str()} - SL 0.35 Fib - 5 MIN HL", False
    if now.weekday()>=5: return False, f"Closed Weekend {now.strftime('%A')} - Use /force_trade", False
    mo=now.replace(hour=9,minute=15,second=0,microsecond=0); mc=now.replace(hour=15,minute=30,second=0,microsecond=0)
    if now<mo: return False, f"Pre-Market {now.strftime('%H:%M')} Opens 9:15 AM - TF {get_timeframe_str()} SL 0.35", False
    if now>mc: return False, f"Post-Market {now.strftime('%H:%M')} Closed 3:30 PM", False
    if STATE["trades_today"]>=5: return False, f"5 Trades Limit {STATE['trades_today']}/5 - Telegram OFF", True
    return True, f"Market Open 9:15 AM - {STATE['trades_today']}/5 - TF {get_timeframe_str()} - SL 0.35 Fib - 5 MIN HL - Delta {STATE['delta']}", False
def send_telegram(text):
    if STATE["trades_today"] >= 5:
        if not STATE["telegram_limit_sent"]:
            try:
                token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
                if not token or not chat: return False
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":f"🔕 *5 Trades Complete TF {get_timeframe_str()} - Telegram OFF*\nTrades: {STATE['trades_today']}/5\nP&L: Rs.{STATE['pnl']}", "parse_mode":"Markdown"},timeout=10)
                STATE["telegram_limit_sent"]=True; STATE["telegram_enabled"]=False
            except: pass
        return False
    if not STATE["telegram_enabled"]: return False
    try:
        token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat: return False
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":text,"parse_mode":"Markdown"},timeout=10)
        if r.status_code==200: STATE["telegram_ok"]=True; return True
        return False
    except: return False
def calculate_delta_approx(spot, strike, premium, option_type="PE"):
    moneyness = (strike - spot) / spot
    est = 0.5 + moneyness * 15
    return max(0.05, min(0.95, est))
def get_real_nse_with_intrinsic_delta():
    try:
        headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.nseindia.com/option-chain"}
        s=requests.Session(); s.headers.update(headers)
        s.get("https://www.nseindia.com/option-chain",timeout=8)
        r=s.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",timeout=8)
        if r.status_code==200:
            d=r.json(); spot=float(d["records"]["underlyingValue"]); all_data = d["records"]["data"]
            candidates = []
            for it in all_data:
                strike = it.get("strikePrice"); pe = it.get("PE")
                if not pe or not strike: continue
                last_price = pe.get("lastPrice", 0)
                if last_price <= 0: continue
                if strike < spot - 400 or strike > spot + 200: continue
                intrinsic = max(strike - spot, 0); time_value = last_price - intrinsic
                if time_value < 0: time_value = last_price
                est_delta = calculate_delta_approx(spot, strike, last_price, "PE")
                if 0.20 <= est_delta <= 0.40:
                    candidates.append({"strike": strike,"last_price": last_price,"intrinsic": intrinsic,"time_value": time_value,"delta": est_delta,"score": abs(est_delta-0.30),"moneyness": (strike - spot)/spot})
            if candidates:
                candidates.sort(key=lambda x: x["score"])
                best = candidates[0]
                add_log(f"NSE REAL TF {get_timeframe_str()} SL 0.35 | Spot {spot:.1f} | Strike {best['strike']} | Premium {best['last_price']:.2f} = Intrinsic {best['intrinsic']:.2f}+Time {best['time_value']:.2f} | Delta {best['delta']:.3f}")
                return spot, best['last_price'], best['strike'], best['intrinsic'], best['time_value'], best['delta'], best['moneyness'], f"NSE_LIVE_TF_{get_timeframe_str()}_SL0.35"
    except Exception as e:
        add_log(f"NSE ERR {e}")
    spot_sim = 22527 + random.uniform(-40, 40)
    strike_sim = int((spot_sim * 0.988)//50*50)
    intrinsic_sim = max(strike_sim - spot_sim, 0)
    base_tv = 65 + random.uniform(-5, 10)
    time_value_sim = base_tv + random.uniform(-3, 3) + math.sin(time.time()/60)*2
    premium_sim = intrinsic_sim + time_value_sim
    delta_sim = calculate_delta_approx(spot_sim, strike_sim, premium_sim)
    moneyness_sim = (strike_sim - spot_sim)/spot_sim
    return spot_sim, premium_sim, strike_sim, intrinsic_sim, time_value_sim, delta_sim, moneyness_sim, f"SIM_TF_{get_timeframe_str()}_SL0.35"

def detect_swings_5min_sl035():
    """
    UPDATE: SL Sarkha hit hotoy - Fibonacci nusar 0.35 la thev - 5 MIN Timeframe cha High Low nusar
    - 5 MIN Timeframe cha High Low
    - Swing detection 5 MIN TF
    - SL = Fib Low + Range * 0.35 (Adhi 0.36 hota - Aata 0.35)
    - Entry = 0.5, SL = 0.35, TGT = 2.414
    - SL thoda khali - Less SL hits - More room!
    """
    tf = STATE["timeframe"]
    min_candles = 12; WINDOW = 5; MIN_GAP = 6
    if len(CANDLES) < min_candles: return None
    clist = list(CANDLES)
    swing_highs = []; swing_lows = []
    for i in range(WINDOW, len(clist)-WINDOW):
        curr = clist[i]
        is_high = True; is_low = True
        for j in range(i-WINDOW, i+WINDOW+1):
            if j == i: continue
            if clist[j]['h'] >= curr['h']: is_high = False
            if clist[j]['l'] <= curr['l']: is_low = False
        if is_high: swing_highs.append({"idx":i,"value":curr['h'],"time":curr['t']})
        if is_low: swing_lows.append({"idx":i,"value":curr['l'],"time":curr['t']})
    if not swing_highs or not swing_lows: return None
    filtered_highs = []; last_idx = -100
    for sh in swing_highs:
        if sh['idx'] - last_idx >= MIN_GAP:
            filtered_highs.append(sh); last_idx = sh['idx']
        else:
            if sh['value'] > filtered_highs[-1]['value']:
                filtered_highs[-1] = sh; last_idx = sh['idx']
    filtered_lows = []; last_idx = -100
    for sl in swing_lows:
        if sl['idx'] - last_idx >= MIN_GAP:
            filtered_lows.append(sl); last_idx = sl['idx']
        else:
            if sl['value'] < filtered_lows[-1]['value']:
                filtered_lows[-1] = sl; last_idx = sl['idx']
    if not filtered_highs or not filtered_lows: return None
    recent_high = filtered_highs[-1]; recent_low = filtered_lows[-1]
    fib_high_actual = max(recent_high['value'], recent_low['value'])
    fib_low_actual = min(recent_high['value'], recent_low['value'])
    rng = fib_high_actual - fib_low_actual
    if rng < 3: return None
    
    # UPDATE: SL Fibonacci 0.35 - 5 MIN TF High Low nusar
    sl_fib = STATE["sl_fib"]  # 0.35
    entry_fib = STATE["entry_fib"]  # 0.5
    tgt_fib = STATE["tgt_fib"]  # 2.414
    
    return {
        "swing_high":recent_high,
        "swing_low":recent_low,
        "fib_high":fib_high_actual,
        "fib_low":fib_low_actual,
        "range":rng,
        "0.35":fib_low_actual+rng*sl_fib,
        "0.36":fib_low_actual+rng*0.36,
        "0.5":fib_low_actual+rng*entry_fib,
        "2.414":fib_low_actual+rng*tgt_fib,
        "sl_fib":sl_fib,
        "entry_fib":entry_fib,
        "tgt_fib":tgt_fib,
        "total_swings_high":len(filtered_highs),
        "total_swings_low":len(filtered_lows),
        "tf":tf
    }

for i in range(20):
    c=68+i*0.8+random.uniform(-2,3)
    if i==5: c=82
    if i==14: c=59
    CANDLES.append({"o":c-1,"h":c+1.5,"l":c-1.2,"c":c,"t":f"10:{i:02d} TF5","maru":False,"buy":False,"sell_sl":False,"sell_tgt":False})

HTML = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{background:#0f172a;color:#e2e8f0;padding:10px;font-family:Arial;margin:0}
h2{color:#22c55e;text-align:center;margin:6px 0;font-size:12px;background:#1e293b;padding:8px;border-radius:10px;border:2px solid #22c55e}
.card{background:#1e293b;padding:10px;border-radius:12px;margin:6px 0;border:1px solid #334155}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.box{background:#0f172a;padding:8px;border-radius:10px;border:1px solid #334155;text-align:center}
.box .l{color:#94a3b8;font-size:9px} .box .v{color:#fff;font-size:13px;font-weight:bold;margin-top:2px}
.entry{color:#22c55e !important} .sl{color:#f97316 !important} .tgt{color:#3b82f6 !important} .prem{color:#eab308 !important} .intr{color:#a855f7 !important} .tv{color:#06b6d4 !important}
#chart{background:#ffffff;border-radius:12px;padding:8px;margin:6px 0;min-height:600px;border:3px solid #22c55e}
canvas{width:100%;height:520px;background:#fff;border-radius:8px}
.btn{padding:6px 10px;font-weight:bold;border-radius:8px;text-decoration:none;display:inline-block;margin:3px;font-size:10px}
.btn-g{background:#22c55e;color:#000} .btn-y{background:#eab308;color:#000} .btn-b{background:#3b82f6;color:#fff} .btn-r{background:#ef4444;color:#fff} .btn-p{background:#a855f7;color:#fff} .btn-o{background:#f97316;color:#fff}
.small{font-size:9px;color:#94a3b8}
.status-open{color:#000;background:#22c55e;padding:5px 10px;border-radius:8px;font-size:11px;font-weight:bold;border:2px solid #fff}
.status-closed{color:#fff;background:#ef4444;padding:5px 10px;border-radius:8px;font-size:11px;font-weight:bold}
.status-limit{color:#fff;background:#6b7280;padding:5px 10px;border-radius:8px;font-size:11px;font-weight:bold}
.timeframe-box{background:#0a1a2a;padding:10px;border-radius:10px;border:3px solid #06b6d4;margin:6px 0;text-align:center}
.sl-update-box{background:#1a0a0a;padding:10px;border-radius:10px;border:3px solid #f97316;margin:6px 0;text-align:center}
.intrinsic-box{background:#1a0a2a;padding:8px;border-radius:10px;border:3px solid #a855f7;margin:6px 0;text-align:center}
.limit-box{background:#1a1a00;padding:8px;border-radius:10px;border:3px solid #eab308;margin:6px 0;text-align:center}
</style></head><body>
<h2 id="main_title">🇮🇳 SL Update - Fibonacci 0.35 - 5 MIN TF High Low Nusar - SL Sarkha Hit Hotoy Fix!</h2>

<div class="sl-update-box">
<div style="color:#f97316;font-weight:bold;font-size:14px">🔧 SL Update: Sarkha Hit Hotoy - Fibonacci 0.35 La Thev - 5 MIN TF High Low Nusar!</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-top:8px">
<div style="background:#0f172a;padding:8px;border-radius:8px;border:3px solid #f97316"><div class="small">Adhi SL</div><div style="color:#ef4444;font-size:18px;font-weight:bold">0.36 Fib</div><div class="small">Sarkha hit hotoy</div><div class="small">Loss jasta</div></div>
<div style="background:#0f172a;padding:8px;border-radius:8px;border:3px solid #22c55e"><div class="small">Aata SL</div><div style="color:#22c55e;font-size:20px;font-weight:bold">0.35 Fib ✅</div><div class="small">Thoda khali</div><div class="small">Kam hit</div></div>
<div style="background:#0f172a;padding:8px;border-radius:8px;border:2px solid #22c55e"><div class="small">Entry</div><div style="color:#22c55e;font-size:18px;font-weight:bold">0.5 Fib</div><div class="small">Same - No change</div></div>
<div style="background:#0f172a;padding:8px;border-radius:8px;border:2px solid #3b82f6"><div class="small">Target</div><div style="color:#3b82f6;font-size:18px;font-weight:bold">2.414 Fib</div><div class="small">Same - No change</div></div>
</div>
<div style="display:flex;gap:6px;justify-content:center;margin-top:8px;flex-wrap:wrap">
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #06b6d4"><div class="small">Timeframe</div><div style="color:#06b6d4;font-size:16px;font-weight:bold">5 MIN TF</div><div class="small">High Low nusar</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #ef4444"><div class="small">Swing High Low</div><div style="color:#ef4444;font-size:12px;font-weight:bold">5 MIN High Low</div><div class="small">15 Candle = 75 MIN</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #f97316"><div class="small">SL Logic</div><div style="color:#f97316;font-size:12px;font-weight:bold">Low + Range x 0.35</div><div class="small">Fib 0.35</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #22c55e"><div class="small">Benefit</div><div style="color:#22c55e;font-size:12px;font-weight:bold">Kam SL Hit</div><div class="small">Jasta room</div></div>
</div>
<div class="small" style="margin-top:6px;color:#fff">✅ Adhi SL 0.36 Fib hota - Sarkha hit hotoy - Aata 0.35 Fib la thevla - Thoda khali - 5 MIN TF High Low nusar - SL la jasta room - Kam hit hoil - P&L vadhil! Entry 0.5, SL 0.35, TGT 2.414 - 5 MIN High Low</div>
</div>

<div class="timeframe-box">
<div style="color:#06b6d4;font-weight:bold;font-size:13px">⏰ 5 MIN TF - High Low - 75 MIN Swing - SL 0.35 Fib</div>
<div style="display:flex;gap:6px;justify-content:center;margin-top:6px;flex-wrap:wrap">
<a class="btn btn-o" href="/set_timeframe/1">1 MIN</a>
<a class="btn btn-y" href="/set_timeframe/3">3 MIN</a>
<a class="btn btn-g" href="/set_timeframe/5">5 MIN Best ✅ SL 0.35</a>
<a class="btn btn-b" href="/set_timeframe/15">15 MIN</a>
</div>
<div style="display:flex;gap:6px;justify-content:center;margin-top:6px;flex-wrap:wrap">
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #06b6d4"><div class="small">Current TF</div><div id="current_tf" style="color:#06b6d4;font-size:18px;font-weight:bold">5 MIN</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #f97316"><div class="small">SL Fib</div><div id="sl_fib_top" style="color:#f97316;font-size:18px;font-weight:bold">0.35</div><div class="small">Updated</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #22c55e"><div class="small">Entry Fib</div><div style="color:#22c55e;font-size:16px;font-weight:bold">0.5</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #3b82f6"><div class="small">TGT Fib</div><div style="color:#3b82f6;font-size:16px;font-weight:bold">2.414</div></div>
</div>
</div>

<div class="intrinsic-box">
<div style="color:#a855f7;font-weight:bold;font-size:11px">💎 5 MIN TF - Intrinsic + Delta 0.30 - SL 0.35 Fib - Premium NOT Stable</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:5px;margin-top:5px">
<div style="background:#0f172a;padding:5px;border-radius:8px;border:1px solid #a855f7"><div class="small">Spot LIVE</div><div id="spot_live" style="color:#fff;font-size:14px;font-weight:bold">22527</div></div>
<div style="background:#0f172a;padding:5px;border-radius:8px;border:1px solid #ef4444"><div class="small">Strike Δ0.30</div><div id="strike_delta" style="color:#eab308;font-size:14px;font-weight:bold">22250PE</div></div>
<div style="background:#0f172a;padding:5px;border-radius:8px;border:1px solid #a855f7"><div class="small">Intrinsic</div><div id="intrinsic_val" style="color:#a855f7;font-size:14px;font-weight:bold">0.00</div></div>
<div style="background:#0f172a;padding:5px;border-radius:8px;border:1px solid #06b6d4"><div class="small">Time Value</div><div id="time_val" style="color:#06b6d4;font-size:14px;font-weight:bold">87.30</div></div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:5px;margin-top:5px">
<div style="background:#0f172a;padding:5px;border-radius:8px;border:1px solid #22c55e"><div class="small">Premium LIVE</div><div id="prem_live" style="color:#eab308;font-size:16px;font-weight:bold">87.30</div></div>
<div style="background:#0f172a;padding:5px;border-radius:8px;border:1px solid #f97316"><div class="small">SL 0.35</div><div id="sl_live" style="color:#f97316;font-size:16px;font-weight:bold">0.35</div><div class="small">Fib SL</div></div>
<div style="background:#0f172a;padding:5px;border-radius:8px;border:1px solid #f97316"><div class="small">Moneyness</div><div id="moneyness_val" style="color:#f97316;font-size:11px;font-weight:bold">-1.20% OTM</div></div>
<div style="background:#0f172a;padding:5px;border-radius:8px;border:1px solid #fff"><div class="small">Breakup</div><div id="breakup_val" style="color:#fff;font-size:9px;font-weight:bold">0 + 87.30 = 87.30</div></div>
</div>
</div>

<div class="limit-box">
<div style="color:#eab308;font-weight:bold;font-size:11px">⏰ Only 5 Trade - TF 5 MIN - SL 0.35 Fib - 5 MIN HL - Delta 0.30</div>
<div style="display:flex;gap:5px;justify-content:center;margin-top:4px;flex-wrap:wrap">
<div style="background:#0f172a;padding:5px 10px;border-radius:8px;border:2px solid #22c55e"><div class="small">Trades</div><div id="trades_today" style="color:#22c55e;font-size:16px;font-weight:bold">0/5</div></div>
<div style="background:#0f172a;padding:5px 10px;border-radius:8px;border:2px solid #f97316"><div class="small">SL Fib</div><div id="sl_fib_box_top" style="color:#f97316;font-size:14px;font-weight:bold">0.35</div></div>
<div style="background:#0f172a;padding:5px 10px;border-radius:8px;border:2px solid #06b6d4"><div class="small">TF</div><div id="tf_top" style="color:#06b6d4;font-size:14px;font-weight:bold">5 MIN</div></div>
<div style="background:#0f172a;padding:5px 10px;border-radius:8px;border:2px solid #eab308"><div class="small">Remain</div><div id="trades_remain_top" style="color:#eab308;font-size:16px;font-weight:bold">5 Left</div></div>
</div>
</div>

<div class="card">
<div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center">
<span id="market_status" class="status-open">● Market Open 9:15 AM - 0/5 - TF 5 MIN SL 0.35</span>
<span id="nse_status" style="color:#000;background:#eab308;padding:3px 6px;border-radius:6px;font-size:9px">● NSE LIVE SL 0.35</span>
<span id="tg_status" style="color:#fff;background:#22c55e;padding:3px 6px;border-radius:6px;font-size:9px">● TELEGRAM ON</span>
<span id="force_status" style="color:#fff;background:#6b7280;padding:3px 6px;border-radius:6px;font-size:9px">● FORCE OFF</span>
<span id="tf_status" style="color:#fff;background:#06b6d4;padding:3px 6px;border-radius:6px;font-size:9px">● TF 5 MIN SL 0.35</span>
<span id="lt" class="small"></span>
</div>

<div class="grid" style="margin-top:6px">
<div class="box"><div class="l">No. Of Trade (Today)</div><div class="v" id="trades" style="font-size:16px">0/5</div></div>
<div class="box"><div class="l">Which Premium Δ0.30</div><div class="v prem" id="which_prem">22250PE Δ0.30</div><div class="small">TF 5 MIN SL 0.35</div></div>
<div class="box"><div class="l">Entry Price (0.5 Fib)</div><div class="v entry" id="entry_p">75.20 BUY</div><div class="small">5 MIN HL 0.5</div></div>
<div class="box"><div class="l">SL Price (0.35 Fib) ✅ Updated</div><div class="v sl" id="sl_p">70.50 → Trail</div><div class="small">5 MIN HL 0.35 - Less hit</div></div>
<div class="box"><div class="l">Target Price (2.414 Fib)</div><div class="v tgt" id="tgt_p">132.62 TGT</div><div class="small">5 MIN HL 2.414</div></div>
<div class="box"><div class="l">Total P&L</div><div class="v" id="pnl" style="color:#22c55e;font-size:16px">Rs.0</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1fr 1fr;gap:4px;margin-top:6px">
<div class="box"><div class="l">Spot</div><div class="v small" id="spot_box">22527 LIVE</div></div>
<div class="box"><div class="l">Strike Δ0.30</div><div class="v small" id="strike_box">22250PE</div></div>
<div class="box"><div class="l">Intrinsic</div><div class="v small intr" id="intrinsic_box">0.00</div></div>
<div class="box"><div class="l">Time Value</div><div class="v small tv" id="time_box">87.30</div></div>
<div class="box"><div class="l">Premium</div><div class="v small prem" id="prem_box">87.30 LIVE</div></div>
<div class="box"><div class="l">SL Fib</div><div class="v small sl" id="sl_fib_box">0.35 ✅</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:4px;margin-top:4px">
<div class="box"><div class="l">TF</div><div class="v small" id="tf_box" style="color:#06b6d4">5 MIN SL 0.35</div></div>
<div class="box"><div class="l">Swing High 5 MIN</div><div class="v small" id="swing_high" style="color:#ef4444">90.2 @10:18</div><div class="small">5 MIN HL</div></div>
<div class="box"><div class="l">Swing Low 5 MIN</div><div class="v small" id="swing_low" style="color:#22c55e">60.2 @10:00</div><div class="small">5 MIN HL</div></div>
<div class="box"><div class="l">Fib H L R SL 0.35</div><div class="v small" id="fib_info">H 90.2 L 60.2 R 30.0 SL 70.5</div></div>
</div>

<div style="margin-top:6px">
<a class="btn btn-o" href="/set_timeframe/1">1 MIN</a>
<a class="btn btn-g" href="/set_timeframe/5">5 MIN Best SL 0.35 ✅</a>
<a class="btn btn-b" href="/set_timeframe/15">15 MIN</a>
<a class="btn btn-p" href="/force_buy">🟢 Force BUY</a>
<a class="btn btn-r" href="/force_sell">🔴 Force SELL</a>
<a class="btn btn-p" href="/force_trade">⚡ Force ON</a>
<a class="btn btn-g" href="/test_telegram">🔔 Test TG</a>
</div>
</div>

<div id="chart">
<div style="color:#000;font-weight:bold;text-align:center;font-size:11px">📈 LIVE 5 MIN - SL 0.35 Fib - 5 MIN High Low Nusar - SL Sarkha Hit Fix! - Less SL Hit - Jasta Room</div>
<canvas id="c" width="800" height="520"></canvas>
<div style="color:#000;font-size:8px;text-align:center;margin-top:2px">✅ SL Update: Adhi 0.36 Fib hota - Sarkha hit hotoy - Aata 0.35 Fib - Thoda khali - 5 MIN TF High Low nusar - SL la jasta room - Kam hit hoil - Entry 0.5, SL 0.35, TGT 2.414 - 5 MIN HL - Delta 0.30 + Intrinsic</div>
<div id="trade_list" style="color:#000;font-size:9px;margin-top:4px;background:#f0f0f0;padding:5px;border-radius:6px"></div>
</div>

<div class="card">
<pre id="log" style="background:#0f172a;color:#22c55e;padding:6px;border-radius:8px;border:1px solid #334155;font-size:8px;max-height:250px;overflow:auto;white-space:pre-wrap"></pre>
</div>

<script>
let candles=[];
let fib={low:60.2,high:90.2,range:30,"0.35":70.5,"0.36":71.0,"0.5":75.2,"2.414":132.62,swingHigh:{value:90.2,time:"10:18"},swingLow:{value:60.2,time:"10:00"},sl_fib:0.35};
let tradesHistory=[];
function draw(){
 let canvas=document.getElementById('c'); let ctx=canvas.getContext('2d');
 let W=canvas.width, H=canvas.height, pad=45;
 if(candles.length==0) return;
 ctx.clearRect(0,0,W,H); ctx.fillStyle="#fff"; ctx.fillRect(0,0,W,H);
 let allHighs=candles.map(c=>c.h); let allLows=candles.map(c=>c.l);
 let min=Math.min(...allLows,fib.low,fib["0.35"])-8; let max=Math.max(...allHighs,fib.high,fib["2.414"])+12;
 let y=v=>H-pad-(v-min)/(max-min)*(H-pad*2); let x=i=>pad+i/(candles.length-1)*(W-pad*2);
 ctx.strokeStyle="#eee"; ctx.lineWidth=1;
 for(let i=0;i<=5;i++){let yy=pad+i*(H-pad*2)/5; ctx.beginPath(); ctx.moveTo(pad,yy); ctx.lineTo(W-pad,yy); ctx.stroke(); ctx.fillStyle="#666"; ctx.font="9px Arial"; ctx.fillText((max-(max-min)*i/5).toFixed(0),5,yy);}
 function line(val,color,label,dash,width){ctx.strokeStyle=color; ctx.lineWidth=width||2; ctx.setLineDash(dash||[]); ctx.beginPath(); ctx.moveTo(pad,y(val)); ctx.lineTo(W-pad,y(val)); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle=color; ctx.font="bold 10px Arial"; ctx.fillText(label+" "+val.toFixed(1),W-pad+5,y(val)-2);}
 line(fib.high,"#ef4444","5MIN Swing High",[8,4],2);
 line(fib.low,"#000","5MIN Swing Low",[8,4],2);
 line(fib["0.5"],"#22c55e","0.5 ENTRY BUY - 5MIN HL",[],3);
 line(fib["0.35"],"#f97316","0.35 SL - Updated - 5MIN HL - Less Hit",[4,4],3);
 line(fib["2.414"],"#3b82f6","2.414 TGT - 5MIN HL",[],3);
 candles.forEach((c,i)=>{
  let g=c.c>=c.o; ctx.fillStyle=g?"#22c55e":"#ef4444"; ctx.strokeStyle=g?"#16a34a":"#dc2626";
  let bh=Math.abs(y(c.o)-y(c.c)); let by=Math.min(y(c.o),y(c.c)); let w=Math.max(4, (W-pad*2)/candles.length*0.6);
  ctx.beginPath(); ctx.moveTo(x(i),y(c.h)); ctx.lineTo(x(i),y(c.l)); ctx.stroke();
  ctx.fillRect(x(i)-w/2,by,w,Math.max(2,bh));
  if(c.buy){ctx.fillStyle="#22c55e"; ctx.beginPath(); ctx.arc(x(i),y(c.c),14,0,Math.PI*2); ctx.fill(); ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle="#fff"; ctx.font="bold 10px Arial"; ctx.fillText("BUY",x(i)-11,y(c.c)+3);}
  if(c.sell_sl){ctx.fillStyle="#f97316"; ctx.beginPath(); ctx.arc(x(i),y(c.c),14,0,Math.PI*2); ctx.fill(); ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle="#fff"; ctx.font="bold 10px Arial"; ctx.fillText("SL 0.35",x(i)-14,y(c.c)+3);}
  if(c.sell_tgt){ctx.fillStyle="#3b82f6"; ctx.beginPath(); ctx.arc(x(i),y(c.c),14,0,Math.PI*2); ctx.fill(); ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle="#fff"; ctx.font="bold 10px Arial"; ctx.fillText("TGT",x(i)-10,y(c.c)+3);}
 });
 ctx.fillStyle="#000"; ctx.font="8px Arial";
 candles.forEach((c,i)=>{if(i%Math.ceil(candles.length/12)==0){ctx.fillText(c.t,x(i)-10,H-12);}});
}
async function refresh(){
 try{
  let r=await fetch('/api/candles?t='+Date.now()); let j=await r.json();
  candles=j.candles;
  fib.high=j.fib_high; fib.low=j.fib_low; fib.range=j.range; fib["0.5"]=j.entry; fib["0.35"]=j.sl; fib["0.36"]=j.sl_old; fib["2.414"]=j.tgt; fib.sl_fib=j.sl_fib;
  fib.swingHigh=j.swing_high; fib.swingLow=j.swing_low;
  tradesHistory=j.trades_history;
  document.getElementById('spot_live').innerText=j.spot_val.toFixed(1);
  document.getElementById('strike_delta').innerText=j.strike+' Δ'+j.delta.toFixed(2);
  document.getElementById('intrinsic_val').innerText=j.intrinsic.toFixed(2);
  document.getElementById('time_val').innerText=j.time_value.toFixed(2);
  document.getElementById('prem_live').innerText=j.prem_val.toFixed(2);
  document.getElementById('sl_live').innerText=j.sl.toFixed(2)+' (0.35 Fib)';
  document.getElementById('moneyness_val').innerText=(j.moneyness*100).toFixed(2)+'% '+(j.moneyness<0?'OTM':'ITM');
  document.getElementById('breakup_val').innerText=j.intrinsic.toFixed(1)+' + '+j.time_value.toFixed(1)+' = '+j.prem_val.toFixed(1);
  document.getElementById('trades').innerText=j.trades_today+'/5';
  document.getElementById('trades_today').innerText=j.trades_today+'/5';
  document.getElementById('trades_today_top').innerText=j.trades_today+'/5';
  document.getElementById('trades_remain').innerText=(5-j.trades_today)+' Left';
  document.getElementById('trades_remain_top').innerText=(5-j.trades_today)+' Left';
  document.getElementById('which_prem').innerText=j.strike+'PE Δ'+j.delta.toFixed(2);
  document.getElementById('entry_p').innerText=j.entry.toFixed(2)+' BUY (0.5 Fib)';
  document.getElementById('sl_p').innerText=j.sl.toFixed(2)+' SL 0.35 Fib ✅ (5MIN HL)';
  document.getElementById('tgt_p').innerText=j.tgt.toFixed(2)+' TGT (2.414 Fib)';
  document.getElementById('pnl').innerText='Rs.'+j.pnl;
  document.getElementById('swing_high').innerText=j.swing_high.value.toFixed(1)+' @'+j.swing_high.time+' (5MIN)';
  document.getElementById('swing_low').innerText=j.swing_low.value.toFixed(1)+' @'+j.swing_low.time+' (5MIN)';
  document.getElementById('fib_info').innerText='H '+j.fib_high.toFixed(1)+' L '+j.fib_low.toFixed(1)+' R '+j.range.toFixed(1)+' SL 0.35='+j.sl.toFixed(1);
  document.getElementById('spot_box').innerText=j.spot_val.toFixed(1)+' LIVE';
  document.getElementById('strike_box').innerText=j.strike+'PE';
  document.getElementById('intrinsic_box').innerText=j.intrinsic.toFixed(2);
  document.getElementById('time_box').innerText=j.time_value.toFixed(2);
  document.getElementById('prem_box').innerText=j.prem_val.toFixed(2)+' LIVE';
  document.getElementById('sl_fib_box').innerText=j.sl_fib.toFixed(2)+' ✅ Updated';
  document.getElementById('sl_fib_top').innerText=j.sl_fib.toFixed(2);
  document.getElementById('sl_fib_box_top').innerText=j.sl_fib.toFixed(2);
  document.getElementById('current_tf').innerText=j.timeframe_str+' SL 0.35';
  document.getElementById('tf_box').innerText=j.timeframe_str+' SL 0.35';
  document.getElementById('tf_top').innerText=j.timeframe_str;
  document.getElementById('market_status').innerText='● '+j.market;
  document.getElementById('nse_status').innerText='● '+j.src;
  document.getElementById('log').innerText=j.logs.slice(-30).join('\n');
  let tl=document.getElementById('trade_list');
  if(tradesHistory.length>0){
   tl.innerHTML='<b>📊 Trades - TF 5 MIN SL 0.35 Fib - Less SL Hit:</b><br>'+tradesHistory.map(t=>`Trade ${t.no}/5: BUY @${t.buy_price.toFixed(1)} ${t.buy_time} → ${t.exit_type} @${t.exit_price.toFixed(1)} ${t.exit_time} P&L Rs.${t.pnl} - ${t.strike} SL 0.35 Fib - TF ${j.timeframe_str}`).join('<br>');
  } else {
   tl.innerHTML='<b>📊 Trades:</b> No trades yet - TF 5 MIN - SL 0.35 Fib - 5 MIN High Low nusar - Less SL Hit - Jasta Room - Entry 0.5, SL 0.35, TGT 2.414!';
  }
  draw();
 }catch(e){console.log(e);}
}
setInterval(refresh,3000); refresh();
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
    sl_fib = STATE["sl_fib"]
    entry_fib = STATE["entry_fib"]
    tgt_fib = STATE["tgt_fib"]
    return jsonify({
        "candles":clist[-100:],
        "trades_today":STATE["trades_today"],"trades":STATE["trades"],"max_trades":5,
        "strike":f"{STATE['strike']}",
        "entry":STATE["fib_low"]+STATE["range"]*entry_fib if STATE["range"]>0 else 75.2,
        "sl":STATE["fib_low"]+STATE["range"]*sl_fib if STATE["range"]>0 else 70.5,
        "sl_old":STATE["fib_low"]+STATE["range"]*0.36 if STATE["range"]>0 else 71.0,
        "tgt":STATE["fib_low"]+STATE["range"]*tgt_fib if STATE["range"]>0 else 132.6,
        "sl_fib":sl_fib,"entry_fib":entry_fib,"tgt_fib":tgt_fib,
        "pnl":STATE["pnl"],
        "spot_val":STATE["spot"],"prem_val":STATE["prem"],"intrinsic":STATE["intrinsic"],"time_value":STATE["time_value"],
        "delta":STATE["delta"],"moneyness":STATE.get("moneyness",-0.012),
        "fib_high":STATE["fib_high"],"fib_low":STATE["fib_low"],"range":STATE["range"],
        "swing_high":STATE.get("swing_high_info",{"value":STATE["fib_high"] if STATE["fib_high"]>0 else 90.2,"time":"10:18"}),
        "swing_low":STATE.get("swing_low_info",{"value":STATE["fib_low"] if STATE["fib_low"]>0 else 60.2,"time":"10:00"}),
        "total_swings_high":STATE.get("total_swings_high",0),"total_swings_low":STATE.get("total_swings_low",0),
        "trades_history":list(TRADES_HISTORY)[-10:],
        "telegram_enabled":STATE["telegram_enabled"],"force_mode":STATE["force_trade"],
        "timeframe":STATE["timeframe"],"timeframe_str":get_timeframe_str(),
        "src":STATE.get("src","NSE"),"is_open":is_open,"is_limit":is_limit,"market":market_msg,"logs":list(LOGS)[-40:]
    })
@app.route('/set_timeframe/<int:tf>')
def set_timeframe(tf):
    allowed = [1,3,5,15,30]
    if tf not in allowed:
        return jsonify({"ok":False,"msg":f"Allowed: {allowed}"})
    old_tf = STATE["timeframe"]; old_str = get_timeframe_str()
    STATE["timeframe"] = tf; STATE["timeframe_str"] = f"{tf} MIN"
    add_log(f"TIMEFRAME UPDATE | {old_str} → {tf} MIN SL {STATE['sl_fib']} Fib | Candles cleared")
    CANDLES.clear()
    for i in range(10):
        c=70+i*0.8+random.uniform(-2,3)
        CANDLES.append({"o":c-1,"h":c+1.5,"l":c-1.2,"c":c,"t":f"TF{tf}:{i:02d}","maru":False,"buy":False,"sell_sl":False,"sell_tgt":False})
    STATE["fib_high"]=0; STATE["fib_low"]=0; STATE["range"]=0
    send_telegram(f"⏰ *TF Update: {old_str} → {tf} MIN SL {STATE['sl_fib']} Fib*")
    return jsonify({"ok":True,"msg":f"TF Updated: {old_str} → {tf} MIN SL {STATE['sl_fib']} Fib","new_tf":tf,"new_tf_str":f"{tf} MIN"})
@app.route('/health')
def health():
    is_open, msg, is_limit = is_market_open()
    return jsonify({"status":"OK","market":msg,"trades_today":f"{STATE['trades_today']}/5","timeframe":f"{STATE['timeframe']} MIN SL {STATE['sl_fib']} Fib","spot":STATE["spot"],"strike":STATE["strike"],"premium":f"{STATE['prem']:.2f} = {STATE['intrinsic']:.2f}+{STATE['time_value']:.2f}","delta":STATE["delta"],"sl_fib":STATE["sl_fib"]})
@app.route('/force_trade')
def force_trade():
    STATE["force_trade"]=True; return jsonify({"ok":True,"tf":get_timeframe_str(),"sl_fib":STATE["sl_fib"]})
@app.route('/disable_force')
def disable_force():
    STATE["force_trade"]=False; return jsonify({"ok":True})
@app.route('/force_buy')
def force_buy():
    if STATE["trades_today"]>=5: return jsonify({"ok":False,"msg":f"5 Trades Limit {STATE['trades_today']}/5"})
    if STATE["pos"] is not None: return jsonify({"ok":False,"msg":"Position already open"})
    try:
        now=datetime.now(IST).strftime("%H:%M")
        curr = STATE["prem"]
        sl_fib = STATE["sl_fib"]; entry_fib = STATE["entry_fib"]; tgt_fib = STATE["tgt_fib"]
        f05=STATE["fib_low"]+STATE["range"]*entry_fib if STATE["range"]>0 else 75.2
        f035=STATE["fib_low"]+STATE["range"]*sl_fib if STATE["range"]>0 else 70.5
        f2414=STATE["fib_low"]+STATE["range"]*tgt_fib if STATE["range"]>0 else 132.6
        CANDLES[-1]["buy"]=True
        STATE["pos"]={"entry":curr,"sl":f035,"tgt":f2414,"buy_time":now,"buy_price":curr,"strike":f"{STATE['strike']}PE","intrinsic":STATE["intrinsic"],"time_value":STATE["time_value"],"delta":STATE["delta"]}
        STATE["trades"]+=1; STATE["trades_today"]+=1
        TRADES_HISTORY.append({"no":STATE["trades_today"],"buy_price":curr,"buy_time":now,"exit_price":0,"exit_time":"OPEN","exit_type":"OPEN FORCE BUY","pnl":0,"strike":f"{STATE['strike']}PE","delta":STATE["delta"]})
        add_log(f"FORCE BUY TF {get_timeframe_str()} SL {sl_fib} Fib | Trade {STATE['trades_today']}/5 | BUY {STATE['strike']}PE @ {curr:.2f} SL {f035:.2f} (0.35 Fib) | 5 MIN HL | {now}")
        send_telegram(f"🟢 *FORCE BUY {STATE['trades_today']}/5 TF {get_timeframe_str()} SL 0.35 Fib*\nStrike: {STATE['strike']}PE Δ{STATE['delta']:.2f}\nBUY @ {curr:.2f} SL {f035:.2f} (0.35 Fib) 5 MIN HL\nTF: {get_timeframe_str()} | Entry 0.5 TGT 2.414\n{now}")
        return jsonify({"ok":True,"msg":f"BUY {STATE['trades_today']}/5 TF {get_timeframe_str()} SL 0.35 @ {curr:.2f} SL {f035:.2f}"})
    except Exception as e: return jsonify({"ok":False,"msg":str(e)})
@app.route('/force_sell')
def force_sell():
    if STATE["pos"] is None: return jsonify({"ok":False,"msg":"No position"})
    try:
        curr = STATE["prem"]; now=datetime.now(IST).strftime("%H:%M")
        pnl=(curr-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
        exit_type = "FORCE SELL"
        if curr<=STATE["pos"]["sl"]: exit_type="SL HIT 0.35 Fib"; CANDLES[-1]["sell_sl"]=True
        elif curr>=STATE["pos"]["tgt"]: exit_type="TGT HIT 2.414"; CANDLES[-1]["sell_tgt"]=True
        else: CANDLES[-1]["sell_sl"]=True
        if TRADES_HISTORY: last = TRADES_HISTORY[-1]; last["exit_price"]=curr; last["exit_time"]=now; last["exit_type"]=exit_type; last["pnl"]=round(pnl,0)
        add_log(f"FORCE SELL TF {get_timeframe_str()} SL 0.35 | {exit_type} @ {curr:.2f} P&L {pnl:.0f}")
        send_telegram(f"🔴 *{exit_type} {STATE['trades_today']}/5 TF {get_timeframe_str()} SL 0.35*\nSELL @ {curr:.2f} P&L {pnl:.0f}")
        STATE["pos"]=None
        return jsonify({"ok":True,"msg":f"SELL @ {curr:.2f} {exit_type} P&L {pnl:.0f}"})
    except Exception as e: return jsonify({"ok":False,"msg":str(e)})
@app.route('/test_telegram')
def test():
    if not STATE["telegram_enabled"]: return jsonify({"ok":False,"msg":"Telegram OFF"})
    token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat: return jsonify({"ok":False})
    try:
        txt=f"Test TF {get_timeframe_str()} SL {STATE['sl_fib']} Fib - Premium {STATE['prem']:.2f} = {STATE['intrinsic']:.2f}+{STATE['time_value']:.2f} - 5 MIN HL"
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":txt,"parse_mode":"Markdown"},timeout=10)
        return jsonify({"ok":r.status_code==200})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})

def bot_loop():
    add_log(f"BOT START | 5 MIN TF SL 0.35 Fib Update - SL Sarkha hit hotoy fix - 5 MIN HL - SL 0.35 - Less hit!")
    time.sleep(2)
    send_telegram(f"🚀 Bot Started TF 5 MIN SL 0.35 Fib\nSL Update: 0.36 → 0.35 Fib\n5 MIN High Low nusar\nKam SL Hit - Jasta Room\nEntry 0.5 SL 0.35 TGT 2.414")
    while True:
        try:
            is_open, market_msg, is_limit = is_market_open()
            if not is_open:
                add_log(f"{market_msg} - Sleeping 30s")
                time.sleep(30); continue
            spot, prem, strike, intrinsic, time_value, delta, moneyness, src = get_real_nse_with_intrinsic_delta()
            STATE["spot"]=round(spot,2); STATE["prem"]=round(prem,2); STATE["strike"]=strike
            STATE["intrinsic"]=round(intrinsic,2); STATE["time_value"]=round(time_value,2); STATE["delta"]=round(delta,3)
            STATE["moneyness"]=moneyness; STATE["src"]=src
            tf = STATE["timeframe"]
            now_dt = datetime.now(IST)
            minute = now_dt.minute
            candle_minute = (minute // tf) * tf
            now_str = f"{now_dt.hour}:{candle_minute:02d} TF{tf}"
            should_new_candle = False
            if len(CANDLES)==0: should_new_candle = True
            else:
                last_t = CANDLES[-1]["t"]
                if last_t != now_str: should_new_candle = True
            if should_new_candle:
                CANDLES.append({"o":prem,"h":prem,"l":prem,"c":prem,"t":now_str,"maru":False,"buy":False,"sell_sl":False,"sell_tgt":False,"tf":tf})
                add_log(f"NEW CANDLE TF {get_timeframe_str()} SL 0.35 | {now_str} | Premium {prem:.2f} = {intrinsic:.2f}+{time_value:.2f} | Spot {spot:.1f} | SL Fib 0.35 = {STATE['fib_low']+STATE['range']*0.35 if STATE['range']>0 else 0:.2f}")
            else:
                c=CANDLES[-1]; c["h"]=max(c["h"],prem); c["l"]=min(c["l"],prem); c["c"]=prem
            fib_data = detect_swings_5min_sl035()
            if fib_data:
                STATE["fib_high"]=fib_data["fib_high"]; STATE["fib_low"]=fib_data["fib_low"]; STATE["range"]=fib_data["range"]
                STATE["swing_high_info"]=fib_data["swing_high"]; STATE["swing_low_info"]=fib_data["swing_low"]
                STATE["total_swings_high"]=fib_data["total_swings_high"]; STATE["total_swings_low"]=fib_data["total_swings_low"]
                f05=fib_data["0.5"]; f035=fib_data["0.35"]; f036=fib_data["0.36"]; f2414=fib_data["2.414"]
                recent=list(CANDLES)[-12:]; curr=recent[-1]['c']; prev=recent[-2]['c'] if len(recent)>=2 else curr
                cross = prev < f05 and curr >= f05
                near_cross = curr >= f05*0.98 and curr <= f05*1.02 and prev < curr
                trigger = cross or near_cross
                add_log(f"TF {get_timeframe_str()} SL 0.35 Fib 5 MIN HL | Spot {spot:.1f} Strike {strike}PE | Premium {prem:.2f} = {intrinsic:.2f}+{time_value:.2f} | Δ{delta:.3f} | Fib H {fib_data['fib_high']:.1f} L {fib_data['fib_low']:.1f} R {fib_data['range']:.1f} | Entry 0.5={f05:.1f} SL 0.35={f035:.1f} (Adhi 0.36={f036:.1f}) TGT 2.414={f2414:.1f} | 5 MIN HL | Trigger {trigger} | Trades {STATE['trades_today']}/5 | SL 0.35 Less Hit!")
                if trigger and STATE["pos"] is None:
                    if STATE["trades_today"]>=5: time.sleep(10); continue
                    CANDLES[-1]["buy"]=True
                    STATE["pos"]={"entry":curr,"sl":f035,"tgt":f2414,"buy_time":now_str,"buy_price":curr,"strike":f"{strike}PE","intrinsic":intrinsic,"time_value":time_value,"delta":delta,"tf":tf,"sl_fib":0.35}
                    STATE["trades"]+=1; STATE["trades_today"]+=1
                    TRADES_HISTORY.append({"no":STATE["trades_today"],"buy_price":curr,"buy_time":now_str,"exit_price":0,"exit_time":"OPEN","exit_type":"OPEN","pnl":0,"strike":f"{strike}PE","delta":delta,"tf":tf,"sl_fib":0.35})
                    add_log(f"BUY TF {get_timeframe_str()} SL 0.35 Fib | Trade {STATE['trades_today']}/5 | BUY {strike}PE @ {curr:.2f} Entry 0.5={f05:.1f} SL 0.35={f035:.1f} (Adhi 0.36={f036:.1f}) - Thoda khali - Less SL Hit! | TGT {f2414:.1f} | 5 MIN HL | Remaining {5-STATE['trades_today']}")
                    send_telegram(f"🎯 *BUY {STATE['trades_today']}/5 TF {get_timeframe_str()} SL 0.35 Fib*\nStrike: {strike}PE | Spot: {spot:.1f}\nBUY @ {curr:.2f} = {intrinsic:.2f}+{time_value:.2f} | Δ{delta:.3f}\nEntry 0.5: {f05:.2f} SL 0.35: {f035:.2f} (Adhi 0.36={f036:.1f}) - Less Hit!\nTGT 2.414: {f2414:.2f} | 5 MIN HL\nRemaining: {5-STATE['trades_today']} Left")
                if STATE["pos"]:
                    if curr<=STATE["pos"]["sl"]:
                        pnl=(STATE["pos"]["sl"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        CANDLES[-1]["sell_sl"]=True
                        if TRADES_HISTORY and TRADES_HISTORY[-1]["exit_time"]=="OPEN":
                            TRADES_HISTORY[-1]["exit_price"]=curr; TRADES_HISTORY[-1]["exit_time"]=now_str; TRADES_HISTORY[-1]["exit_type"]="SL HIT 0.35 Fib"; TRADES_HISTORY[-1]["pnl"]=round(pnl,0)
                        add_log(f"SL HIT 0.35 Fib TF {get_timeframe_str()} | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} | SL 0.35={STATE['pos']['sl']:.2f} (Adhi 0.36 jasta var hota) | 5 MIN HL | Kam hit!")
                        send_telegram(f"🔴 *SL HIT 0.35 Fib {STATE['trades_today']}/5 TF {get_timeframe_str()}*\nSL 0.35 @ {curr:.2f} = {intrinsic:.2f}+{time_value:.2f} | Adhi 0.36 hota - Aata 0.35\nP&L {pnl:.0f} Total {STATE['pnl']:.0f} | 5 MIN HL")
                        STATE["pos"]=None
                    elif curr>=STATE["pos"]["tgt"]:
                        pnl=(STATE["pos"]["tgt"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        CANDLES[-1]["sell_tgt"]=True
                        if TRADES_HISTORY and TRADES_HISTORY[-1]["exit_time"]=="OPEN":
                            TRADES_HISTORY[-1]["exit_price"]=curr; TRADES_HISTORY[-1]["exit_time"]=now_str; TRADES_HISTORY[-1]["exit_type"]="TGT HIT 2.414"; TRADES_HISTORY[-1]["pnl"]=round(pnl,0)
                        add_log(f"TGT HIT TF {get_timeframe_str()} SL 0.35 | Trade {STATE['trades_today']}/5 P&L {pnl:.0f}")
                        send_telegram(f"🟢 *TGT HIT {STATE['trades_today']}/5 TF {get_timeframe_str()} SL 0.35*\nTGT @ {curr:.2f} = {intrinsic:.2f}+{time_value:.2f}\nP&L {pnl:.0f} Total {STATE['pnl']:.0f} | TF {tf} MIN")
                        STATE["pos"]=None
            time.sleep(15)
        except Exception as e:
            import traceback; add_log(f"ERR {e}"); time.sleep(10)
threading.Thread(target=bot_loop, daemon=True).start()
