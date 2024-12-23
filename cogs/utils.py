import asyncio
import io
import os
import platform

import aiocache
import aiohttp
import discord
import psutil
import redis.asyncio as aioredis
from discord import app_commands
from discord.ext import commands, tasks
from discord.ext.commands import Context

from utils.colorthief import get_color


class Utilities(commands.Cog, name="utilities"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.allowed_mentions = discord.AllowedMentions.none()
        self.last_logged_messages = {}

    async def format_number_str(self, num):
        if num >= 1000:
            powers = ["", "k", "M", "B", "T"]
            power = max(0, min(int((len(str(num)) - 1) / 3), len(powers) - 1))
            scaled_num = round(num / (1000**power), 1)
            formatted_num = f"{scaled_num:.1f}{powers[power]}"
            return formatted_num
        else:
            return str(num)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild:
            return
        if len(message.content) < 3 and not message.embeds:
            return
        if (
            message.embeds
            and message.author.id == self.bot.user.id
            and message.embeds[0].author.name.endswith("deleted a message")
        ):
            return
        if message.channel.id not in self.last_logged_messages:
            self.last_logged_messages[message.channel.id] = []
        self.last_logged_messages[message.channel.id].append(
            ("delete", message, None, message.embeds if message.embeds else None)
        )

        asyncio.create_task(self.remove_logged_message(message.channel.id, message))

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild:
            return
        if before.content == after.content:
            return
        if before.channel.id not in self.last_logged_messages:
            self.last_logged_messages[before.channel.id] = []
        self.last_logged_messages[before.channel.id].append(
            ("edit", before, after, None)
        )

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
        embed.add_field(
            name="Shard", value=f"{context.guild.shard_id + 1}/{self.bot.shard_count}"
        )
        embed.add_field(
            name="RAM Usage",
            value=f"{int(psutil.virtual_memory().used / 1024 ** 2)} MB ({int(psutil.Process().memory_info().rss / 1024 ** 2)} MB) / {int(psutil.virtual_memory().total / 1024 ** 2)} MB",
        )

        try:
            redis_client = await aioredis.from_url(
                f"redis://:{os.getenv('REDIS_PASSWORD')}@{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/0"
            )
            info = await redis_client.info()
            keys = await redis_client.dbsize()
            used_memory = int(info["used_memory"]) / (1024 * 1024)

            key_patterns = {}
            async for key in redis_client.scan_iter("*"):
                pattern = key.decode().split(":")[0]
                key_patterns[pattern] = key_patterns.get(pattern, 0) + 1

            pattern_stats = "\n".join(
                f"• [{pattern.replace('---', '] ').capitalize()}: {count:,}"
                for pattern, count in key_patterns.items()
            )

            embed.add_field(
                name="Cache Info",
                value=f"Total Items: {keys:,}\nMemory: {used_memory:.1f} MB",
                inline=False,
            )
            embed.add_field(name="Key Breakdown", value=pattern_stats, inline=False)
            await redis_client.close()
        except Exception as e:
            embed.add_field(
                name="Cache Stats",
                value=f"Unable to fetch cache statistics:\n{e}",
                inline=False,
            )

        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Website",
                style=discord.ButtonStyle.url,
                url="https://keto.boats",
            )
        )
        view.add_item(
            discord.ui.Button(
                label="Add Bot",
                style=discord.ButtonStyle.url,
                url="https://discord.com/oauth2/authorize?client_id=1128948590467895396",
            )
        )
        view.add_item(
            discord.ui.Button(
                label="Support Server",
                style=discord.ButtonStyle.url,
                url="https://discord.gg/FVvaa9QZnm",
            )
        )

        await context.send(embed=embed, view=view)

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

    async def snipe_delete(
        self, message: discord.Message, stored_embeds=None
    ) -> discord.Embed:
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

        return embed, stored_embeds

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

        last_message = messages[-1]
        type, original, after, stored_embeds = last_message
        embed = None
        additional_embeds = None

        try:
            if type == "edit":
                embed = await self.snipe_edit(original, after)
            elif type == "delete":
                embed, additional_embeds = await self.snipe_delete(
                    message=original, stored_embeds=stored_embeds
                )

            if embed is None:
                embed = discord.Embed(
                    description="There are no recently edited or deleted messages in this channel.",
                    color=discord.Color.red(),
                )
                await context.send(embed=embed, ephemeral=True)
                return

            messages.pop()

            if additional_embeds:
                all_embeds = [embed] + (additional_embeds if additional_embeds else [])
                await context.send(embeds=all_embeds)
            else:
                await context.send(embed=embed)

        except:
            embed = discord.Embed(
                description="An error occurred retrieving the message.",
                color=discord.Color.red(),
            )
            await context.send(embed=embed, ephemeral=True)

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

        type, message, _, stored_embeds = messages.pop()
        embed, additional_embeds = await self.snipe_delete(message, stored_embeds)

        if additional_embeds:
            all_embeds = [embed] + (additional_embeds if additional_embeds else [])
            await context.send(embeds=all_embeds)
        else:
            await context.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Utilities(bot))
