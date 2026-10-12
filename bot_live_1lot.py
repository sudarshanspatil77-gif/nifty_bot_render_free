
"""
W PATTERN OTM -> ITM STRATEGY
1MIN TF | Recent High/Low Fibonacci | 20 EMA Cross
Intrinsic Value Concept | Entry 0.5 | SL 0.35 Trailing | Target 2.414
"""
import os, time, math, random
from datetime import datetime
import pytz

SHARED_LOGS = None
SHARED_PNL = None

# --- Angel One Login (ENV) ---
def angel_login():
    try:
        from SmartApi import SmartConnect
        import pyotp
        api_key = os.getenv('ANGEL_API_KEY')
        client_id = os.getenv('ANGEL_CLIENT_ID')
        password = os.getenv('ANGEL_PASSWORD')
        totp_secret = os.getenv('ANGEL_TOTP_SECRET')
        if not api_key: return None
        totp = pyotp.TOTP(totp_secret).now()
        smart = SmartConnect(api_key)
        data = smart.generateSession(client_id, password, totp)
        return smart
    except Exception as e:
        print(f"Angel Login Failed: {e}")
        return None

def send_telegram(msg):
    try:
        import requests
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id: return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

def ema(prices, period=20):
    if len(prices) < period: return None
    k = 2/(period+1)
    ema_val = sum(prices[:period])/period
    for p in prices[period:]:
        ema_val = p*k + ema_val*(1-k)
    return ema_val

def get_fib_levels(high, low):
    diff = high - low
    return {
        "0": low,
        "0.35": low + diff*0.35,
        "0.5": low + diff*0.5,
        "0.618": low + diff*0.618,
        "1": high,
        "2.414": low + diff*2.414
    }

def intrinsic_value(spot, strike, option_type="CE"):
    # Intrinsic = max(0, Spot - Strike) for CE, max(0, Strike-Spot) for PE
    if option_type == "CE":
        return max(0, spot - strike)
    else:
        return max(0, strike - spot)

def log_trade(signal_id, entry, sl, target, pnl, extra=""):
    ist = pytz.timezone('Asia/Kolkata')
    ts = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    t_only = datetime.now(ist).strftime("%H:%M")
    line = f"{ts},{signal_id},W-OTM-ITM,{entry},{sl},{target},{pnl},{extra}"
    print(line)
    if SHARED_LOGS is not None:
        SHARED_LOGS.append(line)
    if SHARED_PNL is not None:
        SHARED_PNL["total_signals"] = len(SHARED_LOGS)
        SHARED_PNL["total_pnl"] += pnl
        SHARED_PNL["pnl_history"].append(SHARED_PNL["total_pnl"])
        SHARED_PNL["time_labels"].append(t_only)

def main():
    ist = pytz.timezone('Asia/Kolkata')
    day = datetime.now(ist).strftime("%A").upper()
    send_telegram(f"🚀 W-Pattern Bot Starting {day}\n1MIN TF | 20EMA x FIB\nEntry: 0.5 | SL:0.35 Trail | Tgt:2.414\nIntrinsic Value ON ✅")

    # For PAPER testing without Angel - use dummy candles
    # Replace this with real Angel historic API: smart.getCandleData(...)
    prices = [24800 + random.randint(-50,50) for _ in range(50)]
    
    last_high = max(prices[-20:])
    last_low = min(prices[-20:])
    trailing_sl_active = False
    position = None # {"entry_price": , "sl": , "target": , "type": }

    while True:
        try:
            # 1. Get latest 1min candle (here simulated, replace with Angel API)
            spot = 24800 + random.randint(-100,100)
            prices.append(spot)
            if len(prices) > 100: prices.pop(0)

            e20 = ema(prices, 20)
            fib = get_fib_levels(last_high, last_low)
            
            # Update recent high/low every 15 candles
            if len(prices) % 15 == 0:
                last_high = max(prices[-20:])
                last_low = min(prices[-20:])
                fib = get_fib_levels(last_high, last_low)

            # 2. W Pattern detection: double bottom near fib 0.35-0.5 + 20 EMA cross
            w_pattern = False
            if e20 and spot > e20 and last_low <= fib["0.5"] <= last_high:
                # Simplified W: price bounced from 0.35 and now crossing 0.5
                if prices[-2] < fib["0.5"] and spot >= fib["0.5"]:
                    w_pattern = True

            # 3. Intrinsic Value Check for OTM->ITM
            # Example: Nifty 24800, OTM 25000 CE (intrinsic 0). If spot goes 25050, intrinsic 50 -> OTM becomes ITM
            otm_strike = round(spot/50)*50 + 200  # 200 points OTM
            intrinsic = intrinsic_value(spot, otm_strike, "CE")
            intrinsic_becoming = spot >= otm_strike - 50  # Near ITM

            # 4. ENTRY Logic
            if w_pattern and intrinsic_becoming and position is None:
                entry = spot
                sl = fib["0.35"]
                target = fib["2.414"]
                log_trade(f"W_BUY_CE_{otm_strike}", entry, sl, target, 0, f"EMA:{e20:.1f} FIB0.5:{fib['0.5']:.1f} Intr:{intrinsic}")
                send_telegram(f"📈 W ENTRY\nStrike:{otm_strike}CE OTM->ITM\nSpot:{spot} EMA20:{e20:.1f}\nFIB 0.5 cross {fib['0.5']:.1f}\nSL 0.35:{sl:.1f} Trail ON\nTGT 2.414:{target:.1f}\nIntrinsic:{intrinsic}")
                position = {"entry": entry, "sl": sl, "target": target, "strike": otm_strike, "high": entry}

            # 5. SL Trailing 0.35 + Target 2.414 Management
            if position:
                # Trailing SL: if price moves up, SL moves to 0.35 of new high-low
                if spot > position["high"]:
                    position["high"] = spot
                    new_fib = get_fib_levels(position["high"], last_low)
                    position["sl"] = max(position["sl"], new_fib["0.35"])  # Trail up only

                if spot <= position["sl"]:
                    pnl = position["sl"] - position["entry"]
                    log_trade(f"SL_HIT_{position['strike']}", position["entry"], position["sl"], position["target"], pnl, "Trailing 0.35")
                    send_telegram(f"🔴 SL Hit Trail 0.35\nP&L: {pnl:.1f}")
                    position = None
                elif spot >= position["target"]:
                    pnl = position["target"] - position["entry"]
                    log_trade(f"TARGET_2.414_{position['strike']}", position["entry"], position["sl"], position["target"], pnl, "FIB 2.414")
                    send_telegram(f"🟢 TARGET 2.414 Hit!\nP&L: {pnl:.1f}")
                    position = None

            time.sleep(60)  # 1 MIN TF

        except Exception as e:
            print(f"Loop Error: {e}")
            import traceback; traceback.print_exc()
            time.sleep(10)

if __name__ == "__main__":
    main()
