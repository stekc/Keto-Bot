import os

import aiohttp
from discord.ext import commands, tasks


class Healthchecks(commands.Cog, name="healthchecks"):
    def __init__(self, bot):
        self.bot = bot
        self.healthchecks.start()

    @tasks.loop(minutes=5.0)
    async def healthchecks(self):
        await self.update_healthchecks()

    async def update_healthchecks(self):
        if os.getenv("HEALTHCHECKS_URL"):
            async with aiohttp.ClientSession() as session:
                async with session.get(os.environ.get("HEALTHCHECKS_URL")) as response:
                    if not response.status == 200:
                        print("Healthchecks.io ping failed.", response.status)


async def setup(bot):
    await bot.add_cog(Healthchecks(bot))
