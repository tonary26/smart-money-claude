from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import telegram

from smc_bot.config import (
    SIM_TTL_HOURS,
    SWEEP_RETURN_PCT,
    VOL_MULT,
    W_CVOL,
    W_HIST,
    W_IATR,
    W_IVOL,
    W_LIQ,
)


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


async def monitor_simulation(sim: Simulation, df_15m: pd.DataFrame,
                             tg: telegram.Bot, chat_id: str, atr: float) -> str:
    price = df_15m['close'].iloc[-1]
    hi    = df_15m['high'].iloc[-1]
    lo    = df_15m['low'].iloc[-1]
    sa, sb = sim.sa, sim.sb

    patterns = _quick_patterns(df_15m, sim.direction)
    vol_ok   = _quick_vol(df_15m)

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

    if sim.status == "a_zone" and not sim.entry_sent:
        in_zone = sa.zone_l <= price <= sa.zone_h
        if in_zone and patterns and vol_ok:
            await _send_entry_confirmed(sim, tg, chat_id, "A", price, patterns, atr)
            sim.entry_sent = True
            return "done"

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
