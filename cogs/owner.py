""""
Copyright © Krypton 2019-2023 - https://github.com/kkrypt0nn (https://krypton.ninja)
Description:
🐍 A simple template to start to code your own and personalized discord bot in Python programming language.

Version: 6.1.0
"""

import json
import os

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context

from utils.jsons import ConfigJSON, SocialsJSON, TrackingJSON


class Owner(commands.Cog, name="owner"):
    def __init__(self, bot) -> None:
        self.bot = bot

    config = ConfigJSON().load_json()

    @commands.command(
        name="sync",
        description="Synchonizes the slash commands.",
    )
    @app_commands.describe(scope="The scope of the sync. Can be `global` or `guild`")
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def sync(self, context: Context, scope: str) -> None:
        """
        Synchonizes the slash commands.

        :param context: The command context.
        :param scope: The scope of the sync. Can be `global` or `guild`.
        """

        if scope == "global":
            await context.bot.tree.sync()
            embed = discord.Embed(
                description="Slash commands have been globally synchronized.",
                color=0xBEBEFE,
            )
            await context.send(embed=embed)
            return
        elif scope == "guild":
            context.bot.tree.copy_global_to(guild=context.guild)
            await context.bot.tree.sync(guild=context.guild)
            embed = discord.Embed(
                description="Slash commands have been synchronized in this guild.",
                color=0xBEBEFE,
            )
            await context.send(embed=embed)
            return
        embed = discord.Embed(
            description="The scope must be `global` or `guild`.", color=0xE02B2B
        )
        await context.send(embed=embed)

    @commands.command(
        name="unsync",
        description="Unsynchonizes the slash commands.",
    )
    @app_commands.describe(
        scope="The scope of the sync. Can be `global`, `current_guild` or `guild`"
    )
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def unsync(self, context: Context, scope: str) -> None:
        """
        Unsynchonizes the slash commands.

        :param context: The command context.
        :param scope: The scope of the sync. Can be `global`, `current_guild` or `guild`.
        """

        if scope == "global":
            context.bot.tree.clear_commands(guild=None)
            await context.bot.tree.sync()
            embed = discord.Embed(
                description="Slash commands have been globally unsynchronized.",
                color=0xBEBEFE,
            )
            await context.send(embed=embed)
            return
        elif scope == "guild":
            context.bot.tree.clear_commands(guild=context.guild)
            await context.bot.tree.sync(guild=context.guild)
            embed = discord.Embed(
                description="Slash commands have been unsynchronized in this guild.",
                color=0xBEBEFE,
            )
            await context.send(embed=embed)
            return
        embed = discord.Embed(
            description="The scope must be `global` or `guild`.", color=0xE02B2B
        )
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="load",
        description="Load a cog",
    )
    @app_commands.describe(cog="The name of the cog to load")
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def load(self, context: Context, cog: str) -> None:
        """
        The bot will load the given cog.

        :param context: The hybrid command context.
        :param cog: The name of the cog to load.
        """
        try:
            await self.bot.load_extension(f"cogs.{cog}")
        except Exception:
            embed = discord.Embed(
                description=f"Could not load the `{cog}` cog.", color=0xE02B2B
            )
            await context.send(embed=embed)
            return
        embed = discord.Embed(
            description=f"Successfully loaded the `{cog}` cog.", color=0xBEBEFE
        )
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="unload",
        description="Unloads a cog.",
    )
    @app_commands.describe(cog="The name of the cog to unload")
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def unload(self, context: Context, cog: str) -> None:
        """
        The bot will unload the given cog.

        :param context: The hybrid command context.
        :param cog: The name of the cog to unload.
        """
        try:
            await self.bot.unload_extension(f"cogs.{cog}")
        except Exception:
            embed = discord.Embed(
                description=f"Could not unload the `{cog}` cog.", color=0xE02B2B
            )
            await context.send(embed=embed)
            return
        embed = discord.Embed(
            description=f"Successfully unloaded the `{cog}` cog.", color=0xBEBEFE
        )
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="reload",
        description="Reloads a cog.",
    )
    @app_commands.describe(cog="The name of the cog to reload")
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def reload(self, context: Context, cog: str) -> None:
        """
        The bot will reload the given cog.

        :param context: The hybrid command context.
        :param cog: The name of the cog to reload.
        """
        try:
            await self.bot.reload_extension(f"cogs.{cog}")
        except Exception:
            embed = discord.Embed(
                description=f"Could not reload the `{cog}` cog.", color=0xE02B2B
            )
            await context.send(embed=embed)
            return
        embed = discord.Embed(
            description=f"Successfully reloaded the `{cog}` cog.", color=0xBEBEFE
        )
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="shutdown",
        description="Make the bot shutdown.",
    )
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def shutdown(self, context: Context) -> None:
        """
        Shuts down the bot.

        :param context: The hybrid command context.
        """
        embed = discord.Embed(description="Shutting down. Bye! :wave:", color=0xBEBEFE)
        await context.send(embed=embed)
        await self.bot.close()

    @commands.hybrid_command(
        name="say",
        description="The bot will say anything you want.",
    )
    @app_commands.describe(message="The message that should be repeated by the bot")
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def say(self, context: Context, *, message: str) -> None:
        """
        The bot will say anything you want.

        :param context: The hybrid command context.
        :param message: The message that should be repeated by the bot.
        """
        await context.send(message)

    @commands.hybrid_command(
        name="embed",
        description="The bot will say anything you want, but within embeds.",
    )
    @app_commands.describe(message="The message that should be repeated by the bot")
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def embed(self, context: Context, *, message: str) -> None:
        """
        The bot will say anything you want, but using embeds.

        :param context: The hybrid command context.
        :param message: The message that should be repeated by the bot.
        """
        embed = discord.Embed(description=message, color=0xBEBEFE)
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="setpfp",
        description="Change the bot's profile picture.",
    )
    @app_commands.describe(image="The image to use as the bot's profile picture")
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def setpfp(self, context: Context, *, image: discord.Attachment) -> None:
        await self.bot.user.edit(avatar=await image.read())
        embed = discord.Embed(
            description="The bot's profile picture has been changed.", color=0xBEBEFE
        )
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="configsummary",
        description="Summarize the configuration database.",
    )
    @app_commands.guilds(discord.Object(id=config["main_guild_id"]))
    @commands.is_owner()
    async def config_summary(self, context: Context) -> None:
        config_cog = self.bot.get_cog("Config")
        if not config_cog:
            await context.send("Config cog not found.")
            return

        async with config_cog.db.execute("SELECT * FROM guild_config") as cursor:
            guild_rows = await cursor.fetchall()

        async with config_cog.db.execute("SELECT * FROM user_config") as cursor:
            user_rows = await cursor.fetchall()

        socials = SocialsJSON().load_json()
        tracking = TrackingJSON().load_json()

        total_servers = len(self.bot.guilds)
        summary = {"Services": {}, "Link Tracking": {}}

        for social in socials:
            summary["Services"][social] = {"enabled": total_servers, "disabled": 0}

        for tracker in tracking:
            summary["Link Tracking"][tracker] = {"disabled": 0}

        for row in guild_rows:
            guild_id, config_json = row
            config = json.loads(config_json)

            for social in socials:
                if social in config:
                    if not config[social].get("enabled", True):
                        summary["Services"][social]["enabled"] -= 1
                        summary["Services"][social]["disabled"] += 1

        for row in user_rows:
            user_id, config_json = row
            config = json.loads(config_json)

            for tracker in tracking:
                if tracker in config:
                    if not config[tracker].get("enabled", True):
                        summary["Link Tracking"][tracker]["disabled"] += 1

        embed = discord.Embed(title="Configuration Summary", color=0xBEBEFE)

        services_content = []
        for service, counts in summary["Services"].items():
            services_content.append(
                f"{service.title().replace('Tiktok', 'TikTok').replace('Imdb', 'Movies and TV')}: {counts['enabled']} enabled, {counts['disabled']} disabled"
            )
        embed.add_field(
            name="Services", value="\n".join(services_content), inline=False
        )

        tracking_content = []
        for tracker, counts in summary["Link Tracking"].items():
            tracking_content.append(
                f"{tracker.title().replace('Tiktok', 'TikTok')}: {counts['disabled']} users disabled"
            )
        embed.add_field(
            name="Link Tracking",
            value="\n".join(tracking_content),
            inline=False,
        )

        await context.send(embed=embed)

    @commands.command(
        name="sudo",
        description="Run any command as the bot owner.",
    )
    @commands.is_owner()
    async def sudo(self, context: Context, *, command_string: str) -> None:
        msg = context.message
        msg.content = self.bot.command_prefix + command_string

        new_ctx = await self.bot.get_context(msg)

        if new_ctx.command:
            temp_command = commands.Command(new_ctx.command.callback)
            temp_command.checks = []
            temp_command.cog = new_ctx.command.cog
            temp_command.params = new_ctx.command.params
            new_ctx.command = temp_command

        try:
            await self.bot.invoke(new_ctx)
        except Exception as e:
            print(f"sudo command failed. Error: {e}")


async def setup(bot) -> None:
    await bot.add_cog(Owner(bot))
