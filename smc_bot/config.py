import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _check_env():
    missing = [k for k in ['BYBIT_API_KEY', 'BYBIT_API_SECRET', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'] if not os.getenv(k)]
    if missing:
        raise EnvironmentError(f"Нет переменных: {', '.join(missing)}")


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
