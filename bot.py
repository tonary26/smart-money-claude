import asyncio
import nest_asyncio

from smc_bot.app import SMCFullBot


if __name__ == "__main__":
    nest_asyncio.apply()
    bot = SMCFullBot()
    asyncio.run(bot.run())
