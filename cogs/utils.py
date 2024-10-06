import asyncio
import io
import platform

import aiohttp
import discord
import psutil
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context

from utils.colorthief import get_color


class Utilities(commands.Cog, name="utilities"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.allowed_mentions = discord.AllowedMentions.none()
        self.last_logged_messages = {}

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild:
            return
        if len(message.content) < 3:
            return
        if message.channel.id not in self.last_logged_messages:
            self.last_logged_messages[message.channel.id] = []
        self.last_logged_messages[message.channel.id].append(("delete", message, None))

        asyncio.create_task(self.remove_logged_message(message.channel.id, message))

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild:
            return
        if before.content == after.content:
            return
        if before.channel.id not in self.last_logged_messages:
            self.last_logged_messages[before.channel.id] = []
        self.last_logged_messages[before.channel.id].append(("edit", before, after))

        asyncio.create_task(self.remove_logged_message(before.channel.id, before))

    async def remove_logged_message(self, channel_id, message):
        await asyncio.sleep(120)
        if channel_id in self.last_logged_messages:
            self.last_logged_messages[channel_id] = [
                m
                for m in self.last_logged_messages[channel_id]
                if m[1].id != message.id
            ]
            if not self.last_logged_messages[channel_id]:
                del self.last_logged_messages[channel_id]

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

    @commands.hybrid_command(
        name="jumbo",
        description="Enlarge an emoji.",
    )
    @app_commands.describe(emoji="Discord emoji.")
    async def jumbo(self, context: Context, emoji: str) -> None:
        get_emoji = discord.PartialEmoji.from_str(emoji)
        if not get_emoji.id:
            return await context.send("You must provide a valid emoji.", ephemeral=True)

        url = f"https://cdn.discordapp.com/emojis/{get_emoji.id}.{('gif' if get_emoji.animated else 'png')}"
        embed = discord.Embed(
            color=await get_color(url),
        )
        embed.set_image(url=url)
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="info",
        description="View information about the bot.",
    )
    async def info(self, context: Context) -> None:
        embed = discord.Embed(color=await get_color(self.bot.user.avatar.url))
        embed.add_field(name="Ping", value=f"{int(self.bot.latency * 1000)} ms")
        embed.add_field(name="Python Version", value=platform.python_version())
        embed.add_field(name="Discord.py Version", value=discord.__version__)
        embed.add_field(
            name="RAM Usage",
            value=f"{int(psutil.virtual_memory().used / 1024 ** 2)} MB ({int(psutil.Process().memory_info().rss / 1024 ** 2)} MB) / {int(psutil.virtual_memory().total / 1024 ** 2)} MB",
        )
        embed.add_field(name="Host", value=platform.system() + " " + platform.release())
        embed.add_field(name="Website", value="https://keto.boats", inline=False)
        embed.add_field(
            name="Add Bot",
            value="https://discord.com/oauth2/authorize?client_id=1128948590467895396",
            inline=False,
        )
        embed.add_field(
            name="Support Server", value="https://discord.gg/FVvaa9QZnm", inline=False
        )
        await context.send(embed=embed)

    async def snipe_edit(
        self, before: discord.Message, after: discord.Message
    ) -> discord.Embed:
        embed = discord.Embed(
            color=await get_color(before.author.avatar.url),
        )

        embed.set_author(
            name=before.author.display_name + " edited a message",
            icon_url=before.author.avatar.url,
        )
        embed.add_field(name="Before", value=before.content, inline=False)
        embed.add_field(name="After", value=after.content, inline=False)
        embed.timestamp = before.created_at

        return embed

    async def snipe_delete(self, message: discord.Message) -> discord.Embed:
        embed = discord.Embed(
            description=message.content,
            color=await get_color(message.author.avatar.url),
        )

        embed.set_author(
            name=message.author.display_name + " deleted a message",
            icon_url=message.author.avatar.url,
        )
        embed.timestamp = message.created_at

        if message.attachments:
            embed.description += "\n\n-# These attachments will be removed by Discord soon, download them quickly."
            attachment_list = []
            for i, attachment in enumerate(message.attachments, 1):
                attachment_list.append(f"[{attachment.filename}]({attachment.url})")
                if i == 1:
                    embed.set_image(url=attachment.url)

            embed.add_field(
                name="Attachments" if len(message.attachments) > 1 else "Attachment",
                value="\n".join(attachment_list),
                inline=False,
            )

        return embed

    @commands.hybrid_command(
        name="snipe",
        description="Show the last edited or deleted message in the current channel.",
    )
    @commands.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def snipe(self, context: Context) -> None:
        messages = self.last_logged_messages.get(context.channel.id, [])
        if not messages:
            embed = discord.Embed(
                description="There are no recently edited or deleted messages in this channel.",
                color=discord.Color.red(),
            )
            await context.send(embed=embed, ephemeral=True)
            return

        type, original, after = messages.pop()
        embed = None

        if type == "edit":
            embed = await self.snipe_edit(original, after)
        elif type == "delete":
            embed = await self.snipe_delete(message=original)

        if embed is None:
            embed = discord.Embed(
                description="There are no recently edited or deleted messages in this channel.",
                color=discord.Color.red(),
            )
            await context.send(embed=embed, ephemeral=True)
            return

        await context.send(embed=embed)

    @commands.hybrid_command(
        name="edited",
        description="Show the last edited message in the current channel.",
    )
    @commands.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def snipe_group_edit(self, context: Context) -> None:
        messages = self.last_logged_messages.get(context.channel.id, [])
        if not messages:
            embed = discord.Embed(
                description="There are no recently edited messages in this channel.",
                color=discord.Color.red(),
            )
            await context.send(embed=embed, ephemeral=True)
            return

        _, original, after = messages.pop()
        embed = await self.snipe_edit(original, after)

        await context.send(embed=embed)

    @commands.hybrid_command(
        name="deleted",
        description="Show the last deleted message in the current channel.",
    )
    @commands.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def snipe_group_delete(self, context: Context) -> None:
        messages = self.last_logged_messages.get(context.channel.id, [])
        if not messages:
            embed = discord.Embed(
                description="There are no recently deleted messages in this channel.",
                color=discord.Color.red(),
            )
            await context.send(embed=embed, ephemeral=True)
            return

        _, message, _ = messages.pop()
        embed = await self.snipe_delete(message)

        await context.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Utilities(bot))
