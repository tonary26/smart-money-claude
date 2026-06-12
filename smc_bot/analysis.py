from datetime import datetime, timezone

import pandas as pd

from smc_bot.config import (
    ATR_PERIOD,
    CHOCH_LOOKBACK,
    EQL_TOLERANCE,
    FVG_MIN_ATR,
    MIN_RR,
    OB_LOOKBACK,
    ROUND_NUM_DIGITS,
    SIGNAL_COOLDOWN,
    SWING_WINDOW_15M,
    SWING_WINDOW_1H,
    SWING_WINDOW_4H,
    VOL_MULT,
)
from smc_bot.exchange import fetch_ohlcv
from smc_bot.simulation import (
    Simulation,
    build_scen_a,
    build_scen_b,
    format_simulation_msg,
    score_scenarios,
)


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


class AnalysisMixin:
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
