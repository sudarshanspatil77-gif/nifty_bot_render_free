"""
NIFTY BOT PRO v5 PAPER — Windows 10 / Angel One SmartAPI
--------------------------------------------------------
PAPER MODE ONLY. This file has NO broker order-placement function.

Features:
- Angel One NIFTY spot candles (5-minute)
- Completed-candle-only signals
- EMA20 + Fibonacci 0.32–0.50 + breakout/retest + opposite-bar elimination
- Telegram YES/NO approval with chat + user authorization
- Duplicate-signal protection across restarts
- Paper-only risk sizing (0.5% default), stop/target monitoring
- Daily loss limit and maximum approved paper trades per day
- CSV audit log

Important:
Paper positions use NIFTY SPOT points as a simulation proxy, NOT option-contract P&L.
This does not select CE/PE contracts and cannot place live orders.
Never put credentials in this file. Keep config.json private.
"""

import csv
import json
import math
import os
import sys
import time
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

APP_NAME = "NIFTY BOT PRO v5 PAPER"
CONFIG_FILE = "config.json"
SIGNALS_FILE = "paper_signals_v5.csv"
TRADES_FILE = "paper_trades_v5.csv"
STATE_FILE = "paper_state_v5.json"

IST = ZoneInfo("Asia/Kolkata")
POLL_SECONDS = 30
CANDLE_MINUTES = 5
PAPER_MODE = True  # Intentionally locked. No live order API exists in this program.

NIFTY_EXCHANGE = "NSE"
NIFTY_TOKEN = "99926000"  # Confirm with current Angel One scrip master if rejected.
NIFTY_SYMBOL = "NIFTY"

DEFAULTS = {
    "paper_capital": 100000.0,
    "risk_percent": 0.5,
    "max_daily_loss_percent": 1.5,
    "max_trades_per_day": 5,
    "reward_risk": 2.0,
    "poll_seconds": POLL_SECONDS,
    "telegram_allowed_user_id": "",
    "telegram_chat_id": "",
}


def get_key(cfg, *names, default=None):
    lowered = {str(k).lower(): v for k, v in cfg.items()}
    for name in names:
        if name in cfg:
            return cfg[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return default


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        raise RuntimeError(f"Cannot read {CONFIG_FILE}: {exc}") from exc

    cfg = dict(DEFAULTS)
    cfg.update(raw)

    def first(*names, default=None):
        return get_key(raw, *names, default=default)

    cfg["api_key"] = first("angel_api_key", "api_key")
    cfg["client_id"] = first("angel_client_id", "client_id")
    cfg["password"] = first("angel_password", "password")
    cfg["totp_secret"] = first("angel_totp_secret", "totp_secret")
    cfg["telegram_token"] = first("telegram_bot_token", "telegram_token", default="")
    cfg["telegram_chat_id"] = str(first("telegram_chat_id", "chat_id", default="") or "")
    cfg["telegram_allowed_user_id"] = str(
        first("telegram_allowed_user_id", "telegram_user_id", "allowed_telegram_user_id", default="") or ""
    )
    cfg["paper_capital"] = float(first("paper_capital", default=cfg["paper_capital"]))
    cfg["risk_percent"] = float(first("risk_percent", default=0.5))
    cfg["max_daily_loss_percent"] = float(
        first("max_daily_loss_percent", default=cfg["max_daily_loss_percent"])
    )
    cfg["max_trades_per_day"] = int(first("max_trades_per_day", default=cfg["max_trades_per_day"]))
    cfg["reward_risk"] = float(first("reward_risk", default=cfg["reward_risk"]))
    cfg["poll_seconds"] = max(10, int(first("poll_seconds", default=POLL_SECONDS)))

    missing = [k for k in ("api_key", "client_id", "password", "totp_secret") if not cfg.get(k)]
    if missing:
        raise RuntimeError("Missing Angel One config values: " + ", ".join(missing))
    if not cfg["telegram_token"] or not cfg["telegram_chat_id"] or not cfg["telegram_allowed_user_id"]:
        raise RuntimeError(
            "Telegram security settings required: telegram_bot_token, telegram_chat_id, "
            "telegram_allowed_user_id. Use your numeric Telegram user ID."
        )
    if cfg["paper_capital"] <= 0 or not (0 < cfg["risk_percent"] <= 1):
        raise RuntimeError("paper_capital must be positive and risk_percent must be > 0 and <= 1.")
    if cfg["max_daily_loss_percent"] <= 0 or cfg["max_trades_per_day"] < 1:
        raise RuntimeError("Daily loss limit and max trades must be positive.")
    return cfg


def now_ist():
    return datetime.now(IST)


def init_csv_files():
    if not os.path.exists(SIGNALS_FILE):
        with open(SIGNALS_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "created_at", "signal_id", "candle_time", "direction", "spot", "ema20",
                "swing_low", "swing_high", "fib_032", "fib_050", "stop", "target",
                "risk_budget", "paper_units", "status", "reason"
            ])
    if not os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "date", "signal_id", "direction", "entry", "stop", "target",
                "paper_units", "risk_budget", "exit_time", "exit_price", "pnl_points_x_units", "status"
            ])


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"date": now_ist().date().isoformat(), "daily_pnl": 0.0,
                "trades_today": 0, "pending": {}, "open_trade": None,
                "last_processed_candle": ""}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        # Preserve the corrupt file for diagnosis; do not silently reset risk state.
        raise RuntimeError(f"{STATE_FILE} is unreadable. Back it up and inspect it before restarting.")
    state.setdefault("pending", {})
    state.setdefault("open_trade", None)
    state.setdefault("daily_pnl", 0.0)
    state.setdefault("trades_today", 0)
    state.setdefault("last_processed_candle", "")
    if state.get("date") != now_ist().date().isoformat():
        # Do not carry a stale open trade into a new day without explicit handling.
        if state.get("open_trade"):
            raise RuntimeError("A paper trade is still open from a previous day. Review state/trades before restart.")
        state = {"date": now_ist().date().isoformat(), "daily_pnl": 0.0,
                 "trades_today": 0, "pending": {}, "open_trade": None,
                 "last_processed_candle": ""}
    return state


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def login_smartapi(cfg):
    try:
        from SmartApi import SmartConnect
        import pyotp
    except ImportError as exc:
        raise RuntimeError("Install dependencies: py -m pip install smartapi-python pyotp requests") from exc
    smart = SmartConnect(api_key=cfg["api_key"])
    totp = pyotp.TOTP(cfg["totp_secret"]).now()
    response = smart.generateSession(cfg["client_id"], cfg["password"], totp)
    if not response or not response.get("status"):
        raise RuntimeError(f"Angel One login failed: {response}")
    print("Angel One login: OK")
    return smart


def parse_candle_time(value):
    if isinstance(value, datetime):
        dt = value
    else:
        text_value = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text_value)
        except ValueError:
            # SmartAPI usually returns ISO timestamps; this is a fallback for common formats.
            dt = datetime.strptime(text_value, "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def get_candles(smart, lookback_minutes=900):
    end = now_ist()
    start = end - timedelta(minutes=lookback_minutes)
    params = {
        "exchange": NIFTY_EXCHANGE,
        "symboltoken": NIFTY_TOKEN,
        "interval": "FIVE_MINUTE",
        "fromdate": start.strftime("%Y-%m-%d %H:%M"),
        "todate": end.strftime("%Y-%m-%d %H:%M"),
    }
    response = smart.getCandleData(params)
    if not response or not response.get("status") or not response.get("data"):
        raise RuntimeError(f"Candle data unavailable: {response}")
    candles = []
    for row in response["data"]:
        if len(row) < 6:
            continue
        dt = parse_candle_time(row[0])
        candles.append({
            "time": dt.isoformat(timespec="seconds"),
            "dt": dt,
            "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]),
            "volume": float(row[5]),
        })
    candles.sort(key=lambda x: x["dt"])
    # Candle timestamps represent candle OPEN time. Exclude the currently forming 5-minute candle.
    current_bucket_minute = (end.minute // CANDLE_MINUTES) * CANDLE_MINUTES
    current_bucket = end.replace(minute=current_bucket_minute, second=0, microsecond=0)
    completed = [c for c in candles if c["dt"] < current_bucket]
    # De-duplicate any repeated timestamps from the API.
    unique = {}
    for candle in completed:
        unique[candle["time"]] = candle
    candles = sorted(unique.values(), key=lambda x: x["dt"])
    if len(candles) < 30:
        raise RuntimeError(f"Only {len(candles)} completed candles available; no signal generated.")
    return candles


def ema(values, period=20):
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result
    return result


def candle_is_green(c):
    return c["close"] > c["open"]


def candle_is_red(c):
    return c["close"] < c["open"]


def make_signal(candles, cfg):
    """
    Uses only completed candles.
    CALL bias: EMA up, price retraced into Fib zone, recent retest, then green candle
    closes above the previous red candle's high (red-bar elimination).
    PUT bias is the mirrored case: EMA down, Fib-zone retest, then red close below
    the previous green candle's low.
    """
    if len(candles) < 30:
        return None
    latest = candles[-1]
    prior = candles[-2]
    closes = [c["close"] for c in candles]
    ema20 = ema(closes, 20)
    if ema20 is None:
        return None

    # Use prior completed candles for the swing, excluding the signal candle.
    swing_window = candles[-21:-1]
    swing_low = min(c["low"] for c in swing_window)
    swing_high = max(c["high"] for c in swing_window)
    span = swing_high - swing_low
    if span <= 0:
        return None

    fib032 = swing_high - span * 0.32
    fib050 = swing_high - span * 0.50
    fib_low, fib_high = min(fib032, fib050), max(fib032, fib050)

    # A retest must have occurred within the last three completed candles.
    retest_window = candles[-4:-1]
    retested_fib = any(c["low"] <= fib_high and c["high"] >= fib_low for c in retest_window)
    retested_ema = any(c["low"] <= ema20 * 1.002 and c["high"] >= ema20 * 0.998 for c in retest_window)
    retest_ok = retested_fib or retested_ema

    # Search backwards for the most recent opposite-colour bar in the last 3 candles.
    recent_opposite_red = next((c for c in reversed(candles[-4:-1]) if candle_is_red(c)), None)
    recent_opposite_green = next((c for c in reversed(candles[-4:-1]) if candle_is_green(c)), None)

    # Basic trend filter uses current EMA and the EMA from 3 completed bars earlier.
    ema_prev = ema(closes[:-3], 20)
    ema_rising = ema_prev is not None and ema20 > ema_prev
    ema_falling = ema_prev is not None and ema20 < ema_prev

    call_break = recent_opposite_red is not None and candle_is_green(latest) and latest["close"] > recent_opposite_red["high"]
    put_break = recent_opposite_green is not None and candle_is_red(latest) and latest["close"] < recent_opposite_green["low"]

    call_retest = retest_ok and latest["close"] > ema20 and latest["low"] <= max(fib_high, ema20 * 1.002)
    put_retest = retest_ok and latest["close"] < ema20 and latest["high"] >= min(fib_low, ema20 * 0.998)

    if ema_rising and call_retest and call_break:
        direction = "CALL_BIAS"
        stop = min(latest["low"], prior["low"])
        if stop >= latest["close"]:
            return None
        reason = "EMA20 rising; Fib/EMA retest; green candle eliminated recent red-bar high."
    elif ema_falling and put_retest and put_break:
        direction = "PUT_BIAS"
        stop = max(latest["high"], prior["high"])
        if stop <= latest["close"]:
            return None
        reason = "EMA20 falling; Fib/EMA retest; red candle broke recent green-bar low."
    else:
        return None

    entry = latest["close"]
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return None
    risk_budget = cfg["paper_capital"] * cfg["risk_percent"] / 100.0
    units = max(1, math.floor(risk_budget / stop_distance))
    reward_risk = cfg["reward_risk"]
    target = entry + stop_distance * reward_risk if direction == "CALL_BIAS" else entry - stop_distance * reward_risk

    candle_key = latest["time"]
    stable = f"{candle_key}|{direction}"
    signal_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:14].upper()
    return {
        "id": signal_id,
        "candle_time": candle_key,
        "direction": direction,
        "spot": round(entry, 2),
        "ema20": round(ema20, 2),
        "swing_low": round(swing_low, 2),
        "swing_high": round(swing_high, 2),
        "fib_032": round(fib032, 2),
        "fib_050": round(fib050, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "risk_budget": round(risk_budget, 2),
        "paper_units": units,
        "reason": reason,
    }


def signal_already_logged(signal_id):
    if not os.path.exists(SIGNALS_FILE):
        return False
    with open(SIGNALS_FILE, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("signal_id") == signal_id:
                return True
    return False


def log_signal(signal, status):
    with open(SIGNALS_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            now_ist().isoformat(timespec="seconds"), signal["id"], signal["candle_time"],
            signal["direction"], signal["spot"], signal["ema20"], signal["swing_low"],
            signal["swing_high"], signal["fib_032"], signal["fib_050"], signal["stop"],
            signal["target"], signal["risk_budget"], signal["paper_units"], status, signal["reason"]
        ])


def update_signal_status(signal_id, status):
    if not os.path.exists(SIGNALS_FILE):
        return
    with open(SIGNALS_FILE, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    for row in reversed(rows[1:]):
        if len(row) > 1 and row[1] == signal_id:
            row[14] = status
            break
    with open(SIGNALS_FILE, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def telegram_api(cfg, method, payload=None, timeout=10):
    url = f"https://api.telegram.org/bot{cfg['telegram_token']}/{method}"
    if method == "getUpdates":
        response = requests.get(url, params=payload or {}, timeout=timeout)
    else:
        response = requests.post(url, json=payload or {}, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body}")
    return body


def telegram_send(cfg, signal, state):
    text = (
        f"{APP_NAME} — PAPER SIGNAL\n"
        f"ID: {signal['id']}\n"
        f"Bias: {signal['direction']} (spot-based; not a CE/PE contract)\n"
        f"NIFTY spot entry: {signal['spot']}\n"
        f"EMA20: {signal['ema20']}\n"
        f"Fib 0.32 / 0.50: {signal['fib_032']} / {signal['fib_050']}\n"
        f"Paper SL: {signal['stop']} | Paper target: {signal['target']}\n"
        f"Risk budget: ₹{signal['risk_budget']} | paper units: {signal['paper_units']}\n"
        f"Reason: {signal['reason']}\n\n"
        "PAPER ONLY. YES opens a simulated NIFTY-spot paper position. No broker order is sent."
    )
    keyboard = {"inline_keyboard": [[
        {"text": "YES — PAPER ONLY", "callback_data": f"YES_{signal['id']}"},
        {"text": "NO — SKIP", "callback_data": f"NO_{signal['id']}"},
    ]]}
    telegram_api(cfg, "sendMessage", {
        "chat_id": cfg["telegram_chat_id"], "text": text, "reply_markup": keyboard
    })
    state["pending"][signal["id"]] = signal
    save_state(state)


def telegram_send_text(cfg, text):
    telegram_api(cfg, "sendMessage", {"chat_id": cfg["telegram_chat_id"], "text": text})


def daily_limits_allow_new_trade(cfg, state):
    max_loss = cfg["paper_capital"] * cfg["max_daily_loss_percent"] / 100.0
    if state["daily_pnl"] <= -max_loss:
        return False, f"Daily paper loss limit reached (₹{max_loss:.2f} risk-limit equivalent)."
    if state["trades_today"] >= cfg["max_trades_per_day"]:
        return False, f"Maximum paper trades today reached: {cfg['max_trades_per_day']}."
    if state.get("open_trade"):
        return False, "A paper trade is already open; one-at-a-time rule is active."
    return True, ""


def handle_telegram_updates(cfg, state, offset):
    body = telegram_api(cfg, "getUpdates", {"timeout": 1, "offset": offset}, timeout=5)
    for update in body.get("result", []):
        offset = max(offset, int(update["update_id"]) + 1)
        callback = update.get("callback_query")
        if not callback:
            continue

        callback_id = callback.get("id", "")
        data = str(callback.get("data", ""))
        message = callback.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        from_id = str((callback.get("from") or {}).get("id", ""))

        # Require BOTH the expected chat and the specific allowed Telegram user.
        authorized = (
            chat_id == cfg["telegram_chat_id"]
            and from_id == cfg["telegram_allowed_user_id"]
        )
        if not authorized:
            try:
                telegram_api(cfg, "answerCallbackQuery", {
                    "callback_query_id": callback_id,
                    "text": "Unauthorized user/chat. No action taken.",
                    "show_alert": True,
                })
            except Exception:
                pass
            print(f"Rejected unauthorized Telegram callback: chat={chat_id}, user={from_id}")
            continue

        try:
            telegram_api(cfg, "answerCallbackQuery", {
                "callback_query_id": callback_id, "text": "Checking paper-trade request..."
            })
        except Exception:
            pass

        if not (data.startswith("YES_") or data.startswith("NO_")):
            continue
        signal_id = data.split("_", 1)[1]
        signal = state["pending"].get(signal_id)
        if not signal:
            telegram_send_text(cfg, f"Signal {signal_id} is expired/already handled. No action taken.")
            continue

        if data.startswith("NO_"):
            state["pending"].pop(signal_id, None)
            update_signal_status(signal_id, "SKIPPED")
            save_state(state)
            telegram_send_text(cfg, f"{signal_id}: skipped. No order or paper position opened.")
            continue

        allowed, reason = daily_limits_allow_new_trade(cfg, state)
        if not allowed:
            state["pending"].pop(signal_id, None)
            update_signal_status(signal_id, "BLOCKED_LIMIT")
            save_state(state)
            telegram_send_text(cfg, f"{signal_id}: NOT opened. {reason}")
            continue

        # Simulated position only; this code intentionally contains no broker order placement.
        state["open_trade"] = {
            "signal_id": signal_id,
            "direction": signal["direction"],
            "entry": float(signal["spot"]),
            "stop": float(signal["stop"]),
            "target": float(signal["target"]),
            "paper_units": int(signal["paper_units"]),
            "risk_budget": float(signal["risk_budget"]),
            "opened_at": now_ist().isoformat(timespec="seconds"),
        }
        state["trades_today"] += 1
        state["pending"].pop(signal_id, None)
        update_signal_status(signal_id, "PAPER_OPEN")
        save_state(state)
        telegram_send_text(
            cfg,
            f"{signal_id}: PAPER POSITION OPENED.\n"
            f"{signal['direction']} at {signal['spot']}; SL {signal['stop']}; "
            f"target {signal['target']}; units {signal['paper_units']}.\n"
            "This is NIFTY spot-point simulation only. No broker order was placed."
        )
    save_state(state)
    return offset


def monitor_paper_trade(cfg, state, candles):
    trade = state.get("open_trade")
    if not trade or not candles:
        return
    # Use only completed candles, as returned by get_candles().
    for candle in candles[-3:]:
        if candle["dt"].isoformat(timespec="seconds") <= trade.get("last_checked_candle", ""):
            continue
        direction = trade["direction"]
        exit_price = None
        exit_reason = ""
        if direction == "CALL_BIAS":
            # Conservative assumption: if both stop and target occur in one candle, count stop first.
            if candle["low"] <= trade["stop"]:
                exit_price, exit_reason = trade["stop"], "STOP_LOSS"
            elif candle["high"] >= trade["target"]:
                exit_price, exit_reason = trade["target"], "TARGET"
        else:
            if candle["high"] >= trade["stop"]:
                exit_price, exit_reason = trade["stop"], "STOP_LOSS"
            elif candle["low"] <= trade["target"]:
                exit_price, exit_reason = trade["target"], "TARGET"

        trade["last_checked_candle"] = candle["dt"].isoformat(timespec="seconds")
        if exit_price is not None:
            points = (exit_price - trade["entry"]) if direction == "CALL_BIAS" else (trade["entry"] - exit_price)
            pnl = round(points * trade["paper_units"], 2)
            state["daily_pnl"] = round(state["daily_pnl"] + pnl, 2)
            with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    now_ist().date().isoformat(), trade["signal_id"], direction, trade["entry"],
                    trade["stop"], trade["target"], trade["paper_units"], trade["risk_budget"],
                    now_ist().isoformat(timespec="seconds"), exit_price, pnl, exit_reason
                ])
            state["open_trade"] = None
            save_state(state)
            msg = (
                f"PAPER EXIT — {exit_reason}\nSignal: {trade['signal_id']}\n"
                f"Exit spot: {exit_price}\nSimulated P&L: {pnl:.2f} spot-points × units\n"
                f"Daily simulated P&L: {state['daily_pnl']:.2f}\n"
                "This is not actual option P&L."
            )
            telegram_send_text(cfg, msg)
            print(msg)
            return
    save_state(state)


def main():
    print(f"--- {APP_NAME} ---")
    print("Safety lock: PAPER MODE ONLY — this program cannot place broker orders.")
    cfg = load_config()
    init_csv_files()
    state = load_state()
    smart = login_smartapi(cfg)
    offset = 0
    print("Angel One login OK. Telegram callbacks restricted to configured chat + user ID.")
    print(f"Risk/trade: {cfg['risk_percent']}% | Daily loss limit: {cfg['max_daily_loss_percent']}% "
          f"| Max trades/day: {cfg['max_trades_per_day']}")
    print("Press Ctrl+C to stop.")

    while True:
        try:
            now = now_ist()
            # Reset daily counters only when there is no open position.
            today = now.date().isoformat()
            if state.get("date") != today:
                if state.get("open_trade"):
                    raise RuntimeError("Open paper trade crossed date boundary; review manually.")
                state.update({"date": today, "daily_pnl": 0.0, "trades_today": 0,
                              "pending": {}, "last_processed_candle": ""})
                save_state(state)

            offset = handle_telegram_updates(cfg, state, offset)

            # NSE cash-session guard (signals only); monitor pending paper trades during the day.
            in_signal_window = (
                now.weekday() < 5
                and (now.hour > 9 or (now.hour == 9 and now.minute >= 20))
                and (now.hour < 15 or (now.hour == 15 and now.minute < 10))
            )
            if not in_signal_window:
                time.sleep(cfg["poll_seconds"])
                continue

            candles = get_candles(smart)
            monitor_paper_trade(cfg, state, candles)

            latest_completed_time = candles[-1]["time"]
            if latest_completed_time == state.get("last_processed_candle"):
                time.sleep(cfg["poll_seconds"])
                continue

            # Mark the candle processed exactly once, even if it produces no signal.
            state["last_processed_candle"] = latest_completed_time
            save_state(state)

            allowed, limit_reason = daily_limits_allow_new_trade(cfg, state)
            if not allowed:
                print(f"[{now:%H:%M:%S}] New signals blocked: {limit_reason}")
                time.sleep(cfg["poll_seconds"])
                continue

            signal = make_signal(candles, cfg)
            if signal and not signal_already_logged(signal["id"]):
                log_signal(signal, "AWAITING_CONFIRMATION")
                print(f"PAPER SIGNAL: {signal}")
                telegram_send(cfg, signal, state)
            else:
                print(f"[{now:%H:%M:%S}] No valid setup on completed candle.")

        except KeyboardInterrupt:
            print("Stopped by user. No live orders were placed.")
            break
        except Exception as exc:
            print(f"[{now_ist():%H:%M:%S}] ERROR: {exc}. No live order was placed.")
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL: {exc}")
        input("Press Enter to close...")
        sys.exit(1)
