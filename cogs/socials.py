import asyncio
import json
import os
import re
from contextlib import suppress

import aiohttp
import discord
from aiocache import cached
from discord.ext import commands

from utils.colorthief import get_color


class Refresh(discord.ui.View):
    def __init__(self, timeout, socials_instance):
        super().__init__(timeout=timeout)
        self.response = None
        self.socials_instance = socials_instance
        self.callback_run = False

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji="🔁")
    async def button_callback(self, interaction, button):
        tiktok_url = await interaction.channel.fetch_message(
            interaction.message.reference.message_id
        )
        tiktok_url = tiktok_url.content

        try:
            likes, comments, views, author, author_link = (
                await self.socials_instance.quickvids_detailed(tiktok_url)
            )
            self.callback_run = True
        except TypeError:
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    disabled=True,
                    style=discord.ButtonStyle.gray,
                    emoji="❌",
                )
            )
            await self.response.edit(view=view)
            return await interaction.response.defer(ephemeral=True)

        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label=await self.socials_instance.format_number_str(likes),
                disabled=True,
                style=discord.ButtonStyle.red,
                emoji="🤍",
            )
        )
        view.add_item(
            discord.ui.Button(
                label=await self.socials_instance.format_number_str(comments),
                disabled=True,
                style=discord.ButtonStyle.blurple,
                emoji="💬",
            )
        )
        view.add_item(
            discord.ui.Button(
                label=await self.socials_instance.format_number_str(views),
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
        await interaction.message.edit(view=view)
        await interaction.response.defer(ephemeral=True)

    async def on_timeout(self):
        if self.callback_run:
            return
        with suppress(discord.errors.NotFound):
            await self.response.edit(view=None)


class Socials(commands.Cog, name="socials"):
    def __init__(self, bot):
        self.bot = bot

        path = os.path.dirname(os.path.realpath(__file__))
        path = os.path.dirname(path)
        path = os.path.join(path, "config/socials.json")

        with open(path) as file:
            self.config = json.load(file)

        self.tiktok_pattern = re.compile(
            r"https:\/\/(www.)?((vm|vt).tiktok.com\/[A-Za-z0-9]+|tiktok.com\/@[\w.]+\/video\/[\d]+\/?|tiktok.com\/t\/[a-zA-Z0-9]+\/)"
        )
        self.instagram_pattern = re.compile(
            r"(https:\/\/(www.)?instagram\.com\/(?:p|reel)\/([^/?#&]+))\/"
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

    @cached(ttl=3600)
    async def quickvids(self, tiktok_url):
        try:
            headers = {
                "content-type": "application/json",
                "user-agent": "Keto 2 - stkc.win",
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                url = "https://api.quickvids.win/v1/shorturl/create"
                data = {"input_text": tiktok_url}
                async with session.post(
                    url, json=data, timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        text = await response.text()
                        data = json.loads(text)
                        quickvids_url = data["quickvids_url"]
                        return quickvids_url
                    else:
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    @cached(ttl=3600)
    async def quickvids_detailed(self, tiktok_url):
        try:
            headers = {
                "content-type": "application/json",
                "user-agent": "Keto - stkc.win",
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                url = "https://api.quickvids.win/v1/shorturl/create"
                data = {"input_text": tiktok_url, "detailed": True}
                async with session.post(
                    url, json=data, timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        text = await response.text()
                        data = json.loads(text)
                        likes = data["details"]["video"]["counts"]["likes"]
                        comments = data["details"]["video"]["counts"]["comments"]
                        views = data["details"]["video"]["counts"]["views"]
                        author = data["details"]["author"]["username"]
                        author_link = data["details"]["author"]["link"]
                        return (
                            likes,
                            comments,
                            views,
                            author,
                            author_link,
                        )
                    else:
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    @cached(ttl=3600)
    async def build_reddit_embed(self, link: str):
        if not self.config["reddit"]["build-embeds"]:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                link = await self.get_url_redirect(link)
                async with session.get(link + ".json", timeout=5) as response:
                    if response.status != 200:
                        return None

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
                    post_domain = post.get("domain") or None
                    image = post.get("url_overridden_by_dest") or None
                    thumbnail = post.get("thumbnail") or None

                    if reply:
                        reply_body = (
                            reply.get("body")
                            .replace("&gt;", "\>")
                            .replace("&lt;", "<")
                            .replace("&amp;", "&")
                            .replace("&#x200B;", "")
                        )
                        reply_author = reply.get("author")

                    if image:
                        image = image.lower()
                        if "v.redd.it" in image or image.endswith((".mp4", ".webm")):
                            return None

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

                    embed = discord.Embed()
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

                    if image:
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

                    return embed

        except (aiohttp.ClientError, asyncio.TimeoutError, UnboundLocalError):
            return None

    @cached(ttl=3600)
    async def is_carousel_tiktok(self, link: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(link, timeout=5) as response:
                    if response.status == 200:
                        text = await response.text()
                        return ">Download All Images</button>" in text
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    @cached(ttl=3600)
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

    async def fix_tiktok(self, message: discord.Message, link: str):
        if not self.config["tiktok"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return
        if (
            redirected_url := await self.get_url_redirect(link)
        ) is None or redirected_url.endswith("/live"):
            return

        quickvids_url = await self.quickvids(link)
        if quickvids_url and not await self.is_carousel_tiktok(quickvids_url):
            redirected_url = quickvids_url
        else:
            redirected_url = redirected_url.replace("www.", "")
            redirected_url = redirected_url.replace("tiktok.com", self.config["tiktok"]["url"])

        if message.channel.permissions_for(message.guild.me).send_messages:
            refresh = Refresh(timeout=300, socials_instance=self)
            response = await message.reply(
                redirected_url, mention_author=False, view=refresh
            )
            refresh.response = response
            await asyncio.sleep(0.75)
            with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                await message.edit(suppress=True)

    async def fix_instagram(self, message: discord.Message, link: str):
        if not self.config["instagram"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return

        link = link.replace("www.", "")
        link = link.replace("instagram.com", self.config["instagram"]["url"])

        if message.channel.permissions_for(message.guild.me).send_messages:
            await message.reply(link, mention_author=False)
            await asyncio.sleep(0.75)
            with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                await message.edit(suppress=True)

    async def fix_reddit(self, message: discord.Message, link: str):
        if not self.config["reddit"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return

        embed = await self.build_reddit_embed(link)
        if embed:
            if message.channel.permissions_for(message.guild.me).send_messages:
                await message.reply(embed=embed, mention_author=False)
                await asyncio.sleep(0.75)
                with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                    await message.edit(suppress=True)
            return

        link = link.replace("www.", "")
        link = link.replace("old.reddit.com", "reddit.com")
        link = link.replace("reddit.com", self.config["reddit"]["url"])

        if message.channel.permissions_for(message.guild.me).send_messages:
            await message.reply(link, mention_author=False)
            await asyncio.sleep(0.75)
            with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                await message.edit(suppress=True)

    async def fix_twitter(self, message: discord.Message, link: str):
        if not self.config["twitter"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return

        link = link.replace("www.", "")
        link = link.replace("x.com", "twitter.com")
        link = link.replace("twitter.com", self.config["twitter"]["url"])

        # twitter embeds work for images again, only fix links with a video
        await asyncio.sleep(2)
        if message.embeds:
            embed = message.embeds[0]
            image = embed.to_dict().get("image")
            if image and "video_thumb" in image.get("url"):
                if message.channel.permissions_for(message.guild.me).send_messages:
                    await message.reply(link, mention_author=False)
                    await asyncio.sleep(0.75)
                    with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                        await message.edit(suppress=True)
        else:
            if message.channel.permissions_for(message.guild.me).send_messages:
                await message.reply(link, mention_author=False)
                await asyncio.sleep(0.75)
                with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                    await message.edit(suppress=True)

    async def fix_youtube_shorts(self, message: discord.Message, link: str):
        if not self.config["youtubeshorts"]["enabled"]:
            return
        if f"<{link}>" in message.content:
            return

        link = link.replace("www.", "")
        link = link.replace("youtube.com/shorts/", self.config["youtubeshorts"]["url"])

        if message.channel.permissions_for(message.guild.me).send_messages:
            await message.reply(link, mention_author=False)
            await asyncio.sleep(0.75)
            with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                await message.edit(suppress=True)


async def setup(bot):
    await bot.add_cog(Socials(bot))
