import json
import re
from contextlib import suppress

import aiohttp
import discord
from discord.ext import commands

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
            r"https:\/\/(open.spotify.com\/track\/[A-Za-z0-9]+|music.apple.com\/[a-zA-Z][a-zA-Z]?\/album\/[a-zA-Z\d%\(\)-]+/[\d]{1,10}\?i=[\d]{1,15}|spotify.link\/[A-Za-z0-9]+)"
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.author.bot:
            return

        match = self.pattern.search(message.content.strip("<>"))
        if match:
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

        if title is not None:
            title = discord.utils.escape_markdown(title)
            title = discord.utils.escape_mentions(title)

        if artist is not None:
            artist = discord.utils.escape_markdown(artist)
            artist = discord.utils.escape_mentions(artist)

        view = discord.ui.View()
        for platform, body in platforms.items():
            platform_links = res.get("linksByPlatform").get(platform)
            if platform_links is not None:
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

        embed = discord.Embed()
        embed.set_author(name=f"{title} - {artist}", icon_url=thumbnail)

        if message.channel.permissions_for(message.guild.me).send_messages:
            await message.reply(embed=embed, view=view, mention_author=False)
        with suppress(discord.errors.Forbidden, discord.errors.NotFound):
            await message.edit(suppress=True)


async def setup(bot):
    await bot.add_cog(Songs(bot))
