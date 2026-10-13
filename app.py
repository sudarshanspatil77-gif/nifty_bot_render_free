from flask import Flask
import threading, time
from datetime import datetime
import pytz
app=Flask(__name__)
LOGS=[]; Pnl={"total_pnl":0,"total_signals":0,"pnl_history":[0],"time_labels":["Start"]}
@app.route('/')
def home():
    return f"CONFIRMED 1 LOT = 65 QTY | GREEN 0.5 CROSS + EMA20 | SL 0.36 TRAIL | TGT 2.414 | Logs: {LOGS[-3:]}"
def start_bot():
    time.sleep(2)
    try:
        import bot_live_1lot
        bot_live_1lot.SHARED_LOGS=LOGS
        bot_live_1lot.SHARED_PNL=Pnl
        bot_live_1lot.main()
    except Exception as e:
        LOGS.append(str(e))
threading.Thread(target=start_bot,daemon=True).start()
