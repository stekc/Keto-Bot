import asyncio
import io
import json
import math
import os
import re
from contextlib import suppress

import aiohttp
import discord
import numpy as np
from aiocache import cached
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context
from PIL import Image

from utils.colorthief import get_color


class Socials(commands.Cog, name="socials"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.allowed_mentions = discord.AllowedMentions.none()

        path = os.path.dirname(os.path.realpath(__file__))
        path = os.path.dirname(path)
        path = os.path.join(path, "config/socials.json")

        with open(path) as file:
            self.config = json.load(file)

        self.tiktok_pattern = re.compile(
            r"https:\/\/(www\.)?((vm|vt)\.tiktok\.com\/[A-Za-z0-9]+|tiktok\.com\/@[\w.]+\/(video|photo)\/[\d]+\/?|tiktok\.com\/t\/[a-zA-Z0-9]+\/)"
        )
        self.instagram_pattern = re.compile(
            r"https:\/\/(www\.)?instagram\.com\/(?:p|reel|reels)\/[^/?#&]+\/?(?:\?[^#\s]*)?"
        )
        self.reddit_pattern = re.compile(
            r"(https?://(?:www\.)?(?:old\.)?reddit\.com/r/[A-Za-z0-9_]+/(?:comments|s)/[A-Za-z0-9_]+(?:/[^/ ]+)?(?:/\w+)?)|(https?://(?:www\.)?redd\.it/[A-Za-z0-9]+)"
        )
        self.twitter_pattern = re.compile(
            r"(https:\/\/(www.)?(twitter|x)\.com\/[a-zA-Z0-9_]+\/status\/[0-9]+)"
        )
        self.youtube_shorts_pattern = re.compile(
            r"https?://(?:www\.)?youtube\.com/shorts/[a-zA-Z0-9_-]+"
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.author.bot:
            return

        message_content = message.content
        if tiktok_match := self.tiktok_pattern.search(message_content):
            link = tiktok_match.group(0)
            await self.fix_tiktok(message, link)
        elif instagram_match := self.instagram_pattern.search(message_content):
            link = instagram_match.group(0)
            await self.fix_instagram(message, link)
        elif reddit_match := self.reddit_pattern.search(message_content):
            link = reddit_match.group(0)
            await self.fix_reddit(message, link)
        elif twitter_match := self.twitter_pattern.search(message_content):
            link = twitter_match.group(0)
            await self.fix_twitter(message, link)
        elif youtube_shorts_match := self.youtube_shorts_pattern.search(
            message_content
        ):
            link = youtube_shorts_match.group(0)
            await self.fix_youtube_shorts(message, link)

    @cached(ttl=86400)
    async def quickvids(self, tiktok_url):
        qv_token = os.getenv("QUICKVIDS_TOKEN")
        if not qv_token or qv_token == "YOUR_QUICKVIDS_TOKEN_HERE":
            return None, None, None, None, None, None

        try:
            headers = {
                "content-type": "application/json",
                "user-agent": "Keto - stkc.win",
                "Authorization": f"Bearer {qv_token}",
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                url = "https://api.quickvids.win/v2/quickvids/shorturl"
                data = {"input_text": tiktok_url, "detailed": True}
                async with session.post(
                    url, json=data, timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        text = await response.text()
                        data = json.loads(text)
                        qv_url = data["quickvids_url"]
                        likes = data["details"]["post"]["counts"]["likes"]
                        comments = data["details"]["post"]["counts"]["comments"]
                        views = data["details"]["post"]["counts"]["views"]
                        author = data["details"]["author"]["username"]
                        author_link = data["details"]["author"]["link"]
                        return qv_url, likes, comments, views, author, author_link
                    else:
                        return None, None, None, None, None, None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None, None, None, None, None, None

    async def build_image_grid(self, image_urls):
        async with aiohttp.ClientSession() as session:

            async def fetch_image(url):
                async with session.get(url) as response:
                    if not response.status == 200:
                        return None
                    image = Image.open(io.BytesIO(await response.read()))
                    image.thumbnail((768, 768))
                    return image

            images = await asyncio.gather(
                *[fetch_image(url) for url in image_urls[:12]]
            )

        num_images = len(images)

        ideal_sqrt = math.sqrt(num_images)
        rows = round(ideal_sqrt)
        cols = math.ceil(num_images / rows)

        while rows * cols < num_images:
            rows += 1

        max_width, max_height = 0, 0
        for img in images:
            max_width = max(max_width, img.width)
            max_height = max(max_height, img.height)

        for i, img in enumerate(images):
            if img.width != max_width or img.height != max_height:
                images[i] = img.resize((max_width, max_height))

        grid_width = cols * max_width
        grid_height = rows * max_height

        grid_image = Image.new("RGB", (grid_width, grid_height))

        x, y = 0, 0
        for i, img in enumerate(images):
            grid_image.paste(img, (x, y))
            x += max_width
            if (i + 1) % cols == 0:
                y += max_height
                x = 0

        if grid_width > 1920:
            ratio = 1920 / grid_width
            grid_image = grid_image.resize((1920, round(grid_height * ratio)))

        output_image = io.BytesIO()
        grid_image.save(output_image, format="JPEG", quality=90)
        output_image.seek(0)
        return output_image

    @cached(ttl=86400)
    async def is_nsfw_reddit(self, link: str):
        try:
            async with aiohttp.ClientSession() as session:
                link = await self.get_url_redirect(link)
                async with session.get(link + ".json", timeout=5) as response:
                    if response.status == 200:
                        json_data = await response.json()
                        return json_data[0]["data"]["children"][0]["data"].get(
                            "over_18", False
                        )
                    return False
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def build_reddit_embed(self, link: str):
        if not self.config["reddit"]["build-embeds"]:
            return None, None

        try:
            async with aiohttp.ClientSession() as session:
                link = await self.get_url_redirect(link)
                async with session.get(link + ".json", timeout=5) as response:
                    if response.status != 200:
                        return None, None

                    json_data = await response.json()
                    post = json_data[0]["data"]["children"][0]["data"]
                    try:
                        reply = json_data[1]["data"]["children"][0]["data"]
                    except IndexError:
                        reply = None

                    post_id = post.get("id")
                    post_title = post.get("title")
                    post_author = post.get("author")
                    subreddit = post.get("subreddit")
                    selftext = (
                        post.get("selftext")
                        .replace("&gt;", "\>")
                        .replace("&lt;", "<")
                        .replace("&amp;", "&")
                        .replace("&#x200B;", "")
                    )
                    upvotes = post.get("ups")
                    comments = post.get("num_comments")
                    gallery = post.get("media_metadata") or None
                    post_domain = post.get("domain") or None
                    image = post.get("url_overridden_by_dest") or None
                    thumbnail = post.get("thumbnail") or None
                    images = []

                    if reply:
                        reply_body = (
                            reply.get("body")
                            .replace("&gt;", "\>")
                            .replace("&lt;", "<")
                            .replace("&amp;", "&")
                            .replace("&#x200B;", "")
                        )
                        reply_author = reply.get("author")

                    if gallery:
                        images = []
                        for key in gallery:
                            images.append(
                                gallery[key]["s"]["u"]
                                .replace("preview.redd.it/", "i.redd.it/")
                                .split("?")[0]
                            )
                        grid = await self.build_image_grid(images)
                    else:
                        grid = None

                    if image:
                        image = image.lower()
                        if "v.redd.it" in image or image.endswith((".mp4", ".webm")):
                            return None, None
                        if not image.endswith((".jpg", ".jpeg", ".png", ".gif")):
                            image = None

                    if thumbnail:
                        thumbnail = thumbnail.lower()
                        if not thumbnail.endswith((".jpg", ".jpeg", ".png", ".gif")):
                            thumbnail = None

                    color = await get_color(image) if image else 0xEC6333
                    color = (
                        await get_color(thumbnail) if thumbnail and not image else color
                    )

                    post_title = (
                        post_title[:253] + "..."
                        if len(post_title) > 256
                        else post_title
                    )
                    selftext = (
                        selftext[:1997] + "..." if len(selftext) > 2000 else selftext
                    )

                    embed = discord.Embed(url=f"https://redd.it/{post_id}")
                    embed.title = (
                        f"{post_title} ({post_domain})"
                        if post_domain
                        and not any(
                            substring in post_domain
                            for substring in (
                                f"self.{subreddit}",
                                "reddit.com",
                                "redd.it",
                            )
                        )
                        else post_title
                    )
                    embed.url = f"https://redd.it/{post_id}"
                    embed.description = selftext
                    embed.color = color

                    embed.set_footer(
                        text=f"u/{post_author} • r/{subreddit} • ⬆️ {await self.format_number_str(upvotes)} • 💬 {await self.format_number_str(comments)}"
                    )

                    if grid:
                        image_file = discord.File(grid, filename=f"{post_id}.jpg")
                        embed.set_image(url=f"attachment://{post_id}.jpg")
                    elif image:
                        embed.set_image(url=image)
                    elif thumbnail:
                        embed.set_thumbnail(url=thumbnail)

                    if re.search(r"/[a-z0-9]{6,7}$", link):
                        embed.description = None
                        embed.add_field(
                            name=f"Reply by u/{reply_author}",
                            value=(
                                ">>> " + reply_body[:1017] + "..."
                                if len(reply_body) > 1020
                                else ">>> " + reply_body
                            ),
                            inline=False,
                        )
                        if len(selftext) > 0:
                            embed.add_field(
                                name="Original Post",
                                value=(
                                    ">>> " + selftext[:1017] + "..."
                                    if len(selftext) > 1020
                                    else ">>> " + selftext
                                ),
                            )
                        else:
                            embed.add_field(name="Original Post", value="[no text]")

                    return embed, image_file if grid else None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None, None

    @cached(ttl=86400)
    async def is_carousel_tiktok(self, link: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(link, timeout=5) as response:
                    if response.status == 200:
                        text = await response.text()
                        return ">Download All Images</button>" in text
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    @cached(ttl=86400)
    async def get_url_redirect(self, link: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(link, allow_redirects=False) as response:
                if response.status != 301:
                    return link

                redirected_url = str(response).split("Location': '")[1].split("'")[0]

        try:
            tracking_id_index = redirected_url.index("?")
            redirected_url = redirected_url[:tracking_id_index]
        except ValueError:
            return link

        return redirected_url

    async def format_number_str(self, num):
        if num >= 1000:
            powers = ["", "k", "M", "B", "T"]
            power = max(0, min(int((len(str(num)) - 1) / 3), len(powers) - 1))
            scaled_num = round(num / (1000**power), 1)
            formatted_num = f"{scaled_num:.1f}{powers[power]}"
            return formatted_num
        else:
            return str(num)

    @commands.hybrid_command(
        name="fix",
        description="Fix a social media link.",
    )
    @app_commands.describe(
        link="The social media link to fix.",
        spoiler="Whether to spoiler the fixed link.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def fix(self, context: Context, link: str, spoiler: bool = False) -> None:
        if re.match(self.tiktok_pattern, link):
            await self.fix_tiktok(context.message, link, context, spoiler)
        elif re.match(self.instagram_pattern, link):
            await self.fix_instagram(context.message, link, context, spoiler)
        elif re.match(self.reddit_pattern, link):
            await self.fix_reddit(context.message, link, context, spoiler)
        elif re.match(self.twitter_pattern, link):
            await self.fix_twitter(context.message, link, context, spoiler)
        elif re.match(self.youtube_shorts_pattern, link):
            await self.fix_youtube_shorts(context.message, link, context, spoiler)
        else:
            await context.send("Invalid social media link.")

    @commands.hybrid_command(
        name="tiktok",
        description="Fix a TikTok link.",
    )
    @app_commands.describe(
        link="The TikTok link to fix.",
        spoiler="Whether to spoiler the fixed link.",
    )
    @app_commands.allowed_installs(guilds=False, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def tiktok(self, context: Context, link: str, spoiler: bool = False) -> None:
        if not re.match(self.tiktok_pattern, link):
            return await context.send("Invalid TikTok link.")
        await self.fix_tiktok(context.message, link, context, spoiler)

    async def fix_tiktok(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
    ):
        if not self.config["tiktok"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return
        spoiler = spoiler or (
            f"||{link}" in message.content and message.content.count("||") >= 2
        )
        if (
            redirected_url := await self.get_url_redirect(link)
        ) is None or redirected_url.endswith("/live"):
            return

        quickvids_url, likes, comments, views, author, author_link = (
            None,
            None,
            None,
            None,
            None,
            None,
        )
        if not spoiler:
            quickvids_url, likes, comments, views, author, author_link = (
                await self.quickvids(link)
            )
        if quickvids_url:
            redirected_url = quickvids_url
        else:
            redirected_url = redirected_url.replace("www.", "")
            redirected_url = redirected_url.replace(
                "tiktok.com", self.config["tiktok"]["url"]
            )

        view = discord.ui.View()
        if likes is not None:
            view.add_item(
                discord.ui.Button(
                    label=await self.format_number_str(likes),
                    disabled=True,
                    style=discord.ButtonStyle.red,
                    emoji="🤍",
                )
            )
            view.add_item(
                discord.ui.Button(
                    label=await self.format_number_str(comments),
                    disabled=True,
                    style=discord.ButtonStyle.blurple,
                    emoji="💬",
                )
            )
            view.add_item(
                discord.ui.Button(
                    label=await self.format_number_str(views),
                    disabled=True,
                    style=discord.ButtonStyle.blurple,
                    emoji="👀",
                )
            )
            view.add_item(
                discord.ui.Button(
                    label="@" + author,
                    style=discord.ButtonStyle.url,
                    url=author_link,
                    emoji="👤",
                )
            )

        if context:
            await context.send(
                redirected_url if not spoiler else f"||{redirected_url}||",
                mention_author=False,
                view=view,
            )
        else:
            if message.channel.permissions_for(message.guild.me).send_messages:
                await message.reply(
                    redirected_url if not spoiler else f"||{redirected_url}||",
                    mention_author=False,
                    view=view,
                )
                await asyncio.sleep(0.75)
                with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                    await message.edit(suppress=True)

    async def fix_instagram(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
    ):
        if not self.config["instagram"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return
        spoiler = spoiler or (
            f"||{link}" in message.content and message.content.count("||") >= 2
        )
        og_link = link
        tracking = False
        tracking_warning = ""

        if self.config["instagram"]["block-tracking"]:
            tracking_pattern = r"\?igsh=[\w=]+"
            if re.search(tracking_pattern, link):
                link = re.sub(tracking_pattern, "", link)
                tracking = True
                tracking_warning = "\n-# Your message was removed because it included a tracking ID (?igsh=...) which could potentially reveal your Instagram account."

        link = link.replace("www.", "")
        link = link.replace("instagram.com", self.config["instagram"]["url"])

        if "/reel/" or "/reels/" in link:
            link = link.replace(
                self.config["instagram"]["url"], "d." + self.config["instagram"]["url"]
            )

        org_msg = link if not spoiler else f"||{link}||"
        msg = org_msg
        if tracking:
            msg = org_msg + tracking_warning
        if len(message.content.replace(og_link, "")) < 10:
            op_msg = ""
        else:
            op_msg = f'\n\n> {message.content.replace("\n", " ").replace(og_link, "")}\n{message.author.mention}'

        if context:
            await context.send(org_msg, mention_author=False)
        else:
            if message.channel.permissions_for(message.guild.me).send_messages:
                fixed = await message.reply(
                    msg + op_msg if tracking else msg, mention_author=False
                )
                if tracking:
                    await message.delete()
                    await asyncio.sleep(10)
                    await fixed.edit(content=org_msg + op_msg)

                else:
                    await asyncio.sleep(0.75)
                    with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                        await message.edit(suppress=True)

    async def fix_reddit(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
    ):
        if not self.config["reddit"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return
        spoiler = spoiler or (
            f"||{link}" in message.content and message.content.count("||") >= 2
        )

        is_nsfw = await self.is_nsfw_reddit(link)

        if message.guild:
            if is_nsfw:
                if not message.channel.is_nsfw():
                    embed = discord.Embed(
                        title="NSFW",
                        description="To use this feature you must be in a NSFW channel.",
                        color=discord.Color.red(),
                    )
                    if context:
                        await context.reply(
                            embed=embed, mention_author=False, delete_after=30
                        )
                        return
                    else:
                        await message.reply(
                            embed=embed,
                            mention_author=False,
                            delete_after=30,
                        )
                        return

        if context:
            embed, file = None, None
        elif not spoiler:
            embed, file = await self.build_reddit_embed(link)
            if embed is None:
                link = link.replace("www.", "")
                link = link.replace("old.reddit.com", "reddit.com")
                link = link.replace("reddit.com", self.config["reddit"]["url"])
                if context:
                    await context.send(
                        link if not spoiler else f"||{link}||", mention_author=False
                    )
                else:
                    if message.channel.permissions_for(message.guild.me).send_messages:
                        await message.reply(
                            link if not spoiler else f"||{link}||", mention_author=False
                        )
                        await asyncio.sleep(0.75)
                        with suppress(
                            discord.errors.Forbidden, discord.errors.NotFound
                        ):
                            await message.edit(suppress=True)
                    return

        if embed:
            if is_nsfw:
                footer = embed.footer.text
                embed.set_footer(text=f"NSFW • {footer}")
            if context:
                await context.send(embed=embed, file=file, mention_author=False)
            else:
                if message.channel.permissions_for(message.guild.me).send_messages:
                    await message.reply(embed=embed, file=file, mention_author=False)
                    await asyncio.sleep(0.75)
                    with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                        await message.edit(suppress=True)

    async def fix_twitter(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
    ):
        if not self.config["twitter"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return
        spoiler = spoiler or (
            f"||{link}" in message.content and message.content.count("||") >= 2
        )

        link = link.replace("www.", "")
        link = link.replace("x.com", "twitter.com")
        link = link.replace("twitter.com", self.config["twitter"]["url"])

        if context:
            await context.send(
                link if not spoiler else f"||{link}||", mention_author=False
            )
        else:
            if message.channel.permissions_for(message.guild.me).send_messages:
                await message.reply(
                    link if not spoiler else f"||{link}||", mention_author=False
                )
                await asyncio.sleep(0.75)
                with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                    await message.edit(suppress=True)

    async def fix_youtube_shorts(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
    ):
        if not self.config["youtubeshorts"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return
        spoiler = spoiler or (
            f"||{link}" in message.content and message.content.count("||") >= 2
        )

        link = link.replace("www.", "")
        link = link.replace("youtube.com/shorts/", self.config["youtubeshorts"]["url"])

        if context:
            await context.reply(
                link if not spoiler else f"||{link}||", mention_author=False
            )
        else:
            if message.channel.permissions_for(message.guild.me).send_messages:
                await message.reply(
                    link if not spoiler else f"||{link}||", mention_author=False
                )
                await asyncio.sleep(0.75)
                with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                    await message.edit(suppress=True)


async def setup(bot):
    await bot.add_cog(Socials(bot))
