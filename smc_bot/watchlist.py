import json

from smc_bot.config import COINS_FILE, DEFAULT_COINS


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
