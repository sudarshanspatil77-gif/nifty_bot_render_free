
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
    "strike_info":"","premium_breakup":""
}

IST = pytz.timezone('Asia/Kolkata')

def add_log(m):
    ts=datetime.now(IST).strftime("%H:%M:%S")
    LOGS.append(f"{ts} | {m}")

def is_market_open():
    now=datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    if STATE["trade_date"] != today:
        if STATE["trade_date"] is not None:
            add_log(f"NEW DAY {today} Reset 0/5 - Telegram ON - New Premium Selection Delta 0.30")
        STATE["trade_date"]=today; STATE["trades_today"]=0; STATE["trades"]=0; STATE["telegram_limit_sent"]=False; STATE["telegram_enabled"]=True
    if STATE["force_trade"]:
        return True, f"FORCE MODE ON - {STATE['trades_today']}/5 - Delta {STATE['delta']} - Intrinsic+TimeValue", False
    if now.weekday()>=5: return False, f"Closed Weekend {now.strftime('%A')} - Use /force_trade", False
    mo=now.replace(hour=9,minute=15,second=0,microsecond=0); mc=now.replace(hour=15,minute=30,second=0,microsecond=0)
    if now<mo: return False, f"Pre-Market {now.strftime('%H:%M')} Opens 9:15 AM - Premium Select on Open", False
    if now>mc: return False, f"Post-Market {now.strftime('%H:%M')} Closed 3:30 PM", False
    if STATE["trades_today"]>=5: return False, f"5 Trades Limit {STATE['trades_today']}/5 - Telegram OFF", True
    return True, f"Market Open 9:15 AM - {STATE['trades_today']}/5 - Delta {STATE['delta']} PE - Intrinsic+TimeValue", False

def send_telegram(text):
    if STATE["trades_today"] >= STATE["max_trades"]:
        if not STATE["telegram_limit_sent"]:
            try:
                token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
                if not token or not chat: return False
                last_msg = f"🔕 *5 Trades Complete - Telegram OFF*\nTrades: {STATE['trades_today']}/5\nNo More Telegram Today\nUdya 9:15 AM ON\nP&L: Rs.{STATE['pnl']}"
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":last_msg,"parse_mode":"Markdown"},timeout=10)
                STATE["telegram_limit_sent"]=True; STATE["telegram_enabled"]=False
                add_log(f"TELEGRAM OFF | 5 Trades Complete")
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
    """Approximate Delta 0.30 selection - For PE OTM"""
    # Simplified delta estimation for NIFTY PE
    # Delta 0.30 PE means OTM Put, strike < spot, premium small vs distance
    # Use moneyness and premium to estimate
    moneyness = (strike - spot) / spot
    # For PE delta 0.30, moneyness around -0.8% to -1.5% typically
    # Return estimated delta based on moneyness and premium
    if option_type == "PE":
        if moneyness > 0:  # ITM
            return 0.70 + moneyness*2
        else:  # OTM
            # OTM PE delta 0.30 around -1% moneyness
            # Formula: delta ~ 0.5 + moneyness*20 approx for near ATM
            # For delta 0.30, moneyness ~ -0.01 to -0.015
            est = 0.5 + moneyness * 15
            return max(0.05, min(0.95, est))
    return 0.30

def get_real_nse_with_intrinsic_delta():
    """
    MARKET OPEN ZALE VAR INTRINSIC VALUE + DELTA 0.30 CONCEPT:
    - Spot live NSE varun
    - Strike selection Delta 0.30 PE (OTM Put, strike < spot)
    - Premium = Intrinsic + Time Value (Not stable!)
    - Intrinsic = max(strike - spot, 0) for PE
    - Time Value = LastPrice - Intrinsic (real market)
    - Premium moves with spot - Not stable!
    """
    try:
        headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.nseindia.com/option-chain"}
        s=requests.Session(); s.headers.update(headers)
        s.get("https://www.nseindia.com/option-chain",timeout=8)
        r=s.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",timeout=8)
        if r.status_code==200:
            d=r.json()
            spot=float(d["records"]["underlyingValue"])
            all_data = d["records"]["data"]
            
            # Find best PE strike with Delta 0.30 - Market Open Concept
            best_strike = None
            best_prem = None
            best_delta = None
            best_intrinsic = 0
            best_time_value = 0
            candidates = []
            
            for it in all_data:
                strike = it.get("strikePrice")
                pe = it.get("PE")
                if not pe or not strike: continue
                last_price = pe.get("lastPrice", 0)
                if last_price <= 0: continue
                
                # Only consider strikes near spot for delta 0.30
                # For PE Delta 0.30, strike should be slightly below spot (OTM)
                # Range: spot - 300 to spot + 100
                if strike < spot - 400 or strike > spot + 200:
                    continue
                
                intrinsic = max(strike - spot, 0)  # PE intrinsic
                time_value = last_price - intrinsic
                if time_value < 0: time_value = last_price
                
                # Estimate delta
                est_delta = calculate_delta_approx(spot, strike, last_price, "PE")
                
                # For Delta 0.30, we want OTM put with delta around 0.25-0.35
                if 0.20 <= est_delta <= 0.40:
                    # Score based on closeness to 0.30 delta
                    score = abs(est_delta - 0.30)
                    candidates.append({
                        "strike": strike,
                        "last_price": last_price,
                        "intrinsic": intrinsic,
                        "time_value": time_value,
                        "delta": est_delta,
                        "score": score,
                        "moneyness": (strike - spot)/spot
                    })
            
            if candidates:
                # Sort by closest to delta 0.30
                candidates.sort(key=lambda x: x["score"])
                best = candidates[0]
                best_strike = best["strike"]
                best_prem = best["last_price"]
                best_delta = best["delta"]
                best_intrinsic = best["intrinsic"]
                best_time_value = best["time_value"]
                
                add_log(f"NSE REAL | Spot {spot:.1f} | Delta 0.30 PE Selected: Strike {best_strike} | Premium {best_prem:.2f} = Intrinsic {best_intrinsic:.2f} + Time {best_time_value:.2f} | Delta {best_delta:.3f} | Moneyness {best['moneyness']*100:.2f}% | Candidates {len(candidates)}")
                
                return spot, best_prem, best_strike, best_intrinsic, best_time_value, best_delta, best["moneyness"], "NSE_LIVE_DELTA_0.30_INTRINSIC"
            
            # Fallback if no candidate in delta range - take nearest OTM
            fallback_strike = int((spot * 0.988)//50*50)  # 1.2% OTM
            for it in all_data:
                if it.get("strikePrice") == fallback_strike and it.get("PE"):
                    lp = float(it["PE"]["lastPrice"])
                    if lp > 0:
                        intrinsic = max(fallback_strike - spot, 0)
                        tv = lp - intrinsic
                        delta_est = calculate_delta_approx(spot, fallback_strike, lp)
                        add_log(f"NSE FALLBACK | Spot {spot:.1f} | Strike {fallback_strike} | Premium {lp:.2f} = Intrinsic {intrinsic:.2f} + Time {tv:.2f} | Delta ~{delta_est:.2f}")
                        return spot, lp, fallback_strike, intrinsic, tv, delta_est, (fallback_strike-spot)/spot, "NSE_FALLBACK_DELTA"
            
    except Exception as e:
        add_log(f"NSE ERR {e}")
    
    # SIMULATION with Intrinsic Concept - Not Stable!
    # Simulate live moving premium based on spot movement
    spot_sim = 22527 + random.uniform(-40, 40)
    # For delta 0.30 OTM PE
    strike_sim = int((spot_sim * 0.988)//50*50)
    intrinsic_sim = max(strike_sim - spot_sim, 0)
    # Time value decays slightly and moves randomly - Not stable!
    base_tv = 65 + random.uniform(-5, 10)
    # Add some volatility to time value - Not stable!
    time_value_sim = base_tv + random.uniform(-3, 3) + math.sin(time.time()/60)*2
    premium_sim = intrinsic_sim + time_value_sim
    delta_sim = calculate_delta_approx(spot_sim, strike_sim, premium_sim)
    moneyness_sim = (strike_sim - spot_sim)/spot_sim
    
    add_log(f"SIM DELTA 0.30 | Spot {spot_sim:.1f} | Strike {strike_sim} | Premium {premium_sim:.2f} = Intrinsic {intrinsic_sim:.2f} + Time {time_value_sim:.2f} | Delta {delta_sim:.3f} | Moneyness {moneyness_sim*100:.2f}% | NOT STABLE - Moves with spot!")
    
    return spot_sim, premium_sim, strike_sim, intrinsic_sim, time_value_sim, delta_sim, moneyness_sim, "SIM_DELTA_INTRINSIC_MOVING"

def detect_swings_easy():
    if len(CANDLES) < 12: return None
    clist = list(CANDLES)
    WINDOW = 5
    MIN_GAP = 10
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
    return {"swing_high":recent_high,"swing_low":recent_low,"fib_high":fib_high_actual,"fib_low":fib_low_actual,"range":rng,"0.36":fib_low_actual+rng*0.36,"0.5":fib_low_actual+rng*0.5,"2.414":fib_low_actual+rng*2.414,"total_swings_high":len(filtered_highs),"total_swings_low":len(filtered_lows)}

def is_marubozu(c):
    body=abs(c['c']-c['o']); rng=c['h']-c['l']
    return rng>0 and c['c']>c['o'] and body/rng>=0.70

for i in range(20):
    c=68+i*0.8+random.uniform(-2,3)
    if i==5: c=82
    if i==14: c=59
    CANDLES.append({"o":c-1,"h":c+1.5,"l":c-1.2,"c":c,"t":f"10:{i:02d}","maru":False,"buy":False,"sell_sl":False,"sell_tgt":False})

HTML = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{background:#0f172a;color:#e2e8f0;padding:10px;font-family:Arial;margin:0}
h2{color:#22c55e;text-align:center;margin:6px 0;font-size:11px;background:#1e293b;padding:8px;border-radius:10px;border:2px solid #22c55e}
.card{background:#1e293b;padding:10px;border-radius:12px;margin:6px 0;border:1px solid #334155}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.box{background:#0f172a;padding:8px;border-radius:10px;border:1px solid #334155;text-align:center}
.box .l{color:#94a3b8;font-size:9px} .box .v{color:#fff;font-size:13px;font-weight:bold;margin-top:2px}
.entry{color:#22c55e !important} .sl{color:#f97316 !important} .tgt{color:#3b82f6 !important} .prem{color:#eab308 !important} .intr{color:#a855f7 !important} .tv{color:#06b6d4 !important}
#chart{background:#ffffff;border-radius:12px;padding:8px;margin:6px 0;min-height:580px;border:3px solid #22c55e}
canvas{width:100%;height:500px;background:#fff;border-radius:8px}
.btn{padding:6px 10px;font-weight:bold;border-radius:8px;text-decoration:none;display:inline-block;margin:3px;font-size:10px}
.btn-g{background:#22c55e;color:#000} .btn-y{background:#eab308;color:#000} .btn-b{background:#3b82f6;color:#fff} .btn-r{background:#ef4444;color:#fff} .btn-p{background:#a855f7;color:#fff}
.small{font-size:9px;color:#94a3b8}
.status-open{color:#000;background:#22c55e;padding:5px 10px;border-radius:8px;font-size:11px;font-weight:bold;border:2px solid #fff}
.status-closed{color:#fff;background:#ef4444;padding:5px 10px;border-radius:8px;font-size:11px;font-weight:bold}
.status-limit{color:#fff;background:#6b7280;padding:5px 10px;border-radius:8px;font-size:11px;font-weight:bold}
.status-force{color:#fff;background:#a855f7;padding:5px 10px;border-radius:8px;font-size:11px;font-weight:bold;border:2px solid #fff}
.intrinsic-box{background:#1a0a2a;padding:8px;border-radius:10px;border:3px solid #a855f7;margin:6px 0;text-align:center}
.delta-box{background:#0a1a1a;padding:8px;border-radius:10px;border:3px solid #22c55e;margin:6px 0;text-align:center}
.limit-box{background:#1a1a00;padding:8px;border-radius:10px;border:3px solid #eab308;margin:6px 0;text-align:center}
.live-dot{animation:blink 1s infinite;width:8px;height:8px;background:#22c55e;border-radius:50%;display:inline-block}
@keyframes blink{0%{opacity:1}50%{opacity:0.3}100%{opacity:1}}
</style></head><body>
<h2>🇮🇳 Market Open - Intrinsic Value + Delta 0.30 PE - Premium NOT Stable - Live Moving!</h2>

<div class="intrinsic-box">
<div style="color:#a855f7;font-weight:bold;font-size:13px">💎 Market Open Zale Var Intrinsic Value Concept + Delta 0.30 - Premium Stable Nako!</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-top:6px">
<div style="background:#0f172a;padding:6px;border-radius:8px;border:2px solid #a855f7"><div class="small">Spot LIVE</div><div id="spot_live" style="color:#fff;font-size:16px;font-weight:bold">22527</div><div class="small">NSE REAL</div></div>
<div style="background:#0f172a;padding:6px;border-radius:8px;border:2px solid #ef4444"><div class="small">Strike Delta 0.30 PE</div><div id="strike_delta" style="color:#eab308;font-size:16px;font-weight:bold">22250PE</div><div class="small">OTM Delta 0.30</div></div>
<div style="background:#0f172a;padding:6px;border-radius:8px;border:2px solid #a855f7"><div class="small">Intrinsic Value</div><div id="intrinsic_val" style="color:#a855f7;font-size:16px;font-weight:bold">0.00</div><div class="small">max(Strike-Spot,0)</div></div>
<div style="background:#0f172a;padding:6px;border-radius:8px;border:2px solid #06b6d4"><div class="small">Time Value</div><div id="time_val" style="color:#06b6d4;font-size:16px;font-weight:bold">87.30</div><div class="small">Premium - Intrinsic</div></div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-top:6px">
<div style="background:#0f172a;padding:6px;border-radius:8px;border:2px solid #22c55e"><div class="small">Premium LIVE</div><div id="prem_live" style="color:#eab308;font-size:18px;font-weight:bold">87.30</div><div class="small">Intrinsic+Time - NOT Stable</div></div>
<div style="background:#0f172a;padding:6px;border-radius:8px;border:2px solid #22c55e"><div class="small">Delta</div><div id="delta_val" style="color:#22c55e;font-size:16px;font-weight:bold">0.30</div><div class="small">PE OTM 0.25-0.35</div></div>
<div style="background:#0f172a;padding:6px;border-radius:8px;border:2px solid #f97316"><div class="small">Moneyness</div><div id="moneyness_val" style="color:#f97316;font-size:12px;font-weight:bold">-1.20% OTM</div><div class="small">Strike-Spot</div></div>
<div style="background:#0f172a;padding:6px;border-radius:8px;border:2px solid #fff"><div class="small">Breakup</div><div id="breakup_val" style="color:#fff;font-size:10px;font-weight:bold">0 + 87.30 = 87.30</div><div class="small">Intrinsic+Time=Premium</div></div>
</div>
<div class="small" style="margin-top:4px;color:#22c55e">✅ Market open zale var NSE varun Delta 0.30 PE select - Premium = Intrinsic (max(Strike-Spot,0)) + Time Value - Premium stable nahi - Spot halchal ki premium halchal - Live moving!</div>
</div>

<div class="delta-box">
<div style="color:#22c55e;font-weight:bold;font-size:12px">📊 Delta 0.30 PE Concept - Market Open Logic</div>
<div style="display:flex;gap:6px;justify-content:center;margin-top:4px;flex-wrap:wrap">
<div style="background:#0f172a;padding:5px 10px;border-radius:8px;border:1px solid #22c55e"><div class="small">Market Open 9:15</div><div style="color:#22c55e;font-size:11px;font-weight:bold">Spot LIVE → Strike Delta 0.30</div></div>
<div style="background:#0f172a;padding:5px 10px;border-radius:8px;border:1px solid #a855f7"><div class="small">Intrinsic</div><div style="color:#a855f7;font-size:11px;font-weight:bold">max(Strike-Spot,0) PE</div></div>
<div style="background:#0f172a;padding:5px 10px;border-radius:8px;border:1px solid #06b6d4"><div class="small">Time Value</div><div style="color:#06b6d4;font-size:11px;font-weight:bold">Premium - Intrinsic - Decay</div></div>
<div style="background:#0f172a;padding:5px 10px;border-radius:8px;border:1px solid #eab308"><div class="small">Premium</div><div style="color:#eab308;font-size:11px;font-weight:bold">Intrinsic+Time - Moving!</div></div>
</div>
</div>

<div class="limit-box">
<div style="color:#eab308;font-weight:bold;font-size:12px">⏰ Only 5 Trade - 15 Candle Swing - Delta 0.30 - Telegram OFF After 5</div>
<div style="display:flex;gap:6px;justify-content:center;margin-top:4px;flex-wrap:wrap">
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #22c55e"><div class="small">Trades</div><div id="trades_today" style="color:#22c55e;font-size:18px;font-weight:bold">0/5</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #ec4899"><div class="small">Telegram</div><div id="tg_status_top" style="color:#ec4899;font-size:11px;font-weight:bold">ON</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #a855f7"><div class="small">Force</div><div id="force_status_top" style="color:#a855f7;font-size:11px;font-weight:bold">OFF</div></div>
<div style="background:#0f172a;padding:6px 12px;border-radius:8px;border:2px solid #eab308"><div class="small">Remain</div><div id="trades_remain_top" style="color:#eab308;font-size:18px;font-weight:bold">5 Left</div></div>
</div>
</div>

<div class="card">
<div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center">
<span id="market_status" class="status-open">● Market Open 9:15 AM - 0/5 - Delta 0.30</span>
<span id="nse_status" style="color:#000;background:#eab308;padding:3px 6px;border-radius:6px;font-size:9px">● NSE LIVE DELTA</span>
<span id="tg_status" style="color:#fff;background:#22c55e;padding:3px 6px;border-radius:6px;font-size:9px">● TELEGRAM ON</span>
<span id="force_status" style="color:#fff;background:#6b7280;padding:3px 6px;border-radius:6px;font-size:9px">● FORCE OFF</span>
<span id="lt" class="small"></span>
</div>

<div class="grid" style="margin-top:6px">
<div class="box"><div class="l">No. Of Trade (Today)</div><div class="v" id="trades" style="font-size:18px">0/5</div></div>
<div class="box"><div class="l">Which Premium Delta 0.30</div><div class="v prem" id="which_prem">22250PE Δ0.30</div><div class="small" id="which_prem_detail">Intrinsic 0 + Time 87.30</div></div>
<div class="box"><div class="l">Entry Price (0.5)</div><div class="v entry" id="entry_p">75.20 BUY</div></div>
<div class="box"><div class="l">SL Price (0.36 Trail)</div><div class="v sl" id="sl_p">71.00 → Trail</div></div>
<div class="box"><div class="l">Target Price (2.414)</div><div class="v tgt" id="tgt_p">132.62 TGT</div></div>
<div class="box"><div class="l">Total P&L</div><div class="v" id="pnl" style="color:#22c55e;font-size:18px">Rs.0</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1fr 1fr;gap:4px;margin-top:6px">
<div class="box"><div class="l">Spot</div><div class="v small" id="spot_box">22527 LIVE</div></div>
<div class="box"><div class="l">Strike Δ0.30</div><div class="v small" id="strike_box">22250PE</div></div>
<div class="box"><div class="l">Intrinsic</div><div class="v small intr" id="intrinsic_box">0.00</div></div>
<div class="box"><div class="l">Time Value</div><div class="v small tv" id="time_box">87.30</div></div>
<div class="box"><div class="l">Premium</div><div class="v small prem" id="prem_box">87.30 LIVE</div></div>
<div class="box"><div class="l">Delta</div><div class="v small" id="delta_box" style="color:#22c55e">0.30</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-top:4px">
<div class="box"><div class="l">Swing High 11C</div><div class="v small" id="swing_high" style="color:#ef4444">90.2 @10:18</div></div>
<div class="box"><div class="l">Swing Low 11C</div><div class="v small" id="swing_low" style="color:#22c55e">60.2 @10:00</div></div>
<div class="box"><div class="l">Fib H L R</div><div class="v small" id="fib_info">H 90.2 L 60.2 R 30.0</div></div>
</div>

<div style="margin-top:6px">
<a class="btn btn-g" href="/test_telegram">🔔 Test TG</a>
<a class="btn btn-p" href="/force_buy">🟢 Force BUY</a>
<a class="btn btn-r" href="/force_sell">🔴 Force SELL</a>
<a class="btn btn-p" href="/force_trade">⚡ Force Trade ON</a>
<a class="btn btn-y" href="/health">Health</a>
<a class="btn btn-b" href="/api/candles">Candles</a>
</div>
</div>

<div id="chart">
<div style="color:#000;font-weight:bold;text-align:center;font-size:11px">📈 LIVE 1 MIN - Delta 0.30 PE - Intrinsic+TimeValue - Premium NOT Stable - Live Moving - Market Open 9:15 AM</div>
<canvas id="c" width="800" height="500"></canvas>
<div style="color:#000;font-size:8px;text-align:center;margin-top:2px">✅ Market open zale var Delta 0.30 PE select - Premium = Intrinsic + Time Value - Premium stable nahi - Spot halchal ki premium halchal - NSE LIVE + Delta 0.30 + Intrinsic concept</div>
<div id="trade_list" style="color:#000;font-size:9px;margin-top:4px;background:#f0f0f0;padding:5px;border-radius:6px"></div>
</div>

<div class="card">
<pre id="log" style="background:#0f172a;color:#22c55e;padding:6px;border-radius:8px;border:1px solid #334155;font-size:8px;max-height:250px;overflow:auto;white-space:pre-wrap"></pre>
</div>

<script>
let candles=[];
let fib={low:60.2,high:90.2,range:30,"0.36":71.0,"0.5":75.2,"2.414":132.62,swingHigh:{value:90.2,time:"10:18"},swingLow:{value:60.2,time:"10:00"}};
let tradesHistory=[];

function draw(){
 let canvas=document.getElementById('c'); let ctx=canvas.getContext('2d');
 let W=canvas.width, H=canvas.height, pad=45;
 if(candles.length==0) return;
 ctx.clearRect(0,0,W,H); ctx.fillStyle="#fff"; ctx.fillRect(0,0,W,H);
 let allHighs=candles.map(c=>c.h); let allLows=candles.map(c=>c.l);
 let min=Math.min(...allLows,fib.low,fib["0.36"])-8; let max=Math.max(...allHighs,fib.high,fib["2.414"])+12;
 let y=v=>H-pad-(v-min)/(max-min)*(H-pad*2); let x=i=>pad+i/(candles.length-1)*(W-pad*2);
 ctx.strokeStyle="#eee"; ctx.lineWidth=1;
 for(let i=0;i<=5;i++){let yy=pad+i*(H-pad*2)/5; ctx.beginPath(); ctx.moveTo(pad,yy); ctx.lineTo(W-pad,yy); ctx.stroke(); ctx.fillStyle="#666"; ctx.font="9px Arial"; ctx.fillText((max-(max-min)*i/5).toFixed(0),5,yy);}
 function line(val,color,label,dash,width){ctx.strokeStyle=color; ctx.lineWidth=width||2; ctx.setLineDash(dash||[]); ctx.beginPath(); ctx.moveTo(pad,y(val)); ctx.lineTo(W-pad,y(val)); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle=color; ctx.font="bold 10px Arial"; ctx.fillText(label+" "+val.toFixed(1),W-pad+5,y(val)-2);}
 line(fib.high,"#ef4444","Swing High",[8,4],2);
 line(fib.low,"#000","Swing Low",[8,4],2);
 line(fib["0.5"],"#22c55e","0.5 ENTRY BUY",[],3);
 line(fib["0.36"],"#f97316","0.36 SL",[4,4],2);
 line(fib["2.414"],"#3b82f6","2.414 TGT",[],3);
 candles.forEach((c,i)=>{
  let g=c.c>=c.o; ctx.fillStyle=g?"#22c55e":"#ef4444"; ctx.strokeStyle=g?"#16a34a":"#dc2626";
  let bh=Math.abs(y(c.o)-y(c.c)); let by=Math.min(y(c.o),y(c.c)); let w=Math.max(4, (W-pad*2)/candles.length*0.6);
  ctx.beginPath(); ctx.moveTo(x(i),y(c.h)); ctx.lineTo(x(i),y(c.l)); ctx.stroke();
  ctx.fillRect(x(i)-w/2,by,w,Math.max(2,bh));
  if(c.swingHigh){ctx.fillStyle="#ef4444"; ctx.beginPath(); ctx.moveTo(x(i),y(c.h)-14); ctx.lineTo(x(i)-9,y(c.h)-3); ctx.lineTo(x(i)+9,y(c.h)-3); ctx.closePath(); ctx.fill(); ctx.font="bold 9px Arial"; ctx.fillText("▲ SH "+c.h.toFixed(1),x(i)-20,y(c.h)-18);}
  if(c.swingLow){ctx.fillStyle="#22c55e"; ctx.beginPath(); ctx.moveTo(x(i),y(c.l)+14); ctx.lineTo(x(i)-9,y(c.l)+3); ctx.lineTo(x(i)+9,y(c.l)+3); ctx.closePath(); ctx.fill(); ctx.font="bold 9px Arial"; ctx.fillText("▼ SL "+c.l.toFixed(1),x(i)-20,y(c.l)+28);}
  if(c.buy){ctx.fillStyle="#22c55e"; ctx.beginPath(); ctx.arc(x(i),y(c.c),14,0,Math.PI*2); ctx.fill(); ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle="#fff"; ctx.font="bold 10px Arial"; ctx.fillText("BUY",x(i)-11,y(c.c)+3);}
  if(c.sell_sl){ctx.fillStyle="#ef4444"; ctx.beginPath(); ctx.arc(x(i),y(c.c),12,0,Math.PI*2); ctx.fill(); ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle="#fff"; ctx.font="bold 9px Arial"; ctx.fillText("SL",x(i)-7,y(c.c)+3);}
  if(c.sell_tgt){ctx.fillStyle="#3b82f6"; ctx.beginPath(); ctx.arc(x(i),y(c.c),12,0,Math.PI*2); ctx.fill(); ctx.strokeStyle="#000"; ctx.lineWidth=2; ctx.stroke(); ctx.fillStyle="#fff"; ctx.font="bold 9px Arial"; ctx.fillText("TGT",x(i)-10,y(c.c)+3);}
 });
 ctx.fillStyle="#000"; ctx.font="8px Arial";
 candles.forEach((c,i)=>{if(i%Math.ceil(candles.length/12)==0){ctx.fillText(c.t,x(i)-10,H-12);}});
}

async function refresh(){
 try{
  let r=await fetch('/api/candles?t='+Date.now()); let j=await r.json();
  candles=j.candles;
  fib.high=j.fib_high; fib.low=j.fib_low; fib.range=j.range; fib["0.5"]=j.entry; fib["0.36"]=j.sl; fib["2.414"]=j.tgt;
  fib.swingHigh=j.swing_high; fib.swingLow=j.swing_low;
  tradesHistory=j.trades_history;
  
  document.getElementById('spot_live').innerText=j.spot_val.toFixed(1);
  document.getElementById('strike_delta').innerText=j.strike+' Δ'+j.delta.toFixed(2);
  document.getElementById('intrinsic_val').innerText=j.intrinsic.toFixed(2);
  document.getElementById('time_val').innerText=j.time_value.toFixed(2);
  document.getElementById('prem_live').innerText=j.prem_val.toFixed(2);
  document.getElementById('delta_val').innerText=j.delta.toFixed(2);
  document.getElementById('moneyness_val').innerText=(j.moneyness*100).toFixed(2)+'% '+(j.moneyness<0?'OTM':'ITM');
  document.getElementById('breakup_val').innerText=j.intrinsic.toFixed(1)+' + '+j.time_value.toFixed(1)+' = '+j.prem_val.toFixed(1);
  
  document.getElementById('trades').innerText=j.trades_today+'/5';
  document.getElementById('trades_today').innerText=j.trades_today+'/5';
  document.getElementById('trades_today_top').innerText=j.trades_today+'/5';
  document.getElementById('trades_remain').innerText=(5-j.trades_today)+' Left';
  document.getElementById('trades_remain_top').innerText=(5-j.trades_today)+' Left';
  document.getElementById('which_prem').innerText=j.strike+'PE Δ'+j.delta.toFixed(2);
  document.getElementById('which_prem_detail').innerText='Intrinsic '+j.intrinsic.toFixed(1)+' + Time '+j.time_value.toFixed(1);
  document.getElementById('entry_p').innerText=j.entry.toFixed(2)+' BUY';
  document.getElementById('sl_p').innerText=j.sl.toFixed(2)+' → Trail';
  document.getElementById('tgt_p').innerText=j.tgt.toFixed(2)+' TGT';
  document.getElementById('pnl').innerText='Rs.'+j.pnl;
  document.getElementById('swing_high').innerText=j.swing_high.value.toFixed(1)+' @'+j.swing_high.time;
  document.getElementById('swing_low').innerText=j.swing_low.value.toFixed(1)+' @'+j.swing_low.time;
  document.getElementById('fib_info').innerText='H '+j.fib_high.toFixed(1)+' L '+j.fib_low.toFixed(1)+' R '+j.range.toFixed(1);
  document.getElementById('spot_box').innerText=j.spot_val.toFixed(1)+' LIVE';
  document.getElementById('strike_box').innerText=j.strike+'PE';
  document.getElementById('intrinsic_box').innerText=j.intrinsic.toFixed(2);
  document.getElementById('time_box').innerText=j.time_value.toFixed(2);
  document.getElementById('prem_box').innerText=j.prem_val.toFixed(2)+' LIVE';
  document.getElementById('delta_box').innerText=j.delta.toFixed(2);
  
  document.getElementById('market_status').innerText='● '+j.market;
  document.getElementById('market_status').className=j.force_mode?'status-force':(j.is_limit?'status-limit':(j.is_open?'status-open':'status-closed'));
  document.getElementById('nse_status').innerText='● '+j.src;
  
  let tg_on = j.telegram_enabled;
  document.getElementById('tg_status').innerText=tg_on ? '● TELEGRAM ON' : '🔕 TELEGRAM OFF';
  document.getElementById('tg_status_top').innerText=tg_on ? 'ON' : '🔕 OFF';
  document.getElementById('force_status').innerText=j.force_mode ? '⚡ FORCE ON' : '● FORCE OFF';
  document.getElementById('force_status_top').innerText=j.force_mode ? '⚡ ON' : 'OFF';
  
  document.getElementById('log').innerText=j.logs.slice(-30).join('\n');
  let tl=document.getElementById('trade_list');
  if(tradesHistory.length>0){
   tl.innerHTML='<b>📊 Trades - Delta 0.30 + Intrinsic:</b><br>'+tradesHistory.map(t=>`Trade ${t.no}/5: BUY @${t.buy_price.toFixed(1)} (${t.intrinsic?t.intrinsic.toFixed(1)+'+'+t.time_value.toFixed(1):''}) ${t.buy_time} → ${t.exit_type} @${t.exit_price.toFixed(1)} ${t.exit_time} P&L Rs.${t.pnl} - ${t.strike} Δ${t.delta?t.delta.toFixed(2):'0.30'}`).join('<br>');
  } else {
   tl.innerHTML='<b>📊 Trades:</b> No trades yet - Market open zale var Delta 0.30 PE select hoil - Premium = Intrinsic+TimeValue - NOT Stable - Live Moving!';
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
    return jsonify({
        "candles":clist[-100:],
        "trades_today":STATE["trades_today"],"trades":STATE["trades"],"max_trades":5,
        "strike":f"{STATE['strike']}",
        "entry":STATE["fib_low"]+STATE["range"]*0.5 if STATE["range"]>0 else 75.2,
        "sl":STATE["fib_low"]+STATE["range"]*0.36 if STATE["range"]>0 else 71.0,
        "tgt":STATE["fib_low"]+STATE["range"]*2.414 if STATE["range"]>0 else 132.6,
        "pnl":STATE["pnl"],
        "spot_val":STATE["spot"],"prem_val":STATE["prem"],"intrinsic":STATE["intrinsic"],"time_value":STATE["time_value"],
        "delta":STATE["delta"],"moneyness":STATE.get("moneyness",-0.012),
        "fib_high":STATE["fib_high"],"fib_low":STATE["fib_low"],"range":STATE["range"],
        "swing_high":STATE.get("swing_high_info",{"value":STATE["fib_high"] if STATE["fib_high"]>0 else 90.2,"time":"10:18"}),
        "swing_low":STATE.get("swing_low_info",{"value":STATE["fib_low"] if STATE["fib_low"]>0 else 60.2,"time":"10:00"}),
        "total_swings_high":STATE.get("total_swings_high",0),"total_swings_low":STATE.get("total_swings_low",0),
        "trades_history":list(TRADES_HISTORY)[-10:],
        "telegram_enabled":STATE["telegram_enabled"],"force_mode":STATE["force_trade"],
        "src":STATE.get("src","NSE"),"is_open":is_open,"is_limit":is_limit,"market":market_msg,"logs":list(LOGS)[-40:]
    })

@app.route('/health')
def health():
    is_open, msg, is_limit = is_market_open()
    return jsonify({
        "status":"OK","market":msg,"trades_today":f"{STATE['trades_today']}/5",
        "spot":STATE["spot"],"strike":STATE["strike"],"premium":f"{STATE['prem']:.2f} = {STATE['intrinsic']:.2f} Intrinsic + {STATE['time_value']:.2f} Time",
        "delta":STATE["delta"],"intrinsic":STATE["intrinsic"],"time_value":STATE["time_value"],
        "telegram": "ON" if STATE["telegram_enabled"] else "OFF","force":STATE["force_trade"]
    })

@app.route('/force_trade')
def force_trade():
    STATE["force_trade"]=True
    add_log("FORCE TRADE ON | Market Override")
    return jsonify({"ok":True})

@app.route('/disable_force')
def disable_force():
    STATE["force_trade"]=False
    return jsonify({"ok":True})

@app.route('/force_buy')
def force_buy():
    if STATE["trades_today"]>=5:
        return jsonify({"ok":False,"msg":f"5 Trades Limit {STATE['trades_today']}/5"})
    if STATE["pos"] is not None:
        return jsonify({"ok":False,"msg":"Position already open"})
    try:
        now=datetime.now(IST).strftime("%H:%M")
        curr = STATE["prem"]
        f05=STATE["fib_low"]+STATE["range"]*0.5 if STATE["range"]>0 else 75.2
        f036=STATE["fib_low"]+STATE["range"]*0.36 if STATE["range"]>0 else 71.0
        f2414=STATE["fib_low"]+STATE["range"]*2.414 if STATE["range"]>0 else 132.6
        CANDLES[-1]["buy"]=True
        STATE["pos"]={"entry":curr,"sl":f036,"tgt":f2414,"buy_time":now,"buy_price":curr,"strike":f"{STATE['strike']}PE","intrinsic":STATE["intrinsic"],"time_value":STATE["time_value"],"delta":STATE["delta"]}
        STATE["trades"]+=1; STATE["trades_today"]+=1
        TRADES_HISTORY.append({"no":STATE["trades_today"],"buy_price":curr,"buy_time":now,"exit_price":0,"exit_time":"OPEN","exit_type":"OPEN FORCE BUY","pnl":0,"strike":f"{STATE['strike']}PE","intrinsic":STATE["intrinsic"],"time_value":STATE["time_value"],"delta":STATE["delta"]})
        add_log(f"FORCE BUY | Trade {STATE['trades_today']}/5 | BUY {STATE['strike']}PE @ {curr:.2f} = Intrinsic {STATE['intrinsic']:.2f} + Time {STATE['time_value']:.2f} | Delta {STATE['delta']:.2f} | {now}")
        send_telegram(f"🟢 *FORCE BUY {STATE['trades_today']}/5 - Delta {STATE['delta']:.2f}*\nStrike: {STATE['strike']}PE\nBUY @ {curr:.2f} = Intrinsic {STATE['intrinsic']:.2f} + Time {STATE['time_value']:.2f}\nDelta: {STATE['delta']:.2f} | Spot: {STATE['spot']:.1f}\n{now}")
        return jsonify({"ok":True,"msg":f"BUY {STATE['trades_today']}/5 @ {curr:.2f} = {STATE['intrinsic']:.2f}+{STATE['time_value']:.2f} Delta {STATE['delta']:.2f}"})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route('/force_sell')
def force_sell():
    if STATE["pos"] is None:
        return jsonify({"ok":False,"msg":"No position"})
    try:
        curr = STATE["prem"]
        now=datetime.now(IST).strftime("%H:%M")
        pnl=(curr-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
        exit_type = "FORCE SELL"
        if curr<=STATE["pos"]["sl"]: exit_type="SL HIT"; CANDLES[-1]["sell_sl"]=True
        elif curr>=STATE["pos"]["tgt"]: exit_type="TGT HIT"; CANDLES[-1]["sell_tgt"]=True
        else: CANDLES[-1]["sell_sl"]=True
        if TRADES_HISTORY:
            last = TRADES_HISTORY[-1]
            last["exit_price"]=curr; last["exit_time"]=now; last["exit_type"]=exit_type; last["pnl"]=round(pnl,0)
        add_log(f"FORCE SELL | {exit_type} @ {curr:.2f} P&L {pnl:.0f}")
        send_telegram(f"🔴 *{exit_type} {STATE['trades_today']}/5*\nSELL @ {curr:.2f} {now}\nP&L {pnl:.0f} Total {STATE['pnl']:.0f}")
        STATE["pos"]=None
        return jsonify({"ok":True,"msg":f"SELL @ {curr:.2f} {exit_type} P&L {pnl:.0f}"})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route('/test_telegram')
def test():
    if not STATE["telegram_enabled"]:
        return jsonify({"ok":False,"msg":"Telegram OFF"})
    token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat: return jsonify({"ok":False})
    try:
        txt=f"Test - Delta 0.30 - Intrinsic {STATE['intrinsic']:.2f} + Time {STATE['time_value']:.2f} = Premium {STATE['prem']:.2f} - Spot {STATE['spot']:.1f} - Strike {STATE['strike']} - Delta {STATE['delta']:.2f}"
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":txt,"parse_mode":"Markdown"},timeout=10)
        return jsonify({"ok":r.status_code==200})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})

def bot_loop():
    add_log("BOT START | Market Open Intrinsic + Delta 0.30 - Premium NOT Stable - Live Moving Concept")
    time.sleep(2)
    send_telegram("🚀 Bot Started - Market Open Logic\nPremium = Intrinsic + Time Value\nDelta 0.30 PE Select\nPremium NOT Stable - Moves with Spot\nSpot halchal ki premium halchal!")
    while True:
        try:
            is_open, market_msg, is_limit = is_market_open()
            if not is_open:
                add_log(f"{market_msg} - Sleeping 30s")
                time.sleep(30); continue
            
            # GET REAL NSE WITH INTRINSIC + DELTA 0.30
            spot, prem, strike, intrinsic, time_value, delta, moneyness, src = get_real_nse_with_intrinsic_delta()
            STATE["spot"]=round(spot,2); STATE["prem"]=round(prem,2); STATE["strike"]=strike
            STATE["intrinsic"]=round(intrinsic,2); STATE["time_value"]=round(time_value,2); STATE["delta"]=round(delta,3)
            STATE["moneyness"]=moneyness; STATE["src"]=src
            STATE["strike_info"]=f"{strike}PE Δ{delta:.2f}"
            STATE["premium_breakup"]=f"{intrinsic:.1f}+{time_value:.1f}={prem:.1f}"
            
            now=datetime.now(IST).strftime("%H:%M")
            if len(CANDLES)==0 or CANDLES[-1]["t"]!=now:
                CANDLES.append({"o":prem,"h":prem,"l":prem,"c":prem,"t":now,"maru":False,"buy":False,"sell_sl":False,"sell_tgt":False})
            else:
                c=CANDLES[-1]; c["h"]=max(c["h"],prem); c["l"]=min(c["l"],prem); c["c"]=prem
            
            fib_data = detect_swings_easy()
            if fib_data:
                STATE["fib_high"]=fib_data["fib_high"]; STATE["fib_low"]=fib_data["fib_low"]; STATE["range"]=fib_data["range"]
                STATE["swing_high_info"]=fib_data["swing_high"]; STATE["swing_low_info"]=fib_data["swing_low"]
                STATE["total_swings_high"]=fib_data["total_swings_high"]; STATE["total_swings_low"]=fib_data["total_swings_low"]
                f05=fib_data["0.5"]; f036=fib_data["0.36"]; f2414=fib_data["2.414"]
                recent=list(CANDLES)[-12:]; curr=recent[-1]['c']; prev=recent[-2]['c'] if len(recent)>=2 else curr
                cross = prev < f05 and curr >= f05
                near_cross = curr >= f05*0.98 and curr <= f05*1.02 and prev < curr
                trigger = cross or near_cross
                
                add_log(f"DELTA 0.30 INTRINSIC | Spot {spot:.1f} Strike {strike}PE | Premium {prem:.2f} = Intrinsic {intrinsic:.2f} + Time {time_value:.2f} | Delta {delta:.3f} Moneyness {moneyness*100:.2f}% | {src} | Fib H {fib_data['fib_high']:.1f} L {fib_data['fib_low']:.1f} R {fib_data['range']:.1f} | 0.5 {f05:.1f} Cross {cross} Trigger {trigger} | Trades {STATE['trades_today']}/5 | NOT STABLE - Moving with spot!")
                
                if trigger and STATE["pos"] is None:
                    if STATE["trades_today"]>=5: time.sleep(10); continue
                    CANDLES[-1]["buy"]=True
                    STATE["pos"]={"entry":curr,"sl":f036,"tgt":f2414,"buy_time":now,"buy_price":curr,"strike":f"{strike}PE","intrinsic":intrinsic,"time_value":time_value,"delta":delta}
                    STATE["trades"]+=1; STATE["trades_today"]+=1
                    TRADES_HISTORY.append({"no":STATE["trades_today"],"buy_price":curr,"buy_time":now,"exit_price":0,"exit_time":"OPEN","exit_type":"OPEN","pnl":0,"strike":f"{strike}PE","intrinsic":intrinsic,"time_value":time_value,"delta":delta})
                    add_log(f"BUY DELTA 0.30 INTRINSIC | Trade {STATE['trades_today']}/5 | BUY {strike}PE @ {curr:.2f} = Intrinsic {intrinsic:.2f}+Time {time_value:.2f} | Delta {delta:.2f} | {now} | Remaining {5-STATE['trades_today']}")
                    send_telegram(f"🎯 *BUY {STATE['trades_today']}/5 - Delta {delta:.2f} - Intrinsic*\nStrike: {strike}PE | Spot: {spot:.1f}\nBUY @ {curr:.2f} = Intrinsic {intrinsic:.2f} + Time {time_value:.2f}\nDelta: {delta:.3f} Moneyness: {moneyness*100:.2f}%\nEntry 0.5: {f05:.2f} SL: {f036:.2f} TGT: {f2414:.2f}\nRemaining: {5-STATE['trades_today']} Left")
                
                if STATE["pos"]:
                    if curr<=STATE["pos"]["sl"]:
                        pnl=(STATE["pos"]["sl"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        CANDLES[-1]["sell_sl"]=True
                        if TRADES_HISTORY and TRADES_HISTORY[-1]["exit_time"]=="OPEN":
                            TRADES_HISTORY[-1]["exit_price"]=curr; TRADES_HISTORY[-1]["exit_time"]=now; TRADES_HISTORY[-1]["exit_type"]="SL HIT"; TRADES_HISTORY[-1]["pnl"]=round(pnl,0)
                        add_log(f"SL HIT | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} | Premium now {curr:.2f} = Intrinsic {intrinsic:.2f}+Time {time_value:.2f}")
                        send_telegram(f"🔴 *SL HIT {STATE['trades_today']}/5 - Delta {STATE['delta']:.2f}*\nSL @ {curr:.2f} = Intrinsic {intrinsic:.2f}+Time {time_value:.2f}\nP&L {pnl:.0f} Total {STATE['pnl']:.0f}")
                        STATE["pos"]=None
                    elif curr>=STATE["pos"]["tgt"]:
                        pnl=(STATE["pos"]["tgt"]-STATE["pos"]["entry"])*65; STATE["pnl"]+=pnl
                        CANDLES[-1]["sell_tgt"]=True
                        if TRADES_HISTORY and TRADES_HISTORY[-1]["exit_time"]=="OPEN":
                            TRADES_HISTORY[-1]["exit_price"]=curr; TRADES_HISTORY[-1]["exit_time"]=now; TRADES_HISTORY[-1]["exit_type"]="TGT HIT 2.414"; TRADES_HISTORY[-1]["pnl"]=round(pnl,0)
                        add_log(f"TGT HIT | Trade {STATE['trades_today']}/5 P&L {pnl:.0f} | Premium now {curr:.2f} = Intrinsic {intrinsic:.2f}+Time {time_value:.2f}")
                        send_telegram(f"🟢 *TGT HIT {STATE['trades_today']}/5 - Delta {STATE['delta']:.2f}*\nTGT @ {curr:.2f} = Intrinsic {intrinsic:.2f}+Time {time_value:.2f}\nP&L {pnl:.0f} Total {STATE['pnl']:.0f}")
                        STATE["pos"]=None
            time.sleep(15)
        except Exception as e:
            import traceback; add_log(f"ERR {e} {traceback.format_exc()[:80]}"); time.sleep(10)

threading.Thread(target=bot_loop, daemon=True).start()
