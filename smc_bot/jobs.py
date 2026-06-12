import asyncio
from datetime import datetime

from smc_bot.analysis import calc_atr
from smc_bot.config import MONITOR_INTERVAL, SCAN_INTERVAL
from smc_bot.exchange import fetch_ohlcv
from smc_bot.simulation import monitor_simulation
from smc_bot.watchlist import load_coins


class JobsMixin:
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
