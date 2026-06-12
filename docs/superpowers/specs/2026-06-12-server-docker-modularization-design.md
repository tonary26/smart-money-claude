# Server Docker Modularization Design

## Goal

Prepare the existing Telegram bot for deployment on a Beget Linux VPS with
Docker Compose and split the 1199-line `bot.py` into focused modules without
changing any bot logic or observable behavior.

## Non-negotiable Behavior Contract

The refactor must preserve:

- every formula, threshold, condition, return value, and calculation order;
- every constant and interval;
- every Telegram command, reply, signal, emoji, and Markdown fragment;
- the A/B simulation construction and monitoring state transitions;
- the sequence of exchange requests, analysis steps, messages, and cooldown
  writes;
- the current exception handling and console output;
- the `coins.json` format, normalization, sorting, defaults, and fallback
  behavior;
- Telegram polling with `drop_pending_updates=True`;
- the current startup message and startup sequence.

No new command, access restriction, validation rule, trading rule, retry rule,
logging framework, database, web interface, or health endpoint will be added.

## Architectural Reference

Use the responsibility boundaries from
`C:\Users\Lenovo\Desktop\smart_money\smart-money`:

- `config.py`
- `exchange.py`
- `watchlist.py`
- `state.py`
- `analysis.py`
- `handlers.py`
- `jobs.py`
- `app.py`

Only the boundaries are reused. No trading or Telegram logic is copied from
that bot. The current project also needs `simulation.py` because its existing
prediction engine is a separate responsibility.

## Target Structure

```text
bot.py
smc_bot/
  __init__.py
  config.py
  exchange.py
  watchlist.py
  state.py
  analysis.py
  simulation.py
  handlers.py
  jobs.py
  app.py
tests/
Dockerfile
compose.yaml
.dockerignore
.env.example
.gitignore
README.md
coins.json
```

## Module Responsibilities

### `smc_bot/config.py`

Load `.env`, perform the existing environment check, and expose the existing
constants with their current values.

### `smc_bot/exchange.py`

Create the existing `ccxt.bybit` client with the same options and credentials.
Keep market-data fetching behavior unchanged.

### `smc_bot/watchlist.py`

Contain the existing `load_coins`, `save_coins`, `add_coin`, and `remove_coin`
functions. Continue using `coins.json`.

### `smc_bot/state.py`

Contain mutable runtime state currently owned by `SMCFullBot`: signal cooldown
timestamps and active simulations. It must not change lifecycle or persistence.

### `smc_bot/analysis.py`

Contain the existing ATR, swing, bias, BOS/CHoCH, OB, FVG, liquidity,
confirmation, levels, signal formatting, and symbol-analysis logic.

### `smc_bot/simulation.py`

Contain the existing `ScenA`, `ScenB`, and `Simulation` dataclasses plus
scenario scoring, construction, formatting, monitoring, quick confirmation,
and confirmed-entry message logic.

### `smc_bot/handlers.py`

Contain the existing Telegram command handlers with identical replies and
argument behavior.

### `smc_bot/jobs.py`

Contain the existing scan, simulation-monitoring, and infinite scan-loop
behavior with the same intervals and retry handling.

### `smc_bot/app.py`

Own bot construction, startup messaging, Telegram handler registration,
polling initialization, and application startup in the current order.

### `bot.py`

Remain a thin executable entry point that applies `nest_asyncio`, creates the
bot, and starts the same asynchronous run path.

## Behavior Verification

Before moving production code, characterization tests will import the current
monolith and pin representative behavior:

- environment validation;
- coin-file loading, fallback, saving, addition, and removal;
- pure analysis functions and dataclass defaults;
- exact signal and simulation message text under fixed timestamps;
- command replies and handler registration order;
- scan and monitor orchestration;
- startup and polling settings.

The tests must initially pass against the monolith. During extraction,
compatibility imports in `bot.py` will keep the same public symbols available
until all tests pass against the modular package.

## Docker Deployment

Use one Python 3.11 container:

- install the existing dependencies from pinned `requirements.txt`;
- load secrets from a server-side `.env`;
- run the existing bot entry point;
- use `init: true`;
- use `restart: unless-stopped`;
- bind-mount `coins.json` so Telegram changes survive rebuilds;
- expose no ports because Telegram polling and Bybit access are outbound.

The deployment target is a Beget cloud VPS/VDS with Docker and Docker Compose,
not shared web hosting.

## Secret Handling

The real `.env` must remain on the local machine and server but stop being
tracked by Git. `.env.example` will contain only empty variable names. Existing
credentials should be rotated because removing `.env` from the current revision
does not remove secrets from prior Git history.

## Documentation

`README.md` will contain exact Beget VPS commands for cloning, configuring
`.env`, building, starting, checking logs, restarting, updating, stopping, and
backing up `coins.json`.

## Acceptance Criteria

1. Characterization tests pass before and after extraction.
2. All Python files compile.
3. `docker compose config` succeeds with a test environment file.
4. The image builds when a Docker daemon is available.
5. `git diff --check` succeeds.
6. Review of the final diff shows only relocation, imports, deployment files,
   tests, and documentation, with no changed bot behavior.
