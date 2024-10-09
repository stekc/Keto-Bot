import asyncio
import json
import re
from contextlib import suppress
from urllib.parse import quote_plus

import aiohttp
import discord
from aiocache import cached
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context
from discord.ui import Button, View

from utils.colorthief import get_color
from utils.jsons import SocialsJSON


class Movies(commands.Cog, name="movies"):
    def __init__(self, bot):
        self.bot = bot
        self.config = SocialsJSON().load_json()
        self.config_cog = self.bot.get_cog("Config")
        self.pattern = re.compile(r"imdb\.com\/title\/(tt\d+)")

    async def check_enabled(self, site: str, config, guild_id: int = None):
        if guild_id is None:
            if not self.config[site]["enabled"]:
                return False
        else:
            if not await self.config_cog.get_config_value(guild_id, site, "enabled"):
                return False
        return True

    async def process_movie_data(self, movie, context=None, is_imdb_link=False):
        mtitle = movie.get("Title", "Unknown Title")
        if year := movie.get("Year"):
            mtitle += f" ({year})"

        genres = ", ".join(movie.get("Genres", []))
        overview = movie.get("Overview", "No overview available")
        if len(overview) > 500:
            overview = overview[:500] + "..."

        poster = next(
            (img["Url"] for img in movie.get("Images", []) if "Url" in img), None
        )
        color = await get_color(poster) if poster else discord.Color.default()

        trailer_id = movie.get("YoutubeTrailerId")
        trailer = f"https://youtu.be/{trailer_id}" if trailer_id else None
        mid = movie.get("ImdbId")

        recommendations = movie.get("Recommendations", [])
        recommended = "\n\n".join(
            [
                f"<:movie:1293632067313078383> **[{rec['Title']}](https://www.themoviedb.org/movie/{rec['TmdbId']})**"
                for rec in recommendations
            ]
        )
        embed = discord.Embed(description=recommended, color=color)
        recommended_embed = embed

        class TrailerButton(Button):
            def __init__(self, trailer_url):
                super().__init__(
                    style=discord.ButtonStyle.secondary,
                    label="Trailer",
                    emoji="<:Music_YouTube:958786388457840700>",
                )
                self.trailer_url = trailer_url

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.send_message(
                    self.trailer_url, ephemeral=True
                )

        class RecommendedButton(Button):
            def __init__(self, recommended_movies):
                super().__init__(
                    style=discord.ButtonStyle.secondary,
                    label="Discover More",
                    emoji="🍿",
                )
                self.recommended_movies = recommended_movies

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.send_message(
                    embed=self.recommended_movies, ephemeral=True
                )

        view = View()
        if mid and not is_imdb_link:
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    emoji="<:imdb:1292962713542332479>",
                    url=f"https://www.imdb.com/title/{mid}",
                )
            )
        if trailer:
            view.add_item(TrailerButton(trailer))
        if recommended:
            view.add_item(RecommendedButton(recommended_embed))
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Open in Stremio",
                emoji="<:stremio:1292976659829362813>",
                url=f"https://keto.boats/stremio?id={movie['ImdbId']}",
            )
        )

        embed = discord.Embed(
            title=mtitle,
            description=overview,
            color=color,
        )
        if poster:
            embed.set_thumbnail(url=poster)

        footer_text = genres
        embed.set_footer(text=footer_text)

        if context:
            await context.send(embed=embed, view=view)
        else:
            return embed, view

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.author.bot and not message.author.id == 356268235697553409:
            return
        if not await self.check_enabled("imdb", self.config, message.guild.id):
            return
        if message.author.bot:
            return
        if match := self.pattern.search(message.content.strip("<>")):
            link = match.group(1)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.radarr.video/v1/movie/imdb/{link}"
                ) as response:
                    movie_data = await response.json()

            if (
                not movie_data
                or not isinstance(movie_data, list)
                or len(movie_data) == 0
            ):
                return

            movie = movie_data[0]
            embed, view = await self.process_movie_data(movie, is_imdb_link=True)

            await message.reply(embed=embed, view=view)
            await self.config_cog.increment_link_fix_count("imdb")
            await asyncio.sleep(0.75)
            await message.edit(suppress=True)

    @commands.hybrid_command(
        name="imdb",
        description="Search for a movie on IMDb.",
    )
    @app_commands.describe(query="Title of the movie you want to search for.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def imdb(self, context: Context, *, query: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.radarr.video/v1/search?q={quote_plus(query)}&year="
            ) as response:
                movie_data = await response.json()

        if not movie_data or not isinstance(movie_data, list) or len(movie_data) == 0:
            return await context.send("No results found.")

        movie = movie_data[0]
        await self.process_movie_data(movie, context, is_imdb_link=False)


async def setup(bot):
    await bot.add_cog(Movies(bot))
