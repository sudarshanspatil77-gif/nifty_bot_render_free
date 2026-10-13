
"""
FINAL LOCKED: Price Green Line 0.5 Cross + Above 20 EMA = Entry
SL 0.36 with Trailing | Target 2.414
Photo: NIFTY PUT - Green line 50.10 (0.5) is entry
"""
import os, time, random
from datetime import datetime
import pytz
SHARED_LOGS=None; SHARED_PNL=None

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
    d=high-low
    if d==0: d=1
    return {
        "low": low, "high": high,
        "0": low,
        "0.36": low + d*0.36,  # SL - user said 0.36
        "0.5": low + d*0.5,    # GREEN LINE ENTRY
        "0.618": low + d*0.618,
        "1": high,
        "2.414": low + d*2.414  # TARGET
    }

def logt(sid, entry, sl, tgt, pnl, extra=""):
    ist=pytz.timezone('Asia/Kolkata')
    ts=datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    to=datetime.now(ist).strftime("%H:%M")
    line=f"{ts},{sid},GREEN-0.5-EMA20,{entry:.2f},{sl:.2f},{tgt:.2f},{pnl:.2f},{extra}"
    if SHARED_LOGS is not None: SHARED_LOGS.append(line)
    if SHARED_PNL is not None:
        SHARED_PNL["total_signals"]=len(SHARED_LOGS)
        SHARED_PNL["total_pnl"]+=pnl
        SHARED_PNL["pnl_history"].append(SHARED_PNL["total_pnl"])
        SHARED_PNL["time_labels"].append(to)
    print(line)

def main():
    ist=pytz.timezone('Asia/Kolkata')
    day=datetime.now(ist).strftime("%A").upper()
    send_telegram(f"🚀 FINAL BOT LOCKED {day}\n✅ Entry: Price Green Line 0.5 Cross + Above 20 EMA\n✅ SL: 0.36 Trailing | Target: 2.414\nPhoto Pattern: 50.10 Green Line✅")

    # Photo pattern premium history: 19.80 low -> 50.10 green -> 111 high
    prem_hist=[38,35,32,28,22,19.8,24,31,42,48,50.5,55,62,71,78,85,92,105,111,108]
    low=min(prem_hist[-20:]); high=max(prem_hist[-20:]); fib=fib_levels(low, high)
    position=None

    while True:
        try:
            # Simulate live premium - in real: get Angel PUT OTM LTP
            # When no position, keep near low for W formation
            if position is None:
                premium = 45 + random.randint(-10,15)  # Around entry zone
                if random.random()<0.2: premium = fib["0.5"] + random.randint(0,5)  # Cross green line
            else:
                premium = position["high"] + random.randint(-5,12)
                if random.random()<0.15: premium = fib["2.414"] + random.randint(-5,5)

            prem_hist.append(premium)
            if len(prem_hist)>100: prem_hist.pop(0)
            
            low=min(prem_hist[-30:]); high=max(prem_hist[-30:])
            fib=fib_levels(low, high)
            e20=ema(prem_hist, 20)

            # --- FINAL ENTRY LOGIC ---
            # 1. Price crosses above GREEN LINE 0.5
            # 2. Price above 20 EMA
            green_cross = False
            above_ema = False
            
            if len(prem_hist)>=2:
                prev=prem_hist[-2]; curr=prem_hist[-1]
                # Green line 0.5 cross
                if prev < fib["0.5"] and curr >= fib["0.5"]:
                    green_cross = True

            if e20:
                if premium > e20:
                    above_ema = True

            # ENTRY: Green 0.5 cross + Above 20 EMA
            if green_cross and above_ema and position is None:
                entry=premium
                sl=fib["0.36"]  # SL 0.36
                tgt=fib["2.414"] # Target 2.414
                # Safety for SL
                if entry - sl > entry*0.6: sl=entry*0.65

                logt(f"BUY_GREEN0.5_EMA20",entry,sl,tgt,0,f"Green:{fib['0.5']:.1f} Cross EMA20:{e20:.1f} SL0.36:{sl:.1f} TGT2.414:{tgt:.1f}")
                send_telegram(f"📈 ENTRY LOCKED\n✅ Price {premium:.1f} > Green Line 0.5 ({fib['0.5']:.1f}) CROSS\n✅ Above 20 EMA {e20:.1f}\nSL: 0.36 = {sl:.1f} Trail\nTGT: 2.414 = {tgt:.1f}\nLow:{low:.1f} High:{high:.1f}")
                position={"entry":entry,"sl":sl,"tgt":tgt,"high":entry,"low":low,"sl_base":sl}

            # --- SL 0.36 Trailing + Target 2.414 ---
            if position:
                if premium > position["high"]:
                    position["high"]=premium
                    # Trail SL to 0.36 of new high-low
                    new_fib=fib_levels(position["low"], position["high"])
                    position["sl"]=max(position["sl"], new_fib["0.36"])

                if premium <= position["sl"]:
                    pnl=position["sl"]-position["entry"]
                    logt(f"SL_0.36_TRAIL",position["entry"],position["sl"],position["tgt"],pnl,f"Prem:{premium:.1f} Trail SL Hit")
                    send_telegram(f"🔴 SL 0.36 Trail Hit P&L:{pnl:.1f} Prem:{premium:.1f}")
                    position=None
                elif premium >= position["tgt"]:
                    pnl=position["tgt"]-position["entry"]
                    logt(f"TGT_2.414",position["entry"],position["sl"],position["tgt"],pnl,f"Target Hit Prem:{premium:.1f}")
                    send_telegram(f"🟢 TARGET 2.414 Hit! 🚀\nEntry:{position['entry']:.1f} -> {premium:.1f}\nP&L:{pnl:.1f} ({pnl/position['entry']*100:.1f}%)")
                    position=None

            time.sleep(60)

        except Exception as e:
            print(f"Err {e}"); import traceback; traceback.print_exc(); time.sleep(10)

if __name__=="__main__": main()
