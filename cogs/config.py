import json
from typing import List

import aiosqlite
import discord
from discord import Interaction, app_commands
from discord.ext import commands
from discord.ext.commands import Context

from utils.jsons import SocialsJSON


class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "config.db"
        self.db = None

    socials = SocialsJSON().load_json()

    async def cog_load(self):
        self.db = await aiosqlite.connect(self.db_path)
        await self.create_tables()

    async def cog_unload(self):
        await self.db.close()

    async def create_tables(self):
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                config TEXT NOT NULL
            )
        """
        )
        await self.db.commit()

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

    @commands.hybrid_group(
        name="config",
        description="Show or modify guild configuration",
        fallback="show",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @commands.has_permissions(manage_guild=True)
    async def config_group(self, context: Context):
        await context.send(
            f"```json\n{json.dumps(await self.get_guild_config(context.guild.id), indent=2)}\n```"
        )

    async def social_autofix_autocompletion(
        self, interaction: Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        data = []
        for choice in list(self.socials.keys()):
            if current.lower() in choice.lower():
                data.append(app_commands.Choice(name=choice, value=choice))
        return data

    class SocialAutofixTransformer(app_commands.Transformer):
        async def transform(self, interaction: discord.Interaction, value: str):
            if value not in list(SocialsJSON().load_json().keys()):
                return None

            return value

    @config_group.command(
        name="social-autofix", description="Enable or disable social autofix per site"
    )
    @app_commands.describe(site="Site to modify")
    @app_commands.autocomplete(site=social_autofix_autocompletion)
    @app_commands.describe(enabled="Enable or disable autofix for this site")
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
            f"```json\n{json.dumps(await self.get_guild_config(context.guild.id), indent=2)}\n```"
        )


async def setup(bot):
    await bot.add_cog(Config(bot))
