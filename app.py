
from flask import Flask, jsonify
import threading, time
app = Flask(__name__)
LOGS = []; Pnl = {"total_pnl":0,"total_signals":0,"pnl_history":[0],"time_labels":["Start"]}
HTML = """<html><head><meta name="viewport" content="width=device-width"><style>
body{font-family:Arial;background:#0d1117;color:#fff;padding:10px}
h1{color:#00ff88;text-align:center;background:#161b22;padding:10px;border-radius:8px;border:1px solid #00ff88}
.card{background:#161b22;padding:12px;border-radius:10px;margin:10px 0;border-left:4px solid #00ff88;border:1px solid #30363d}
.badge{display:inline-block;padding:5px 10px;border-radius:6px;font-size:11px;margin:2px;font-weight:bold}
.g{background:#00ff88;color:#000} .b{background:#1f6feb;color:#fff} .y{background:#f0883e;color:#000} .p{background:#8957e5;color:#fff}
#chartBox{background:#fff;border-radius:12px;padding:15px;min-height:300px;border:2px solid #00ff88}
.bar{height:22px;background:#00ff88;margin:5px 0;border-radius:6px;color:#000;font-weight:bold;padding-left:10px;display:flex;align-items:center;font-size:12px}
table{width:100%;font-size:12px;border-collapse:collapse} th{color:#00ff88;padding:8px;background:#21262d} td{padding:7px;border-bottom:1px solid #21262d}
pre{background:#0d1117;color:#00ff88;padding:10px;border-radius:8px;border:1px solid #30363d;font-size:11px;max-height:250px;overflow:auto}
</style></head><body>
<h1>DELTA 0.30 OTM - 1 LOT 65 QTY - CONFIRMED</h1>
<div class="card"><span class="badge g">DELTA 0.30 OTM</span><span class="badge p">PUT Delta -0.30</span><span class="badge g">GREEN 0.5 CROSS</span><span class="badge b">EMA20</span><span class="badge y">SL 0.36</span>
<div style="margin-top:8px"><b>P&L:</b> <span id="pnl" style="color:#00ff88;font-size:20px">Rs.0</span> | <b>Sig:</b> <span id="sig">0</span> | <span id="lt"></span></div>
<div style="font-size:10px;color:#8b949e">Delta 0.30 = ~300 point OTM | Best Risk:Reward | OTM->ITM</div></div>
<div id="chartBox"><div style="color:#000;font-weight:bold;text-align:center">DELTA 0.30 OTM P&L - 65 QTY</div><div id="bars" style="margin-top:15px"></div></div>
<div class="card"><table id="tt"><tr><th>Time</th><th>Strike (Δ0.30)</th><th>Qty</th><th>Premium</th><th>P&L</th></tr></table></div>
<div class="card"><pre id="log">Loading Delta 0.30 OTM...</pre></div>
<script>
function drawBars(h){let b=document.getElementById('bars');let max=Math.max(...h,100);if(max==0)max=100;let html='';h.slice(-10).forEach((v,i)=>{let w=Math.max(10,Math.min(90,(Math.abs(v)/max)*80+10));let c=v>=0?'#00ff88':'#ff4444';html+=`<div style="display:flex"><div style="width:40px;color:#000;font-size:11px">${i}</div><div class="bar" style="width:${w}%;background:${c}">Rs.${v}</div></div>`});b.innerHTML=html||'<div style="color:#000;text-align:center;padding:20px">Waiting Delta 0.30...</div>';}
async function ref(){try{let r=await fetch('/api/data?t='+Date.now());let j=await r.json();document.getElementById('pnl').innerText='Rs.'+j.total_pnl.toFixed(2);document.getElementById('sig').innerText=j.total_signals;document.getElementById('log').innerText=j.logs.slice(-12).join('\n');drawBars(j.pnl_history);let html='<tr><th>Time</th><th>Strike (Δ0.30)</th><th>Qty</th><th>Premium</th><th>P&L</th></tr>';j.logs.slice(-8).reverse().forEach(l=>{let p=l.split(',');html+=`<tr><td>${(p[0]||'').substring(11,19)}</td><td>${p[1]||''}</td><td>${p[2]||''}</td><td>${p[3]||''}</td><td>${p[6]||''}</td></tr>`});document.getElementById('tt').innerHTML=html;}catch(e){}}
setInterval(ref,3000);ref();setInterval(()=>{document.getElementById('lt').innerText=new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})},1000);
</script></body></html>
"""
@app.route('/')
def home(): return HTML
@app.route('/api/data')
def api_data():
    return jsonify({"total_pnl":Pnl["total_pnl"],"total_signals":Pnl["total_signals"],"pnl_history":Pnl["pnl_history"][-20:],"time_labels":Pnl["time_labels"][-20:],"logs":LOGS[-100:]})
def start_bot():
    time.sleep(2)
    try:
        import bot_live_1lot; bot_live_1lot.SHARED_LOGS=LOGS; bot_live_1lot.SHARED_PNL=Pnl; bot_live_1lot.main()
    except Exception as e: LOGS.append(str(e))
threading.Thread(target=start_bot,daemon=True).start()
