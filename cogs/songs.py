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
            r"https:\/\/(music\.apple\.com\/[a-zA-Z]{2}\/album\/[a-zA-Z\d%\(\)-]+\/[\d]{1,10}\?i=[\d]{1,15}|"
            r"music\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11})"
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.author.bot and not message.author.id == 356268235697553409:
            return
        if message.author.bot and message.author.id == 356268235697553409:
            if message.embeds:
                lastfm_pattern = re.compile(
                    r"https:\/\/www\.last\.fm\/music\/[A-Za-z0-9\+\-_%]+\/_\/[A-Za-z0-9\+\-_%\,\'\s]+"
                )
                embed_json = str(message.embeds[0].to_dict())
                lastfm_match = lastfm_pattern.search(embed_json)
                if lastfm_match:
                    lastfm_link = lastfm_match.group(0)
                    spotify_link = await self.lastfm_to_spotify(lastfm_link)
                    if spotify_link:
                        await self.generate_view(message, spotify_link)
                        return
        if match := self.pattern.search(message.content.strip("<>")):
            link = match.group(0)
            await self.generate_view(message, link)
            return

    async def lastfm_to_spotify(self, link: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(link) as resp:
                if resp.status != 200:
                    return None
                content = await resp.text()
                match = re.search(
                    r'href="(https:\/\/open\.spotify\.com\/track\/[a-zA-Z0-9]+)"',
                    content,
                )
                if match:
                    spotify_link = match.group(1)
                    return spotify_link
                else:
                    return None

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
        original_platform = None
        has_spotify_or_apple = False
        has_youtube = False
        for platform, body in platforms.items():
            if (platform_links := res.get("linksByPlatform").get(platform)) is not None:
                platform_url = platform_links.get("url")
                if platform_url in link:
                    original_platform = platform
                if platform in ["spotify", "appleMusic"]:
                    has_spotify_or_apple = True
                elif platform == "youtube":
                    has_youtube = True
                view.add_item(
                    discord.ui.Button(
                        style=discord.ButtonStyle.link,
                        emoji=body["emote"],
                        url=(
                            platform_url + "?autoplay=0"
                            if platform.lower() == "spotify"
                            else platform_url
                        ),
                    )
                )

        should_reply = (original_platform in ["spotify", "appleMusic"]) or (
            has_youtube and has_spotify_or_apple
        )
        if should_reply:
            embed = discord.Embed(color=await get_color(thumbnail))
            embed.set_author(name=f"{artist} - {title}", icon_url=thumbnail)

            if message.channel.permissions_for(message.guild.me).send_messages:
                original_embed_suppressed = (
                    self.suppress_embed_pattern.search(link) is not None
                )
                if original_embed_suppressed:
                    await message.reply(embed=embed, view=view, mention_author=False)
                else:
                    await message.reply(view=view, mention_author=False)

            if self.suppress_embed_pattern.search(link):
                with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                    await message.edit(suppress=True)


async def setup(bot):
    await bot.add_cog(Songs(bot))
