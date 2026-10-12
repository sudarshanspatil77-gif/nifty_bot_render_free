
from flask import Flask, jsonify, render_template_string, Response
import threading, time, os
from datetime import datetime
import pytz

app = Flask(__name__)
LOGS = []
Pnl = {"total_pnl": 0, "total_signals": 0, "pnl_history": [0], "time_labels": ["Start"]}

HTML = """<!DOCTYPE html>
<html>
<head>
<title>Nifty Bot - W Pattern LIVE</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body{font-family:Arial;background:#0a0e13;color:#fff;padding:12px;margin:0}
h1{color:#00ff88;text-align:center;font-size:20px;margin:8px}
.card{background:#1a222e;padding:12px;border-radius:12px;margin:10px 0;border-left:4px solid #00ff88}
.badge{display:inline-block;padding:3px 8px;border-radius:6px;font-size:11px;background:#00ff88;color:#000;margin:2px}
.green{color:#00ff88} .red{color:#ff4444}
table{width:100%;color:#ccc;font-size:11px;border-collapse:collapse}
th{color:#00ff88;text-align:left;padding:5px;border-bottom:1px solid #333}
td{padding:4px;border-bottom:1px solid #222}
#chartWrap{background:#ffffff;padding:10px;border-radius:12px;height:320px}
pre{white-space:pre-wrap;word-wrap:break-word;font-size:10px;color:#b0bfd8;max-height:180px;overflow:auto;background:#0f1722;padding:8px;border-radius:6px}
.small{font-size:11px;color:#8f9bb3}
</style>
</head>
<body>
<h1>🚀 Nifty Bot - {{day}} LIVE - W Pattern</h1>
<div class="card">
<span class="badge">OTM->ITM</span> <span class="badge">20 EMA x FIB</span> <span class="badge">1 MIN TF</span><br>
<b>Day:</b> <span class="green">{{day}}</span> | <b>Time:</b> {{time}}<br>
<b>P&L:</b> <span id="pnl" class="green">Rs. {{pnl.total_pnl}}</span> | <b>Signals:</b> <span id="sig">{{pnl.total_signals}}</span> | <b>Mode:</b> PAPER<br>
<span class="small">Entry: FIB 0.5 cross | SL: 0.35 trailing | Target: 2.414 | Intrinsic Value ON</span>
</div>
<div id="chartWrap"><canvas id="pnlChart"></canvas></div>
<div class="card"><h3 style="margin:0 0 8px 0">📊 P&L History (Adhi Jaisa)</h3><table id="pnlTable"><tr><th>Time</th><th>Signal</th><th>Entry</th><th>P&L</th></tr></table></div>
<div class="card"><h3 style="margin:0 0 6px 0">Logs Auto Loaded ✅</h3><pre id="logs">{{logs_text}}</pre></div>
<script>
let chart;
function initChart(){
 const ctx = document.getElementById('pnlChart').getContext('2d');
 chart = new Chart(ctx, {
  type: 'line',
  data: {labels: {{ time_labels | tojson }}, datasets: [{label:'Cumulative P&L', data: {{ pnl_history | tojson }}, borderColor:'#00b050', backgroundColor:'rgba(0,176,80,0.2)', borderWidth:2, tension:0.4, fill:true, pointRadius:3}]},
  options: {responsive:true, maintainAspectRatio:false, plugins:{legend:{labels:{color:'#000'}}}, scales:{x:{ticks:{color:'#000'}}, y:{ticks:{color:'#000'}}}}
 });
}
async function refresh(){
 try{
  const r = await fetch('/api/data'); const j = await r.json();
  document.getElementById('pnl').innerText = 'Rs. '+j.total_pnl.toFixed(2);
  document.getElementById('sig').innerText = j.total_signals;
  document.getElementById('logs').innerText = j.logs.slice(-12).join('\n');
  if(chart){ chart.data.labels = j.time_labels; chart.data.datasets[0].data = j.pnl_history; chart.update(); }
  let html='<tr><th>Time</th><th>Signal</th><th>Entry</th><th>P&L</th></tr>';
  j.logs.slice(-10).reverse().forEach(l=>{
   const p=l.split(',');
   html+=`<tr><td>${(p[0]||'').substring(11,19)}</td><td>${p[1]||''}</td><td>${p[3]||''}</td><td>${p[6]||''}</td></tr>`;
  });
  document.getElementById('pnlTable').innerHTML=html;
 }catch(e){console.log(e)}
}
initChart(); setInterval(refresh, 3000); refresh();
</script>
</body>
</html>
"""

@app.route('/')
def home():
    import pytz
    from datetime import datetime
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    day = now.strftime("%A").upper()
    time_str = now.strftime("%d-%m-%Y %H:%M:%S")
    logs_text = "\n".join(LOGS[-15:]) if LOGS else "Waiting for W Pattern..."
    return render_template_string(HTML, pnl=Pnl, logs_text=logs_text, time=time_str, day=day,
                                  time_labels=Pnl["time_labels"][-30:], pnl_history=Pnl["pnl_history"][-30:])

@app.route('/logs')
def logs_csv():
    header = "timestamp,signal_id,bias,entry,sl,target,pnl\n"
    return Response(header + "\n".join(LOGS), mimetype='text/csv')

@app.route('/api/data')
def api_data():
    return jsonify({
        "total_pnl": Pnl["total_pnl"],
        "total_signals": Pnl["total_signals"],
        "pnl_history": Pnl["pnl_history"][-60:],
        "time_labels": Pnl["time_labels"][-60:],
        "logs": LOGS[-100:]
    })

def start_bot_background():
    time.sleep(2)
    try:
        import bot_live_1lot
        bot_live_1lot.SHARED_LOGS = LOGS
        bot_live_1lot.SHARED_PNL = Pnl
        if hasattr(bot_live_1lot, 'main'): bot_live_1lot.main()
    except Exception as e:
        LOGS.append(f"{datetime.now()} ERROR {e}")
        import traceback; traceback.print_exc()

threading.Thread(target=start_bot_background, daemon=True).start()
