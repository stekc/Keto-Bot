import io
import json
import os
import re

import aiohttp
import discord
from discord import Interaction, app_commands
from discord.ext import commands

from utils.jsons import ConfigJSON


class PFPView(discord.ui.View):
    def __init__(self, interaction: Interaction, embed=discord.Embed):
        super().__init__(timeout=30)
        self.embed = embed
        self.interaction = interaction

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

        if self.interaction.response.is_done():
            await self.interaction.message.edit(embed=self.embed, view=self)
        else:
            await self.interaction.response.send_message(embed=self.embed, view=self)


class PFPButton(discord.ui.Button):
    def __init__(self, member: discord.Member):
        super().__init__(label="Show other avatar", style=discord.ButtonStyle.primary)
        self.member = member
        self.other = False

    async def callback(self, interaction: discord.Interaction):
        if not self.other:
            avatar = self.member.guild_avatar
            self.other = not self.other
        else:
            avatar = self.member.avatar or self.member.default_avatar
            self.other = not self.other

        embed = interaction.message.embeds[0]
        embed.set_image(url=avatar.replace(size=4096))

        animated = ["gif", "png", "jpeg", "webp"]
        not_animated = ["png", "jpeg", "webp"]

        def fmt(format_):
            return f"[{format_}]({avatar.replace(format=format_, size=4096)})"

        if avatar.is_animated():
            embed.description = (
                f"View As\n {'  '.join([fmt(format_) for format_ in animated])}"
            )
        else:
            embed.description = (
                f"View As\n {'  '.join([fmt(format_) for format_ in not_animated])}"
            )

        self.view.embed = embed
        await interaction.response.edit_message(embed=embed)


config = ConfigJSON().load_json()


async def handle_avatar(interaction: Interaction, member: discord.Member):
    embed = discord.Embed(title=f"{member}'s avatar")
    animated = ["gif", "png", "jpeg", "webp"]
    not_animated = ["png", "jpeg", "webp"]

    avatar = member.avatar or member.default_avatar

    def fmt(format_):
        return f"[{format_}]({avatar.replace(format=format_, size=4096)})"

    if member.display_avatar.is_animated():
        embed.description = f"{'  '.join([fmt(format_) for format_ in animated])}"
    else:
        embed.description = f"{'  '.join([fmt(format_) for format_ in not_animated])}"

    embed.set_image(url=avatar.replace(size=4096))
    embed.color = discord.Color.random()

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def handle_steal(interaction: Interaction, message: discord.Message):
    added = []
    matches = re.finditer(r"(?:a:|<a:|<:)?(\w+):(\d+)(?:>)?", message.content)

    for match in matches:
        full_match = match.group(0)
        emoji_name = match.group(1)

        get_emoji = discord.PartialEmoji.from_str(full_match)

        if get_emoji.id:
            url = f"https://cdn.discordapp.com/emojis/{get_emoji.id}.{('gif' if get_emoji.animated else 'png')}"

        async with aiohttp.ClientSession() as session:
            async with session.get(full_match if not get_emoji.id else url) as resp:
                image = io.BytesIO(await resp.read())
                e = await interaction.guild.create_custom_emoji(
                    name=get_emoji.name if get_emoji.name else emoji_name,
                    image=image.read(),
                    reason=f"Emoji added by @{interaction.user} ({interaction.user.id})",
                )
                added.append(e)

    if not added:
        embed = discord.Embed(
            color=discord.Color.red(),
        )
        embed.description = "No emojis were found in the message."
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    text = f"The following emojis were added:"
    for e in added:
        text = f"{text}\n- <{'a' if e.animated else ''}:{e.name}:{e.id}> `:{e.name}:`"

    embed = discord.Embed(
        color=discord.Color.green(),
    )
    embed.description = text

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


def add_context_commands(bot: commands.Bot):
    @bot.tree.context_menu(name="View Avatar")
    async def avatar_rc(interaction: discord.Interaction, member: discord.Member):
        await handle_avatar(interaction, member)

    @bot.tree.context_menu(name="View Avatar")
    async def avatar_msg(interaction: discord.Interaction, message: discord.Message):
        await handle_avatar(interaction, message.author)

    @app_commands.guild_only()
    @bot.tree.context_menu(name="Steal Emojis")
    async def steal_emoji_msg(
        interaction: discord.Interaction, message: discord.Message
    ):
        if not interaction.user.guild_permissions.create_expressions:
            embed = discord.Embed(
                color=discord.Color.red(),
            )
            embed.description = "You are missing the permission(s) `create_expressions` to execute this command!"
            await interaction.response.send_message(embed=embed)
        else:
            await handle_steal(interaction, message)
