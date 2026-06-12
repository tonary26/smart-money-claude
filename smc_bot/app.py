import os

import telegram
from telegram.ext import Application, CommandHandler

from smc_bot.analysis import AnalysisMixin
from smc_bot.config import _check_env
from smc_bot.exchange import create_exchange
from smc_bot.handlers import HandlerMixin
from smc_bot.jobs import JobsMixin
from smc_bot.state import ActiveSimulations, LastSignals
from smc_bot.watchlist import load_coins


class SMCFullBot(AnalysisMixin, HandlerMixin, JobsMixin):
    def __init__(self):
        _check_env()
        self.exchange = create_exchange()
        self.token    = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id  = os.getenv('TELEGRAM_CHAT_ID')
        self.tg       = telegram.Bot(token=self.token)
        self.last_signals: LastSignals = {}
        self.active_sims: ActiveSimulations = {}
        print("🧠 SMC Full Bot инициализирован")
        print(f"   Монет в списке: {len(load_coins())}")

    async def send(self, text: str):
        await self.tg.send_message(chat_id=self.chat_id, text=text, parse_mode='Markdown')

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
