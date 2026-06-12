import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BYBIT_API_KEY", "test-bybit-key")
os.environ.setdefault("BYBIT_API_SECRET", "test-bybit-secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "987654")

import pandas as pd

import bot


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 12, 10, 20, 30, tzinfo=tz)


def make_update():
    return SimpleNamespace(
        message=SimpleNamespace(reply_text=AsyncMock())
    )


class ConfigurationTests(unittest.TestCase):
    def test_constants_and_default_coins_are_pinned(self):
        expected_constants = {
            "ATR_PERIOD": 14,
            "SWING_WINDOW_4H": 5,
            "SWING_WINDOW_1H": 5,
            "SWING_WINDOW_15M": 4,
            "EQL_TOLERANCE": 0.001,
            "OB_LOOKBACK": 40,
            "FVG_MIN_ATR": 0.25,
            "VOL_MULT": 1.3,
            "CHOCH_LOOKBACK": 30,
            "MIN_RR": 1.5,
            "SIGNAL_COOLDOWN": 7200,
            "SCAN_INTERVAL": 60,
            "MONITOR_INTERVAL": 5,
            "SIM_TTL_HOURS": 48,
            "SWEEP_MIN_ATR": 0.3,
            "SWEEP_MAX_ATR": 1.8,
            "SWEEP_RETURN_PCT": 0.003,
            "W_LIQ": 0.30,
            "W_IVOL": 0.20,
            "W_IATR": 0.20,
            "W_HIST": 0.15,
            "W_CVOL": 0.15,
        }

        for name, expected in expected_constants.items():
            self.assertEqual(getattr(bot, name), expected)

        self.assertEqual(
            bot.DEFAULT_COINS,
            [
                "BTCUSDT",
                "ETHUSDT",
                "SOLUSDT",
                "BNBUSDT",
                "TONUSDT",
                "TAOUSDT",
                "HYPEUSDT",
                "ENAUSDT",
                "WLDUSDT",
                "ADAUSDT",
                "AVAXUSDT",
                "DOGEUSDT",
            ],
        )

    def test_missing_environment_names_are_reported_in_existing_order(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                EnvironmentError,
                "Нет переменных: BYBIT_API_KEY, BYBIT_API_SECRET, "
                "TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID",
            ):
                bot._check_env()


class WatchlistTests(unittest.TestCase):
    def test_missing_file_creates_existing_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coins.json"
            with patch.object(bot, "COINS_FILE", path):
                result = bot.load_coins()

            self.assertEqual(result, bot.DEFAULT_COINS)
            self.assertEqual(json.loads(path.read_text()), sorted(bot.DEFAULT_COINS))

    def test_invalid_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coins.json"
            path.write_text("{invalid")
            with patch.object(bot, "COINS_FILE", path):
                result = bot.load_coins()

            self.assertEqual(result, bot.DEFAULT_COINS)

    def test_add_and_remove_keep_existing_normalization_and_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coins.json"
            path.write_text('["BTCUSDT"]')

            with patch.object(bot, "COINS_FILE", path):
                self.assertEqual(
                    bot.add_coin(" eth "),
                    (True, "ETHUSDT добавлен ✅"),
                )
                self.assertEqual(
                    bot.add_coin("ethusdt"),
                    (False, "ETHUSDT уже в списке"),
                )
                self.assertEqual(
                    bot.remove_coin("btc"),
                    (True, "BTCUSDT удалён ✅"),
                )
                self.assertEqual(
                    bot.remove_coin("btc"),
                    (False, "BTCUSDT не найден в списке"),
                )

            self.assertEqual(json.loads(path.read_text()), ["ETHUSDT"])


class AnalysisFunctionTests(unittest.TestCase):
    def test_atr_and_swings_match_existing_results(self):
        atr_df = pd.DataFrame({
            "high": list(range(11, 27)),
            "low": list(range(9, 25)),
            "close": list(range(10, 26)),
        })
        self.assertEqual(bot.calc_atr(atr_df), 2.0)

        swing_df = pd.DataFrame({
            "ts": pd.date_range("2026-01-01", periods=5, freq="h"),
            "high": [1, 2, 5, 2, 1],
            "low": [5, 4, 1, 4, 5],
        })
        self.assertEqual(
            bot.get_swing_highs(swing_df, 2),
            [{"idx": 2, "price": 5, "ts": swing_df["ts"].iloc[2]}],
        )
        self.assertEqual(
            bot.get_swing_lows(swing_df, 2),
            [{"idx": 2, "price": 1, "ts": swing_df["ts"].iloc[2]}],
        )

    def test_level_calculation_is_pinned(self):
        levels = bot.calc_levels(
            "LONG",
            100,
            {"low": 95, "high": 101},
            {"impulse_size": 20},
            {"above": [110, 120], "below": []},
            2,
        )

        self.assertEqual(
            levels,
            {
                "entry": 100,
                "sl": 94.2,
                "tp1": 110,
                "tp2": 120,
                "tp3": 120,
                "rr": 1.72,
            },
        )

    def test_signal_message_is_exact(self):
        struct = {
            "type": "CHoCH",
            "level": 101.5,
        }
        zone = {
            "type": "Бычий OB",
            "low": 99.0,
            "high": 100.5,
        }
        confirmation = {
            "patterns": ["Молот"],
            "vol_ok": True,
            "vol_ratio": 1.7,
        }
        levels = {
            "entry": 100.0,
            "sl": 98.0,
            "tp1": 104.0,
            "tp2": 106.0,
            "tp3": 108.0,
            "rr": 2.0,
        }
        liquidity = {
            "above": [104.0, 106.0],
            "below": [],
            "eq_highs": [105.0],
            "eq_lows": [],
            "round_near": [110.0, 90.0],
        }
        expected = (
            "🟢 *SMC ЛОНГ* — BTCUSDT\n\n"
            "💪 Сила: 🔥 СИЛЬНЫЙ\n\n"
            "*Структура:*\n"
            "⚡ CHoCH на 1h: уровень `101.5`\n"
            "📐 4h Bias: BULLISH\n"
            "📏 ATR(14): `1.25`\n\n"
            "*Зона входа на 15м:*\n"
            "📦 Бычий OB: `99.0` – `100.5`\n\n"
            "*Подтверждение:*\n"
            "✅ Паттерны: Молот\n"
            "✅ Объём: x1.7 от среднего\n\n"
            "*Ликвидность (цели):*\n"
            "💧 `104.0` → `106.0`\n"
            "📊 Equal Highs: `105.0`\n"
            "🔵 Округлые уровни: `110.0`\n\n"
            "*Уровни:*\n"
            "🎯 Вход:  `100.0`\n"
            "🛑 SL:    `98.0`\n"
            "✅ TP1:   `104.0`\n"
            "✅ TP2:   `106.0`\n"
            "✅ TP3:   `108.0`\n"
            "⚖️  R:R:   `2.0`\n\n"
            "🕐 12.06 10:20 UTC"
        )

        with patch.object(bot, "datetime", FixedDatetime):
            actual = bot.format_signal(
                "BTCUSDT",
                "LONG",
                "BULLISH",
                struct,
                zone,
                confirmation,
                levels,
                liquidity,
                1.25,
            )

        self.assertEqual(actual, expected)


class SimulationTests(unittest.TestCase):
    def test_dataclass_defaults_and_simulation_message_are_exact(self):
        self.assertEqual(bot.ScenA().prob, 0.5)
        self.assertEqual(bot.ScenB().triggered, False)

        simulation = bot.Simulation(
            symbol="BTCUSDT",
            direction="LONG",
            created=datetime(2026, 6, 12, 10, 0, 0),
            struct={},
            zone={},
            liquidity={},
            atr=1.25,
            sa=bot.ScenA(
                zone_h=101.0,
                zone_l=99.0,
                zone_mid=100.0,
                zone_type="Бычий OB",
                ret_pct=50.0,
                prob=0.6,
            ),
            sb=bot.ScenB(
                sweep_tgt=97.0,
                depth_atr=0.8,
                entry_ret=99.0,
                prob=0.4,
            ),
            winner="A",
        )

        self.assertEqual(
            bot.format_simulation_msg("BTCUSDT", simulation),
            "🧠 *Симуляция запущена* — BTCUSDT\n\n"
            "🟢 Направление: *LONG*\n"
            "ATR(14): `1.25`\n\n"
            "*Сценарий A* _60%_ — чистый откат\n"
            "Зона: `99.0` – `101.0` (Бычий OB)\n"
            "Откат 50.0% от импульса\n\n"
            "*Сценарий B* _40%_ — вынос стопов\n"
            "Sweep → `97.0` (-0.8x ATR ниже свинга)\n"
            "Вход после возврата: `99.0`\n\n"
            "Победитель: *A — откат (60%)*\n"
            "_Мониторинг каждые 5 минут_",
        )


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_constructor_uses_existing_bybit_and_telegram_arguments(self):
        exchange = object()
        telegram_bot = object()

        with (
            patch.object(bot, "_check_env") as check_env,
            patch.object(bot.ccxt, "bybit", return_value=exchange) as bybit,
            patch.object(bot.telegram, "Bot", return_value=telegram_bot) as tg,
            patch.object(bot, "load_coins", return_value=["BTCUSDT"]),
            patch("builtins.print"),
        ):
            instance = bot.SMCFullBot()

        check_env.assert_called_once_with()
        bybit.assert_called_once_with({
            "apiKey": os.getenv("BYBIT_API_KEY"),
            "secret": os.getenv("BYBIT_API_SECRET"),
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        tg.assert_called_once_with(token=os.getenv("TELEGRAM_BOT_TOKEN"))
        self.assertIs(instance.exchange, exchange)
        self.assertIs(instance.tg, telegram_bot)
        self.assertEqual(instance.last_signals, {})
        self.assertEqual(instance.active_sims, {})

    async def test_command_replies_are_exact(self):
        instance = object.__new__(bot.SMCFullBot)

        update = make_update()
        await instance.cmd_add(update, SimpleNamespace(args=[]))
        update.message.reply_text.assert_awaited_once_with(
            "Использование: /add BTCUSDT"
        )

        update = make_update()
        with patch.object(bot, "load_coins", return_value=["ETHUSDT", "BTCUSDT"]):
            await instance.cmd_list(update, SimpleNamespace())
        update.message.reply_text.assert_awaited_once_with(
            "📋 Монет в списке: 2\n\n• BTCUSDT\n• ETHUSDT"
        )

        update = make_update()
        instance.active_sims = {}
        await instance.cmd_sims(update, SimpleNamespace())
        update.message.reply_text.assert_awaited_once_with(
            "Нет активных симуляций."
        )

    async def test_run_keeps_startup_message_handler_order_and_polling(self):
        instance = object.__new__(bot.SMCFullBot)
        instance.token = os.getenv("TELEGRAM_BOT_TOKEN")
        instance.send = AsyncMock()
        instance._scan_loop = AsyncMock()

        application = MagicMock()
        application.initialize = AsyncMock()
        application.start = AsyncMock()
        application.updater = SimpleNamespace(start_polling=AsyncMock())

        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = application

        with (
            patch.object(bot.Application, "builder", return_value=builder),
            patch.object(
                bot,
                "CommandHandler",
                side_effect=lambda command, callback: (command, callback),
            ),
            patch.object(bot, "load_coins", return_value=["BTCUSDT"]),
            patch("builtins.print"),
        ):
            await instance.run()

        instance.send.assert_awaited_once_with(
            "🧠 *SMC Full Bot запущен*\n\n"
            "Таймфреймы: 4h → 1h → 15m\n"
            "Логика: BOS/CHoCH + OB/FVG + ликвидность + паттерн + объём\n"
            "Prediction: симуляция сценариев A/B для каждого сетапа\n\n"
            "Монет в списке: 1\n"
            "Используй /help для списка команд"
        )
        self.assertEqual(
            application.add_handler.call_args_list,
            [
                call(("add", instance.cmd_add)),
                call(("remove", instance.cmd_remove)),
                call(("list", instance.cmd_list)),
                call(("scan", instance.cmd_scan)),
                call(("sims", instance.cmd_sims)),
                call(("help", instance.cmd_help)),
            ],
        )
        application.initialize.assert_awaited_once_with()
        application.start.assert_awaited_once_with()
        application.updater.start_polling.assert_awaited_once_with(
            drop_pending_updates=True
        )
        instance._scan_loop.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
