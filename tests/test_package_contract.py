import importlib
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BYBIT_API_KEY", "test-bybit-key")
os.environ.setdefault("BYBIT_API_SECRET", "test-bybit-secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "987654")


class PackageContractTests(unittest.TestCase):
    def test_expected_modules_are_importable(self):
        modules = [
            "smc_bot.config",
            "smc_bot.exchange",
            "smc_bot.watchlist",
            "smc_bot.simulation",
            "smc_bot.state",
            "smc_bot.analysis",
            "smc_bot.handlers",
            "smc_bot.jobs",
            "smc_bot.app",
        ]

        for module in modules:
            with self.subTest(module=module):
                importlib.import_module(module)

    def test_composed_bot_exposes_existing_runtime_surface(self):
        from smc_bot.app import SMCFullBot

        expected_methods = [
            "analyze",
            "cmd_add",
            "cmd_remove",
            "cmd_list",
            "cmd_scan",
            "cmd_sims",
            "cmd_help",
            "monitor_sims",
            "scan_all",
            "_scan_loop",
            "send",
            "run",
        ]

        for method in expected_methods:
            with self.subTest(method=method):
                self.assertTrue(callable(getattr(SMCFullBot, method)))


if __name__ == "__main__":
    unittest.main()
