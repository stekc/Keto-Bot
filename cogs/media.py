import asyncio
import json
import os
import re
from contextlib import suppress
from urllib.parse import quote_plus

import aiohttp
import discord
from aiocache import cached
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context
from discord.ui import Button, Select, View

from utils.colorthief import get_color
from utils.jsons import SocialsJSON


class TrailerPaginator(View):
    def __init__(self, trailers):
        super().__init__(timeout=604800)
        self.trailers = trailers
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        if len(self.trailers) > 1:
            self.add_item(
                Button(
                    style=discord.ButtonStyle.secondary,
                    label="Previous",
                    custom_id="prev",
                )
            )
            self.add_item(
                Button(
                    style=discord.ButtonStyle.secondary, label="Next", custom_id="next"
                )
            )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data["custom_id"] == "prev":
            self.current_page = (self.current_page - 1) % len(self.trailers)
        elif interaction.data["custom_id"] == "next":
            self.current_page = (self.current_page + 1) % len(self.trailers)

        content = self.trailers[self.current_page]
        if len(self.trailers) > 1:
            content = f"({self.current_page + 1}/{len(self.trailers)}) {content}"

        await interaction.response.edit_message(
            content=content,
            view=self,
        )
        return True


class TrailerView(View):
    def __init__(self, trailers):
        super().__init__(timeout=604800)
        self.trailers = trailers
        if trailers:
            self.add_trailer_button()

    def add_trailer_button(self):
        label = "Trailer" if len(self.trailers) == 1 else "Trailers"
        button = Button(
            style=discord.ButtonStyle.secondary,
            label=label,
            emoji="<:Music_YouTube:958786388457840700>",
        )
        button.callback = self.button_callback
        self.add_item(button)

    async def button_callback(self, interaction: discord.Interaction):
        paginator = TrailerPaginator(self.trailers)
        content = self.trailers[0]
        if len(self.trailers) > 1:
            content = f"(1/{len(self.trailers)}) {content}"
        await interaction.response.send_message(
            content,
            view=paginator,
            ephemeral=True,
        )


class DiscoverView(View):
    def __init__(self, imdb_id, cog):
        super().__init__(timeout=604800)
        self.imdb_id = imdb_id
        self.cog = cog
        self.add_discover_button()

    def add_discover_button(self):
        button = Button(
            style=discord.ButtonStyle.secondary,
            label="Discover More",
            emoji="🍿",
        )
        button.callback = self.button_callback
        self.add_item(button)

    async def button_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = discord.Embed(
            color=discord.Color.light_gray(),
            description="<a:discordloading:1199066225381228546> Fetching suggested movies...",
        )
        msg = await interaction.followup.send(embed=embed, ephemeral=True)
        suggested_movies = await self.cog.get_suggested_movies(self.imdb_id)

        options = [
            discord.SelectOption(
                label=movie["Title"][:100],
                value=str(movie["TmdbId"]),
                description=movie["Overview"][:100],
            )
            for movie in suggested_movies[:25]
        ]

        select = Select(
            placeholder="Suggested Movies",
            options=options,
            custom_id="discover_select",
        )

        async def select_callback(interaction: discord.Interaction):
            tmdb_id = interaction.data["values"][0]
            query = next(
                movie["Title"]
                for movie in suggested_movies
                if str(movie["TmdbId"]) == tmdb_id
            )
            await interaction.response.defer()

            embed = discord.Embed(
                color=discord.Color.light_gray(),
                description=f"<a:discordloading:1199066225381228546> Fetching details for {query}...",
            )
            await msg.edit(embed=embed, view=None)

            search = await self.cog.search_cinemeta_movie(query)
            (
                moviedb_id,
                title,
                year,
                description,
                poster,
                genres,
                runtime,
                trailers,
            ) = await self.cog.detailed_cinemeta_movie(search)
            embed = discord.Embed(
                title=f"{title} ({year})",
                description=description,
                color=await get_color(poster),
            )
            embed.set_thumbnail(url=poster)
            if genres and runtime:
                embed.set_footer(
                    text=f"Runtime: {runtime} | Genres: {', '.join(genres)}"
                )
            elif genres:
                embed.set_footer(text=f"Genres: {', '.join(genres)}")
            elif runtime:
                embed.set_footer(text=f"Runtime: {runtime}")

            view = View(timeout=604800)
            trailer_view = TrailerView(trailers) if trailers else None
            if trailer_view:
                for item in trailer_view.children:
                    view.add_item(item)
            view.add_item(select)

            stremio_button = StremioButton(search)
            view.add_item(stremio_button)

            await msg.edit(embed=embed, view=view)

        select.callback = select_callback

        view = View(timeout=604800)
        view.add_item(select)

        await msg.edit(embed=None, view=view)


class StremioButton(Button):
    def __init__(self, imdb_id: str, is_tv: bool = False):
        url = f"https://keto.boats/stremio?id={imdb_id}"
        if is_tv:
            url += "&series=true"
        super().__init__(
            style=discord.ButtonStyle.link,
            label="Open in Stremio",
            url=url,
            emoji="<:stremio:1292976659829362813>",
        )


class Media(commands.Cog, name="media"):
    def __init__(self, bot):
        self.bot = bot
        self.config = SocialsJSON().load_json()
        self.config_cog = self.bot.get_cog("Config")
        self.imdb_pattern = re.compile(r"imdb\.com\/title\/(tt\d+)")
        self.tmdb_pattern = re.compile(r"themoviedb\.org\/(tv|movie)\/(\d+)(?:[-\w]*)")
        self.trakt_pattern = re.compile(r"trakt\.tv\/(movies|shows)\/([\w-]+)")

    @cached(ttl=86400)
    async def search_cinemeta_movie(self, query: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://v3-cinemeta.strem.io/catalog/movie/top/search={quote_plus(query)}.json"
            ) as response:
                data = await response.json()
                if not data.get("metas"):
                    return None
                imdb_id = data["metas"][0]["id"]
                return imdb_id

    @cached(ttl=86400)
    async def search_cinemeta_tv(self, query: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://v3-cinemeta.strem.io/catalog/series/top/search={quote_plus(query)}.json"
            ) as response:
                data = await response.json()
                if not data.get("metas"):
                    return None
                imdb_id = data["metas"][0]["id"]
                return imdb_id

    @cached(ttl=86400)
    async def detailed_cinemeta_movie(self, imdb_id: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://cinemeta-live.strem.io/meta/movie/{imdb_id}.json"
            ) as response:
                data = await response.json()
                moviedb_id = data["meta"].get("moviedb_id", None)
                title = data["meta"].get("name", "Unknown")
                year = data["meta"].get("releaseInfo", "Unknown")
                description = data["meta"].get("description", "Unknown")
                poster = data["meta"].get("poster", None)
                genres = data["meta"].get("genres", None)
                runtime = data["meta"].get("runtime", None)
                trailers = [
                    "https://youtu.be/" + trailer["source"]
                    for trailer in data["meta"].get("trailers", [])
                ]

                return (
                    moviedb_id,
                    title,
                    year,
                    description,
                    poster,
                    genres,
                    runtime,
                    trailers,
                )

    @cached(ttl=86400)
    async def detailed_cinemeta_tv(self, imdb_id: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://cinemeta-live.strem.io/meta/series/{imdb_id}.json"
            ) as response:
                data = await response.json()
                moviedb_id = data["meta"].get("moviedb_id", None)
                title = data["meta"].get("name", "Unknown")
                year = data["meta"].get("releaseInfo", "Unknown")
                description = data["meta"].get("description", "Unknown")
                poster = data["meta"].get("poster", None)
                genres = data["meta"].get("genres", None)
                trailers = [
                    "https://youtu.be/" + trailer["source"]
                    for trailer in data["meta"].get("trailers", [])
                ]

                return moviedb_id, title, year, description, poster, genres, trailers

    @cached(ttl=86400)
    async def tmdb_to_imdb(self, tmdb_id: str, type: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.themoviedb.org/3/{type}/{tmdb_id}/external_ids?api_key={os.getenv('TMDB_TOKEN')}"
            ) as ext_response:
                ext_data = await ext_response.json()
                imdb_id = ext_data.get("imdb_id")

                if not imdb_id:
                    return None

                return imdb_id

    @cached(ttl=86400)
    async def trakt_to_imdb(self, trakt_url: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://{trakt_url}") as response:
                chunk_size = 8192
                content = b""
                pattern = r"imdb\.com/title/(tt\d{7,10})"
                async for chunk in response.content.iter_chunked(chunk_size):
                    content += chunk
                    decoded_content = content.decode("utf-8", errors="ignore")
                    match = re.search(pattern, decoded_content)
                    if match:
                        return match.group(1)
                    if len(content) > 1000000:
                        break

                return None

    @cached(ttl=86400)
    async def get_suggested_movies(self, imdb_id: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.radarr.video/v1/movie/imdb/{imdb_id}"
            ) as response:
                data = await response.json()
                if isinstance(data, list) and len(data) > 0:
                    suggested = data[0].get("Recommendations", [])
                else:
                    suggested = []

                for movie in suggested:
                    movie["ImdbId"] = await self.tmdb_to_imdb(
                        str(movie["TmdbId"]), "movie"
                    )
                    (
                        _,
                        _,
                        _,
                        description,
                        _,
                        _,
                        _,
                        _,
                    ) = await self.detailed_cinemeta_movie(movie["ImdbId"])
                    movie["Overview"] = description

                return suggested

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not await self.config_cog.get_config_value(
            message.guild.id, "imdb", "enabled"
        ):
            return
        if imdb_id := self.imdb_pattern.search(message.content.strip("<>")):
            for _ in range(5):
                if message.embeds:
                    break
                await asyncio.sleep(1)

            imdb_id = imdb_id.group(1)
            embeds = [embed.to_dict() for embed in message.embeds]
            embed = next((e for e in embeds if e["title"]), None)
            if not embed:
                return
            title = embed["title"].split(" ⭐ ")[0]
            title_match = re.search(
                r"^(.*?)\s*\((?:TV (?:Mini )?Series )?(\d{4}(?:[–-]\d{4})?\s*)\)?",
                title,
            )
            if title_match:
                title = title_match.group(1)
                year = title_match.group(2).strip("–")

            try:
                (
                    moviedb_id,
                    cm_title,
                    cm_year,
                    description,
                    poster,
                    genres,
                    trailers,
                ) = await self.detailed_cinemeta_tv(imdb_id)
                if cm_title == title and cm_year.split("–")[0] == year:
                    embed = discord.Embed(
                        title=f"{title} ({year})",
                        description=description,
                        color=await get_color(poster),
                    )
                    embed.set_thumbnail(url=poster)
                    if genres:
                        embed.set_footer(text=f"Genres: {', '.join(genres)}")

                    trailer_view = TrailerView(trailers) if trailers else None
                    stremio_button = StremioButton(imdb_id, is_tv=True)

                    combined_view = View(timeout=604800)
                    if trailer_view:
                        for item in trailer_view.children:
                            combined_view.add_item(item)
                    combined_view.add_item(stremio_button)

                    await message.reply(embed=embed, view=combined_view)
                    await self.config_cog.increment_link_fix_count("imdb")
                    await asyncio.sleep(0.75)
                    await message.edit(suppress=True)
                    return
            except:
                pass

            try:
                (
                    moviedb_id,
                    cm_title,
                    cm_year,
                    description,
                    poster,
                    genres,
                    runtime,
                    trailers,
                ) = await self.detailed_cinemeta_movie(imdb_id)
                if cm_title == title and cm_year == year:
                    embed = discord.Embed(
                        title=f"{title} ({year})",
                        description=description,
                        color=await get_color(poster),
                    )
                    embed.set_thumbnail(url=poster)
                    if genres and runtime:
                        embed.set_footer(
                            text=f"Runtime: {runtime} | Genres: {', '.join(genres)}"
                        )
                    elif genres:
                        embed.set_footer(text=f"Genres: {', '.join(genres)}")
                    elif runtime:
                        embed.set_footer(text=f"Runtime: {runtime}")

                    trailer_view = TrailerView(trailers) if trailers else None
                    stremio_button = StremioButton(imdb_id)
                    discover_view = DiscoverView(imdb_id, self)

                    combined_view = View(timeout=604800)
                    if trailer_view:
                        for item in trailer_view.children:
                            combined_view.add_item(item)
                    for item in discover_view.children:
                        combined_view.add_item(item)
                    combined_view.add_item(stremio_button)

                    await message.reply(embed=embed, view=combined_view)
                    await self.config_cog.increment_link_fix_count("imdb")
                    await asyncio.sleep(0.75)
                    await message.edit(suppress=True)
                    return
            except:
                pass

        if tmdb_info := self.tmdb_pattern.search(message.content.strip("<>")):
            tmdb_type = tmdb_info.group(1)
            tmdb_id = tmdb_info.group(2)

            imdb_id = await self.tmdb_to_imdb(tmdb_id, tmdb_type)

            if not imdb_id:
                return

            if tmdb_type == "movie":
                (
                    moviedb_id,
                    title,
                    year,
                    description,
                    poster,
                    genres,
                    runtime,
                    trailers,
                ) = await self.detailed_cinemeta_movie(imdb_id)
            else:
                (
                    moviedb_id,
                    title,
                    year,
                    description,
                    poster,
                    genres,
                    trailers,
                ) = await self.detailed_cinemeta_tv(imdb_id)

            embed = discord.Embed(
                title=f"{title} ({year})",
                description=description,
                color=await get_color(poster),
            )

            embed.set_thumbnail(url=poster)

            trailer_view = TrailerView(trailers) if trailers else None
            stremio_button = (
                StremioButton(imdb_id, is_tv=True)
                if tmdb_type == "tv"
                else StremioButton(imdb_id)
            )

            combined_view = View(timeout=604800)
            if trailer_view:
                for item in trailer_view.children:
                    combined_view.add_item(item)
            if tmdb_type == "movie":
                discover_view = DiscoverView(imdb_id, self)
                for item in discover_view.children:
                    combined_view.add_item(item)
            combined_view.add_item(stremio_button)

            await message.reply(embed=embed, view=combined_view)
            await self.config_cog.increment_link_fix_count("imdb")
            await asyncio.sleep(0.75)
            await message.edit(suppress=True)
            return

        if trakt_info := self.trakt_pattern.search(message.content.strip("<>")):
            imdb_id = await self.trakt_to_imdb(trakt_info.group(0))

            if not imdb_id:
                return

            if "/movies/" in trakt_info.group(0):
                (
                    moviedb_id,
                    title,
                    year,
                    description,
                    poster,
                    genres,
                    runtime,
                    trailers,
                ) = await self.detailed_cinemeta_movie(imdb_id)
            else:
                (
                    moviedb_id,
                    title,
                    year,
                    description,
                    poster,
                    genres,
                    trailers,
                ) = await self.detailed_cinemeta_tv(imdb_id)

            embed = discord.Embed(
                title=f"{title} ({year})",
                description=description,
                color=await get_color(poster),
            )

            embed.set_thumbnail(url=poster)

            trailer_view = TrailerView(trailers) if trailers else None

            combined_view = View(timeout=604800)
            if trailer_view:
                for item in trailer_view.children:
                    combined_view.add_item(item)

            if "/movies/" in trakt_info.group(0):
                discover_view = DiscoverView(imdb_id, self)
                for item in discover_view.children:
                    combined_view.add_item(item)

            stremio_button = (
                StremioButton(imdb_id, is_tv=True)
                if "/shows/" in trakt_info.group(0)
                else StremioButton(imdb_id)
            )
            combined_view.add_item(stremio_button)

            await message.reply(embed=embed, view=combined_view)
            await self.config_cog.increment_link_fix_count("imdb")
            await asyncio.sleep(0.75)
            await message.edit(suppress=True)
            return

    @commands.hybrid_group(
        name="search",
        description="Search for movies or TV shows.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def search(self, context: Context):
        pass

    @search.command(name="movie", description="Search for a movie.")
    @app_commands.describe(query="The movie to search for.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def search_movie(self, context: Context, query: str):
        await context.defer()
        search = await self.search_cinemeta_movie(query)
        if not search:
            embed = discord.Embed(
                description=f"No results found.",
                color=discord.Color.red(),
            )
            await context.send(embed=embed)
            return

        (
            moviedb_id,
            title,
            year,
            description,
            poster,
            genres,
            runtime,
            trailers,
        ) = await self.detailed_cinemeta_movie(search)
        embed = discord.Embed(
            title=f"{title} ({year})",
            description=description,
            color=await get_color(poster),
        )
        embed.set_thumbnail(url=poster)
        if genres and runtime:
            embed.set_footer(text=f"Runtime: {runtime} | Genres: {', '.join(genres)}")
        elif genres:
            embed.set_footer(text=f"Genres: {', '.join(genres)}")
        elif runtime:
            embed.set_footer(text=f"Runtime: {runtime}")

        trailer_view = TrailerView(trailers) if trailers else None
        discover_view = DiscoverView(search, self)
        stremio_button = StremioButton(search)

        combined_view = View(timeout=604800)
        imdb_link_button = discord.ui.Button(
            style=discord.ButtonStyle.link,
            emoji="<:imdb:1292962713542332479>",
            url=f"https://www.imdb.com/title/{search}",
        )
        combined_view.add_item(imdb_link_button)
        if trailer_view:
            for item in trailer_view.children:
                combined_view.add_item(item)
        for item in discover_view.children:
            combined_view.add_item(item)
        combined_view.add_item(stremio_button)

        await context.send(embed=embed, view=combined_view)

    @search.command(name="tv", description="Search for a TV show.")
    @app_commands.describe(query="The TV show to search for.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def search_tv(self, context: Context, query: str):
        await context.defer()
        search = await self.search_cinemeta_tv(query)
        if not search:
            embed = discord.Embed(
                description=f"No results found.",
                color=discord.Color.red(),
            )
            await context.send(embed=embed)
            return

        (
            moviedb_id,
            title,
            year,
            description,
            poster,
            genres,
            trailers,
        ) = await self.detailed_cinemeta_tv(search)
        embed = discord.Embed(
            title=f"{title} ({year})",
            description=description,
            color=await get_color(poster),
        )
        embed.set_thumbnail(url=poster)
        if genres:
            embed.set_footer(text=f"Genres: {', '.join(genres)}")

        combined_view = View(timeout=604800)
        imdb_link_button = discord.ui.Button(
            style=discord.ButtonStyle.link,
            emoji="<:imdb:1292962713542332479>",
            url=f"https://www.imdb.com/title/{search}",
        )
        combined_view.add_item(imdb_link_button)
        trailer_view = TrailerView(trailers) if trailers else None
        if trailer_view:
            for item in trailer_view.children:
                combined_view.add_item(item)
        stremio_button = StremioButton(search, is_tv=True)
        combined_view.add_item(stremio_button)

        await context.send(embed=embed, view=combined_view)


async def setup(bot):
    await bot.add_cog(Media(bot))
