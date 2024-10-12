import asyncio
import io
import os
import platform
from typing import List, Optional

import aiohttp
import discord
import psutil
from discord import Interaction, app_commands
from discord.ext import commands, tasks
from discord.ext.commands import Context
from openai import AsyncOpenAI

from utils.colorthief import get_color


class AI(commands.Cog, name="AI"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.allowed_mentions = discord.AllowedMentions.none()
        self.openai = AsyncOpenAI(api_key=os.getenv("OPENAI_TOKEN"))
        self.models = ["gpt-4o-mini", "gpt-4o", "o1-mini", "o1-preview"]
        approved_guilds_str = os.getenv('OPENAI_APPROVED_GUILDS')
        self.approved_guilds = [int(guild_id) for guild_id in approved_guilds_str.split(',')]
        approved_users_str= os.getenv('OPENAI_APPROVED_USERS')
        self.approved_users = [int(user_id) for user_id in approved_users_str.split(',')]

    async def models_autocompletion(
        self, interaction: Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices = self.models
        return [
            app_commands.Choice(name=choice, value=choice)
            for choice in choices
            if current.lower() in choice.lower()
        ]

    @commands.hybrid_command(
        name="chatgpt",
        description="Talk with ChatGPT.",
    )
    @app_commands.autocomplete(model=models_autocompletion)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def chatgpt(
        self,
        context: Context,
        message: str,
        image: Optional[discord.Attachment] = None,
        model: str = None,
    ):
        if not model:
            model = "gpt-4o-mini"
        if model in ["o1-mini", "o1-preview"] and image:
            return await context.send(
                "Images are not supported for o1 models.",
                ephemeral=True,
            )
        if model not in self.models:
            return await context.send(
                "Invalid model. Please choose from the available models.",
                ephemeral=True,
            )

        if context.guild:
            if (
                context.guild.id not in self.approved_guilds
                and context.author.id not in self.approved_users
            ):
                return await context.send(
                    "This server is not whitelisted to use this command.",
                    ephemeral=True,
                )
        else:
            if context.author.id not in self.approved_users:
                return await context.send(
                    "You are not whitelisted to use this command.", ephemeral=True
                )

        async with context.typing():
            prompt = [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": message}],
                }
            ]

            if image:
                prompt[0]["content"].append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image.url,
                        },
                    }
                )

            completion = await self.openai.chat.completions.create(
                model=model,
                messages=prompt,
            )
            response = completion.choices[0].message.content
            if len(response) > 4096:
                messages = []
                for i in range(0, len(response), 4096):
                    embed = discord.Embed(
                        description=response[i : i + 4096], color=discord.Color.blue()
                    )
                    if i == 0:
                        embed.title = f"{model} says:"
                    msg = await context.send(embed=embed)
                    messages.append(msg)
            else:
                embed = discord.Embed(description=response, color=discord.Color.blue())
                embed.title = f"{model} says:"
                msg = await context.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AI(bot))
