
from flask import Flask, jsonify, render_template_string
import threading, time
from datetime import datetime
import pytz
app=Flask(__name__)
LOGS=[]; Pnl={"total_pnl":0,"total_signals":0,"pnl_history":[0],"time_labels":["Start"]}
HTML="""<!DOCTYPE html><html><head><title>Green 0.5 + EMA20 Bot</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body{font-family:Arial;background:#0a0e13;color:#fff;padding:12px;margin:0}
h1{color:#00ff88;text-align:center;font-size:15px}
.card{background:#1a222e;padding:12px;border-radius:12px;margin:10px 0;border-left:4px solid #00ff88}
.badge{padding:3px 8px;border-radius:6px;font-size:10px;margin:2px;display:inline-block}
.g{background:#00ff88;color:#000} .b{background:#3b82f6;color:#fff} .y{background:#fbbf24;color:#000}
#chartWrap{background:#fff;padding:10px;border-radius:12px;height:320px}
pre{white-space:pre-wrap;font-size:10px;color:#b0bfd8;max-height:160px;overflow:auto;background:#0f1722;padding:8px;border-radius:6px}
table{width:100%;color:#ccc;font-size:11px;border-collapse:collapse}
th{color:#00ff88;padding:5px;border-bottom:1px solid #333;text-align:left}
td{padding:4px;border-bottom:1px solid #222}
</style></head><body>
<h1>🚀 GREEN 0.5 CROSS + 20 EMA - {{day}} LIVE</h1>
<div class="card">
<span class="badge g">Entry: Green 0.5 Cross</span> <span class="badge b">Above 20 EMA</span> <span class="badge y">SL 0.36 Trail</span> <span class="badge g">TGT 2.414</span><br>
<b>{{day}}</b> | {{time}} | <b>P&L:</b> <span id="pnl">Rs. {{pnl.total_pnl}}</span> | <b>Sig:</b> <span id="sig">{{pnl.total_signals}}</span><br>
<small>Photo: Green Line 50.10 = 0.5 | SL 31.40 = 0.36 | Premium Chart</small>
</div>
<div id="chartWrap"><canvas id="pnlChart"></canvas></div>
<div class="card"><table id="pnlTable"><tr><th>Time</th><th>Signal</th><th>Entry</th><th>P&L</th></tr></table></div>
<div class="card"><pre id="logs">{{logs_text}}</pre></div>
<script>
let chart;
function initChart(){
 const ctx=document.getElementById('pnlChart').getContext('2d');
 chart=new Chart(ctx,{type:'line',data:{labels:{{ time_labels|tojson }},datasets:[{label:'P&L Green 0.5+EMA20',data:{{ pnl_history|tojson }},borderColor:'#00b050',backgroundColor:'rgba(0,176,80,0.2)',borderWidth:2,tension:0.4,fill:true}]},options:{responsive:true,maintainAspectRatio:false}});
}
async function refresh(){
 const r=await fetch('/api/data'); const j=await r.json();
 document.getElementById('pnl').innerText='Rs. '+j.total_pnl.toFixed(2);
 document.getElementById('sig').innerText=j.total_signals;
 document.getElementById('logs').innerText=j.logs.slice(-10).join('\n');
 if(chart){chart.data.labels=j.time_labels; chart.data.datasets[0].data=j.pnl_history; chart.update();}
 let html='<tr><th>Time</th><th>Signal</th><th>Entry</th><th>P&L</th></tr>';
 j.logs.slice(-8).reverse().forEach(l=>{const p=l.split(','); html+=`<tr><td>${(p[0]||'').substring(11,19)}</td><td>${p[1]||''}</td><td>${p[3]||''}</td><td>${p[6]||''}</td></tr>`;});
 document.getElementById('pnlTable').innerHTML=html;
}
initChart(); setInterval(refresh,3000); refresh();
</script></body></html>"""
@app.route('/')
def home():
    ist=pytz.timezone('Asia/Kolkata'); now=datetime.now(ist); day=now.strftime("%A").upper(); ts=now.strftime("%d-%m-%Y %H:%M:%S")
    txt="\n".join(LOGS[-12:]) if LOGS else "Waiting: Green Line 0.5 Cross + Above 20 EMA..."
    return render_template_string(HTML,pnl=Pnl,logs_text=txt,time=ts,day=day,time_labels=Pnl["time_labels"][-30:],pnl_history=Pnl["pnl_history"][-30:])
@app.route('/api/data')
def api_data():
    from flask import jsonify
    return jsonify({"total_pnl":Pnl["total_pnl"],"total_signals":Pnl["total_signals"],"pnl_history":Pnl["pnl_history"][-60:],"time_labels":Pnl["time_labels"][-60:],"logs":LOGS[-100:]})
def start_bot():
    time.sleep(2)
    try: import bot_live_1lot; bot_live_1lot.SHARED_LOGS=LOGS; bot_live_1lot.SHARED_PNL=Pnl; bot_live_1lot.main()
    except Exception as e: LOGS.append(f"ERR {e}")
threading.Thread(target=start_bot,daemon=True).start()
