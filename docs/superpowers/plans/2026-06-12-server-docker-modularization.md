# Server Docker Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the existing Telegram bot on a Beget Docker VPS and split `bot.py` into a package without changing calculations, messages, commands, timing, state ownership, or control flow.

**Architecture:** Preserve `SMCFullBot` as the runtime owner of exchange, Telegram, cooldown, and simulation state. Move existing methods into `AnalysisMixin`, `HandlerMixin`, and `JobsMixin`; move pure functions into responsibility-specific modules; compose the same class in `smc_bot/app.py`. Keep `bot.py` as the executable compatibility entry point.

**Tech Stack:** Python 3.11, ccxt, pandas, NumPy, python-telegram-bot, python-dotenv, nest_asyncio, unittest, Docker, Docker Compose.

---

## File Map

- Create `smc_bot/config.py`: existing environment loading, validation, and constants.
- Create `smc_bot/exchange.py`: existing Bybit client construction and `fetch_ohlcv`.
- Create `smc_bot/watchlist.py`: unchanged `coins.json` functions.
- Create `smc_bot/state.py`: type aliases for instance-owned runtime dictionaries.
- Create `smc_bot/simulation.py`: unchanged scenario dataclasses and functions.
- Create `smc_bot/analysis.py`: unchanged market-analysis functions and `analyze` method body.
- Create `smc_bot/handlers.py`: unchanged Telegram command method bodies.
- Create `smc_bot/jobs.py`: unchanged scan and monitor method bodies.
- Create `smc_bot/app.py`: `SMCFullBot` construction, sending, startup, registration, and polling.
- Modify `bot.py`: import/re-export `SMCFullBot` and execute the same `nest_asyncio`/`asyncio.run` startup.
- Create `tests/test_monolith_characterization.py`: behavior snapshots against the original monolith.
- Create `tests/test_package_contract.py`: package import and architecture contract.
- Create `tests/test_modular_behavior.py`: the same behavior snapshots against extracted modules.
- Create `tests/test_deployment.py`: Docker and secret-handling contract.
- Create `Dockerfile`, `compose.yaml`, `.dockerignore`, `.gitignore`, `.env.example`, `README.md`.
- Stop tracking `.env` while keeping the local file.

### Task 1: Pin Existing Behavior

**Files:**
- Create: `tests/test_monolith_characterization.py`

- [ ] **Step 1: Write characterization tests for the current monolith**

Tests must set non-secret environment defaults before importing `bot`, use
temporary `coins.json` files, fixed timestamps, fake exchanges, and async fake
Telegram objects. They must assert:

```python
EXPECTED_CONSTANTS = {
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
}
```

Also pin coin normalization/sorting, ATR and swing results, level calculation,
exact formatted signal/simulation text, scenario dataclass defaults, command
replies, Bybit constructor arguments, startup handler order, and polling with
`drop_pending_updates=True`.

- [ ] **Step 2: Run the characterization suite**

Run:

```powershell
python -m unittest tests.test_monolith_characterization -v
```

Expected: all tests pass against the unchanged `bot.py`.

- [ ] **Step 3: Commit the behavior baseline**

```powershell
git add tests/test_monolith_characterization.py
git commit -m "test: pin existing bot behavior"
```

### Task 2: Create a Failing Modular Architecture Contract

**Files:**
- Create: `tests/test_package_contract.py`

- [ ] **Step 1: Write the package import contract**

```python
MODULES = [
    "smc_bot.config",
    "smc_bot.exchange",
    "smc_bot.watchlist",
    "smc_bot.state",
    "smc_bot.analysis",
    "smc_bot.simulation",
    "smc_bot.handlers",
    "smc_bot.jobs",
    "smc_bot.app",
]

def test_expected_modules_are_importable(self):
    for module in MODULES:
        importlib.import_module(module)
```

Assert that `smc_bot.app.SMCFullBot` exposes `analyze`, all six command
handlers, `monitor_sims`, `scan_all`, `_scan_loop`, `send`, and `run`.

- [ ] **Step 2: Run the contract and verify RED**

Run:

```powershell
python -m unittest tests.test_package_contract -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'smc_bot'`.

- [ ] **Step 3: Commit the failing contract**

```powershell
git add tests/test_package_contract.py
git commit -m "test: define modular package contract"
```

### Task 3: Extract Configuration, Exchange, Watchlist, and State

**Files:**
- Create: `smc_bot/__init__.py`
- Create: `smc_bot/config.py`
- Create: `smc_bot/exchange.py`
- Create: `smc_bot/watchlist.py`
- Create: `smc_bot/state.py`

- [ ] **Step 1: Move environment code and constants unchanged**

`config.py` must contain the existing `load_dotenv()`, `_check_env()`,
`COINS_FILE`, all numeric constants, weights, and `DEFAULT_COINS` values.

- [ ] **Step 2: Move exchange code unchanged**

```python
def create_exchange():
    return ccxt.bybit({
        "apiKey": os.getenv("BYBIT_API_KEY"),
        "secret": os.getenv("BYBIT_API_SECRET"),
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
```

Move `fetch_ohlcv` without changing its body.

- [ ] **Step 3: Move watchlist functions unchanged**

Move `load_coins`, `save_coins`, `add_coin`, and `remove_coin` with the same
JSON operations, normalization, messages, sorting, and fallback.

- [ ] **Step 4: Preserve instance-owned state types**

`state.py` defines only:

```python
from datetime import datetime
from typing import TypeAlias

from smc_bot.simulation import Simulation

LastSignals: TypeAlias = dict[str, datetime]
ActiveSimulations: TypeAlias = dict[str, Simulation]
```

No global mutable bot state is introduced.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest tests.test_monolith_characterization tests.test_package_contract -v
```

Expected: package-contract imports advance past these modules; the complete
contract remains red until all modules exist. Monolith tests remain green.

### Task 4: Extract Simulation and Analysis

**Files:**
- Create: `smc_bot/simulation.py`
- Create: `smc_bot/analysis.py`

- [ ] **Step 1: Move simulation code without edits to formulas or messages**

Move `ScenA`, `ScenB`, `Simulation`, `_liq_above_swing`,
`score_scenarios`, `build_scen_a`, `build_scen_b`,
`format_simulation_msg`, `monitor_simulation`, `_send_entry_confirmed`,
`_quick_patterns`, and `_quick_vol`.

- [ ] **Step 2: Move pure analysis functions unchanged**

Move `calc_atr`, swing functions, bias, BOS/CHoCH, OB, FVG, liquidity,
confirmation, levels, and `format_signal`. Import `fetch_ohlcv` from
`smc_bot.exchange`.

- [ ] **Step 3: Move the existing `analyze` body into a mixin**

```python
class AnalysisMixin:
    async def analyze(self, symbol: str) -> dict | None:
        try:
            df_4h = fetch_ohlcv(self.exchange, symbol, "4h", 150)
            df_1h = fetch_ohlcv(self.exchange, symbol, "1h", 200)
            df_15m = fetch_ohlcv(self.exchange, symbol, "15m", 200)
```

Continue with the complete existing body from `bot.py:997` through
`bot.py:1074`; only symbol-resolution imports change. The operation order and
method body do not.

- [ ] **Step 4: Add modular behavior tests and verify GREEN**

Create `tests/test_modular_behavior.py` by applying the characterization
assertions to `smc_bot.analysis`, `smc_bot.simulation`,
`smc_bot.watchlist`, and the composed class.

Run:

```powershell
python -m unittest tests.test_modular_behavior -v
```

Expected: analysis and simulation snapshots pass.

### Task 5: Extract Handlers, Jobs, and Application

**Files:**
- Create: `smc_bot/handlers.py`
- Create: `smc_bot/jobs.py`
- Create: `smc_bot/app.py`
- Modify: `bot.py`

- [ ] **Step 1: Move command handlers into `HandlerMixin`**

Move `cmd_add`, `cmd_remove`, `cmd_list`, `cmd_scan`, `cmd_sims`, and
`cmd_help` without changing their bodies or reply arguments.

- [ ] **Step 2: Move jobs into `JobsMixin`**

Move `monitor_sims`, `scan_all`, and `_scan_loop` without changing their
bodies.

- [ ] **Step 3: Compose the original runtime class**

```python
class SMCFullBot(AnalysisMixin, HandlerMixin, JobsMixin):
    def __init__(self):
        _check_env()
        self.exchange = create_exchange()
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.tg = telegram.Bot(token=self.token)
        self.last_signals = {}
        self.active_sims = {}
        print("🧠 SMC Full Bot инициализирован")
        print(f"   Монет в списке: {len(load_coins())}")
```

Move `send` and `run` with the same bodies and startup order.

- [ ] **Step 4: Replace `bot.py` with a compatibility entry point**

```python
import asyncio
import nest_asyncio

from smc_bot.app import SMCFullBot

if __name__ == "__main__":
    nest_asyncio.apply()
    bot = SMCFullBot()
    asyncio.run(bot.run())
```

- [ ] **Step 5: Run all Python behavior tests**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all monolith snapshots ported to modular assertions pass, and the
package contract turns green.

- [ ] **Step 6: Commit the extraction**

```powershell
git add bot.py smc_bot tests
git commit -m "refactor: split bot into modules without behavior changes"
```

### Task 6: Add Docker and Beget Deployment Files

**Files:**
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `.dockerignore`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Modify Git index: `.env`
- Modify: `requirements.txt`
- Create: `tests/test_deployment.py`

- [ ] **Step 1: Pin the locally verified dependency versions**

Read installed versions with:

```powershell
python -m pip show ccxt pandas numpy python-telegram-bot python-dotenv nest-asyncio
```

Write exact versions to `requirements.txt` so the server runtime matches the
verified local runtime.

- [ ] **Step 2: Write the container image**

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY smc_bot ./smc_bot
COPY coins.json .

CMD ["python", "bot.py"]
```

- [ ] **Step 3: Write Compose with persistent `coins.json`**

```yaml
services:
  bot:
    build:
      context: .
    image: smc-full-bot:latest
    env_file:
      - .env
    init: true
    restart: unless-stopped
    stop_grace_period: 30s
    volumes:
      - type: bind
        source: ./coins.json
        target: /app/coins.json
```

- [ ] **Step 4: Protect secrets**

Add `.env`, virtual environments, caches, IDE files, `.dual-graph`, and
`.impeccable` to `.gitignore` and `.dockerignore`. Create `.env.example` with
four empty variable assignments. Run:

```powershell
git rm --cached -- .env
```

This must keep the local `.env` file present.

- [ ] **Step 5: Document Beget VPS deployment**

Document creation of a Beget cloud VPS with the Docker image, SSH clone,
`.env` setup, `docker compose up -d --build`, logs, restart, update, stop,
backup of `coins.json`, and credential rotation.

- [ ] **Step 6: Write and run deployment contract tests**

`tests/test_deployment.py` verifies that Compose has no published ports,
uses `.env`, `init: true`, `restart: unless-stopped`, and bind-mounts
`coins.json`; it also verifies `.env` is ignored and `.env.example` has no
values.

Run:

```powershell
python -m unittest tests.test_deployment -v
```

Expected: all deployment contract tests pass.

- [ ] **Step 7: Commit deployment support**

```powershell
git add .gitignore .dockerignore .env.example Dockerfile compose.yaml README.md requirements.txt tests/test_deployment.py
git commit -m "build: add Beget Docker deployment"
```

### Task 7: Final Verification

- [ ] **Step 1: Run the complete test suite**

```powershell
python -m unittest discover -s tests -v
```

Expected: zero failures and zero errors.

- [ ] **Step 2: Compile all Python code**

```powershell
python -m compileall bot.py smc_bot tests
```

Expected: exit code 0.

- [ ] **Step 3: Validate Compose**

```powershell
docker compose --env-file .env.example config
```

Expected: resolved configuration with one service, no published ports, and the
`coins.json` bind mount.

- [ ] **Step 4: Build the image when Docker is available**

```powershell
docker build -t smc-full-bot:local .
```

Expected: image build succeeds. If the daemon is unavailable, report that
specific limitation and retain successful static Compose validation.

- [ ] **Step 5: Check diff and repository state**

```powershell
git diff --check HEAD~3..HEAD
git status --short
git ls-files .env
Test-Path .env
```

Expected: no whitespace errors, `.env` absent from tracked files, and the local
`.env` still exists.

- [ ] **Step 6: Review behavior preservation**

Compare the final modules against the original commit `b5204ca:bot.py` and
confirm that all formulas, constants, strings, command names, handler order,
polling options, and loop intervals are represented without semantic edits.
