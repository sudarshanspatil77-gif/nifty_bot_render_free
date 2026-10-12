"""NIFTY BOT PRO v3 - SAFE PAPER TRADING EDITION

IMPORTANT:
- PAPER ONLY. This script contains NO Angel One placeOrder call.
- Uses real NIFTY index candles from Angel One SmartAPI when login/API works.
- Simulates entries/exits on NIFTY index points, NOT option premium.
- IV / option-chain values are intentionally disabled (no fabricated/random IV).
- Telegram YES/NO buttons are supported when configured.

Install (Windows 10 CMD):
    py -m pip install smartapi-python pyotp requests
Run from the folder containing this file and config.json:
    py NIFTY_BOT_PRO_v3_PAPER_SAFE.py
"""

import csv
import json
import os
import sys
import time
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List, Tuple

import requests

BOT_NAME = "NIFTY BOT PRO v3 | SAFE PAPER"
CONFIG_FILE = "config.json"
TRADES_FILE = "paper_trades.csv"
STATE_FILE = "paper_state.json"

# Paper strategy defaults. Change in config.json if desired.
DEFAULTS = {
    "angel_api_key": "",
    "angel_client_id": "",
    "angel_password": "",
    "angel_totp_secret": "",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "paper_only": True,
    "exchange": "NSE",
    "symbol": "NIFTY",
    "symbol_token": "99926000",
    "candle_interval": "FIVE_MINUTE",
    "lookback_candles": 20,
    "risk_percent": 0.5,
    "paper_start_balance": 100000,
    "max_daily_loss": 1500,
    "max_daily_profit": 5000,
    "max_trades_per_day": 5,
    "paper_quantity": 1,
    "stop_buffer_points": 5,
    "reward_risk": 2.0,
    "trailing_sl_enabled": True,
    "breakeven_at_r": 1.0,
    "trail_candle_buffer_points": 5,
    "ema_trailing_buffer_points": 5,
    "ema_trailing_period": 20,
    "poll_seconds": 30,
    "market_open": "09:20",
    "last_entry_time": "15:00",
    "square_off_time": "15:15",
    "require_telegram_confirmation": True,
    "signal_expiry_minutes": 5
}


def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, indent=2)
        raise RuntimeError(
            f"{CONFIG_FILE} तयार केला आहे. Angel One आणि Telegram details भरून पुन्हा चालवा."
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    cfg = DEFAULTS.copy()
    cfg.update(raw)
    if cfg.get("paper_only") is not True:
        raise RuntimeError("Safety lock: paper_only must be true. This script is paper-only.")
    for key in ("max_daily_loss", "max_daily_profit", "max_trades_per_day", "paper_quantity"):
        if float(cfg[key]) <= 0:
            raise ValueError(f"config.json मध्ये {key} positive असणे आवश्यक आहे.")
    return cfg


def parse_hhmm(value: str) -> Tuple[int, int]:
    hh, mm = value.split(":", 1)
    return int(hh), int(mm)


def time_reached(now: datetime, hhmm: str) -> bool:
    h, m = parse_hhmm(hhmm)
    return (now.hour, now.minute) >= (h, m)


def ensure_trade_file() -> None:
    if not os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "date", "time", "signal_id", "direction", "entry_spot", "exit_spot",
                "stop_spot", "target_spot", "quantity_units", "pnl_points",
                "pnl_rupees_estimate", "exit_reason"
            ])


def load_state() -> Dict[str, Any]:
    today = date.today().isoformat()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        state = {}
    if state.get("date") != today:
        state = {
            "date": today,
            "realized_pnl_points": 0.0,
            "realized_pnl_rupees_estimate": 0.0,
            "trades_today": 0,
            "last_candle_time": None,
            "active_trade": None,
            "pending_signal": None,
            "telegram_update_offset": 0,
            "stopped": False,
        }
        save_state(state)
    return state


def save_state(state: Dict[str, Any]) -> None:
    temp = STATE_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(temp, STATE_FILE)


def telegram_send(cfg: Dict[str, Any], text: str, signal_id: Optional[str] = None) -> None:
    token, chat_id = cfg.get("telegram_bot_token"), cfg.get("telegram_chat_id")
    if not token or not chat_id:
        print("\n--- TELEGRAM CONFIG नाही ---\n" + text + "\n")
        return
    payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
    if signal_id:
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "✅ YES - PAPER BUY", "callback_data": f"YES_{signal_id}"},
                {"text": "❌ NO - SKIP", "callback_data": f"NO_{signal_id}"}
            ]]
        }
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=10)
        r.raise_for_status()
        result = r.json()
        if not result.get("ok"):
            print("Telegram API error:", result)
    except Exception as exc:
        print("Telegram send error:", exc)


def telegram_poll(cfg: Dict[str, Any], state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Poll Telegram callbacks. Only the configured chat ID may confirm signals."""
    token = cfg.get("telegram_bot_token")
    chat_id = str(cfg.get("telegram_chat_id") or "")
    if not token or not chat_id:
        return []
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": int(state.get("telegram_update_offset", 0)), "timeout": 1},
            timeout=5,
        )
        r.raise_for_status()
        body = r.json()
        if not body.get("ok"):
            return []
        actions = []
        for update in body.get("result", []):
            state["telegram_update_offset"] = max(
                int(state.get("telegram_update_offset", 0)), int(update["update_id"]) + 1
            )
            callback = update.get("callback_query")
            if not callback:
                continue
            callback_id = callback.get("id")
            message = callback.get("message", {})
            sender_chat = str(message.get("chat", {}).get("id", ""))
            data = str(callback.get("data", ""))
            if sender_chat == chat_id and (data.startswith("YES_") or data.startswith("NO_")):
                actions.append({"action": data.split("_", 1)[0], "signal_id": data.split("_", 1)[1]})
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                        json={"callback_query_id": callback_id, "text": "Paper bot received your choice."},
                        timeout=5,
                    )
                except Exception:
                    pass
        save_state(state)
        return actions
    except Exception as exc:
        print("Telegram poll error:", exc)
        return []


def connect_angel(cfg: Dict[str, Any]):
    required = ["angel_api_key", "angel_client_id", "angel_password", "angel_totp_secret"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print("Angel One credentials missing:", ", ".join(missing))
        return None
    try:
        from SmartApi import SmartConnect
        import pyotp
        obj = SmartConnect(api_key=cfg["angel_api_key"])
        totp = pyotp.TOTP(cfg["angel_totp_secret"]).now()
        response = obj.generateSession(cfg["angel_client_id"], cfg["angel_password"], totp)
        if not response or not response.get("status"):
            print("Angel One login failed:", response)
            return None
        print("Angel One login OK. Paper mode only; no orders will be sent.")
        return obj
    except Exception as exc:
        print("Angel One login/import error:", exc)
        return None


def get_candles(obj, cfg: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    if obj is None:
        return None
    now = datetime.now()
    # Ask for enough data for EMA and recent range; use local computer time.
    start = now - timedelta(days=4)
    params = {
        "exchange": cfg["exchange"],
        "symboltoken": str(cfg["symbol_token"]),
        "interval": cfg["candle_interval"],
        "fromdate": start.strftime("%Y-%m-%d %H:%M"),
        "todate": now.strftime("%Y-%m-%d %H:%M"),
    }
    try:
        response = obj.getCandleData(params)
        rows = response.get("data") if isinstance(response, dict) else None
        if not response or not response.get("status") or not rows:
            print("Candle API returned no data:", response)
            return None
        candles = []
        for row in rows:
            # SmartAPI row: timestamp, open, high, low, close, volume
            if len(row) < 5:
                continue
            try:
                ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                candle = {
                    "time": ts.isoformat(),
                    "timestamp": ts.timestamp(),
                    "open": float(row[1]), "high": float(row[2]),
                    "low": float(row[3]), "close": float(row[4]),
                    "volume": float(row[5]) if len(row) > 5 and row[5] is not None else 0.0,
                }
                if all(candle[k] > 0 for k in ("open", "high", "low", "close")):
                    candles.append(candle)
            except (TypeError, ValueError, OverflowError):
                continue
        candles.sort(key=lambda c: c["timestamp"])
        # Never use the newest candle: it may still be forming. Use only closed candles.
        if len(candles) >= 2:
            candles = candles[:-1]
        return candles
    except Exception as exc:
        print("Candle fetch error:", exc)
        return None


def ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def make_signal(candles: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lookback = max(10, int(cfg["lookback_candles"]))
    if len(candles) < max(25, lookback + 2):
        return None
    # Most recent closed candle and its predecessor.
    prev, cur = candles[-2], candles[-1]
    closes = [c["close"] for c in candles]
    ema20 = ema(closes, 20)[-1]
    range_candles = candles[-(lookback + 1):-1]
    swing_high = max(c["high"] for c in range_candles)
    swing_low = min(c["low"] for c in range_candles)
    fib50 = swing_low + (swing_high - swing_low) * 0.5
    # Closed-candle confirmation, EMA filter, Fib 50 level and previous candle breakout.
    bullish = (
        cur["close"] > cur["open"] and cur["close"] > ema20 and
        cur["close"] > fib50 and cur["close"] > prev["high"]
    )
    bearish = (
        cur["close"] < cur["open"] and cur["close"] < ema20 and
        cur["close"] < fib50 and cur["close"] < prev["low"]
    )
    if not bullish and not bearish:
        return None
    direction = "BUY" if bullish else "SELL"
    entry = cur["close"]  # paper fill at confirmed candle close, before slippage/fees
    buffer = float(cfg["stop_buffer_points"])
    stop = min(cur["low"], prev["low"]) - buffer if bullish else max(cur["high"], prev["high"]) + buffer
    risk = abs(entry - stop)
    if risk <= 0 or risk > max(100.0, entry * 0.02):
        return None
    rr = float(cfg["reward_risk"])
    target = entry + risk * rr if bullish else entry - risk * rr
    signal_id = f"{int(cur['timestamp'])}_{direction}"
    return {
        "signal_id": signal_id, "direction": direction, "entry": round(entry, 2),
        "stop": round(stop, 2), "target": round(target, 2),
        "candle_time": cur["time"], "candle_timestamp": cur["timestamp"],
        "ema20": round(ema20, 2), "fib50": round(fib50, 2),
        "swing_high": round(swing_high, 2), "swing_low": round(swing_low, 2),
        "created_at": time.time(),
    }


def close_trade(state: Dict[str, Any], price: float, reason: str, cfg: Dict[str, Any]) -> None:
    tr = state.get("active_trade")
    if not tr:
        return
    direction_sign = 1 if tr["direction"] == "BUY" else -1
    pnl_points = (price - tr["entry"]) * direction_sign * int(tr["quantity_units"])
    # This is a notional estimate for index points only, NOT option P&L or broker P&L.
    pnl_est = pnl_points
    state["realized_pnl_points"] = round(float(state.get("realized_pnl_points", 0)) + pnl_points, 2)
    state["realized_pnl_rupees_estimate"] = round(float(state.get("realized_pnl_rupees_estimate", 0)) + pnl_est, 2)
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            date.today().isoformat(), datetime.now().strftime("%H:%M:%S"), tr["signal_id"],
            tr["direction"], tr["entry"], round(price, 2), tr["stop"], tr["target"],
            tr["quantity_units"], round(pnl_points, 2), round(pnl_est, 2), reason
        ])
    msg = (
        f"PAPER TRADE CLOSED\nDirection: {tr['direction']}\nEntry spot: {tr['entry']}\n"
        f"Exit spot: {price:.2f}\nReason: {reason}\nPnL: {pnl_points:.2f} index points\n"
        f"Daily paper PnL: {state['realized_pnl_points']:.2f} points\n"
        "Note: underlying index simulation only; not option premium or real-money P&L."
    )
    print(msg)
    telegram_send(cfg, msg)
    state["active_trade"] = None
    state["trades_today"] = int(state.get("trades_today", 0)) + 1
    save_state(state)


def manage_active_trade(
    state: Dict[str, Any], last_candle: Dict[str, Any], candles: List[Dict[str, Any]],
    cfg: Dict[str, Any]
) -> None:
    """Manage paper SL/target and trail the stop using the closed-candle EMA20.

    Rules:
    - At +breakeven_at_r * initial risk, move SL to entry (breakeven).
    - After breakeven, BUY stop follows EMA20 minus buffer; SELL stop follows EMA20 plus buffer.
    - Stop only tightens: it never moves away from profit.
    - Updated stop applies from the next candle; current candle is checked against the prior stop.
    """
    tr = state.get("active_trade")
    if not tr:
        return

    direction = tr["direction"]
    # Check the stop/target that was active BEFORE this candle closed.
    # If both are touched in one candle, conservatively assume SL first.
    if direction == "BUY":
        hit_sl = last_candle["low"] <= tr["stop"]
        hit_tp = last_candle["high"] >= tr["target"]
    else:
        hit_sl = last_candle["high"] >= tr["stop"]
        hit_tp = last_candle["low"] <= tr["target"]

    if hit_sl:
        close_trade(state, tr["stop"], "TRAILING_STOP" if tr.get("trailing_active") else "STOP_LOSS", cfg)
        return
    if hit_tp:
        close_trade(state, tr["target"], "TARGET", cfg)
        return

    if not cfg.get("trailing_sl_enabled", True):
        return

    entry = float(tr["entry"])
    initial_risk = float(tr.get("initial_risk", abs(entry - float(tr.get("initial_stop", tr["stop"])))) )
    if initial_risk <= 0:
        return
    close = float(last_candle["close"])
    sign = 1 if direction == "BUY" else -1
    profit_points = (close - entry) * sign
    breakeven_trigger = float(cfg.get("breakeven_at_r", 1.0)) * initial_risk
    old_stop = float(tr["stop"])
    new_stop = old_stop
    ema_period = max(2, int(cfg.get("ema_trailing_period", 20)))
    ema_values = ema([float(c["close"]) for c in candles], ema_period)
    if not ema_values:
        return
    ema_value = float(ema_values[-1])
    buffer = float(cfg.get("ema_trailing_buffer_points", cfg.get("stop_buffer_points", 5)))

    if profit_points >= breakeven_trigger:
        # Lock at breakeven first, then trail along EMA20 with a configurable buffer.
        if direction == "BUY":
            ema_candidate = ema_value - buffer
            new_stop = max(old_stop, entry, ema_candidate)
            new_stop = min(new_stop, close - 0.05)  # simulated stop remains below close
        else:
            ema_candidate = ema_value + buffer
            new_stop = min(old_stop, entry, ema_candidate)
            new_stop = max(new_stop, close + 0.05)  # simulated stop remains above close

        improved = new_stop > old_stop if direction == "BUY" else new_stop < old_stop
        if improved:
            tr["stop"] = round(new_stop, 2)
            tr["breakeven_done"] = tr["stop"] >= entry if direction == "BUY" else tr["stop"] <= entry
            tr["trailing_active"] = True
            print(f"EMA{ema_period} TRAILING SL updated for next candle: {old_stop:.2f} -> {tr['stop']:.2f} (EMA={ema_value:.2f})")
            telegram_send(cfg, f"PAPER EMA{ema_period} TRAILING SL UPDATE\n{direction} NIFTY\nEMA: {ema_value:.2f}\nOld SL: {old_stop:.2f}\nNew SL: {tr['stop']:.2f}\nEntry: {entry:.2f}\nApplies from next candle.")
            save_state(state)


def daily_limit_reached(state: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[str]:
    pnl = float(state.get("realized_pnl_points", 0))
    if pnl <= -float(cfg["max_daily_loss"]):
        return f"Daily loss limit reached ({pnl:.2f} points)"
    if pnl >= float(cfg["max_daily_profit"]):
        return f"Daily profit limit reached ({pnl:.2f} points)"
    if int(state.get("trades_today", 0)) >= int(cfg["max_trades_per_day"]):
        return "Maximum trades per day reached"
    return None


def main() -> None:
    print(f"--- {BOT_NAME} ---")
    cfg = load_config()
    ensure_trade_file()
    state = load_state()
    obj = connect_angel(cfg)
    if obj is None:
        raise RuntimeError("Angel One live candle data उपलब्ध नाही. बनावट data वापरून trade केला जाणार नाही.")

    print("Mode: PAPER ONLY | No live orders | IV/option premium disabled | EMA20 Trailing SL enabled")
    print(f"Interval: {cfg['candle_interval']} | Max trades/day: {cfg['max_trades_per_day']} | Risk setting: {cfg['risk_percent']}% (informational; index-unit simulation)")
    print("Ctrl+C दाबून bot थांबवू शकता. Market बंद असताना नवीन entry घेऊ नका.")

    while True:
        try:
            now = datetime.now()
            if now.weekday() >= 5:
                print("Weekend: market बंद असण्याची शक्यता. 5 मिनिटांनी पुन्हा तपासतो.")
                time.sleep(300)
                continue
            if time_reached(now, cfg["square_off_time"]):
                candles = get_candles(obj, cfg)
                if state.get("active_trade") and candles:
                    close_trade(state, candles[-1]["close"], "TIME_SQUARE_OFF", cfg)
                state["pending_signal"] = None
                state["stopped"] = True
                save_state(state)
                print("Square-off time reached. Bot stopped for today.")
                break
            if state.get("stopped"):
                print("Daily risk/trade limit already reached; bot stopped for today.")
                break

            for action in telegram_poll(cfg, state):
                pending = state.get("pending_signal")
                if not pending or action["signal_id"] != pending.get("signal_id"):
                    continue
                if time.time() - float(pending.get("created_at", 0)) > int(cfg["signal_expiry_minutes"]) * 60:
                    state["pending_signal"] = None
                    telegram_send(cfg, "Signal expired. No paper trade opened.")
                    continue
                if action["action"] == "NO":
                    telegram_send(cfg, f"Signal {pending['signal_id']} skipped by user.")
                    state["pending_signal"] = None
                    save_state(state)
                elif action["action"] == "YES" and not state.get("active_trade"):
                    state["active_trade"] = {
                        **pending,
                        "quantity_units": int(cfg["paper_quantity"]),
                        "initial_stop": float(pending["stop"]),
                        "initial_risk": abs(float(pending["entry"]) - float(pending["stop"])),
                        "trailing_active": False,
                        "breakeven_done": False,
                        "opened_at": datetime.now().isoformat(),
                    }
                    state["pending_signal"] = None
                    save_state(state)
                    telegram_send(cfg, f"PAPER ENTRY CONFIRMED: {pending['direction']} NIFTY spot at {pending['entry']}; SL {pending['stop']}; target {pending['target']}.")

            candles = get_candles(obj, cfg)
            if not candles or len(candles) < 25:
                print("Live candle data कमी/नाही. Trade नाही.")
                time.sleep(int(cfg["poll_seconds"]))
                continue

            latest = candles[-1]
            if state.get("last_candle_time") == latest["time"]:
                time.sleep(int(cfg["poll_seconds"]))
                continue
            state["last_candle_time"] = latest["time"]

            manage_active_trade(state, latest, candles, cfg)
            limit_reason = daily_limit_reached(state, cfg)
            if limit_reason:
                state["stopped"] = True
                state["pending_signal"] = None
                save_state(state)
                telegram_send(cfg, f"BOT STOPPED: {limit_reason}. Paper trading only.")
                print(limit_reason)
                break

            # New entries only during configured entry window.
            if time_reached(now, cfg["market_open"]) and not time_reached(now, cfg["last_entry_time"]):
                if not state.get("active_trade") and not state.get("pending_signal"):
                    sig = make_signal(candles, cfg)
                    if sig:
                        state["pending_signal"] = sig
                        save_state(state)
                        msg = (
                            f"NIFTY PAPER SIGNAL | {sig['direction']}\n"
                            f"Closed candle: {sig['candle_time']}\n"
                            f"Spot entry: {sig['entry']}\nSL: {sig['stop']}\nTarget: {sig['target']}\n"
                            f"EMA20: {sig['ema20']} | Fib 0.50: {sig['fib50']}\n"
                            f"Recent range: {sig['swing_low']} - {sig['swing_high']}\n"
                            f"Signal ID: {sig['signal_id']}\n"
                            "This is an underlying-index paper simulation, NOT an option buy recommendation."
                        )
                        print(msg)
                        if cfg.get("require_telegram_confirmation", True):
                            telegram_send(cfg, msg, sig["signal_id"])
                        else:
                            state["active_trade"] = {
                                **sig,
                                "quantity_units": int(cfg["paper_quantity"]),
                                "initial_stop": float(sig["stop"]),
                                "initial_risk": abs(float(sig["entry"]) - float(sig["stop"])),
                                "trailing_active": False,
                                "breakeven_done": False,
                                "opened_at": datetime.now().isoformat(),
                            }
                            state["pending_signal"] = None
                            save_state(state)

            print(
                f"[{now.strftime('%H:%M:%S')}] NIFTY {latest['close']:.2f} | "
                f"Daily PnL {state.get('realized_pnl_points', 0):.2f} points | "
                f"Trades {state.get('trades_today', 0)}/{cfg['max_trades_per_day']} | "
                f"Active {'YES' if state.get('active_trade') else 'NO'} | PAPER ONLY"
            )
            save_state(state)
            time.sleep(max(10, int(cfg["poll_seconds"])))
        except KeyboardInterrupt:
            print("Bot manually stopped. Existing paper state saved.")
            save_state(state)
            break
        except Exception as exc:
            print("Loop error:", repr(exc))
            time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("FATAL:", error)
        print("config.json, Angel One API login आणि SmartAPI candle access तपासा.")
        input("Exit साठी Enter दाबा...")
