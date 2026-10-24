import os
import time
import math
import datetime
import threading
import pandas as pd
import numpy as np
from flask import Flask
from SmartApi import SmartConnect
import pyotp
from scipy.stats import norm

# ==========================================================
# 1. FLASK HEALTH CHECK SERVER (For Render Web Service)
# ==========================================================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Angel One Trading Bot is Running Smoothly!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# ==========================================================
# 2. CREDENTIALS (Fetch from Render Environment Variables)
# ==========================================================
API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_KEY = os.getenv("ANGEL_TOTP_KEY")

smart_api = None

def init_angel_one():
    global smart_api
    try:
        smart_api = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_KEY).now()
        data = smart_api.generateSession(CLIENT_CODE, PASSWORD, totp)
        if data['status']:
            print("[SUCCESS] Angel One Session Generated Successfully!")
        else:
            print(f"[ERROR] Session Generation Failed: {data['message']}")
    except Exception as e:
        print(f"[EXCEPTION] Angel One Connection Error: {e}")

# ==========================================================
# 3. STRATEGY LOGIC & DELTA CALCULATIONS
# ==========================================================
RISK_FREE_RATE = 0.07
IV_ESTIMATE = 0.13
sl_state = "INITIAL"

def calculate_delta(spot_price, strike_price, time_to_expiry, iv=IV_ESTIMATE, option_type='CE'):
    if time_to_expiry <= 0:
        return 0.0
    t = max(time_to_expiry, 1) / 365.0
    d1 = (math.log(spot_price / strike_price) + (RISK_FREE_RATE + 0.5 * iv**2) * t) / (iv * math.sqrt(t))
    if option_type == 'CE':
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1.0

def calculate_fibo_levels(high_price, low_price):
    diff = high_price - low_price
    return {
        'SL_0.382': low_price + (0.382 * diff),
        'Entry_0.5': low_price + (0.500 * diff),
        'Level_1.0': low_price + (1.000 * diff),
        'Level_1.618': low_price + (1.618 * diff),
        'Level_2.414': low_price + (2.414 * diff),
        'Level_3.414': low_price + (3.414 * diff)
    }

def is_red_bar_eliminated(df):
    """ Confirmation: Red Bar's High broken by current Green Candle """
    if len(df) < 2:
        return False
    prev_candle = df.iloc[-2]
    curr_candle = df.iloc[-1]
    
    is_prev_red = prev_candle['close'] < prev_candle['open']
    is_eliminated = (curr_candle['close'] > prev_candle['high']) and (curr_candle['close'] > curr_candle['open'])
    
    return is_prev_red and is_eliminated

def manage_trailing_sl(current_price, df_candles, fibo, current_sl):
    global sl_state
    confirmation = is_red_bar_eliminated(df_candles)
    
    if current_price >= fibo['Level_1.0'] and sl_state == "INITIAL" and confirmation:
        sl_state = "COST"
        print(f"[TRAILING SL] Moved to Cost (0.5 Level): {fibo['Entry_0.5']}")
        return fibo['Entry_0.5']

    elif current_price >= fibo['Level_1.618'] and sl_state == "COST" and confirmation:
        sl_state = "1.0"
        print(f"[TRAILING SL] Moved to Level 1.0: {fibo['Level_1.0']}")
        return fibo['Level_1.0']

    elif current_price >= fibo['Level_2.414'] and sl_state == "1.0" and confirmation:
        sl_state = "1.618"
        print(f"[TRAILING SL] Moved to Level 1.618: {fibo['Level_1.618']}")
        return fibo['Level_1.618']

    elif current_price >= fibo['Level_3.414'] and sl_state == "1.618" and confirmation:
        sl_state = "2.414"
        print(f"[TRAILING SL] Moved to Level 2.414: {fibo['Level_2.414']}")
        return fibo['Level_2.414']

    return current_sl

# ==========================================================
# 4. MAIN TRADING BOT LOOP
# ==========================================================
def bot_loop():
    init_angel_one()
    
    while True:
        try:
            now = datetime.datetime.now().time()
            
            # Market Time Check (09:15 to 15:30)
            if datetime.time(9, 15) <= now <= datetime.time(15, 30):
                # NOTE: इथे तुम्ही तुमचे Angel One वरून Live Spot High/Low डेटा आणून Fibo कॅल्क्युलेट करू शकता
                pass
            
            time.sleep(10) # Run cycle every 10 seconds
        except Exception as e:
            print(f"[BOT ERROR] Loop exception: {e}")
            time.sleep(5)

# ==========================================================
# 5. ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    # Start Trading Bot in Background Thread
    bot_thread = threading.Thread(target=bot_loop)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Start Flask Web Server
    run_flask()