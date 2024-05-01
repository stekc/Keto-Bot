import os

import aiohttp
from discord.ext import commands, tasks


class Topgg(commands.Cog, name="topgg"):
    def __init__(self, bot):
        self.bot = bot
        self.update_topgg.start()

    @tasks.loop(minutes=5.0)
    async def update_topgg(self):
        await self.topgg_refresh()

    async def topgg_refresh(self):
        if os.getenv("TOPGG_TOKEN"):
            url = "https://botblock.org/api/count"
            data = {
                "server_count": len(self.bot.guilds),
                "bot_id": f"{self.bot.user.id}",
                "top.gg": os.getenv("TOPGG_TOKEN"),
            }
            if data["server_count"] == 0:
                return

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    data = await response.json()
                    return data


async def setup(bot):
    await bot.add_cog(Topgg(bot))
