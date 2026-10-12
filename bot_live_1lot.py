
import os, time, random
from datetime import datetime
import pytz
SHARED_LOGS = None
SHARED_PNL = None
def send_telegram(msg):
    try:
        import requests
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id: return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass
def log_signal(signal_id, pnl=0):
    import pytz
    from datetime import datetime
    ist = pytz.timezone('Asia/Kolkata')
    ts = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    time_only = datetime.now(ist).strftime("%H:%M")
    entry=21000+random.randint(-100,100)
    line = f"{ts},{signal_id},BULLISH,{entry},{entry-50},{entry+100},{pnl}"
    if SHARED_LOGS is not None: SHARED_LOGS.append(line)
    if SHARED_PNL is not None:
        SHARED_PNL["total_signals"] = len(SHARED_LOGS)
        SHARED_PNL["total_pnl"] += pnl
        SHARED_PNL["pnl_history"].append(SHARED_PNL["total_pnl"])
        SHARED_PNL["time_labels"].append(time_only)
    print(line)
def main():
    ist = pytz.timezone('Asia/Kolkata')
    day = datetime.now(ist).strftime("%A").upper()
    now = datetime.now(ist).strftime("%d-%m-%Y %H:%M:%S")
    send_telegram(f"🚀 Bot Starting {day}\nTime: {now}\nMode: PAPER\nP&L Chart ON ✅")
    log_signal(f"START_{day}", 0)
    count=0
    while True:
        time.sleep(90)
        count+=1
        pnl = random.choice([-20, 30, 45, -15, 50])
        log_signal(f"SIGNAL_{day}_{count}", pnl)
        if count % 4 == 0:
            total = SHARED_PNL["total_pnl"] if SHARED_PNL else 0
            send_telegram(f"📊 {day} Update - Signals: {count} - P&L: Rs.{total}")

if __name__ == "__main__":
    main()
