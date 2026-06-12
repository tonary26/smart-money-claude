from telegram import Update
from telegram.ext import ContextTypes

from smc_bot.watchlist import add_coin, load_coins, remove_coin


class HandlerMixin:
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
