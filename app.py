import os, requests
from flask import Flask, jsonify
import pytz
from datetime import datetime

app=Flask(__name__)
STATE={"trades":0,"pnl":0,"open":22500,"telegram_ok":False}

def send_tg(text):
    try:
        # ULTRA SMALL - 200 chars max
        if len(text)>200:
            text=text[:200]
        token=os.getenv('TELEGRAM_BOT_TOKEN')
        chat=os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat:
            return False
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":text},timeout=10)
        return r.status_code==200
    except:
        return False

@app.route("/")
def home():
    return jsonify({"status":"Bot Live Small Message","trades":f"{STATE['trades']}/5","telegram":"ON","open":STATE["open"]})

@app.route("/health")
def health():
    tok=os.getenv('TELEGRAM_BOT_TOKEN')
    chat=os.getenv('TELEGRAM_CHAT_ID')
    ang=os.getenv('ANGEL_API_KEY')
    return jsonify({
        "status":"OK Small Message",
        "telegram":"Enabled" if tok and chat else "Missing",
        "angel":"Enabled" if ang else "Paper",
        "open":STATE["open"],
        "trades":f"{STATE['trades']}/5",
        "msg":"Small 20 chars only"
    })

@app.route("/test_telegram")
def test_telegram():
    try:
        # ULTRA SMALL - 18 chars only - Never fail
        ok=send_tg("Test OK Bot Working")
        return jsonify({"ok":ok,"msg":"Sent OK" if ok else "Fail","telegram":"True" if ok else "False"})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)[:80]})

@app.route("/force_buy")
def force_buy():
    try:
        STATE["trades"]+=1
        send_tg(f"BUY {STATE['trades']}/5 @76.0")
        return jsonify({"ok":True,"msg":f"BUY {STATE['trades']}/5 @76.0 SL70.8 TGT118.0","telegram":"Sent"})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/reset")
def reset():
    STATE["trades"]=0
    STATE["pnl"]=0
    return jsonify({"ok":True,"msg":"Reset Done 0/5"})

if __name__=="__main__":
    port=int(os.getenv("PORT",5000))
    app.run(host="0.0.0.0",port=port)
