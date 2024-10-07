import json
from typing import List

import aiosqlite
import discord
from discord import Interaction, app_commands
from discord.ext import commands, tasks
from discord.ext.commands import Context

from utils.jsons import SocialsJSON, TrackingJSON


class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "config.db"
        self.db = None
        self.link_fix_counts = {
            "tiktok": 0,
            "instagram": 0,
            "reddit": 0,
            "twitter": 0,
            "songs": 0,
        }

    socials = SocialsJSON().load_json()
    tracking = TrackingJSON().load_json()

    async def cog_load(self):
        self.db = await aiosqlite.connect(self.db_path)
        await self.create_tables()
        self.sync_db_task.start()

    async def cog_unload(self):
        if self.db:
            await self.db.close()
        self.sync_db_task.cancel()

    async def create_tables(self):
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                config TEXT NOT NULL
            )
        """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS link_fix_counts (
                id INTEGER PRIMARY KEY,
                tiktok INTEGER DEFAULT 0,
                instagram INTEGER DEFAULT 0,
                reddit INTEGER DEFAULT 0,
                twitter INTEGER DEFAULT 0,
                songs INTEGER DEFAULT 0
            )
        """
        )
        await self.db.commit()

    @tasks.loop(hours=1)
    async def sync_db_task(self):
        async with self.db.execute(
            "SELECT * FROM link_fix_counts WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                db_counts = dict(
                    zip(
                        ["id", "tiktok", "instagram", "reddit", "twitter", "songs"], row
                    )
                )
                for platform in self.link_fix_counts:
                    db_counts[platform] += self.link_fix_counts[platform]
                    self.link_fix_counts[platform] = 0
                await self.db.execute(
                    "UPDATE link_fix_counts SET tiktok = ?, instagram = ?, reddit = ?, twitter = ?, songs = ? WHERE id = 1",
                    (
                        db_counts["tiktok"],
                        db_counts["instagram"],
                        db_counts["reddit"],
                        db_counts["twitter"],
                        db_counts["songs"],
                    ),
                )
            else:
                await self.db.execute(
                    "INSERT INTO link_fix_counts (id, tiktok, instagram, reddit, twitter, songs) VALUES (1, ?, ?, ?, ?, ?)",
                    tuple(self.link_fix_counts.values()),
                )
                self.link_fix_counts = {k: 0 for k in self.link_fix_counts}
        await self.db.commit()

        self.link_fix_counts = {k: 0 for k in self.link_fix_counts}

    async def get_link_fix_counts(self):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM link_fix_counts WHERE id = 1"
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(
                        zip(
                            ["id", "tiktok", "instagram", "reddit", "twitter", "songs"],
                            row,
                        )
                    )
        return {
            "id": 1,
            "tiktok": 0,
            "instagram": 0,
            "reddit": 0,
            "twitter": 0,
            "songs": 0,
        }

    async def get_guild_config(self, guild_id: int):
        async with self.db.execute(
            "SELECT config FROM guild_config WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
        return json.loads("{}")

    async def set_guild_config(self, guild_id: int, config: dict):
        config_json = json.dumps(config)
        await self.db.execute(
            """
            INSERT OR REPLACE INTO guild_config (guild_id, config)
            VALUES (?, ?)
        """,
            (guild_id, config_json),
        )
        await self.db.commit()

    async def get_config_value(self, guild_id: int, key: str, value: str):
        config = await self.get_guild_config(guild_id)
        return config.get(key, {}).get(value, self.socials.get(key, {}).get(value))

    async def make_config_embed(self, guild_id: int):
        guild_config = await self.get_guild_config(guild_id)

        embed = discord.Embed(title="Guild Configuration", color=discord.Color.blue())

        for platform in self.socials:
            config = guild_config.get(platform, {"enabled": True})
            status = "🟢 Enabled" if config.get("enabled", True) else "🔴 Disabled"
            embed.add_field(
                name=platform.title().replace("Tiktok", "TikTok"),
                value=status,
                inline=False,
            )

        return embed

    @commands.hybrid_group(
        name="config",
        description="Show or modify guild configuration.",
        fallback="show",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @commands.has_permissions(manage_guild=True)
    async def config_group(self, context: Context):
        await context.send(
            embed=await self.make_config_embed(context.guild.id),
        )

    async def social_autofix_autocompletion(
        self, interaction: Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        data = []
        for choice in list(self.socials.keys()):
            if current.lower() in choice.lower():
                data.append(
                    app_commands.Choice(
                        name=choice.title().replace("Tiktok", "TikTok"), value=choice
                    )
                )
        return data

    class SocialAutofixTransformer(app_commands.Transformer):
        async def transform(self, interaction: discord.Interaction, value: str):
            if value not in list(SocialsJSON().load_json().keys()):
                return None

            return value

    @config_group.command(
        name="autofix", description="Enable or disable social autofix per site."
    )
    @app_commands.describe(site="Site to modify.")
    @app_commands.autocomplete(site=social_autofix_autocompletion)
    @app_commands.describe(enabled="Enable or disable autofix for this site.")
    @commands.has_permissions(manage_guild=True)
    async def social_autofix(
        self, context: Context, site: SocialAutofixTransformer, enabled: bool
    ):
        if site is None:
            embed = discord.Embed(
                color=discord.Color.red(),
            )
            embed.description = "No site found with that name."

            await context.send(embed=embed, ephemeral=True)
            return

        config = await self.get_guild_config(context.guild.id)
        config[site] = {}
        config[site]["enabled"] = enabled
        await self.set_guild_config(context.guild.id, config)

        await context.send(
            embed=await self.make_config_embed(context.guild.id),
        )

    async def increment_link_fix_count(self, platform: str):
        if platform in self.link_fix_counts:
            self.link_fix_counts[platform] += 1

    async def get_config_value(self, guild_id: int, key: str, value: str):
        config = await self.get_guild_config(guild_id)
        return config.get(key, {}).get(value, self.socials.get(key, {}).get(value))

    async def make_config_embed(self, guild_id: int):
        guild_config = await self.get_guild_config(guild_id)

        embed = discord.Embed(title="Guild Configuration", color=discord.Color.blue())

        for platform in self.socials:
            config = guild_config.get(platform, {"enabled": True})
            status = "🟢 Enabled" if config.get("enabled", True) else "🔴 Disabled"
            embed.add_field(
                name=platform.title().replace("Tiktok", "TikTok"),
                value=status,
                inline=False,
            )

        return embed

    @commands.hybrid_group(
        name="config",
        description="Show or modify guild configuration.",
        fallback="show",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @commands.has_permissions(manage_guild=True)
    async def config_group(self, context: Context):
        await context.send(
            embed=await self.make_config_embed(context.guild.id),
        )

    async def social_autofix_autocompletion(
        self, interaction: Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        data = []
        for choice in list(self.socials.keys()):
            if current.lower() in choice.lower():
                data.append(
                    app_commands.Choice(
                        name=choice.title().replace("Tiktok", "TikTok"), value=choice
                    )
                )
        return data

    class SocialAutofixTransformer(app_commands.Transformer):
        async def transform(self, interaction: discord.Interaction, value: str):
            if value not in list(SocialsJSON().load_json().keys()):
                return None

            return value

    @config_group.command(
        name="autofix", description="Enable or disable social autofix per site."
    )
    @app_commands.describe(site="Site to modify.")
    @app_commands.autocomplete(site=social_autofix_autocompletion)
    @app_commands.describe(enabled="Enable or disable autofix for this site.")
    @commands.has_permissions(manage_guild=True)
    async def social_autofix(
        self, context: Context, site: SocialAutofixTransformer, enabled: bool
    ):
        if site is None:
            embed = discord.Embed(
                color=discord.Color.red(),
            )
            embed.description = "No site found with that name."

            await context.send(embed=embed, ephemeral=True)
            return

        config = await self.get_guild_config(context.guild.id)
        config[site] = {}
        config[site]["enabled"] = enabled
        await self.set_guild_config(context.guild.id, config)

        await context.send(
            embed=await self.make_config_embed(context.guild.id),
        )


async def setup(bot):
    await bot.add_cog(Config(bot))
