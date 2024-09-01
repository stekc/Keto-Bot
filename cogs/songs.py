import json
import re
from contextlib import suppress

import aiohttp
import discord
from discord.ext import commands

from utils.colorthief import get_color

platforms = {
    "spotify": {"name": "Spotify", "emote": "<:Music_Spotify:958786315883794532>"},
    "appleMusic": {
        "name": "Apple Music",
        "emote": "<:Music_AppleMusic:958786213337264169>",
    },
    "youtube": {"name": "YouTube", "emote": "<:Music_YouTube:958786388457840700>"},
}


class Songs(commands.Cog, name="songs"):
    def __init__(self, bot):
        self.bot = bot
        self.pattern = re.compile(
            r"https:\/\/(open\.spotify\.com\/track\/[A-Za-z0-9]+|"
            r"music\.apple\.com\/[a-zA-Z]{2}\/album\/[a-zA-Z\d%\(\)-]+\/[\d]{1,10}\?i=[\d]{1,15}|"
            r"spotify\.link\/[A-Za-z0-9]+|"
            r"youtu\.be\/[A-Za-z0-9_-]{11}|"
            r"(?:www\.|m\.)?youtube\.com\/watch\?v=[A-Za-z0-9_-]{11}|"
            r"music\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11})"
        )
        self.suppress_embed_pattern = re.compile(
            r"https:\/\/(open\.spotify\.com\/track\/[A-Za-z0-9]+|"
            r"music\.apple\.com\/[a-zA-Z]{2}\/album\/[a-zA-Z\d%\(\)-]+\/[\d]{1,10}\?i=[\d]{1,15}|"
            r"spotify\.link\/[A-Za-z0-9]+|"
            r"music\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11})"
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        if match := self.pattern.search(message.content.strip("<>")):
            link = match.group(0)
            await self.generate_view(message, link)
            return

    async def generate_view(self, message: discord.Message, link: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.song.link/v1-alpha.1/links?url={link}"
            ) as resp:
                if resp.status != 200:
                    return None

                res = await resp.text()
                res = json.loads(res)

        spotify_data = res.get("linksByPlatform").get("spotify")
        unique_id = (
            spotify_data.get("entityUniqueId")
            if spotify_data is not None
            else res.get("entityUniqueId")
        )
        data = res.get("entitiesByUniqueId").get(unique_id)
        artist = data.get("artistName")
        title = data.get("title")
        thumbnail = data.get("thumbnailUrl")

        if not all([artist, title, thumbnail]):
            return

        view = discord.ui.View()
        for platform, body in platforms.items():
            if (platform_links := res.get("linksByPlatform").get(platform)) is not None:
                view.add_item(
                    discord.ui.Button(
                        style=discord.ButtonStyle.link,
                        emoji=body["emote"],
                        url=(
                            platform_links.get("url") + "?autoplay=0"
                            if platform.lower() == "spotify"
                            else platform_links.get("url")
                        ),
                    )
                )

        embed = discord.Embed(color=await get_color(thumbnail))
        embed.set_author(name=f"{artist} - {title}", icon_url=thumbnail)

        if message.channel.permissions_for(message.guild.me).send_messages:
            await message.reply(embed=embed, view=view, mention_author=False)

        if self.suppress_embed_pattern.search(link):
            with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                await message.edit(suppress=True)


async def setup(bot):
    await bot.add_cog(Songs(bot))
