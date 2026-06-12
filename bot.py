"""
SMC Full Bot — Smart Money Concepts
════════════════════════════════════════════════════════════════════════
Полная SMC-логика по всем уровням:

ТАЙМФРЕЙМЫ:
  4h  — глобальный bias (общее направление рынка)
  1h  — структура (BOS / CHoCH), зоны OB/FVG
  15m — точка входа (подтверждение паттерн + объём)

ЛОГИКА ЛОНГ:
  1. 4h bias = BULLISH (цена выше ключевого свинг-лоя)
  2. 1h CHoCH вверх (смена характера) или BOS вверх
  3. 15m откат в бычий OB или FVG
  4. 15m паттерн + объём подтверждают
  5. Ликвидность выше (цель движения)

ЛОГИКА ШОРТ:
  1. 4h bias = BEARISH (цена ниже ключевого свинг-хая)
  2. 1h CHoCH вниз или BOS вниз
  3. 15m откат в медвежий OB или FVG
  4. 15m паттерн + объём подтверждают
  5. Ликвидность ниже (цель движения)

ЛИКВИДНОСТЬ:
  - Equal Highs / Equal Lows (±0.1% допуск)
  - Свинг-хаи / свинг-лои выше/ниже текущей цены
  - Зоны округлых чисел (00, 50, 000)

УПРАВЛЕНИЕ МОНЕТАМИ:
  - Через файл coins.json (добавить/удалить без перезапуска)
  - Команды Telegram: /add BTCUSDT, /remove BTCUSDT, /list, /scan
════════════════════════════════════════════════════════════════════════
"""

import ccxt
import pandas as pd
import asyncio
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Literal
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _check_env():
    missing = [k for k in ['BYBIT_API_KEY', 'BYBIT_API_SECRET', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'] if not os.getenv(k)]
    if missing:
        raise EnvironmentError(f"Нет переменных: {', '.join(missing)}")


# ══════════════════════════════════════════════════════════
#  КОНСТАНТЫ
# ══════════════════════════════════════════════════════════

COINS_FILE         = Path("coins.json")
ATR_PERIOD         = 14
SWING_WINDOW_4H    = 5
SWING_WINDOW_1H    = 5
SWING_WINDOW_15M   = 4
EQL_TOLERANCE      = 0.001
ROUND_NUM_DIGITS   = [2, 1, 0]
OB_LOOKBACK        = 40
FVG_MIN_ATR        = 0.25
VOL_MULT           = 1.3
CHOCH_LOOKBACK     = 30
MIN_RR             = 1.5
SIGNAL_COOLDOWN    = 7200
SCAN_INTERVAL      = 60
MONITOR_INTERVAL   = 5
SIM_TTL_HOURS      = 48
SWEEP_MIN_ATR      = 0.3
SWEEP_MAX_ATR      = 1.8
SWEEP_RETURN_PCT   = 0.003

W_LIQ   = 0.30
W_IVOL  = 0.20
W_IATR  = 0.20
W_HIST  = 0.15
W_CVOL  = 0.15

DEFAULT_COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "TONUSDT", "TAOUSDT", "HYPEUSDT", "ENAUSDT",
    "WLDUSDT", "ADAUSDT", "AVAXUSDT", "DOGEUSDT",
]


# ══════════════════════════════════════════════════════════
#  УПРАВЛЕНИЕ МОНЕТАМИ
# ══════════════════════════════════════════════════════════

def load_coins() -> list[str]:
    if COINS_FILE.exists():
        try:
            return json.loads(COINS_FILE.read_text())
        except Exception:
            pass
    save_coins(DEFAULT_COINS)
    return DEFAULT_COINS.copy()


def save_coins(coins: list[str]):
    COINS_FILE.write_text(json.dumps(sorted(set(coins)), indent=2, ensure_ascii=False))


def add_coin(symbol: str) -> tuple[bool, str]:
    coins = load_coins()
    sym = symbol.upper().strip()
    if not sym.endswith("USDT"):
        sym += "USDT"
    if sym in coins:
        return False, f"{sym} уже в списке"
    coins.append(sym)
    save_coins(coins)
    return True, f"{sym} добавлен ✅"


def remove_coin(symbol: str) -> tuple[bool, str]:
    coins = load_coins()
    sym = symbol.upper().strip()
    if not sym.endswith("USDT"):
        sym += "USDT"
    if sym not in coins:
        return False, f"{sym} не найден в списке"
    coins.remove(sym)
    save_coins(coins)
    return True, f"{sym} удалён ✅"


# ══════════════════════════════════════════════════════════
#  ДАННЫЕ
# ══════════════════════════════════════════════════════════

def fetch_ohlcv(exchange, symbol: str, tf: str, limit: int = 200) -> pd.DataFrame | None:
    try:
        data = exchange.fetch_ohlcv(symbol, tf, limit=limit)
        df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df.reset_index(drop=True)
    except Exception as e:
        print(f"  [fetch] {symbol} {tf}: {e}")
        return None


def calc_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    if len(df) < period + 1:
        return 0.0
    prev = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev).abs(),
        (df['low'] - prev).abs(),
    ], axis=1).max(axis=1)
    return float(tr.iloc[-(period + 1):-1].mean())


# ══════════════════════════════════════════════════════════
#  СВИНГИ
# ══════════════════════════════════════════════════════════

def get_swing_highs(df: pd.DataFrame, w: int) -> list[dict]:
    res = []
    for i in range(w, len(df) - w):
        h = df['high'].iloc[i]
        if (df['high'].iloc[i - w:i] < h).all() and (df['high'].iloc[i + 1:i + w + 1] < h).all():
            res.append({'idx': i, 'price': h, 'ts': df['ts'].iloc[i]})
    return res


def get_swing_lows(df: pd.DataFrame, w: int) -> list[dict]:
    res = []
    for i in range(w, len(df) - w):
        l = df['low'].iloc[i]
        if (df['low'].iloc[i - w:i] > l).all() and (df['low'].iloc[i + 1:i + w + 1] > l).all():
            res.append({'idx': i, 'price': l, 'ts': df['ts'].iloc[i]})
    return res


# ══════════════════════════════════════════════════════════
#  BIAS НА 4H
# ══════════════════════════════════════════════════════════

def get_bias_4h(df_4h: pd.DataFrame) -> str:
    if len(df_4h) < 30:
        return "NEUTRAL"

    highs = get_swing_highs(df_4h, SWING_WINDOW_4H)
    lows  = get_swing_lows(df_4h, SWING_WINDOW_4H)
    cur   = df_4h['close'].iloc[-1]

    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1]['price'] > highs[-2]['price']
        hl = lows[-1]['price']  > lows[-2]['price']
        lh = highs[-1]['price'] < highs[-2]['price']
        ll = lows[-1]['price']  < lows[-2]['price']

        if hh and hl:
            return "BULLISH"
        if lh and ll:
            return "BEARISH"

    if highs and cur > highs[-1]['price']:
        return "BULLISH"
    if lows and cur < lows[-1]['price']:
        return "BEARISH"

    return "NEUTRAL"


# ══════════════════════════════════════════════════════════
#  BOS И CHOCH НА 1H
# ══════════════════════════════════════════════════════════

def detect_bos_choch_1h(df_1h: pd.DataFrame) -> dict | None:
    if len(df_1h) < CHOCH_LOOKBACK + SWING_WINDOW_1H * 2:
        return None

    df    = df_1h.tail(CHOCH_LOOKBACK + SWING_WINDOW_1H * 2).copy().reset_index(drop=True)
    cur   = df['close'].iloc[-1]
    highs = get_swing_highs(df, SWING_WINDOW_1H)
    lows  = get_swing_lows(df, SWING_WINDOW_1H)

    highs = [h for h in highs if h['idx'] < len(df) - SWING_WINDOW_1H]
    lows  = [l for l in lows  if l['idx'] < len(df) - SWING_WINDOW_1H]

    if len(highs) < 2 or len(lows) < 2:
        return None

    last_high = highs[-1]['price']
    last_low  = lows[-1]['price']
    prev_high = highs[-2]['price']
    prev_low  = lows[-2]['price']

    bullish_trend = highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']
    bearish_trend = highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']

    event_type = None
    direction  = None
    level      = None

    if bullish_trend and cur < last_low:
        event_type = "CHoCH"
        direction  = "SHORT"
        level      = last_low
    elif bearish_trend and cur > last_high:
        event_type = "CHoCH"
        direction  = "LONG"
        level      = last_high
    elif cur < prev_low and not bullish_trend:
        event_type = "BOS"
        direction  = "SHORT"
        level      = prev_low
    elif cur > prev_high and not bearish_trend:
        event_type = "BOS"
        direction  = "LONG"
        level      = prev_high

    if event_type is None:
        return None

    if direction == "SHORT":
        impulse_start = max(h['price'] for h in highs[-3:]) if highs else cur
        impulse_size  = impulse_start - cur
    else:
        impulse_start = min(l['price'] for l in lows[-3:]) if lows else cur
        impulse_size  = cur - impulse_start

    return {
        'type':          event_type,
        'direction':     direction,
        'level':         round(level, 6),
        'impulse_start': round(impulse_start, 6),
        'impulse_size':  round(impulse_size, 6),
        'swing_high':    round(last_high, 6),
        'swing_low':     round(last_low, 6),
        'cur':           round(cur, 6),
    }


# ══════════════════════════════════════════════════════════
#  ORDER BLOCK
# ══════════════════════════════════════════════════════════

def find_ob(df_15m: pd.DataFrame, direction: str) -> dict | None:
    if len(df_15m) < OB_LOOKBACK:
        return None

    df  = df_15m.tail(OB_LOOKBACK).copy().reset_index(drop=True)
    cur = df['close'].iloc[-1]

    if direction == "LONG":
        for i in range(len(df) - 4, 2, -1):
            c = df.iloc[i]
            if c['close'] >= c['open']:
                continue
            bulls = sum(1 for j in range(i + 1, min(i + 4, len(df))) if df.iloc[j]['close'] > df.iloc[j]['open'])
            if bulls < 2:
                continue
            if c['high'] > cur:
                continue
            in_ob = c['low'] <= cur <= c['high'] * 1.002
            if not in_ob:
                continue
            return {
                'type':    'Бычий OB',
                'high':    round(c['high'], 6),
                'low':     round(c['low'], 6),
                'mid':     round((c['high'] + c['low']) / 2, 6),
                'in_zone': True,
            }

    elif direction == "SHORT":
        for i in range(len(df) - 4, 2, -1):
            c = df.iloc[i]
            if c['close'] <= c['open']:
                continue
            bears = sum(1 for j in range(i + 1, min(i + 4, len(df))) if df.iloc[j]['close'] < df.iloc[j]['open'])
            if bears < 2:
                continue
            if c['low'] < cur:
                continue
            in_ob = c['low'] * 0.998 <= cur <= c['high']
            if not in_ob:
                continue
            return {
                'type':    'Медвежий OB',
                'high':    round(c['high'], 6),
                'low':     round(c['low'], 6),
                'mid':     round((c['high'] + c['low']) / 2, 6),
                'in_zone': True,
            }

    return None


# ══════════════════════════════════════════════════════════
#  FAIR VALUE GAP
# ══════════════════════════════════════════════════════════

def find_fvg(df_15m: pd.DataFrame, direction: str, atr: float) -> dict | None:
    if len(df_15m) < 30:
        return None

    df  = df_15m.tail(40).copy().reset_index(drop=True)
    cur = df['close'].iloc[-1]
    mn  = atr * FVG_MIN_ATR

    best = None

    for i in range(1, len(df) - 2):
        cp = df.iloc[i - 1]
        cm = df.iloc[i]
        cn = df.iloc[i + 1]

        if direction == "LONG":
            gap_bot = cp['high']
            gap_top = cn['low']
            if gap_top <= gap_bot:
                continue
            if gap_top - gap_bot < mn:
                continue
            if cm['close'] <= cm['open']:
                continue
            filled = df.iloc[i + 2:]['low'].min() <= gap_bot if i + 2 < len(df) else False
            if filled:
                continue
            if not (gap_bot <= cur <= gap_top):
                continue
            best = {
                'type': 'Бычий FVG',
                'high': round(gap_top, 6),
                'low':  round(gap_bot, 6),
                'mid':  round((gap_top + gap_bot) / 2, 6),
                'size': round(gap_top - gap_bot, 6),
            }

        elif direction == "SHORT":
            gap_top = cp['low']
            gap_bot = cn['high']
            if gap_bot >= gap_top:
                continue
            if gap_top - gap_bot < mn:
                continue
            if cm['close'] >= cm['open']:
                continue
            filled = df.iloc[i + 2:]['high'].max() >= gap_top if i + 2 < len(df) else False
            if filled:
                continue
            if not (gap_bot <= cur <= gap_top):
                continue
            best = {
                'type': 'Медвежий FVG',
                'high': round(gap_top, 6),
                'low':  round(gap_bot, 6),
                'mid':  round((gap_top + gap_bot) / 2, 6),
                'size': round(gap_top - gap_bot, 6),
            }

    return best


# ══════════════════════════════════════════════════════════
#  ЗОНЫ ЛИКВИДНОСТИ
# ══════════════════════════════════════════════════════════

def find_liquidity_zones(df_4h: pd.DataFrame, df_1h: pd.DataFrame,
                         df_15m: pd.DataFrame, cur: float) -> dict:
    all_highs = []
    all_lows  = []

    for df, w in [(df_4h, SWING_WINDOW_4H), (df_1h, SWING_WINDOW_1H), (df_15m, SWING_WINDOW_15M)]:
        if df is not None:
            all_highs += [h['price'] for h in get_swing_highs(df, w)]
            all_lows  += [l['price'] for l in get_swing_lows(df, w)]

    def find_equal_levels(levels: list[float], tolerance: float) -> list[float]:
        eq = []
        for i, a in enumerate(levels):
            for b in levels[i + 1:]:
                if abs(a - b) / max(a, 0.0001) <= tolerance:
                    eq.append(round((a + b) / 2, 6))
        return list(set(eq))

    eq_highs = find_equal_levels(all_highs, EQL_TOLERANCE)
    eq_lows  = find_equal_levels(all_lows, EQL_TOLERANCE)

    highs_above = sorted([h for h in all_highs if h > cur * 1.001])
    lows_below  = sorted([l for l in all_lows  if l < cur * 0.999], reverse=True)

    round_levels = []
    for digits in ROUND_NUM_DIGITS:
        step  = 10 ** (len(str(int(cur))) - 1 - digits)
        start = round(cur * 0.85 / step) * step
        end   = round(cur * 1.15 / step) * step
        lvl   = start
        while lvl <= end:
            if abs(lvl - cur) / cur > 0.003:
                round_levels.append(round(lvl, 6))
            lvl += step
    round_levels = sorted(set(round_levels))

    round_above = sorted([r for r in round_levels if r > cur])
    round_below = sorted([r for r in round_levels if r < cur], reverse=True)

    liq_above = []
    seen = set()
    for lvl in sorted(highs_above[:3] + eq_highs[:2] + round_above[:2]):
        k = round(lvl, max(0, len(str(int(cur))) - 2))
        if k not in seen:
            seen.add(k)
            liq_above.append(round(lvl, 6))
    liq_above = sorted(liq_above)[:4]

    liq_below = []
    seen = set()
    for lvl in sorted(lows_below[:3] + eq_lows[:2] + round_below[:2], reverse=True):
        k = round(lvl, max(0, len(str(int(cur))) - 2))
        if k not in seen:
            seen.add(k)
            liq_below.append(round(lvl, 6))
    liq_below = sorted(liq_below, reverse=True)[:4]

    return {
        'above':      liq_above,
        'below':      liq_below,
        'eq_highs':   eq_highs[:3],
        'eq_lows':    eq_lows[:3],
        'round_near': (round_above[:2] if round_above else []) + (round_below[:2] if round_below else []),
    }


# ══════════════════════════════════════════════════════════
#  ПАТТЕРНЫ И ОБЪЁМ (15М)
# ══════════════════════════════════════════════════════════

def check_entry_confirmation(df_15m: pd.DataFrame, direction: str) -> dict:
    patterns = []
    if len(df_15m) < 4:
        return {'ok': False, 'patterns': [], 'vol_ok': False, 'vol_ratio': 0}

    c1 = df_15m.iloc[-3]
    c2 = df_15m.iloc[-2]
    c3 = df_15m.iloc[-1]

    body3  = abs(c3['close'] - c3['open'])
    uw3    = c3['high'] - max(c3['open'], c3['close'])
    lw3    = min(c3['open'], c3['close']) - c3['low']
    range3 = c3['high'] - c3['low']

    if direction == "LONG":
        if c2['close'] < c2['open'] and c3['close'] > c3['open'] and c3['open'] < c2['close'] and c3['close'] > c2['open']:
            patterns.append("Бычье поглощение")
        if body3 > 0 and lw3 >= 2 * body3 and uw3 < body3:
            patterns.append("Молот")
        if range3 > 0 and lw3 / range3 > 0.6 and body3 / range3 < 0.25:
            patterns.append("Бычий пин-бар")
        b1 = abs(c1['close'] - c1['open'])
        b2 = abs(c2['close'] - c2['open'])
        if c1['close'] < c1['open'] and b2 < 0.3 * b1 and c3['close'] > c3['open'] and c3['close'] > (c1['open'] + c1['close']) / 2:
            patterns.append("Утренняя звезда")
        if c2['close'] < c2['open'] and c3['close'] > c3['open'] and c3['high'] < c2['high'] and c3['low'] > c2['low']:
            patterns.append("Бычий харами")

    elif direction == "SHORT":
        if c2['close'] > c2['open'] and c3['close'] < c3['open'] and c3['open'] > c2['close'] and c3['close'] < c2['open']:
            patterns.append("Медвежье поглощение")
        if body3 > 0 and uw3 >= 2 * body3 and lw3 < body3:
            patterns.append("Падающая звезда")
        if range3 > 0 and uw3 / range3 > 0.6 and body3 / range3 < 0.25:
            patterns.append("Медвежий пин-бар")
        b1 = abs(c1['close'] - c1['open'])
        b2 = abs(c2['close'] - c2['open'])
        if c1['close'] > c1['open'] and b2 < 0.3 * b1 and c3['close'] < c3['open'] and c3['close'] < (c1['open'] + c1['close']) / 2:
            patterns.append("Вечерняя звезда")
        if c2['close'] > c2['open'] and c3['close'] < c3['open'] and c3['high'] < c2['high'] and c3['low'] > c2['low']:
            patterns.append("Медвежий харами")

    avg_vol   = df_15m['volume'].iloc[-21:-1].mean()
    cur_vol   = df_15m['volume'].iloc[-1]
    vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0
    vol_ok    = vol_ratio >= VOL_MULT

    confirmed = len(patterns) > 0 and vol_ok

    return {
        'ok':        confirmed,
        'patterns':  patterns,
        'vol_ok':    vol_ok,
        'vol_ratio': round(vol_ratio, 2),
    }


# ══════════════════════════════════════════════════════════
#  УРОВНИ SL / TP
# ══════════════════════════════════════════════════════════

def calc_levels(direction: str, entry: float, zone: dict, struct: dict,
                liquidity: dict, atr: float) -> dict:
    if direction == "LONG":
        sl  = round(zone['low'] - atr * 0.4, 6)
        liq = liquidity['above']
        tp1 = round(liq[0], 6) if len(liq) > 0 else round(entry + atr * 1.5, 6)
        tp2 = round(liq[1], 6) if len(liq) > 1 else round(entry + atr * 2.5, 6)
        tp3 = round(entry + struct['impulse_size'], 6)
    else:
        sl  = round(zone['high'] + atr * 0.4, 6)
        liq = liquidity['below']
        tp1 = round(liq[0], 6) if len(liq) > 0 else round(entry - atr * 1.5, 6)
        tp2 = round(liq[1], 6) if len(liq) > 1 else round(entry - atr * 2.5, 6)
        tp3 = round(entry - struct['impulse_size'], 6)

    risk   = abs(sl - entry)
    reward = abs(tp1 - entry)
    rr     = round(reward / risk, 2) if risk > 0 else 0

    return {'entry': round(entry, 6), 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp3': tp3, 'rr': rr}


# ══════════════════════════════════════════════════════════
#  ФОРМАТИРОВАНИЕ СООБЩЕНИЯ
# ══════════════════════════════════════════════════════════

def format_signal(symbol: str, direction: str, bias_4h: str, struct: dict,
                  zone: dict, conf: dict, levels: dict, liquidity: dict, atr: float) -> str:

    dir_emoji    = "🟢" if direction == "LONG" else "🔴"
    dir_label    = "ЛОНГ" if direction == "LONG" else "ШОРТ"
    struct_emoji = "⚡" if struct['type'] == "CHoCH" else "💥"

    liq_targets = liquidity['above'] if direction == "LONG" else liquidity['below']
    liq_str = " → ".join([f"`{p}`" for p in liq_targets[:3]]) if liq_targets else "не найдена"

    eq_str = ""
    if direction == "LONG" and liquidity['eq_highs']:
        eq_str = "\n📊 Equal Highs: " + " | ".join([f"`{p}`" for p in liquidity['eq_highs'][:2]])
    elif direction == "SHORT" and liquidity['eq_lows']:
        eq_str = "\n📊 Equal Lows: " + " | ".join([f"`{p}`" for p in liquidity['eq_lows'][:2]])

    round_str = ""
    if liquidity['round_near']:
        near = [r for r in liquidity['round_near'] if
                (direction == "LONG" and r > levels['entry']) or
                (direction == "SHORT" and r < levels['entry'])]
        if near:
            round_str = "\n🔵 Округлые уровни: " + " | ".join([f"`{p}`" for p in near[:2]])

    score = 0
    if struct['type'] == "CHoCH":                          score += 3
    if struct['type'] == "BOS":                            score += 2
    if zone['type'] in ('Бычий OB', 'Медвежий OB'):       score += 2
    if zone['type'] in ('Бычий FVG', 'Медвежий FVG'):     score += 1
    if len(conf['patterns']) >= 2:                         score += 2
    elif conf['patterns']:                                 score += 1
    if conf['vol_ok']:                                     score += 1

    strength = "🔥 СИЛЬНЫЙ" if score >= 7 else "⚡ ХОРОШИЙ" if score >= 5 else "✅ СТАНДАРТ"

    msg = (
        f"{dir_emoji} *SMC {dir_label}* — {symbol}\n\n"
        f"💪 Сила: {strength}\n\n"
        f"*Структура:*\n"
        f"{struct_emoji} {struct['type']} на 1h: уровень `{struct['level']}`\n"
        f"📐 4h Bias: {bias_4h}\n"
        f"📏 ATR(14): `{round(atr, 6)}`\n\n"
        f"*Зона входа на 15м:*\n"
        f"📦 {zone['type']}: `{zone['low']}` – `{zone['high']}`\n\n"
        f"*Подтверждение:*\n"
        f"✅ Паттерны: {', '.join(conf['patterns'])}\n"
        f"✅ Объём: x{conf['vol_ratio']} от среднего\n\n"
        f"*Ликвидность (цели):*\n"
        f"💧 {liq_str}"
        f"{eq_str}"
        f"{round_str}\n\n"
        f"*Уровни:*\n"
        f"🎯 Вход:  `{levels['entry']}`\n"
        f"🛑 SL:    `{levels['sl']}`\n"
        f"✅ TP1:   `{levels['tp1']}`\n"
        f"✅ TP2:   `{levels['tp2']}`\n"
        f"✅ TP3:   `{levels['tp3']}`\n"
        f"⚖️  R:R:   `{levels['rr']}`\n\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%d.%m %H:%M')} UTC"
    )
    return msg


# ══════════════════════════════════════════════════════════
#  PREDICTION ENGINE — DATACLASSES
# ══════════════════════════════════════════════════════════

@dataclass
class ScenA:
    zone_h:    float = 0.0
    zone_l:    float = 0.0
    zone_mid:  float = 0.0
    zone_type: str   = ""
    ret_pct:   float = 0.0
    prob:      float = 0.5
    sl:  float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0


@dataclass
class ScenB:
    sweep_tgt:  float = 0.0
    depth_atr:  float = 0.8
    entry_ret:  float = 0.0
    prob:       float = 0.5
    sl:         float = 0.0
    tp1:        float = 0.0
    tp2:        float = 0.0
    tp3:        float = 0.0
    triggered:  bool  = False
    sweep_hi:   float = 0.0
    sweep_lo:   float = 0.0


@dataclass
class Simulation:
    symbol:     str
    direction:  str
    created:    datetime
    struct:     dict
    zone:       dict
    liquidity:  dict
    atr:        float
    sa:         ScenA
    sb:         ScenB
    winner:     str
    status:     str  = "watching"
    entry_sent: bool = False
    db_id:      int  = 0


# ══════════════════════════════════════════════════════════
#  PREDICTION ENGINE — ПОСТРОЕНИЕ СЦЕНАРИЕВ
# ══════════════════════════════════════════════════════════

def _liq_above_swing(df: pd.DataFrame, level: float, atr: float) -> float:
    thr  = level - atr * 0.3
    near = df[df['high'] >= thr]
    return min(len(near) / max(len(df.tail(30)), 1) * 3, 1.0)


def score_scenarios(df_15m: pd.DataFrame, struct: dict, atr: float, direction: str) -> tuple[float, float]:
    swing  = struct['swing_high'] if direction == "SHORT" else struct['swing_low']
    imp_sz = struct['impulse_size']

    liq = _liq_above_swing(df_15m, swing, atr)

    avg_vol = df_15m['volume'].iloc[-35:-5].mean() or 1
    pk_vol  = df_15m['volume'].iloc[-5:].max()
    vs = min((pk_vol / avg_vol - 1.5) / 3, 1.0)

    imp_atr = imp_sz / atr if atr > 0 else 0
    as_     = min((imp_atr - 2) / 4, 1.0)

    hist = 0.5

    near = df_15m[df_15m['high'] >= swing * 0.998].tail(3)
    cv = min(near['volume'].mean() / avg_vol if len(near) > 0 else 0, 1.0)

    raw_b = (
        liq        * W_LIQ +
        max(vs, 0) * W_IVOL +
        max(as_, 0) * W_IATR +
        hist       * W_HIST +
        cv         * W_CVOL
    )
    prob_b = round(min(max(raw_b, 0.10), 0.88), 3)
    prob_a = round(1.0 - prob_b, 3)
    return prob_a, prob_b


def build_scen_a(df_15m: pd.DataFrame, struct: dict, zone: dict,
                 atr: float, direction: str, prob: float) -> ScenA:
    cur  = df_15m['close'].iloc[-1]
    imp  = struct['impulse_size']
    zh, zl = zone['high'], zone['low']
    zmid = (zh + zl) / 2

    ret_pct = abs(zmid - cur) / imp * 100 if imp > 0 else 0

    if direction == "LONG":
        sl  = round(zl - atr * 0.4, 6)
        tp1 = round(cur + atr * 1.5, 6)
        tp2 = round(cur + imp * 0.5, 6)
        tp3 = round(cur + imp, 6)
    else:
        sl  = round(zh + atr * 0.4, 6)
        tp1 = round(cur - atr * 1.5, 6)
        tp2 = round(cur - imp * 0.5, 6)
        tp3 = round(cur - imp, 6)

    return ScenA(
        zone_h=round(zh, 6), zone_l=round(zl, 6), zone_mid=round(zmid, 6),
        zone_type=zone['type'], ret_pct=round(ret_pct, 1), prob=prob,
        sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
    )


def build_scen_b(df_15m: pd.DataFrame, struct: dict, atr: float,
                 direction: str, prob: float) -> ScenB:
    cur = df_15m['close'].iloc[-1]
    imp = struct['impulse_size']

    if direction == "SHORT":
        swing     = struct['swing_high']
        sweep_tgt = round(swing + atr * 0.8, 6)
        entry_ret = round(swing - atr * 0.3, 6)
        sl        = round(sweep_tgt + atr * 0.3, 6)
        tp1       = round(cur - atr * 1.5, 6)
        tp2       = round(cur - imp * 0.5, 6)
        tp3       = round(cur - imp, 6)
        return ScenB(sweep_tgt=sweep_tgt, depth_atr=0.8, entry_ret=entry_ret, prob=prob,
                     sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, sweep_hi=swing)
    else:
        swing     = struct['swing_low']
        sweep_tgt = round(swing - atr * 0.8, 6)
        entry_ret = round(swing + atr * 0.3, 6)
        sl        = round(sweep_tgt - atr * 0.3, 6)
        tp1       = round(cur + atr * 1.5, 6)
        tp2       = round(cur + imp * 0.5, 6)
        tp3       = round(cur + imp, 6)
        return ScenB(sweep_tgt=sweep_tgt, depth_atr=0.8, entry_ret=entry_ret, prob=prob,
                     sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, sweep_lo=swing)


def format_simulation_msg(symbol: str, sim: Simulation) -> str:
    sa, sb = sim.sa, sim.sb
    dir_e  = "🟢" if sim.direction == "LONG" else "🔴"
    winner_label = {
        "A":     f"A — откат ({sa.prob:.0%})",
        "B":     f"B — вынос ({sb.prob:.0%})",
        "equal": "равные шансы",
    }[sim.winner]

    if sim.direction == "SHORT":
        sweep_info = f"Sweep → `{sb.sweep_tgt}` (+{sb.depth_atr}x ATR выше свинга)"
    else:
        sweep_info = f"Sweep → `{sb.sweep_tgt}` (-{sb.depth_atr}x ATR ниже свинга)"

    return (
        f"🧠 *Симуляция запущена* — {symbol}\n\n"
        f"{dir_e} Направление: *{sim.direction}*\n"
        f"ATR(14): `{sim.atr}`\n\n"
        f"*Сценарий A* _{sa.prob:.0%}_ — чистый откат\n"
        f"Зона: `{sa.zone_l}` – `{sa.zone_h}` ({sa.zone_type})\n"
        f"Откат {sa.ret_pct}% от импульса\n\n"
        f"*Сценарий B* _{sb.prob:.0%}_ — вынос стопов\n"
        f"{sweep_info}\n"
        f"Вход после возврата: `{sb.entry_ret}`\n\n"
        f"Победитель: *{winner_label}*\n"
        f"_Мониторинг каждые 5 минут_"
    )


# ══════════════════════════════════════════════════════════
#  PREDICTION ENGINE — МОНИТОРИНГ
# ══════════════════════════════════════════════════════════

async def monitor_simulation(sim: Simulation, df_15m: pd.DataFrame,
                             tg: telegram.Bot, chat_id: str, atr: float) -> str:
    price = df_15m['close'].iloc[-1]
    hi    = df_15m['high'].iloc[-1]
    lo    = df_15m['low'].iloc[-1]
    sa, sb = sim.sa, sim.sb

    patterns = _quick_patterns(df_15m, sim.direction)
    vol_ok   = _quick_vol(df_15m)

    # ── Сценарий A: цена вошла в зону откатa ──────────────
    if sim.status == "watching" and sim.winner in ("A", "equal"):
        in_zone = sa.zone_l <= price <= sa.zone_h
        if in_zone:
            sim.status = "a_zone"
            if patterns and vol_ok and not sim.entry_sent:
                await _send_entry_confirmed(sim, tg, chat_id, "A", price, patterns, atr)
                sim.entry_sent = True
                return "done"
            else:
                await tg.send_message(
                    chat_id=chat_id,
                    parse_mode='Markdown',
                    text=(
                        f"📍 *Зона A достигнута* — {sim.symbol}\n\n"
                        f"Цена: `{price}` в зоне `{sa.zone_l}`–`{sa.zone_h}`\n"
                        f"{'✅' if patterns else '⏳'} Паттерны: {', '.join(patterns) if patterns else 'ждём...'}\n"
                        f"{'✅' if vol_ok else '⏳'} Объём: {'подтверждён' if vol_ok else 'слабый'}\n"
                        f"_Жду подтверждение_"
                    )
                )
            return "a_zone"

    # ── Сценарий A зона: ждём подтверждение ───────────────
    if sim.status == "a_zone" and not sim.entry_sent:
        in_zone = sa.zone_l <= price <= sa.zone_h
        if in_zone and patterns and vol_ok:
            await _send_entry_confirmed(sim, tg, chat_id, "A", price, patterns, atr)
            sim.entry_sent = True
            return "done"

    # ── Сценарий B: цена пошла на вынос ───────────────────
    sweep_triggered = False
    if sim.direction == "SHORT" and hi >= sb.sweep_hi:
        sweep_triggered = True
        sb.sweep_hi = max(sb.sweep_hi, hi)
    elif sim.direction == "LONG" and lo <= sb.sweep_lo:
        sweep_triggered = True
        sb.sweep_lo = min(sb.sweep_lo, lo)

    if sweep_triggered and sim.status in ("watching", "a_zone") and sim.winner in ("B", "equal"):
        sim.status = "b_sweep"
        sb.triggered = True
        lvl = sb.sweep_hi if sim.direction == "SHORT" else sb.sweep_lo
        await tg.send_message(
            chat_id=chat_id,
            parse_mode='Markdown',
            text=(
                f"⚡ *Вынос стопов* — {sim.symbol}\n\n"
                f"Цена пробила ключевой уровень: `{lvl}`\n"
                f"Цель выноса: `{sb.sweep_tgt}`\n\n"
                f"_Жду возврат для входа {sim.direction}_"
            )
        )
        return "b_sweep"

    # ── Сценарий B: вынос был, ждём возврат ───────────────
    if sim.status == "b_sweep":
        returned = False
        if sim.direction == "SHORT" and price <= sim.struct['swing_high'] * (1 - SWEEP_RETURN_PCT):
            returned = True
        elif sim.direction == "LONG" and price >= sim.struct['swing_low'] * (1 + SWEEP_RETURN_PCT):
            returned = True

        if returned and not sim.entry_sent:
            if patterns and vol_ok:
                await _send_entry_confirmed(sim, tg, chat_id, "B", price, patterns, atr)
                sim.entry_sent = True
                return "done"
            sim.status = "b_triggered"
        return sim.status

    # ── TTL ───────────────────────────────────────────────
    age = (datetime.now(timezone.utc) - sim.created.replace(tzinfo=timezone.utc)).total_seconds() / 3600
    if age > SIM_TTL_HOURS:
        return "expired"

    return sim.status


async def _send_entry_confirmed(sim: Simulation, tg, chat_id, scenario, price, patterns, atr):
    sa, sb = sim.sa, sim.sb
    if scenario == "A":
        sl, tp1, tp2, tp3 = sa.sl, sa.tp1, sa.tp2, sa.tp3
        scenario_label = f"A — чистый откат ({sa.prob:.0%})"
        zone_info = f"Откат {sa.ret_pct}% к {sa.zone_type} `{sa.zone_l}`–`{sa.zone_h}`"
    else:
        sl, tp1, tp2, tp3 = sb.sl, sb.tp1, sb.tp2, sb.tp3
        scenario_label = f"B — вынос стопов ({sb.prob:.0%})"
        zone_info = f"Вынос завершён, возврат к `{sim.struct.get('swing_high', sb.sweep_hi)}`"

    risk   = abs(sl - price)
    reward = abs(tp1 - price)
    rr     = round(reward / risk, 2) if risk > 0 else 0
    dir_e  = "🟢" if sim.direction == "LONG" else "🔴"

    await tg.send_message(
        chat_id=chat_id,
        parse_mode='Markdown',
        text=(
            f"🎯 *ВХОД ПОДТВЕРЖДЁН* {dir_e} — {sim.symbol}\n\n"
            f"Сценарий *{scenario_label}*\n"
            f"📍 {zone_info}\n\n"
            f"✅ Паттерны: {', '.join(patterns)}\n"
            f"✅ Объём подтверждён\n\n"
            f"🎯 Вход:  `{price}`\n"
            f"🛑 SL:    `{sl}`\n"
            f"✅ TP1:   `{tp1}`\n"
            f"✅ TP2:   `{tp2}`\n"
            f"✅ TP3:   `{tp3}`\n"
            f"⚖️  R:R:   `{rr}`\n\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%d.%m %H:%M')} UTC"
        )
    )


def _quick_patterns(df: pd.DataFrame, direction: str) -> list[str]:
    if len(df) < 4:
        return []
    c2, c3 = df.iloc[-2], df.iloc[-1]
    p    = []
    body = abs(c3['close'] - c3['open'])
    uw   = c3['high'] - max(c3['open'], c3['close'])
    lw   = min(c3['open'], c3['close']) - c3['low']
    rng  = c3['high'] - c3['low']
    if direction == "LONG":
        if c2['close'] < c2['open'] and c3['close'] > c3['open'] and c3['open'] < c2['close'] and c3['close'] > c2['open']:
            p.append("Бычье поглощение")
        if body > 0 and lw >= 2 * body and uw < body:
            p.append("Молот")
        if rng > 0 and lw / rng > 0.6 and body / rng < 0.25:
            p.append("Бычий пин-бар")
    else:
        if c2['close'] > c2['open'] and c3['close'] < c3['open'] and c3['open'] > c2['close'] and c3['close'] < c2['open']:
            p.append("Медвежье поглощение")
        if body > 0 and uw >= 2 * body and lw < body:
            p.append("Падающая звезда")
        if rng > 0 and uw / rng > 0.6 and body / rng < 0.25:
            p.append("Медвежий пин-бар")
    return p


def _quick_vol(df: pd.DataFrame) -> bool:
    if len(df) < 22:
        return False
    avg = df['volume'].iloc[-21:-1].mean()
    return df['volume'].iloc[-1] > avg * VOL_MULT


# ══════════════════════════════════════════════════════════
#  ГЛАВНЫЙ БОТ
# ══════════════════════════════════════════════════════════

class SMCFullBot:
    def __init__(self):
        _check_env()
        self.exchange = ccxt.bybit({
            'apiKey':          os.getenv('BYBIT_API_KEY'),
            'secret':          os.getenv('BYBIT_API_SECRET'),
            'enableRateLimit': True,
            'options':         {'defaultType': 'future'},
        })
        self.token    = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id  = os.getenv('TELEGRAM_CHAT_ID')
        self.tg       = telegram.Bot(token=self.token)
        self.last_signals: dict[str, datetime] = {}
        self.active_sims:  dict[str, Simulation] = {}
        print("🧠 SMC Full Bot инициализирован")
        print(f"   Монет в списке: {len(load_coins())}")

    async def send(self, text: str):
        await self.tg.send_message(chat_id=self.chat_id, text=text, parse_mode='Markdown')

    async def analyze(self, symbol: str) -> dict | None:
        try:
            df_4h  = fetch_ohlcv(self.exchange, symbol, '4h',  150)
            df_1h  = fetch_ohlcv(self.exchange, symbol, '1h',  200)
            df_15m = fetch_ohlcv(self.exchange, symbol, '15m', 200)

            if df_4h is None or df_1h is None or df_15m is None:
                return None

            atr = calc_atr(df_15m)
            if atr == 0:
                return None

            cur = df_15m['close'].iloc[-1]

            bias_4h = get_bias_4h(df_4h)
            if bias_4h == "NEUTRAL":
                return None

            struct = detect_bos_choch_1h(df_1h)
            if struct is None:
                return None

            direction = struct['direction']

            bias_match = (bias_4h == "BULLISH" and direction == "LONG") or \
                         (bias_4h == "BEARISH" and direction == "SHORT")
            if not bias_match:
                return None

            ob  = find_ob(df_15m, direction)
            fvg = find_fvg(df_15m, direction, atr)
            zone = ob or fvg
            if zone is None:
                return None

            conf = check_entry_confirmation(df_15m, direction)
            if not conf['ok']:
                print(f"  [{symbol}] {direction} — зона найдена, нет подтверждения "
                      f"(паттерны: {conf['patterns']}, объём: x{conf['vol_ratio']})")
                return None

            liquidity = find_liquidity_zones(df_4h, df_1h, df_15m, cur)

            levels = calc_levels(direction, cur, zone, struct, liquidity, atr)
            if levels['rr'] < MIN_RR:
                print(f"  [{symbol}] R:R={levels['rr']} < {MIN_RR} — пропуск")
                return None

            key  = f"{symbol}_{direction}"
            last = self.last_signals.get(key)
            if last and (datetime.now() - last).total_seconds() < SIGNAL_COOLDOWN:
                return None

            msg = format_signal(symbol, direction, bias_4h, struct,
                                zone, conf, levels, liquidity, atr)
            await self.send(msg)
            self.last_signals[key] = datetime.now()

            if symbol not in self.active_sims:
                prob_a, prob_b = score_scenarios(df_15m, struct, atr, direction)
                sa     = build_scen_a(df_15m, struct, zone, atr, direction, prob_a)
                sb     = build_scen_b(df_15m, struct, atr, direction, prob_b)
                winner = "A" if prob_a > prob_b + 0.1 else "B" if prob_b > prob_a + 0.1 else "equal"

                sim = Simulation(
                    symbol=symbol, direction=direction, created=datetime.now(),
                    struct=struct, zone=zone, liquidity=liquidity, atr=round(atr, 6),
                    sa=sa, sb=sb, winner=winner,
                )
                self.active_sims[symbol] = sim
                await self.send(format_simulation_msg(symbol, sim))

            print(f"  ✅ {direction} {symbol} | {struct['type']} | {zone['type']} | "
                  f"{', '.join(conf['patterns'])} | R:R={levels['rr']}")

            return {'symbol': symbol, 'direction': direction, 'levels': levels}

        except Exception as e:
            print(f"  [analyze] {symbol}: {e}")
        return None

    async def monitor_sims(self):
        done = []
        for sym, sim in list(self.active_sims.items()):
            df_15m = fetch_ohlcv(self.exchange, sym, '15m', 50)
            if df_15m is None:
                continue
            try:
                atr        = calc_atr(df_15m)
                new_status = await monitor_simulation(sim, df_15m, self.tg, self.chat_id, atr)
                sim.status = new_status
                if new_status in ("done", "expired"):
                    done.append(sym)
                    if new_status == "expired":
                        print(f"  ⏰ Симуляция {sym} истекла")
            except Exception as e:
                print(f"  [monitor_sims] {sym}: {e}")
        for s in done:
            self.active_sims.pop(s, None)

    async def scan_all(self) -> int:
        coins   = load_coins()
        results = await asyncio.gather(*[self.analyze(s) for s in coins], return_exceptions=True)
        return sum(1 for r in results if isinstance(r, dict))

    async def cmd_add(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not ctx.args:
            await update.message.reply_text("Использование: /add BTCUSDT")
            return
        ok, msg = add_coin(ctx.args[0])
        await update.message.reply_text(msg)

    async def cmd_remove(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not ctx.args:
            await update.message.reply_text("Использование: /remove BTCUSDT")
            return
        ok, msg = remove_coin(ctx.args[0])
        await update.message.reply_text(msg)

    async def cmd_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        coins = load_coins()
        text  = f"📋 Монет в списке: {len(coins)}\n\n" + "\n".join(f"• {c}" for c in sorted(coins))
        await update.message.reply_text(text)

    async def cmd_scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 Запускаю сканирование...")
        n = await self.scan_all()
        await update.message.reply_text(f"✅ Сканирование завершено. Сигналов: {n}")

    async def cmd_sims(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.active_sims:
            await update.message.reply_text("Нет активных симуляций.")
            return
        lines = [f"🧠 Активных симуляций: {len(self.active_sims)}\n"]
        for sym, sim in self.active_sims.items():
            lines.append(f"• {sym} {sim.direction} | Сценарий {sim.winner} | {sim.status}")
        await update.message.reply_text("\n".join(lines))

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🧠 *SMC Full Bot* — команды:\n\n"
            "/add SYMBOL — добавить монету\n"
            "/remove SYMBOL — удалить монету\n"
            "/list — список монет\n"
            "/scan — немедленное сканирование\n"
            "/sims — активные симуляции\n"
            "/help — эта справка\n\n"
            "Бот сканирует автоматически каждую минуту.",
            parse_mode='Markdown'
        )

    async def _scan_loop(self):
        retry = SCAN_INTERVAL
        cycle = 0
        while True:
            try:
                cycle += 1
                coins = load_coins()
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Цикл #{cycle} — {len(coins)} монет")
                n = await self.scan_all()
                print(f"   Сигналов: {n} | Симуляций: {len(self.active_sims)}")
                if cycle % MONITOR_INTERVAL == 0 and self.active_sims:
                    print(f"  🔍 Мониторинг {len(self.active_sims)} симуляций...")
                    await self.monitor_sims()
                retry = SCAN_INTERVAL
                await asyncio.sleep(retry)
            except Exception as e:
                print(f"[loop] Ошибка: {e}. Повтор через {retry}с")
                await asyncio.sleep(retry)
                retry = min(retry * 2, 600)

    async def run(self):
        print("🧠 SMC Full Bot запущен")
        print(f"   Таймфреймы: 4h (bias) → 1h (BOS/CHoCH) → 15m (OB/FVG + подтверждение)")
        print(f"   Ликвидность: Equal Highs/Lows + свинги + округлые числа")
        print(f"   Команды: /add /remove /list /scan /sims /help")
        await self.send(
            "🧠 *SMC Full Bot запущен*\n\n"
            "Таймфреймы: 4h → 1h → 15m\n"
            "Логика: BOS/CHoCH + OB/FVG + ликвидность + паттерн + объём\n"
            "Prediction: симуляция сценариев A/B для каждого сетапа\n\n"
            f"Монет в списке: {len(load_coins())}\n"
            "Используй /help для списка команд"
        )

        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("add",    self.cmd_add))
        app.add_handler(CommandHandler("remove", self.cmd_remove))
        app.add_handler(CommandHandler("list",   self.cmd_list))
        app.add_handler(CommandHandler("scan",   self.cmd_scan))
        app.add_handler(CommandHandler("sims",   self.cmd_sims))
        app.add_handler(CommandHandler("help",   self.cmd_help))

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        await self._scan_loop()


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    bot = SMCFullBot()
    asyncio.run(bot.run())