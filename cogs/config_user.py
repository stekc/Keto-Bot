import json
from typing import List

import aiosqlite
import discord
from discord import Interaction, app_commands
from discord.ext import commands
from discord.ext.commands import Context

from utils.jsons import SocialsJSON, TrackingJSON


class UserConfig(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "config.db"
        self.db = None

    socials = TrackingJSON().load_json()

    async def cog_load(self):
        self.db = await aiosqlite.connect(self.db_path)
        await self.create_tables()

    async def cog_unload(self):
        await self.db.close()

    async def create_tables(self):
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_config (
                user_id INTEGER PRIMARY KEY,
                config TEXT NOT NULL
            )
        """
        )
        await self.db.commit()

    async def get_user_config(self, user_id: int):
        async with self.db.execute(
            "SELECT config FROM user_config WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
        return json.loads("{}")

    async def set_user_config(self, user_id: int, config: dict):
        config_json = json.dumps(config)
        await self.db.execute(
            """
            INSERT OR REPLACE INTO user_config (user_id, config)
            VALUES (?, ?)
        """,
            (user_id, config_json),
        )
        await self.db.commit()

    async def get_config_value(self, user_id: int, key: str, value: str):
        config = await self.get_user_config(user_id)
        return config.get(key, {}).get(
            value, self.socials.get(key, {}).get(value, True)
        )

    async def make_config_embed(self, user_id: int):
        user_config = await self.get_user_config(user_id)

        embed = discord.Embed(title="User Configuration", color=discord.Color.blue())

        for platform in self.socials:
            config = user_config.get(platform, {"enabled": True})
            status = "🟢 Enabled" if config.get("enabled", True) else "🔴 Disabled"
            embed.add_field(
                name=platform.title().replace("Tiktok", "TikTok") + " Tracking Warning",
                value=status,
                inline=False,
            )

        return embed

    @commands.hybrid_group(
        name="preferences",
        description="Show or modify user configuration.",
        fallback="show",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def config_group(self, context: Context):
        await context.send(
            embed=await self.make_config_embed(context.author.id), ephemeral=True
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
        name="tracking",
        description="Enable or disable tracking warnings per site.",
    )
    @app_commands.describe(site="Site to modify.")
    @app_commands.autocomplete(site=social_autofix_autocompletion)
    @app_commands.describe(enabled="Enable or disable tracking warnings for this site.")
    async def tracking(
        self, context: Context, site: SocialAutofixTransformer, enabled: bool
    ):
        if site is None:
            embed = discord.Embed(
                color=discord.Color.red(),
            )
            embed.description = "No site found with that name."

            await context.send(embed=embed, ephemeral=True)
            return

        config = await self.get_user_config(context.author.id)
        config[site] = {}
        config[site]["enabled"] = enabled
        await self.set_user_config(context.author.id, config)

        await context.send(
            embed=await self.make_config_embed(context.author.id), ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(UserConfig(bot))
