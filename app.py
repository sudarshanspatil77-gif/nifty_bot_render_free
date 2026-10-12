
import os, threading, time
from datetime import datetime
from flask import Flask, send_from_directory, jsonify
app = Flask(__name__)
bot_status = {"running": False, "last_login": None, "last_signal": None, "pnl_today": 0, "trades_today": 0, "token_auto": "ON", "logic": "MONDAY READY FIB 0.5/0.32/2.14 + TELEGRAM FULL", "started_at": datetime.now().isoformat()}
def run_bot():
    global bot_status
    while True:
        try:
            print("[RENDER MONDAY] Starting bot thread...")
            import bot_live_1lot as bot_module
            print("[RENDER MONDAY] Loaded FIB + TELEGRAM FULL")
            bot_status["running"] = True
            bot_status["last_login"] = datetime.now().isoformat()
            bot_module.main()
        except Exception as e:
            print(f"[RENDER MONDAY] Bot error: {e}")
            import traceback; traceback.print_exc()
            bot_status["running"] = False
            time.sleep(10)
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
print("[RENDER MONDAY] Bot thread started (gunicorn compatible)")
@app.route('/')
def home():
    return f"<html><head><title>Nifty Bot Monday</title><style>body{{background:#0f172a;color:white;font-family:Arial;padding:20px}}.card{{background:#1e293b;padding:20px;border-radius:12px;margin:15px 0}}h1{{color:#22c55e}}a{{color:#3b82f6}}</style></head><body><h1>🚀 NIFTY BOT - MONDAY READY ✅ LIVE</h1><div class='card'><h2>Status: {'🟢 RUNNING' if bot_status['running'] else '🟡 STARTING'}</h2><p>Started: {bot_status['started_at']}<br>Logic: {bot_status['logic']}<br>Token: Auto ON<br>Last Login: {bot_status['last_login']}</p></div><div class='card'><h2>📊 Links</h2><p><a href='/dashboard'>📈 Dashboard</a> | <a href='/status'>🔍 Status</a> | <a href='/logs'>📝 Logs</a></p></div></body></html>"
@app.route('/dashboard')
def dashboard():
    try: return send_from_directory('.', 'pnl_chart.html')
    except: return "<h1>Dashboard missing</h1>"
@app.route('/status')
def status(): return jsonify(bot_status)
@app.route('/logs')
def logs():
    txt="=== BOT LOGS MONDAY ===\n"
    try:
        with open('paper_signals.csv','r') as f: txt+=f.read()[-2000:]+'\n'
    except: txt+="No signals yet - Monday 9:15 waiting...\n"
    txt+=f"\n{bot_status}\n"
    return f"<pre style='background:#000;color:#0f0;padding:20px'>{txt}</pre>"
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
