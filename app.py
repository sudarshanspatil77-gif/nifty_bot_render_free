
from flask import Flask, jsonify, render_template_string
import threading, time
from datetime import datetime
import pytz
app = Flask(__name__)
LOGS = []
Pnl = {"total_pnl": 0, "total_signals": 0, "pnl_history": [0], "time_labels": ["Start"]}

HTML = '''
<!DOCTYPE html>
<html>
<head>
<title>1 LOT 65 QTY - Chart Fixed</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
body{font-family:Arial;background:#0a0e13;color:#fff;padding:12px;margin:0}
h1{color:#00ff88;text-align:center;font-size:16px;margin:8px}
.card{background:#1a222e;padding:12px;border-radius:12px;margin:10px 0;border-left:4px solid #00ff88}
.badge{padding:4px 10px;border-radius:6px;font-size:11px;margin:2px;display:inline-block;font-weight:bold}
.g{background:#00ff88;color:#000} .b{background:#3b82f6;color:#fff} .y{background:#fbbf24;color:#000} .r{background:#ff4444;color:#fff}
#chartWrap{background:#ffffff;padding:12px;border-radius:12px;height:380px;position:relative}
pre{white-space:pre-wrap;font-size:11px;color:#00ff88;max-height:200px;overflow:auto;background:#0f1722;padding:10px;border-radius:8px;border:1px solid #00ff88}
table{width:100%;color:#ccc;font-size:12px;border-collapse:collapse}
th{color:#00ff88;padding:6px;border-bottom:1px solid #333;text-align:left}
td{padding:6px;border-bottom:1px solid #222}
.small{font-size:10px;color:#888}
</style>
</head>
<body>
<h1>🚀 FINAL 1 LOT = 65 QTY - CHART FIXED</h1>

<div class="card">
<span class="badge g">1 LOT = 65 QTY CONFIRMED</span> 
<span class="badge g">Green 0.5 Cross</span> 
<span class="badge b">Above 20 EMA</span> 
<span class="badge y">SL 0.36 Trail</span> 
<span class="badge g">TGT 2.414</span><br>
<div style="margin-top:8px">
<b id="day">{{day}}</b> | <span id="time">{{time}}</span> | 
<b>P&L:</b> <span id="pnl" style="color:#00ff88;font-size:18px">Rs. {{pnl.total_pnl}}</span> | 
<b>Signals:</b> <span id="sig">{{pnl.total_signals}}</span>
</div>
<div class="small">1 MIN TF | OTM Premium Chart | Lot 65 | Photo Pattern</div>
</div>

<div id="chartWrap">
<canvas id="pnlChart"></canvas>
</div>

<div class="card">
<h3 style="margin:0 0 8px 0;color:#00ff88">📊 Live Trades - Green 0.5 + EMA20</h3>
<table id="pnlTable">
<tr><th>Time</th><th>Signal</th><th>Qty</th><th>Entry/SL/TGT</th><th>P&L</th></tr>
<tr><td colspan="5" class="small">Waiting for Green Line 0.5 Cross + EMA20...</td></tr>
</table>
</div>

<div class="card">
<h3 style="margin:0 0 8px 0;color:#00ff88">📝 Live Logs - Auto Refresh 3 sec</h3>
<pre id="logs">{{logs_text}}</pre>
<div class="small">Green Line 0.5 = Entry | 0.36 = SL Trail | 2.414 = Target | 1 MIN Candle</div>
</div>

<script>
let chart;
function initChart(){
 const ctx = document.getElementById('pnlChart').getContext('2d');
 chart = new Chart(ctx, {
  type: 'line',
  data: {
   labels: {{ time_labels|tojson }},
   datasets: [{
    label: 'P&L (65 Qty Lot)',
    data: {{ pnl_history|tojson }},
    borderColor: '#00b050',
    backgroundColor: 'rgba(0,176,80,0.2)',
    borderWidth: 3,
    tension: 0.4,
    fill: true,
    pointRadius: 3,
    pointBackgroundColor: '#00ff88'
   }]
  },
  options: {
   responsive: true,
   maintainAspectRatio: false,
   plugins: { legend: { display: true } },
   scales: {
    y: { beginAtZero: false, grid: { color: '#eee' } },
    x: { grid: { color: '#eee' } }
   }
  }
 });
}

async function refresh(){
 try {
  const r = await fetch('/api/data');
  const j = await r.json();
  document.getElementById('pnl').innerText = 'Rs. ' + j.total_pnl.toFixed(2);
  document.getElementById('sig').innerText = j.total_signals;
  document.getElementById('logs').innerText = j.logs.slice(-12).join('\n') || 'Waiting for Green 0.5 Cross + EMA20...';
  
  if(chart){
   chart.data.labels = j.time_labels;
   chart.data.datasets[0].data = j.pnl_history;
   chart.update();
  }
  
  let html='<tr><th>Time</th><th>Signal</th><th>Qty</th><th>Entry/SL/TGT</th><th>P&L</th></tr>';
  if(j.logs.length==0){
    html+='<tr><td colspan="5" class="small">Waiting for W Pattern at low...</td></tr>';
  } else {
    j.logs.slice(-10).reverse().forEach(l=>{
     const p=l.split(',');
     html+=`<tr><td>${(p[0]||'').substring(11,19)}</td><td>${p[1]||''}</td><td>${p[2]||''}</td><td>${(p[3]||'')}/${(p[4]||'')}/${(p[5]||'')}</td><td style="color:${parseFloat(p[6])>=0?'#00ff88':'#ff4444'}">${p[6]||''}</td></tr>`;
    });
  }
  document.getElementById('pnlTable').innerHTML=html;
 } catch(e){ console.log('Refresh error', e); }
}

initChart();
setInterval(refresh, 3000);
refresh();
setInterval(()=>{ document.getElementById('time').innerText = new Date().toLocaleString('en-IN', {timeZone:'Asia/Kolkata'}); }, 1000);
</script>
</body>
</html>
'''

@app.route('/')
def home():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    day = now.strftime("%A").upper()
    ts = now.strftime("%d-%m-%Y %H:%M:%S")
    txt = "\n".join(LOGS[-15:]) if LOGS else "CHART FIXED ✅\n1 LOT = 65 QTY CONFIRMED\nWaiting: Green Line 0.5 Cross + Above 20 EMA...\n1 MIN TF | Photo Pattern Same"
    return render_template_string(HTML, pnl=Pnl, logs_text=txt, time=ts, day=day, time_labels=Pnl["time_labels"][-40:], pnl_history=Pnl["pnl_history"][-40:])

@app.route('/api/data')
def api_data():
    return jsonify({
        "total_pnl": Pnl["total_pnl"],
        "total_signals": Pnl["total_signals"],
        "pnl_history": Pnl["pnl_history"][-60:],
        "time_labels": Pnl["time_labels"][-60:],
        "logs": LOGS[-100:]
    })

@app.route('/health')
def health():
    return "OK - Chart Fixed - 1 Lot 65 Qty"

def start_bot():
    time.sleep(3)
    try:
        import bot_live_1lot
        bot_live_1lot.SHARED_LOGS = LOGS
        bot_live_1lot.SHARED_PNL = Pnl
        bot_live_1lot.main()
    except Exception as e:
        LOGS.append(f"Bot Error: {e}")
        import traceback; LOGS.append(traceback.format_exc()[:500])

threading.Thread(target=start_bot, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
