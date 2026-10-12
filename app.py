
from flask import Flask, jsonify, render_template_string, Response
import threading, time, os, csv, io
from datetime import datetime
import pytz

app = Flask(__name__)

# In-memory storage for logs - Render free var file delete hota
LOGS = []
Pnl = {"total_pnl": 0, "total_signals": 0, "win_rate": 0}

HTML_DASH = """
<!DOCTYPE html>
<html>
<head><title>Nifty Bot Live</title>
<meta http-equiv="refresh" content="5">
<style>body{font-family:Arial;background:#111;color:#0f0;padding:20px} .card{background:#222;padding:15px;border-radius:10px;margin:10px 0} table{width:100%;color:#fff} th{color:#0f0}</style>
</head>
<body>
<h1>🚀 Nifty Bot - MONDAY LIVE</h1>
<div class="card">Total P&L: Rs. {{pnl.total_pnl}} | Signals: {{pnl.total_signals}} | Time: {{time}}</div>
<div class="card"><h3>Logs Auto Loaded ✅</h3><pre id="logs">{{logs_text}}</pre></div>
<script>
setInterval(()=>fetch('/api/logs').then(r=>r.text()).then(t=>document.getElementById('logs').innerText=t), 3000);
</script>
</body>
</html>
"""

@app.route('/')
def home():
    logs_text = "\n".join(LOGS[-50:]) if LOGS else "Waiting for signals... Bot Starting..."
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist).strftime("%d-%m-%Y %H:%M:%S")
    return render_template_string(HTML_DASH, pnl=Pnl, logs_text=logs_text, time=now)

@app.route('/logs')
def logs_page():
    # For your old link
    if LOGS:
        return Response("\n".join(LOGS), mimetype='text/csv')
    # Try file fallback
    try:
        if os.path.exists('paper_signals.csv'):
            with open('paper_signals.csv') as f:
                return Response(f.read(), mimetype='text/csv')
    except: pass
    return "timestamp,signal_id,bias,entry,sl,target,pnl\nWaiting for bot to generate signals...\n"

@app.route('/api/logs')
def api_logs():
    return "\n".join(LOGS[-100:]) if LOGS else "Waiting..."

@app.route('/health')
def health():
    return "OK"

def start_bot_background():
    print("🚀 Auto-Run Thread Starting...")
    time.sleep(3)
    try:
        import bot_live_1lot
        # Inject our LOGS list into bot module so it writes to us
        bot_live_1lot.SHARED_LOGS = LOGS
        bot_live_1lot.SHARED_PNL = Pnl
        if hasattr(bot_live_1lot, 'main'):
            bot_live_1lot.main()
        elif hasattr(bot_live_1lot, 'start'):
            bot_live_1lot.start()
    except Exception as e:
        print(f"Bot Thread Error: {e}")
        import traceback; traceback.print_exc()
        LOGS.append(f"{datetime.now()} ERROR {e}")

# Auto-run on Render start
threading.Thread(target=start_bot_background, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
