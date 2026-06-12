import os

import ccxt
import pandas as pd


def create_exchange():
    return ccxt.bybit({
        'apiKey':          os.getenv('BYBIT_API_KEY'),
        'secret':          os.getenv('BYBIT_API_SECRET'),
        'enableRateLimit': True,
        'options':         {'defaultType': 'future'},
    })


def fetch_ohlcv(exchange, symbol: str, tf: str, limit: int = 200) -> pd.DataFrame | None:
    try:
        data = exchange.fetch_ohlcv(symbol, tf, limit=limit)
        df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df.reset_index(drop=True)
    except Exception as e:
        print(f"  [fetch] {symbol} {tf}: {e}")
        return None
