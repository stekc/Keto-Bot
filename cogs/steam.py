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


class ScreenshotsPaginator(View):
    def __init__(self, screenshots):
        super().__init__(timeout=604800)
        self.screenshots = screenshots
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        if len(self.screenshots) > 1:
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
            self.current_page = (self.current_page - 1) % len(self.screenshots)
        elif interaction.data["custom_id"] == "next":
            self.current_page = (self.current_page + 1) % len(self.screenshots)

        content = self.screenshots[self.current_page]
        if len(self.screenshots) > 1:
            content = f"({self.current_page + 1}/{len(self.screenshots)}) [Screenshot]({content})"

        await interaction.response.edit_message(
            content=content,
            view=self,
        )
        return True


class Screenshots(View):
    def __init__(self, screenshots):
        super().__init__(timeout=604800)
        self.screenshots = (
            [screenshot["path_full"] for screenshot in screenshots]
            if screenshots
            else []
        )
        if self.screenshots:
            self.add_screenshots_button()

    def add_screenshots_button(self):
        label = "Screenshot" if len(self.screenshots) == 1 else "Screenshots"
        button = Button(
            style=discord.ButtonStyle.secondary,
            label=label,
            emoji="🖼️",
        )
        button.callback = self.button_callback
        self.add_item(button)

    async def button_callback(self, interaction: discord.Interaction):
        paginator = ScreenshotsPaginator(self.screenshots)
        content = self.screenshots[0]
        if len(self.screenshots) > 1:
            content = f"(1/{len(self.screenshots)}) [Screenshot]({content})"
        await interaction.response.send_message(
            content,
            view=paginator,
            ephemeral=True,
        )


class Steam(commands.Cog, name="Steam"):
    def __init__(self, bot):
        self.bot = bot
        self.config = SocialsJSON().load_json()
        self.config_cog = self.bot.get_cog("Config")
        self.steam_pattern = re.compile(r"store\.steampowered\.com\/app\/(\d+)")
        self.steam_community_pattern = re.compile(r"steamcommunity\.com\/app\/(\d+)")

    @cached(ttl=604800)
    async def steamlist(self):
        url = f"https://api.steampowered.com/ISteamApps/GetAppList/v2/"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data

    @cached(ttl=604800)
    async def steamsearch(self, query: str):
        data = await self.steamlist()
        if not data or "applist" not in data or "apps" not in data["applist"]:
            return None

        apps = data["applist"]["apps"]
        best_match = None
        best_ratio = 0

        query = re.sub(r"[^\w\s-]", "", query.lower())
        query = " ".join(query.split())

        for app in apps:
            if "name" in app and app["name"]:
                name = re.sub(r"[^\w\s-]", "", app["name"].lower())
                name = " ".join(name.split())

                if query == name:
                    return app["appid"]

                if query in name:
                    ratio = len(query) / len(name)
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match = app["appid"]

        return best_match

    @cached(ttl=604800)
    async def steaminfo(self, appid: int):
        url = f"http://store.steampowered.com/api/appdetails?appids={appid}&cc=US&l=english"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if str(appid) not in data or not data[str(appid)].get("success"):
                        return None
                    game_info = data[str(appid)].get("data")
                    if not game_info:
                        return None

                    type = game_info.get("type")
                    if type.lower() != "game":
                        return None

                    name = game_info.get("name")
                    description = game_info.get("short_description")
                    price = game_info.get("price_overview", {})
                    release_date = game_info.get("release_date", {}).get(
                        "date", "No release date"
                    )
                    developer = game_info.get("developers", ["Unknown"])
                    publisher = game_info.get("publishers", ["Unknown"])
                    platforms = game_info.get("platforms", {})
                    categories = game_info.get("categories", [])
                    genres = game_info.get("genres", [])
                    header_image = game_info.get("header_image")
                    banner_url = game_info.get("background")
                    capsule_url = game_info.get("capsule_image")
                    controller_support = game_info.get("controller_support")
                    screenshots = game_info.get("screenshots")
                    ratings = game_info.get("ratings")
                    nsfw = False
                    if ratings:
                        esrb_rating = ratings.get("esrb", {}).get("rating")
                        if not esrb_rating or esrb_rating.lower() == "ao":
                            nsfw = True
                    external_account = game_info.get("ext_user_account_notice")

                    return (
                        name,
                        type,
                        description,
                        price,
                        release_date,
                        developer,
                        publisher,
                        platforms,
                        categories,
                        genres,
                        header_image,
                        banner_url,
                        capsule_url,
                        controller_support,
                        screenshots,
                        ratings,
                        nsfw,
                        external_account,
                    )
            return None

    @cached(ttl=604800)
    async def steam_price(self, price: dict):
        if price:
            currency = price.get("currency", "USD")
            initial = price.get("initial", 0) / 100
            final = price.get("final", 0) / 100
            discount_percent = price.get("discount_percent", 0)

            if discount_percent > 0:
                return f"~~${initial:.2f}~~ ${final:.2f} (-{discount_percent}%)"
            else:
                return f"${final:.2f}"

        return "Free"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not await self.config_cog.get_config_value(
            message.guild.id, "steam", "enabled"
        ):
            return
        if appid := self.steam_pattern.search(
            message.content.strip("<>")
        ) or self.steam_community_pattern.search(message.content.strip("<>")):
            game_info = await self.steaminfo(appid.group(1))
            if game_info:
                (
                    name,
                    type,
                    description,
                    price,
                    release_date,
                    developer,
                    publisher,
                    platforms,
                    categories,
                    genres,
                    header_image,
                    banner_url,
                    capsule_url,
                    controller_support,
                    screenshots,
                    ratings,
                    nsfw,
                    external_account,
                ) = game_info
                embed = discord.Embed(
                    title=name,
                    description=description,
                    color=discord.Color.blue(),
                )
                embed.add_field(name="Price", value=await self.steam_price(price))
                embed.add_field(name="Release Date", value=release_date)
                embed.add_field(name="Developer", value=developer[0])
                embed.add_field(
                    name="Platforms",
                    value=", ".join(
                        [
                            platform.title()
                            for platform, is_supported in platforms.items()
                            if is_supported
                        ]
                    ),
                )
                embed.set_thumbnail(url=capsule_url)
                if categories and len(categories) > 1:
                    embed.set_footer(
                        text=f"Tags: {', '.join([category['description'] for category in categories if 'description' in category])}"
                    )

                view = Screenshots(screenshots) if screenshots else None
                if external_account:
                    view.add_item(
                        Button(
                            style=discord.ButtonStyle.red,
                            label=f"Requires {re.sub(r'(\s*\([^)]*\))', lambda m: (' Account' if not re.sub(r'\s*\([^)]*\)', '', external_account).lower().endswith('account') else '') + m.group(1), external_account.strip()).replace(' (Supports Linking to Steam Account)', '')}",
                            emoji="⚠️",
                            disabled=True,
                        )
                    )
                if not nsfw or (nsfw and message.channel.is_nsfw()):
                    await message.reply(embed=embed, view=view)
                else:
                    await message.reply(embed=embed)
                await self.config_cog.increment_link_fix_count("steam")
                await asyncio.sleep(0.75)
                await message.edit(suppress=True)

    async def create_game_embed(self, game_info, channel_is_nsfw):
        (
            name,
            type,
            description,
            price,
            release_date,
            developer,
            publisher,
            platforms,
            categories,
            genres,
            header_image,
            banner_url,
            capsule_url,
            controller_support,
            screenshots,
            ratings,
            nsfw,
            external_account,
        ) = game_info

        embed = discord.Embed(
            title=name,
            description=description,
            color=discord.Color.blue(),
        )
        embed.add_field(name="Price", value=await self.steam_price(price))
        embed.add_field(name="Release Date", value=release_date)
        embed.add_field(name="Developer", value=developer[0])
        embed.add_field(
            name="Platforms",
            value=", ".join(
                [
                    platform.title()
                    for platform, is_supported in platforms.items()
                    if is_supported
                ]
            ),
        )
        embed.set_thumbnail(url=capsule_url)
        if categories and len(categories) > 1:
            embed.set_footer(
                text=f"Tags: {', '.join([category['description'] for category in categories if 'description' in category])}"
            )

        view = discord.ui.View()

        if not nsfw or (nsfw and channel_is_nsfw):
            screenshots_view = Screenshots(screenshots) if screenshots else None
            if screenshots_view:
                view.add_item(screenshots_view.children[0])

        if external_account:
            view.add_item(
                Button(
                    style=discord.ButtonStyle.red,
                    label=f"Requires {re.sub(r'(\s*\([^)]*\))', lambda m: (' Account' if not re.sub(r'\s*\([^)]*\)', '', external_account).lower().endswith('account') else '') + m.group(1), external_account.strip()).replace(' (Supports Linking to Steam Account)', '')}",
                    emoji="⚠️",
                    disabled=True,
                )
            )

        return embed, view, nsfw

    async def update_game_info(self, interaction, appid):
        game_info = await self.steaminfo(appid)
        if game_info:
            embed, game_view, nsfw = await self.create_game_embed(
                game_info, interaction.channel.is_nsfw()
            )

            search_view = SteamSearchView(self.last_search_options, self)

            combined_view = discord.ui.View(timeout=180.0)

            combined_view.add_item(search_view.children[0])

            for item in game_view.children:
                combined_view.add_item(item)

            await interaction.edit_original_response(embed=embed, view=combined_view)
        else:
            error_embed = discord.Embed(
                color=discord.Color.red(),
                description="Failed to fetch game information.",
            )
            await interaction.edit_original_response(embed=error_embed, view=None)

    @commands.hybrid_command(
        name="steam",
        description="Search for a game on Steam",
    )
    @app_commands.describe(
        query="The game title to search for",
        spoiler="Whether to mark the result as a spoiler",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def steam(self, context: Context, query: str, spoiler: bool = False) -> None:
        await context.defer()
        data = await self.steamlist()
        if not data or "applist" not in data or "apps" not in data["applist"]:
            await context.send("Failed to fetch Steam game list.")
            return

        apps = data["applist"]["apps"]
        matches = []
        query_lower = query.lower()

        for app in apps:
            if "name" in app and app["name"]:
                name = app["name"].lower()
                if query_lower in name:
                    game_info = await self.steaminfo(app["appid"])
                    if game_info:
                        matches.append(app)

        if not matches:
            await context.send("No games found matching your search.")
            return

        matches.sort(key=lambda x: len(x["name"]))

        unique_appids = set()
        options = []

        for app in matches:
            appid = str(app["appid"])
            if appid not in unique_appids:
                unique_appids.add(appid)
                options.append(
                    discord.SelectOption(label=app["name"][:100], value=appid)
                )

            if len(options) == 25:
                break

        self.last_search_options = options

        search_view = SteamSearchView(options, self)

        first_game_info = await self.steaminfo(int(options[0].value))
        if first_game_info:
            embed, game_view, nsfw = await self.create_game_embed(
                first_game_info, context.channel.is_nsfw()
            )

            combined_view = discord.ui.View(timeout=604800)

            combined_view.add_item(search_view.children[0])

            for item in game_view.children:
                combined_view.add_item(item)

            await context.send(embed=embed, view=combined_view)
        else:
            await context.send("Failed to fetch game information.")


class SteamSearchSelect(discord.ui.Select):
    def __init__(self, options, steam_cog):
        super().__init__(placeholder="Select a game", options=options, row=0)
        self.steam_cog = steam_cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        appid = int(self.values[0])
        game_name = next(
            option.label for option in self.options if option.value == str(appid)
        )

        loading_embed = discord.Embed(
            color=discord.Color.light_gray(),
            description=f"<a:discordloading:1199066225381228546> Fetching details for {game_name}...",
        )

        loading_message = await interaction.followup.send(
            embed=loading_embed, ephemeral=True
        )

        game_info = await self.steam_cog.steaminfo(appid)
        if game_info:
            embed, game_view, nsfw = await self.steam_cog.create_game_embed(
                game_info, interaction.channel.is_nsfw()
            )
            await loading_message.edit(embed=embed, view=game_view)
        else:
            error_embed = discord.Embed(
                color=discord.Color.red(),
                description="Failed to fetch game information.",
            )
            await loading_message.edit(embed=error_embed, view=None)


class SteamSearchView(discord.ui.View):
    def __init__(self, options, steam_cog):
        super().__init__()
        self.add_item(SteamSearchSelect(options, steam_cog))


async def setup(bot):
    await bot.add_cog(Steam(bot))
