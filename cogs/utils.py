import io

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context


class Utilities(commands.Cog, name="utilities"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.allowed_mentions = discord.AllowedMentions.none()

    @commands.hybrid_command(
        name="steal",
        description="Add a new emoji to the server.",
    )
    @app_commands.describe(emoji="Discord emoji or a URL to an image.")
    @app_commands.describe(name="The name of the new emoji.")
    @app_commands.guild_only()
    @commands.has_permissions(create_expressions=True)
    @commands.bot_has_permissions(create_expressions=True)
    async def steal(self, context: Context, emoji: str, name: str = None) -> None:
        get_emoji = discord.PartialEmoji.from_str(emoji)
        if name and not name.isalnum():
            return await context.send(
                "Emoji name must be alphanumeric.", ephemeral=True
            )
        if get_emoji.id:
            url = f"https://cdn.discordapp.com/emojis/{get_emoji.id}.{('gif' if get_emoji.animated else 'png')}"
        elif name is None:
            return await context.send(
                "You must provide a name for the emoji.", ephemeral=True
            )

        async with aiohttp.ClientSession() as session:
            async with session.get(emoji if not get_emoji.id else url) as resp:
                image = io.BytesIO(await resp.read())
                e = await context.guild.create_custom_emoji(
                    name=name if name else get_emoji.name,
                    image=image.read(),
                    reason=f"Emoji added by @{context.author} ({context.author.id})",
                )
                await context.send(
                    f"Emoji <{'a' if e.animated else ''}:{e.name}:{e.id}> `:{e.name}:` was added."
                )


async def setup(bot):
    await bot.add_cog(Utilities(bot))
