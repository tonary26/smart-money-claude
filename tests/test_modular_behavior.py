import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BYBIT_API_KEY", "test-bybit-key")
os.environ.setdefault("BYBIT_API_SECRET", "test-bybit-secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "987654")

import pandas as pd

from smc_bot import analysis, app, jobs, simulation


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 12, 10, 20, 30, tzinfo=tz)


def runtime_instance():
    instance = object.__new__(app.SMCFullBot)
    instance.exchange = object()
    instance.tg = object()
    instance.chat_id = "987654"
    instance.last_signals = {}
    instance.active_sims = {}
    instance.send = AsyncMock()
    return instance


class AnalysisOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_keeps_existing_call_order_messages_and_state(self):
        instance = runtime_instance()
        df_4h = pd.DataFrame({"close": [100]})
        df_1h = pd.DataFrame({"close": [100]})
        df_15m = pd.DataFrame({"close": [100]})
        struct = {
            "type": "CHoCH",
            "direction": "LONG",
            "level": 99,
            "impulse_size": 10,
            "swing_high": 105,
            "swing_low": 95,
        }
        zone = {"type": "Бычий OB", "high": 101, "low": 99}
        confirmation = {
            "ok": True,
            "patterns": ["Молот"],
            "vol_ok": True,
            "vol_ratio": 1.5,
        }
        liquidity = {
            "above": [104],
            "below": [],
            "eq_highs": [],
            "eq_lows": [],
            "round_near": [],
        }
        levels = {
            "entry": 100,
            "sl": 98,
            "tp1": 104,
            "tp2": 105,
            "tp3": 110,
            "rr": 2,
        }
        scen_a = simulation.ScenA(prob=0.6)
        scen_b = simulation.ScenB(prob=0.4)

        with (
            patch.object(
                analysis,
                "fetch_ohlcv",
                side_effect=[df_4h, df_1h, df_15m],
            ) as fetch_ohlcv,
            patch.object(analysis, "calc_atr", return_value=2),
            patch.object(analysis, "get_bias_4h", return_value="BULLISH"),
            patch.object(
                analysis,
                "detect_bos_choch_1h",
                return_value=struct,
            ),
            patch.object(analysis, "find_ob", return_value=zone),
            patch.object(analysis, "find_fvg", return_value=None),
            patch.object(
                analysis,
                "check_entry_confirmation",
                return_value=confirmation,
            ),
            patch.object(
                analysis,
                "find_liquidity_zones",
                return_value=liquidity,
            ),
            patch.object(analysis, "calc_levels", return_value=levels),
            patch.object(analysis, "format_signal", return_value="signal"),
            patch.object(
                analysis,
                "score_scenarios",
                return_value=(0.6, 0.4),
            ),
            patch.object(analysis, "build_scen_a", return_value=scen_a),
            patch.object(analysis, "build_scen_b", return_value=scen_b),
            patch.object(
                analysis,
                "format_simulation_msg",
                return_value="simulation",
            ),
            patch.object(analysis, "datetime", FixedDatetime),
            patch("builtins.print"),
        ):
            result = await instance.analyze("BTCUSDT")

        self.assertEqual(
            fetch_ohlcv.call_args_list,
            [
                call(instance.exchange, "BTCUSDT", "4h", 150),
                call(instance.exchange, "BTCUSDT", "1h", 200),
                call(instance.exchange, "BTCUSDT", "15m", 200),
            ],
        )
        self.assertEqual(result, {
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "levels": levels,
        })
        self.assertEqual(
            instance.send.await_args_list,
            [call("signal"), call("simulation")],
        )
        self.assertEqual(
            instance.last_signals,
            {"BTCUSDT_LONG": FixedDatetime(2026, 6, 12, 10, 20, 30)},
        )
        self.assertEqual(instance.active_sims["BTCUSDT"].winner, "A")
        self.assertEqual(instance.active_sims["BTCUSDT"].created, FixedDatetime.now())

    async def test_existing_cooldown_stops_signal_before_sending(self):
        instance = runtime_instance()
        instance.last_signals["BTCUSDT_LONG"] = FixedDatetime.now()
        frame = pd.DataFrame({"close": [100]})

        with (
            patch.object(
                analysis,
                "fetch_ohlcv",
                side_effect=[frame, frame, frame],
            ),
            patch.object(analysis, "calc_atr", return_value=2),
            patch.object(analysis, "get_bias_4h", return_value="BULLISH"),
            patch.object(
                analysis,
                "detect_bos_choch_1h",
                return_value={
                    "direction": "LONG",
                    "impulse_size": 10,
                },
            ),
            patch.object(
                analysis,
                "find_ob",
                return_value={"type": "Бычий OB", "high": 101, "low": 99},
            ),
            patch.object(analysis, "find_fvg", return_value=None),
            patch.object(
                analysis,
                "check_entry_confirmation",
                return_value={
                    "ok": True,
                    "patterns": ["Молот"],
                    "vol_ok": True,
                    "vol_ratio": 1.5,
                },
            ),
            patch.object(
                analysis,
                "find_liquidity_zones",
                return_value={
                    "above": [104],
                    "below": [],
                    "eq_highs": [],
                    "eq_lows": [],
                    "round_near": [],
                },
            ),
            patch.object(
                analysis,
                "calc_levels",
                return_value={"rr": 2},
            ),
            patch.object(analysis, "datetime", FixedDatetime),
        ):
            result = await instance.analyze("BTCUSDT")

        self.assertIsNone(result)
        instance.send.assert_not_awaited()


class JobsTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_all_counts_only_dictionary_results(self):
        instance = runtime_instance()
        instance.analyze = AsyncMock(
            side_effect=[
                {"symbol": "BTCUSDT"},
                None,
                RuntimeError("failed"),
            ]
        )

        with patch.object(
            jobs,
            "load_coins",
            return_value=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        ):
            result = await instance.scan_all()

        self.assertEqual(result, 1)
        self.assertEqual(
            instance.analyze.await_args_list,
            [call("BTCUSDT"), call("ETHUSDT"), call("SOLUSDT")],
        )

    async def test_monitor_sims_removes_done_simulation(self):
        instance = runtime_instance()
        current_simulation = SimpleNamespace(status="watching")
        instance.active_sims = {"BTCUSDT": current_simulation}
        frame = pd.DataFrame({"close": [100]})

        with (
            patch.object(jobs, "fetch_ohlcv", return_value=frame),
            patch.object(jobs, "calc_atr", return_value=2),
            patch.object(
                jobs,
                "monitor_simulation",
                new=AsyncMock(return_value="done"),
            ) as monitor,
        ):
            await instance.monitor_sims()

        monitor.assert_awaited_once_with(
            current_simulation,
            frame,
            instance.tg,
            instance.chat_id,
            2,
        )
        self.assertEqual(instance.active_sims, {})


if __name__ == "__main__":
    unittest.main()
