
import os, time, random
from datetime import datetime
import pytz
SHARED_LOGS=None; SHARED_PNL=None
LOT_QTY = 65
LOTS = 1
def send_telegram(m):
    try:
        import requests; t=os.getenv('TELEGRAM_BOT_TOKEN'); c=os.getenv('TELEGRAM_CHAT_ID')
        if not t or not c: return
        requests.post(f"https://api.telegram.org/bot{t}/sendMessage",json={"chat_id":c,"text":m},timeout=10)
    except: pass
def ema(prices, period=20):
    if len(prices)<period: return None
    k=2/(period+1); e=sum(prices[:period])/period
    for p in prices[period:]: e=p*k+e*(1-k)
    return e
def fib_levels(low, high):
    d=high-low or 1
    return {"low":low,"high":high,"0":low,"0.36":low+d*0.36,"0.5":low+d*0.5,"2.414":low+d*2.414}
def logt(sid, entry, sl, tgt, pnl, extra=""):
    ist=pytz.timezone('Asia/Kolkata'); ts=datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S"); to=datetime.now(ist).strftime("%H:%M")
    qty = LOT_QTY * LOTS
    line=f"{ts},{sid},1LOT={qty}Qty,{entry:.2f},{sl:.2f},{tgt:.2f},{pnl*qty:.2f},{extra}"
    if SHARED_LOGS is not None: SHARED_LOGS.append(line)
    if SHARED_PNL is not None:
        SHARED_PNL["total_signals"]=len(SHARED_LOGS); SHARED_PNL["total_pnl"]+=pnl*qty
        SHARED_PNL["pnl_history"].append(SHARED_PNL["total_pnl"]); SHARED_PNL["time_labels"].append(to)
    print(line)
def main():
    ist=pytz.timezone('Asia/Kolkata'); day=datetime.now(ist).strftime("%A").upper()
    send_telegram(f"CONFIRMED 1 LOT = {LOT_QTY} QTY BOT {day} START - 1MIN Green 0.5 Cross + 20 EMA")
    prem_hist=[38,35,32,28,22,19.8,24,31,42,48,50.5,55,62,71,78,85,92,105,111,108]
    position=None
    while True:
        try:
            premium = 45 + random.randint(-10,15) if position is None else 100+random.randint(-5,12)
            prem_hist.append(premium)
            if len(prem_hist)>100: prem_hist.pop(0)
            low=min(prem_hist[-30:]); high=max(prem_hist[-30:])
            fib=fib_levels(low, high); e20=ema(prem_hist,20)
            green_cross=False; above_ema=False
            if len(prem_hist)>=2:
                if prem_hist[-2] < fib["0.5"] and prem_hist[-1] >= fib["0.5"]: green_cross=True
            if e20 and premium > e20: above_ema=True
            if green_cross and above_ema and position is None:
                entry=premium; sl=fib["0.36"]; tgt=fib["2.414"]
                if entry-sl>entry*0.6: sl=entry*0.65
                qty=LOT_QTY*LOTS
                logt(f"BUY_1LOT_{qty}Qty",entry,sl,tgt,0,f"Green:{fib['0.5']:.1f} EMA:{e20:.1f}")
                send_telegram(f"ENTRY 1 LOT CONFIRMED Qty:{qty} Prem:{premium:.1f} Green 0.5 {fib['0.5']:.1f} Cross Above EMA {e20:.1f}")
                position={"entry":entry,"sl":sl,"tgt":tgt,"high":entry,"low":low}
            if position:
                if premium>position["high"]:
                    position["high"]=premium; nf=fib_levels(position["low"],position["high"]); position["sl"]=max(position["sl"],nf["0.36"])
                if premium<=position["sl"]:
                    pnl=position["sl"]-position["entry"]; qty=LOT_QTY*LOTS; logt(f"SL_0.36_1LOT",position["entry"],position["sl"],position["tgt"],pnl,f"Qty:{qty}"); send_telegram(f"SL Hit P&L:{pnl*qty:.1f}"); position=None
                elif premium>=position["tgt"]:
                    pnl=position["tgt"]-position["entry"]; qty=LOT_QTY*LOTS; logt(f"TGT_2.414_1LOT",position["entry"],position["sl"],position["tgt"],pnl,f"Qty:{qty}"); send_telegram(f"TGT 2.414 Hit P&L:{pnl*qty:.1f}"); position=None
            time.sleep(60)
        except Exception as e:
            print(e); time.sleep(10)
