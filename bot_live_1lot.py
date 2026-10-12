import os, json, time, logging
from datetime import datetime, timedelta
from dataclasses import dataclass
import requests
import pandas as pd
import numpy as np

SYMBOLS = ["NIFTY"]
EMA_LENGTH = 20
FIB_ENTRY = 0.50
FIB_SL = 0.32
FIB_TARGET = 2.414
POLL_SECONDS = 30

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ENABLE_LIVE_ORDER = os.getenv("ENABLE_LIVE_ORDER", "False").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
NIFTY_TOKEN = "99926000"
NIFTY_EXCH = "NSE"
obj = None
config = {}

def load_config():
    global config, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    try:
        with open("config.json","r") as f:
            config=json.load(f)
        print("[CONFIG] Loaded config.json")
    except:
        print("[CONFIG] Using ENV vars - Render Monday Ready")
        config={}
        config["angel_api_key"]=os.getenv("ANGEL_API_KEY","")
        config["angel_client_id"]=os.getenv("ANGEL_CLIENT_ID","")
        config["angel_password"]=os.getenv("ANGEL_PASSWORD","")
        config["angel_totp_secret"]=os.getenv("ANGEL_TOTP_SECRET","")
        config["telegram_bot_token"]=os.getenv("TELEGRAM_BOT_TOKEN","")
        config["telegram_chat_id"]=os.getenv("TELEGRAM_CHAT_ID","")
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN:
        TELEGRAM_BOT_TOKEN=config.get("telegram_bot_token") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
    if not TELEGRAM_CHAT_ID:
        TELEGRAM_CHAT_ID=config.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID") or ""
    print(f"[TELEGRAM] Bot:{'YES' if TELEGRAM_BOT_TOKEN else 'NO'} Chat:{'YES' if TELEGRAM_CHAT_ID else 'NO'} Live:{ENABLE_LIVE_ORDER}")
    print(f"[ANGEL] API:{'YES' if config.get('angel_api_key') or os.getenv('ANGEL_API_KEY') else 'NO'} Client:{'YES' if config.get('angel_client_id') or os.getenv('ANGEL_CLIENT_ID') else 'NO'}")

def get_key(cfg, *names):
    for n in names:
        if n in cfg and cfg[n]:
            return cfg[n]
        for k in cfg.keys():
            if k.lower()==n.lower() and cfg[k]:
                return cfg[k]
    for n in names:
        v=os.getenv(n.upper())
        if v:
            return v
    return None

def telegram_send(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM SKIP - No Token/Chat] {msg[:80]}")
        return False
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r=requests.post(url, json={"chat_id":TELEGRAM_CHAT_ID,"text":msg}, timeout=10)
        ok=r.status_code==200
        print(f"[TELEGRAM {'SENT' if ok else 'FAIL'}] {r.text[:100] if not ok else msg[:60]}")
        return ok
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def telegram_login_success(client_code):
    telegram_send(f"🚀 NIFTY BOT LIVE - MONDAY\n✅ Login Success\n👤 {client_code}\n🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}\n🔑 JWT Auto\n🤖 FIB 0.5/0.32/2.14\n📊 {'LIVE' if ENABLE_LIVE_ORDER else 'PAPER'}")

def telegram_signal(sig):
    bias="📈 BULLISH" if sig.option_type=="CE" else "📉 BEARISH"
    telegram_send(f"🚨 SIGNAL MONDAY 🚨\n{bias} | {sig.symbol} BUY {sig.option_type}\n💰 Underlying: {sig.underlying_price:.2f}\n🎯 Strike: {sig.strike}\n📍 Entry 0.50: {sig.entry:.2f}\n🛑 SL 0.32: {sig.sl:.2f}\n🎯 Target 2.14: {sig.target:.2f}\n📊 {sig.reason}\n🕐 {datetime.now().strftime('%H:%M:%S')}")

def angel_login():
    global obj
    api_key=get_key(config,"angel_api_key","api_key")
    client_id=get_key(config,"angel_client_id","client_id")
    password=get_key(config,"angel_password","password")
    totp_secret=get_key(config,"angel_totp_secret","totp_secret")
    if not api_key or not client_id or not password or not totp_secret:
        print("❌ Angel keys missing - Set ENV vars in Render Dashboard!")
        print("Need: ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET")
        time.sleep(30)
        return None
    try:
        from SmartApi import SmartConnect
        import pyotp
        totp=pyotp.TOTP(totp_secret).now()
        print(f"[LOGIN MONDAY] Client {client_id} TOTP {totp}")
        obj=SmartConnect(api_key=api_key)
        data=obj.generateSession(client_id, password, totp)
        if not data.get("status"):
            print(f"Login Failed: {data}")
            return None
        print(f"✅ Login OK MONDAY: {data['data']['clientcode']}")
        telegram_login_success(data['data']['clientcode'])
        return obj
    except Exception as e:
        print(f"Login Error: {e}")
        import traceback; traceback.print_exc()
        return None

@dataclass
class Signal:
    symbol: str
    option_type: str
    reason: str
    underlying_price: float
    entry: float
    sl: float
    target: float
    fib_entry: float
    fib_sl: float
    fib_target: float
    timestamp: str
    strike: float = 0.0

def ema(s,l): return s.ewm(span=l,adjust=False).mean()
def add_indicators(df):
    df=df.copy()
    df["ema20"]=ema(df["close"],20)
    df["green"]=df["close"]>df["open"]
    df["red"]=df["close"]<df["open"]
    return df
def recent_swing(df,lb=30):
    x=df.tail(lb)
    return float(x["low"].min()), float(x["high"].max())

def make_signal(symbol,df1,df5):
    if df1 is None or df5 is None or len(df1)<25:
        return None
    df1=add_indicators(df1)
    df5=add_indicators(df5)
    underlying=float(df1.iloc[-1]["close"])
    low,high=recent_swing(df5,30)
    c5=df5.iloc[-1]
    bull=c5["close"]>c5["ema20"] and c5["green"]
    bear=c5["close"]<c5["ema20"] and c5["red"]
    rng=high-low
    if rng<=0:
        return None
    fib_50_bull=high-rng*0.50
    fib_32_bull=high-rng*0.32
    fib_214_bull=high+rng*2.414
    fib_50_bear=low+rng*0.50
    fib_32_bear=low+rng*0.32
    fib_214_bear=low-rng*2.414
    curr=df1.iloc[-1]["close"]
    if abs(curr-fib_50_bull)/curr<0.002 and bull:
        return Signal(symbol, "CE", f"BULL FIB 0.50 + EMA20 High {high:.1f} Low {low:.1f}", underlying, fib_50_bull, fib_32_bull, fib_214_bull, 0.5, 0.32, 2.414, datetime.now().isoformat())
    if abs(curr-fib_50_bear)/curr<0.002 and bear:
        return Signal(symbol, "PE", f"BEAR FIB 0.50 + EMA20 High {high:.1f} Low {low:.1f}", underlying, fib_50_bear, fib_32_bear, fib_214_bear, 0.5, 0.32, 2.414, datetime.now().isoformat())
    return None

def get_candle_df(exch,token,interval,days=1):
    global obj
    if obj is None:
        return None
    try:
        to_date=datetime.now()
        from_date=to_date-timedelta(days=days)
        hp={"exchange":exch,"symboltoken":token,"interval":interval,"fromdate":from_date.strftime("%Y-%m-%d %H:%M"),"todate":to_date.strftime("%Y-%m-%d %H:%M")}
        resp=obj.getCandleData(hp)
        if not resp or not resp.get("data"):
            return None
        df=pd.DataFrame(resp["data"],columns=["timestamp","open","high","low","close","volume"])
        df["timestamp"]=pd.to_datetime(df["timestamp"])
        return df
    except Exception as e:
        print(f"Candle error {e}")
        return None

def get_market_data(sym):
    df1=get_candle_df(NIFTY_EXCH,NIFTY_TOKEN,"ONE_MINUTE",2)
    df5=get_candle_df(NIFTY_EXCH,NIFTY_TOKEN,"FIVE_MINUTE",3)
    if df1 is None or df5 is None:
        now=datetime.now()
        dummy=pd.DataFrame([{"timestamp":now,"open":22000,"high":22100,"low":21900,"close":22050,"volume":1000}]*50)
        return dummy,dummy
    return df1,df5

last_key=None
def run_once():
    global last_key,obj
    if obj is None:
        obj=angel_login()
        if obj is None:
            time.sleep(60)
            return
    for sym in SYMBOLS:
        try:
            df1,df5=get_market_data(sym)
            sig=make_signal(sym,df1,df5)
            if sig is None:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {sym} Scanning Monday... No Fib 0.50 yet")
                continue
            sig.strike=round(sig.underlying_price/50)*50
            key=(sig.symbol,sig.option_type,sig.timestamp[:16])
            if key==last_key:
                continue
            last_key=key
            print(f"✅ SIGNAL MONDAY: {sig.symbol} {sig.option_type} Entry {sig.entry:.2f} SL {sig.sl:.2f}")
            telegram_signal(sig)
        except Exception as e:
            print(f"{sym} error: {e}")

def main():
    load_config()
    print("="*60)
    print("NIFTY BOT MONDAY FINAL - FIB 0.50 + TELEGRAM FULL + ENV")
    print("="*60)
    telegram_send(f"🚀 Bot Starting MONDAY\nTime: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}\nMode: {'LIVE' if ENABLE_LIVE_ORDER else 'PAPER'}\nIf you see this, Telegram OK!")
    obj=angel_login()
    while True:
        run_once()
        time.sleep(30)

if __name__=="__main__":
    main()
