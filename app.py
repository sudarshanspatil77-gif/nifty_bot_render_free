
from flask import Flask, jsonify
import threading, time, os, random, requests
from datetime import datetime
import pytz

app = Flask(__name__)
LOGS = []
Pnl = {"total_pnl":0,"total_signals":0,"pnl_history":[0],"time_labels":["Start"]}

def add_log(msg):
    ist = pytz.timezone('Asia/Kolkata')
    ts = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts},{msg}"
    LOGS.append(line)
    if len(LOGS)>120: LOGS.pop(0)
    print(line)

def send_telegram(text):
    try:
        t=os.getenv('TELEGRAM_BOT_TOKEN'); c=os.getenv('TELEGRAM_CHAT_ID')
        if not t or not c: 
            add_log(f"TELEGRAM_MISSING,Token={bool(t)} Chat={bool(c)},65,0,0,0,Set in Render Env")
            return False
        r=requests.post(f"https://api.telegram.org/bot{t}/sendMessage",json={"chat_id":c,"text":text},timeout=10)
        add_log(f"TELEGRAM_SENT,{r.status_code},65,0,0,0,{text[:70]}")
        return True
    except Exception as e:
        add_log(f"TELEGRAM_ERROR,{e},65,0,0,0,Error")
        return False

def get_nifty_spot_live():
    """Live Nifty Spot from NSE - 3 methods"""
    # Method 1: NSE Official API
    try:
        headers = {
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":"application/json",
            "Accept-Language":"en-US,en;q=0.9",
            "Referer":"https://www.nseindia.com/"
        }
        sess = requests.Session()
        sess.headers.update(headers)
        # Get cookies first
        sess.get("https://www.nseindia.com/", timeout=10)
        # Option chain gives underlyingValue
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        r = sess.get(url, timeout=10)
        if r.status_code==200:
            data=r.json()
            spot = data["records"]["underlyingValue"]
            add_log(f"LIVE_SPOT_NSE,Spot {spot} from NSE Option Chain,65,{spot},0,0,Live Price")
            return float(spot), "NSE_LIVE"
    except Exception as e:
        add_log(f"NSE_API_FAIL,{e},65,0,0,0,Trying Yahoo")
    
    # Method 2: Yahoo Finance Nifty 50 ^NSEI
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=1m&range=1d"
        headers={"User-Agent":"Mozilla/5.0"}
        r=requests.get(url, headers=headers, timeout=10)
        if r.status_code==200:
            data=r.json()
            spot = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            add_log(f"LIVE_SPOT_YAHOO,Spot {spot} from Yahoo ^NSEI,65,{spot},0,0,Live Price")
            return float(spot), "YAHOO_LIVE"
    except Exception as e:
        add_log(f"YAHOO_FAIL,{e},65,0,0,0,Trying fallback")
    
    # Method 3: Fallback demo with real-ish price
    spot = 24850 + random.randint(-200,200)
    add_log(f"DEMO_SPOT,Spot {spot} Demo (NSE/Yahoo failed),65,{spot},0,0,Add Angel API for 100% live or check internet")
    return float(spot), "DEMO"

def get_option_premium_live(strike, option_type="PE"):
    """Live Option Premium for Delta 0.30 strike"""
    # Try NSE option chain for that strike premium
    try:
        headers = {
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer":"https://www.nseindia.com/"
        }
        sess = requests.Session()
        sess.headers.update(headers)
        sess.get("https://www.nseindia.com/", timeout=10)
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        r = sess.get(url, timeout=10)
        if r.status_code==200:
            data=r.json()
            # Find strike
            for item in data["records"]["data"]:
                if item.get("strikePrice")==strike:
                    pe = item.get("PE",{})
                    if pe and "lastPrice" in pe:
                        prem = float(pe["lastPrice"])
                        add_log(f"LIVE_PREMIUM_NSE,Strike {strike}{option_type} Premium {prem} from NSE,65,{prem},0,0,Live Premium")
                        return prem, "NSE_LIVE"
    except Exception as e:
        add_log(f"PREMIUM_NSE_FAIL,{e},65,0,0,0,Using calculated premium")
    
    # Calculate premium approx from spot distance (demo)
    # Real premium approx: ATM ~ 200, OTM 250 point ~ 50-70
    return None, "CALC"

def ema(prices, period=20):
    if len(prices)<period: return None
    k=2/(period+1); e=sum(prices[:period])/period
    for p in prices[period:]: e=p*k+e*(1-k)
    return e

def fib_levels(low, high):
    d=high-low or 1
    return {"low":low,"high":high,"0.36":low+d*0.36,"0.5":low+d*0.5,"2.414":low+d*2.414}

def find_delta_030(spot):
    dist=int(spot*0.012); dist=(dist//50)*50
    return spot-dist, -0.31

HTML = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>LIVE MARKET PRICE</title>
<style>
body{background:#0d1117;color:#fff;padding:10px;font-family:Arial;margin:0}
h1{color:#00ff88;text-align:center;background:#161b22;padding:12px;border-radius:12px;border:2px solid #00ff88;font-size:13px}
.card{background:#161b22;padding:12px;border-radius:10px;margin:10px 0;border-left:4px solid #00ff88;border:1px solid #30363d}
.badge{display:inline-block;padding:5px 10px;border-radius:6px;font-size:10px;margin:2px;font-weight:bold}
.g{background:#00ff88;color:#000}.b{background:#1f6feb;color:#fff}.y{background:#f0883e;color:#000}.p{background:#8957e5;color:#fff}.r{background:#ff4444;color:#fff}.live{background:#ffeb3b;color:#000;animation:blink 1s infinite}
@keyframes blink{0%{opacity:1}50%{opacity:0.5}}
#chart{background:#ffffff;border-radius:12px;padding:18px;margin:10px 0;min-height:400px;border:3px solid #00ff88}
.bar-row{display:flex;align-items:center;margin:8px 0}.bar-label{width:60px;color:#000;font-weight:bold;font-size:11px}.bar{height:26px;border-radius:8px;color:#000;font-weight:bold;display:flex;align-items:center;padding-left:10px;font-size:11px}.green{background:#00ff88}.red{background:#ff6b6b}
table{width:100%;font-size:11px;border-collapse:collapse}th{color:#00ff88;padding:8px;background:#21262d}td{padding:7px;border-bottom:1px solid #21262d}
pre{background:#0d1117;color:#00ff88;padding:10px;border-radius:8px;border:1px solid #00ff88;font-size:10px;max-height:350px;overflow:auto;white-space:pre-wrap}
</style></head><body>
<h1>🔴 LIVE MARKET PRICE - DELTA 0.30 OTM<br>1 LOT 65 QTY - GREEN 0.5 + EMA20 + SL 0.36 + TGT 2.414</h1>
<div class="card">
<span class="badge live">● LIVE NSE PRICE</span><span class="badge g">DELTA 0.30 OTM</span><span class="badge p">PUT Δ-0.30</span><span class="badge g">GREEN 0.5 CROSS</span><span class="badge b">EMA20</span><span class="badge y">SL 0.36</span><span class="badge r">65 QTY</span>
<div style="margin-top:8px">
<b>Spot:</b> <span id="spot" style="font-size:18px;color:#ffeb3b">Loading...</span> | <b>Strike:</b> <span id="strike" style="color:#00ff88">-</span> | <b>Premium:</b> <span id="prem" style="color:#00ff88">-</span> | <b>Source:</b> <span id="src" style="color:#8b949e">-</span><br>
<b>P&L:</b> <span id="pnl" style="font-size:20px;color:#00ff88">Rs.0</span> | <b>Sig:</b> <span id="sig">0</span> | <span id="lt"></span><br>
<small style="color:#8b949e">Live: NSE Option Chain API + Yahoo ^NSEI | OTM = Spot -1.2% = Delta -0.30 | Green 0.5 Cross + EMA20 = BUY 65 Qty</small><br>
<small><a href="/test_telegram">Test Telegram</a> | <a href="/api/live_price">Live Price JSON</a></small>
</div>
</div>
<div id="chart">
<div style="color:#000;font-weight:bold;text-align:center">LIVE MARKET P&L - 65 QTY - NSE LIVE PRICE</div>
<div id="bars" style="margin-top:15px"></div>
<div style="margin-top:15px;padding:10px;background:#f0fff4;border-radius:8px;border:1px solid #00ff88;color:#000;font-size:11px">
<b>✓ LIVE MARKET PRICE LOGIC:</b><br>
1) Spot: NSE API (nseindia.com/api/option-chain-indices) → underlyingValue<br>
2) Strike: Spot -1.2% = Delta -0.30 OTM (eg Spot 24850 → 24600PE)<br>
3) Premium: NSE Option Chain lastPrice for that strike (Live)<br>
4) Entry: Premium Low 19.80 High 76.00 Green 0.5=50.10 Cross + Above EMA20 → BUY 65 Qty<br>
5) SL 0.36 Trail + TGT 2.414
</div>
</div>
<div class="card"><table id="tt"><tr><th>Time</th><th>Spot</th><th>Strike Δ0.30</th><th>Premium Live</th><th>P&L</th></tr></table></div>
<div class="card"><pre id="log">Loading live market price...</pre></div>
<script>
async function refresh(){
 try{
  let r=await fetch('/api/data?t='+Date.now()); let j=await r.json();
  document.getElementById('pnl').innerText='Rs.'+j.total_pnl.toFixed(2);
  document.getElementById('sig').innerText=j.total_signals;
  document.getElementById('spot').innerText=j.spot||'-';
  document.getElementById('strike').innerText=j.strike||'-';
  document.getElementById('prem').innerText=j.premium||'-';
  document.getElementById('src').innerText=j.price_source||'-';
  document.getElementById('log').innerText=j.logs.slice(-15).join('\n');
  let h=j.pnl_history; let max=Math.max(...h,100); let html='';
  h.slice(-8).forEach((v,i)=>{let w=Math.max(12,Math.min(92,(Math.abs(v)/max)*80+12));let c=v>=0?"#00ff88":"#ff4444";html+=`<div style="display:flex;margin:6px 0"><div style="width:50px;color:#000;font-size:11px">L${i}</div><div class="bar" style="width:${w}%;background:${c}">Rs.${v}</div></div>`});
  document.getElementById('bars').innerHTML=html||'<div style="color:#000;text-align:center;padding:20px">Waiting for live NSE price...</div>';
  let thtml='<tr><th>Time</th><th>Spot</th><th>Strike Δ0.30</th><th>Premium Live</th><th>P&L</th></tr>';
  j.logs.slice(-10).reverse().forEach(l=>{let p=l.split(',');thtml+=`<tr><td>${(p[0]||'').substring(11,19)}</td><td>${p[1]||''}</td><td>${p[2]||''}</td><td>${p[3]||''}</td><td style="color:#00ff88">${p[4]||''}</td></tr>`});
  document.getElementById('tt').innerHTML=thtml;
 }catch(e){}
}
setInterval(refresh,5000); refresh();
setInterval(()=>{document.getElementById('lt').innerText=new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})},1000);
</script></body></html>
"""

@app.route('/')
def home(): return HTML

@app.route('/api/live_price')
def live_price_api():
    spot, src = get_nifty_spot_live()
    strike, delta = find_delta_030(spot)
    prem, psrc = get_option_premium_live(strike)
    if prem is None: prem = 50.10
    return jsonify({"spot":spot,"strike":f"{strike}PE","delta":delta,"premium":prem,"spot_source":src,"premium_source":psrc,"time":datetime.now(pytz.timezone('Asia/Kolkata')).isoformat()})

@app.route('/api/data')
def api_data():
    return jsonify({
        "total_pnl":Pnl["total_pnl"],
        "total_signals":Pnl["total_signals"],
        "pnl_history":Pnl["pnl_history"][-20:],
        "time_labels":Pnl["time_labels"][-20:],
        "logs":LOGS[-100:],
        "spot": getattr(app, 'last_spot', '-'),
        "strike": getattr(app, 'last_strike', '-'),
        "premium": getattr(app, 'last_premium', '-'),
        "price_source": getattr(app, 'last_source', '-')
    })

@app.route('/health')
def health(): return "OK LIVE MARKET PRICE - NSE"

@app.route('/test_telegram')
def test_tele():
    ok=send_telegram("✅ LIVE MARKET PRICE TEST - Nifty Spot Live from NSE - Delta 0.30 - 65 Qty")
    return f"Telegram sent: {ok}"

def bot_loop():
    time.sleep(1)
    add_log(f"BOT_START,LIVE MARKET PRICE BOT START - DELTA 0.30 - 65 QTY,65,0,0,0,Fetching Live NSE Spot + Premium")
    prem_hist=[38,35,32,28,22,19.8,24,31,42,48,50.5]
    position=None
    while True:
        try:
            # LIVE SPOT
            spot, src = get_nifty_spot_live()
            app.last_spot = spot
            app.last_source = src
            
            strike, delta = find_delta_030(spot)
            app.last_strike = f"{strike}PE Δ{delta}"
            
            # LIVE PREMIUM
            prem_live, psrc = get_option_premium_live(strike)
            if prem_live is None:
                # Estimate from history if NSE premium fetch fails
                premium = prem_hist[-1] + random.randint(-3,4)
            else:
                premium = prem_live
            
            app.last_premium = f"{premium:.2f} ({psrc})"
            prem_hist.append(premium)
            if len(prem_hist)>100: prem_hist.pop(0)
            
            low=min(prem_hist[-30:]); high=max(prem_hist[-30:])
            fib=fib_levels(low, high); e20=ema(prem_hist,20)
            
            green_cross = len(prem_hist)>=2 and prem_hist[-2]<fib["0.5"] and prem_hist[-1]>=fib["0.5"]
            above_ema = e20 and premium>e20
            
            add_log(f"LIVE_CHECK,Spot {spot:.1f} ({src}) Strike {strike}PE Δ{delta} Prem {premium:.2f} ({psrc}) Green {fib['0.5']:.1f} EMA {e20:.1f if e20 else 0:.1f} Cross {green_cross} Above {above_ema},65,{premium:.2f},{fib['0.36']:.1f},{fib['2.414']:.1f},Low {low:.1f} High {high:.1f} LIVE PRICE")
            
            if green_cross and above_ema and position is None:
                entry=premium; sl=fib["0.36"]; tgt=fib["2.414"]
                if entry-sl>entry*0.6: sl=entry*0.72
                qty=65
                add_log(f"LIVE_TRADE_HIT,BUY {strike}PE Δ{delta} @ {entry:.2f} Live Spot {spot:.1f} Qty {qty} Green {fib['0.5']:.1f} Cross EMA {e20:.1f},65,{entry:.2f},{sl:.2f},{tgt:.2f},LIVE MARKET PRICE - NSE Spot {spot:.1f} Premium {premium:.2f}")
                send_telegram(f"🔥 LIVE TRADE HIT\nSpot {spot:.1f} ({src})\nBUY {strike}PE Δ{delta} @ {entry:.2f} Premium Live {premium:.2f} ({psrc})\nQty {qty}\nGreen {fib['0.5']:.1f} Cross EMA {e20:.1f}\nSL {sl:.2f} TGT {tgt:.2f}\nSource: {src} + {psrc}")
                position={"entry":entry,"sl":sl,"tgt":tgt,"high":entry,"low":low,"strike":strike,"delta":delta,"spot":spot}
                Pnl["total_signals"]+=1
            
            if position:
                if premium>position["high"]:
                    position["high"]=premium
                    nf=fib_levels(position["low"],position["high"])
                    position["sl"]=max(position["sl"],nf["0.36"])
                if premium<=position["sl"]:
                    pnl=position["sl"]-position["entry"]; total=pnl*65
                    add_log(f"SL_HIT,SL {position['sl']:.2f} Hit Prem {premium:.2f} Live Spot {spot:.1f} P&L {total:.2f},65,{position['entry']:.2f},{position['sl']:.2f},{position['tgt']:.2f},Qty 65 SL 0.36 Trail Live Price")
                    send_telegram(f"🔴 SL HIT LIVE\nSpot {spot:.1f} P&L Rs.{total:.2f} Qty 65\nStrike {position['strike']}PE")
                    Pnl["total_pnl"]+=total; Pnl["pnl_history"].append(Pnl["total_pnl"]); Pnl["time_labels"].append(datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%H:%M"))
                    position=None
                elif premium>=position["tgt"]:
                    pnl=position["tgt"]-position["entry"]; total=pnl*65
                    add_log(f"TGT_HIT,TGT {position['tgt']:.2f} Hit Prem {premium:.2f} Live Spot {spot:.1f} P&L {total:.2f},65,{position['entry']:.2f},{position['sl']:.2f},{position['tgt']:.2f},Qty 65 TGT 2.414 Hit Live OTM->ITM")
                    send_telegram(f"🚀 TGT HIT LIVE\nSpot {spot:.1f} P&L Rs.{total:.2f} Qty 65\nStrike {position['strike']}PE OTM->ITM Live Price")
                    Pnl["total_pnl"]+=total; Pnl["pnl_history"].append(Pnl["total_pnl"]); Pnl["time_labels"].append(datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%H:%M"))
                    position=None
            
            time.sleep(60)  # 1 min live check
        except Exception as e:
            add_log(f"LOOP_ERROR,{e},65,0,0,0,Retry 10s")
            import traceback; add_log(f"TRACE,{traceback.format_exc()[:200]},65,0,0,0,Error")
            time.sleep(10)

threading.Thread(target=bot_loop, daemon=True).start()
