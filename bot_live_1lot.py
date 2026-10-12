
import os, time, csv
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
    except Exception as e:
        print(f"Telegram Error: {e}")

def log_signal(text):
    ist = pytz.timezone('Asia/Kolkata')
    ts = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts},{text}"
    print(line)
    if SHARED_LOGS is not None:
        SHARED_LOGS.append(line)
    # Also try file
    try:
        header = not os.path.exists('paper_signals.csv')
        with open('paper_signals.csv','a',newline='') as f:
            if header:
                f.write('timestamp,signal_id,bias,entry,sl,target,pnl\n')
            f.write(line+'\n')
    except: pass
    if SHARED_PNL is not None:
        SHARED_PNL['total_signals'] = len(SHARED_LOGS) if SHARED_LOGS else SHARED_PNL['total_signals']+1

def main():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist).strftime("%d-%m-%Y %H:%M:%S")
    msg = f"🚀 Bot Starting MONDAY\nTime: {now}\nMode: PAPER\nIf you see this, Telegram OK!"
    send_telegram(msg)
    log_signal(f"START,Monday Bot Live, PAPEr mode OK,{now}")

    # Dummy loop for testing - real trading logic here
    # Replace with your actual Nifty logic
    count=0
    while True:
        time.sleep(60)
        count+=1
        log_signal(f"SIGNAL_{count},BUY_CE,21000,200,250,0")
        if count % 5 == 0:
            send_telegram(f"📊 Bot Alive - Signals: {count} - Time: {datetime.now(ist).strftime('%H:%M:%S')}")

if __name__ == "__main__":
    main()
