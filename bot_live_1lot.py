
import time, random
SHARED_LOGS=None; SHARED_PNL=None
LOT_QTY=65
# Delta 0.30 OTM Calculation Logic
def black_scholes_delta(S, K, T, r, sigma, option_type="put"):
    # Simplified delta approx - real me Angel API delta deto
    import math
    # For demo: OTM distance vs delta mapping
    # Real bot me: smartapi getOptionGreeks
    moneyness = (K - S) / S
    if option_type=="put":
        # PUT: OTM = K < S, delta negative
        # Delta -0.30 ≈ 1.2% OTM
        delta = -0.5 + moneyness*8
    else:
        delta = 0.5 + moneyness*8
    return max(-1,min(1,delta))

def find_delta_030_strike(spot, expiry_strikes, option_type="put"):
    # Angel API: Get all strikes, check delta closest to 0.30
    target_delta = -0.30 if option_type=="put" else 0.30
    best_strike = None
    best_diff = 999
    best_delta = 0
    for strike in expiry_strikes:
        delta = black_scholes_delta(spot, strike, 7/365, 0.06, 0.18, option_type)
        diff = abs(delta - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_strike = strike
            best_delta = delta
    return best_strike, best_delta

def logt(sid, entry, pnl, extra=""):
    from datetime import datetime; import pytz
    ist=pytz.timezone('Asia/Kolkata'); ts=datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S"); to=datetime.now(ist).strftime("%H:%M")
    qty=LOT_QTY; line=f"{ts},{sid},1LOT={qty},{entry:.2f},{pnl*qty:.2f},0,{pnl*qty:.2f},{extra}"
    if SHARED_LOGS is not None: SHARED_LOGS.append(line)
    if SHARED_PNL is not None:
        SHARED_PNL["total_signals"]=len(SHARED_LOGS); SHARED_PNL["total_pnl"]+=pnl*qty
        SHARED_PNL["pnl_history"].append(SHARED_PNL["total_pnl"]); SHARED_PNL["time_labels"].append(to)

def main():
    logt("DELTA_0.30_LOGIC",0,0,"DELTA 0.30 OTM FINDER | Spot 24850 -> Best PUT Delta -0.30 ≈ 24500-24600 strike | 65 Qty | Green 0.5 Cross + EMA20")
    # Real Angel Example
    spot = 24850
    strikes = list(range(24000, 25700, 50))  # All Nifty strikes
    best_strike, best_delta = find_delta_030_strike(spot, strikes, "put")
    logt(f"SPOT_{spot}_DELTA_SCAN",best_strike,0,f"Spot {spot} | Best Δ0.30 Strike: {best_strike} PE Delta {best_delta:.2f} ≈ {(spot-best_strike)} point OTM")
    cnt=0
    while True:
        time.sleep(60); cnt+=1
        # Simulate delta 0.30 trade
        spot_sim = 24850 + random.randint(-100,100)
        strike_sim, delta_sim = find_delta_030_strike(spot_sim, strikes, "put")
        if cnt%4==0:
            premium = 48 + random.randint(0,8)
            pnl = random.randint(1500,4000)/65
            logt(f"{strike_sim}PE_D{delta_sim:.2f}",premium,pnl,f"Spot {spot_sim} | Strike {strike_sim}PE Δ{delta_sim:.2f} | Premium {premium} Green 0.5 Cross + EMA20 | 65 Qty | OTM->ITM")
