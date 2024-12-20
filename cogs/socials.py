import asyncio
import base64
import hashlib
import io
import json
import logging
import math
import os
import re
import urllib.parse
from contextlib import suppress

import aiohttp
import discord
import ffmpeg
import numpy as np
from aiocache import cached
from async_whisper import AsyncWhisper
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context
from openai import AsyncOpenAI
from PIL import Image
from pydub import AudioSegment
from yt_dlp import YoutubeDL

from utils.colorthief import get_color
from utils.jsons import SocialsJSON, TrackingJSON


class SummarizeTikTokButton(discord.ui.Button):
    def __init__(self, link: str):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="✨",
            label="Summarize",
        )
        self.link = link
        self.summary = None
        self.api_key = os.getenv("OPENAI_TOKEN")
        self.is_generating = False
        self.logger = logging.getLogger("Keto")

    @cached(
        ttl=604800,
        key=lambda *args, **kwargs: f"tiktok_summary:{hashlib.md5(kwargs['link'].encode()).hexdigest()}",
    )
    async def generate_summary(self, link: str):
        video_path = None
        audio_path = None
        frame_paths = []
        try:
            description = None
            qv_token = os.getenv("QUICKVIDS_TOKEN")
            if qv_token:
                headers = {
                    "content-type": "application/json",
                    "user-agent": "Keto - stkc.win",
                    "Authorization": f"Bearer {qv_token}",
                }
                async with aiohttp.ClientSession(headers=headers) as session:
                    url = "https://api.quickvids.win/v2/quickvids/shorturl"
                    data = {"input_text": link, "detailed": True}
                    async with session.post(
                        url, json=data, timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        if response.status == 200:
                            text = await response.text()
                            data = json.loads(text)
                            description = data["details"]["post"]["description"]

            ydl_opts = {
                "format": "mp4",
                "outtmpl": f"/tmp/video_%(id)s.%(ext)s",
                "quiet": True,
                "no_warnings": True,
            }

            loop = asyncio.get_event_loop()
            ydl = YoutubeDL(ydl_opts)
            video_info = await loop.run_in_executor(None, ydl.extract_info, link, False)
            video_path = ydl.prepare_filename(video_info)
            await loop.run_in_executor(None, ydl.process_info, video_info)

            timestamps = [video_info["duration"] * i / 2 for i in range(3)]
            frame_base64s = []

            for i, timestamp in enumerate(timestamps):
                try:
                    frame_path = f"/tmp/frame_{video_info['id']}_{i}.jpg"
                    frame_paths.append(frame_path)

                    stream = ffmpeg.input(video_path, ss=timestamp)
                    stream = ffmpeg.output(stream, frame_path, vframes=1)
                    ffmpeg.run(
                        stream,
                        capture_stdout=True,
                        capture_stderr=True,
                        overwrite_output=True,
                        quiet=True,
                    )

                    with Image.open(frame_path) as img:
                        aspect_ratio = img.width / img.height
                        new_height = 720
                        new_width = int(aspect_ratio * new_height)

                        resized_img = img.resize(
                            (new_width, new_height), Image.Resampling.LANCZOS
                        )

                        buffer = io.BytesIO()
                        resized_img.save(buffer, format="JPEG")
                        buffer.seek(0)

                        frame_base64s.append(
                            base64.b64encode(buffer.getvalue()).decode("utf-8")
                        )
                        buffer.close()

                except Exception as e:
                    continue

            audio_path = f"/tmp/audio_{video_info['id']}.m4a"
            ffmpeg_cmd = (
                f"ffmpeg -i {video_path} -vn -acodec copy {audio_path} -loglevel panic"
            )
            await loop.run_in_executor(None, os.system, ffmpeg_cmd)

            audio = AudioSegment.from_file(audio_path, format="m4a")
            if len(audio) > 180000 or len(audio) < 1000:
                return None

            whisper_client = AsyncWhisper(os.getenv("OPENAI_TOKEN"))
            try:
                transcription = await asyncio.wait_for(
                    whisper_client.transcribe_audio(audio), timeout=10
                )
            except (asyncio.TimeoutError, Exception) as e:
                transcription = None

            if description or transcription:
                message = f"I want you to provide a short summary of a TikTok video based off of the transcription, video description, and video frames [attached] from the beginning, middle, and end of the video. You are allowed to swear. The transcription may not be accurate (song lyrics, no spoken voices) so use all three together. If the video contains a movie or TV show, it is likely mentioned in the video's description. Do not introduce yourself, the summary, or anything else. Only respond with the video summary.\n\nTikTok video description:\n\n{description if description else 'No video description available.'}\n\nVideo transcription:\n\n{transcription if transcription else 'No transcription available.'}"

                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                }

                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": message}]
                            + [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{frame_base64}"
                                    },
                                }
                                for frame_base64 in frame_base64s
                            ],
                        }
                    ],
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return data["choices"][0]["message"]["content"]

            return None

        except Exception as e:
            return None

        finally:
            for path in [video_path, audio_path] + frame_paths:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    async def callback(self, interaction: discord.Interaction):
        if self.is_generating:
            embed = discord.Embed(
                color=discord.Color.light_gray(),
                description="A summary is currently being generated. Try again soon.",
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if interaction.guild:
            self.logger.info(
                f"Executed TikTok summary in {interaction.guild.name} (ID: {interaction.guild.id}) by {interaction.user} (ID: {interaction.user.id})"
            )
        else:
            self.logger.info(
                f"Executed TikTok summary by {interaction.user} (ID: {interaction.user.id}) in DMs"
            )

        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            color=discord.Color.light_gray(),
            description="<a:discordloading:1199066225381228546> Summarizing video...",
        )
        msg = await interaction.followup.send(embed=embed, ephemeral=True)

        try:
            self.is_generating = True
            response = await self.generate_summary(self.link)

            if response:
                embed = discord.Embed(
                    description=response,
                    color=discord.Color.light_gray(),
                )
                embed.set_author(name="Summarized TikTok Video")
                embed.set_footer(text="Summaries may be inaccurate.")
                await msg.edit(embed=embed)
            else:
                embed = discord.Embed(
                    color=discord.Color.light_gray(),
                    description="An error occurred summarizing the video.",
                )
                await msg.edit(embed=embed)
                self.disabled = True
                await interaction.message.edit(view=self.view)

        except Exception as e:
            embed = discord.Embed(
                color=discord.Color.light_gray(),
                description="An error occurred summarizing the video.",
            )
            await msg.edit(embed=embed)
            self.disabled = True
            await interaction.message.edit(view=self.view)

        finally:
            self.is_generating = False


class SummarizeInstagramButton(discord.ui.Button):
    def __init__(self, link: str):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="✨",
            label="Summarize",
        )
        self.link = link
        self.summary = None
        self.api_key = os.getenv("OPENAI_TOKEN")
        self.is_generating = False
        self.logger = logging.getLogger("Keto")

    @cached(
        ttl=604800,
        key=lambda *args, **kwargs: f"instagram_summary:{hashlib.md5(kwargs['link'].encode()).hexdigest()}",
    )
    async def generate_summary(self, link: str, video_bytes=None, message_id=None):
        if self.summary:
            return self.summary

        url_hash = hashlib.md5(link.encode()).hexdigest()[:10]
        video_path = f"/tmp/insta_video_{url_hash}.mp4"
        audio_path = f"/tmp/audio_insta_{url_hash}.m4a"
        frame_paths = []

        try:
            if not video_bytes:
                return None

            with open(video_path, "wb") as f:
                f.write(video_bytes.getvalue())

            probe = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-i",
                video_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await probe.communicate()
            duration_match = re.search(
                r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})", stderr.decode()
            )
            if duration_match:
                hours, minutes, seconds = map(float, duration_match.groups())
                duration = hours * 3600 + minutes * 60 + seconds
                timestamps = [duration * i / 2 for i in range(3)]
            else:
                timestamps = [0, 1, 2]

            frame_base64s = []
            for i, timestamp in enumerate(timestamps):
                try:
                    frame_path = f"/tmp/frame_insta_{url_hash}_{i}.jpg"
                    frame_paths.append(frame_path)

                    stream = ffmpeg.input(video_path, ss=timestamp)
                    stream = ffmpeg.output(stream, frame_path, vframes=1)
                    ffmpeg.run(
                        stream,
                        capture_stdout=True,
                        capture_stderr=True,
                        overwrite_output=True,
                        quiet=True,
                    )

                    with Image.open(frame_path) as img:
                        aspect_ratio = img.width / img.height
                        new_height = 720
                        new_width = int(aspect_ratio * new_height)

                        resized_img = img.resize(
                            (new_width, new_height), Image.Resampling.LANCZOS
                        )

                        buffer = io.BytesIO()
                        resized_img.save(buffer, format="JPEG")
                        buffer.seek(0)

                        frame_base64s.append(
                            base64.b64encode(buffer.getvalue()).decode("utf-8")
                        )
                        buffer.close()

                except Exception as e:
                    continue

            audio_path = f"/tmp/audio_insta_{url_hash}.m4a"
            ffmpeg_cmd = (
                f"ffmpeg -i {video_path} -vn -acodec copy {audio_path} -loglevel panic"
            )
            await asyncio.get_event_loop().run_in_executor(None, os.system, ffmpeg_cmd)

            audio = AudioSegment.from_file(audio_path, format="m4a")
            if len(audio) > 180000 or len(audio) < 1000:
                return None

            whisper_client = AsyncWhisper(os.getenv("OPENAI_TOKEN"))
            try:
                transcription = await asyncio.wait_for(
                    whisper_client.transcribe_audio(audio), timeout=10
                )
            except (asyncio.TimeoutError, Exception) as e:
                transcription = None

            if transcription:
                message = f"I want you to provide a short summary of an Instagram video based off of the transcription and video frames [attached] from the beginning, middle, and end of the video. You are allowed to swear. The transcription may not be accurate (song lyrics, no spoken voices) so use both together. Do not introduce yourself, the summary, or anything else. Only respond with the video summary.\n\nVideo transcription:\n\n{transcription if transcription else 'No transcription available.'}"

                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                }

                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": message}]
                            + [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{frame_base64}"
                                    },
                                }
                                for frame_base64 in frame_base64s
                            ],
                        }
                    ],
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            self.summary = data["choices"][0]["message"]["content"]
                            return self.summary

            return None

        except Exception as e:
            return None

        finally:
            for path in [video_path, audio_path] + frame_paths:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    async def callback(self, interaction: discord.Interaction):
        if self.is_generating:
            embed = discord.Embed(
                color=discord.Color.light_gray(),
                description="A summary is currently being generated. Try again soon.",
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if interaction.guild:
            self.logger.info(
                f"Executed Instagram summary in {interaction.guild.name} (ID: {interaction.guild.id}) by {interaction.user} (ID: {interaction.user.id})"
            )
        else:
            self.logger.info(
                f"Executed Instagram summary by {interaction.user} (ID: {interaction.user.id}) in DMs"
            )

        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            color=discord.Color.light_gray(),
            description="<a:discordloading:1199066225381228546> Summarizing video...",
        )
        msg = await interaction.followup.send(embed=embed, ephemeral=True)

        try:
            self.is_generating = True

            video_attachment = next(
                (
                    a
                    for a in interaction.message.attachments
                    if a.filename.endswith(".mp4")
                ),
                None,
            )

            if video_attachment:
                video_bytes = io.BytesIO()
                await video_attachment.save(video_bytes)
                response = await self.generate_summary(
                    self.link, video_bytes, message_id=interaction.message.id
                )
            else:
                response = None

            if response:
                embed = discord.Embed(
                    description=response,
                    color=discord.Color.light_gray(),
                )
                embed.set_author(name="Summarized Instagram Video")
                embed.set_footer(text="Summaries may be inaccurate.")
                await msg.edit(embed=embed)
            else:
                embed = discord.Embed(
                    color=discord.Color.light_gray(),
                    description="An error occurred summarizing the video.",
                )
                await msg.edit(embed=embed)
                self.disabled = True
                await interaction.message.edit(view=self.view)

        except Exception as e:
            embed = discord.Embed(
                color=discord.Color.light_gray(),
                description="An error occurred summarizing the video.",
            )
            await msg.edit(embed=embed)
            self.disabled = True
            await interaction.message.edit(view=self.view)

        finally:
            self.is_generating = False


class Socials(commands.Cog, name="socials"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.allowed_mentions = discord.AllowedMentions.none()

        self.session_id = os.getenv("INSTAGRAM_SESSION_ID")

        self.config = SocialsJSON().load_json()
        self.config_cog = self.bot.get_cog("Config")
        self.user_config_cog = self.bot.get_cog("UserConfig")
        self.tracking = TrackingJSON().load_json()

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
        self.bluesky_pattern = re.compile(
            r"https:\/\/bsky\.app\/profile\/[a-zA-Z0-9.-]+\/post\/[a-zA-Z0-9]+"
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
            await self.fix_tiktok(message, link, guild_id=message.guild.id)
        elif instagram_match := self.instagram_pattern.search(message_content):
            link = instagram_match.group(0)
            await self.fix_instagram(message, link, guild_id=message.guild.id)
        elif reddit_match := self.reddit_pattern.search(message_content):
            link = reddit_match.group(0)
            await self.fix_reddit(message, link, guild_id=message.guild.id)
        elif twitter_match := self.twitter_pattern.search(message_content):
            link = twitter_match.group(0)
            await self.fix_twitter(message, link, guild_id=message.guild.id)
        elif bluesky_match := self.bluesky_pattern.search(message_content):
            link = bluesky_match.group(0)
            await self.fix_bluesky(message, link, guild_id=message.guild.id)
        # elif youtube_shorts_match := self.youtube_shorts_pattern.search(
        #    message_content
        # ):
        #    link = youtube_shorts_match.group(0)
        #    await self.fix_youtube_shorts(message, link, guild_id=message.guild.id)

    @cached(ttl=604800)
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
        images = []
        try:
            async with aiohttp.ClientSession() as session:

                async def fetch_image(url):
                    async with session.get(url) as response:
                        if not response.status == 200:
                            return None
                        image_data = await response.read()
                        return Image.open(io.BytesIO(image_data))

                images = await asyncio.gather(
                    *[fetch_image(url) for url in image_urls[:12]]
                )
                images = [img for img in images if img is not None]

                if not images:
                    return None

                num_images = len(images)
                ideal_sqrt = math.sqrt(num_images)
                rows = round(ideal_sqrt)
                cols = math.ceil(num_images / rows)

                while rows * cols < num_images:
                    rows += 1

                cell_width = max(img.width for img in images)
                cell_height = max(img.height for img in images)

                resized_images = []
                for img in images:
                    width_ratio = cell_width / img.width
                    height_ratio = cell_height / img.height
                    scale = min(width_ratio, height_ratio)

                    new_width = int(img.width * scale)
                    new_height = int(img.height * scale)

                    resized = img.resize(
                        (new_width, new_height), Image.Resampling.LANCZOS
                    )

                    centered = Image.new(
                        "RGBA", (cell_width, cell_height), (0, 0, 0, 0)
                    )
                    x_offset = (cell_width - new_width) // 2
                    y_offset = (cell_height - new_height) // 2
                    centered.paste(resized, (x_offset, y_offset))

                    resized_images.append(centered)

                grid_width = cols * cell_width
                grid_height = rows * cell_height
                grid_image = Image.new("RGBA", (grid_width, grid_height), (0, 0, 0, 0))

                x, y = 0, 0
                for i, img in enumerate(resized_images):
                    grid_image.paste(img, (x, y))
                    x += cell_width
                    if (i + 1) % cols == 0:
                        y += cell_height
                        x = 0

                if grid_width > 1920:
                    ratio = 1920 / grid_width
                    grid_image = grid_image.resize(
                        (1920, round(grid_height * ratio)), Image.Resampling.LANCZOS
                    )

                output_image = io.BytesIO()
                grid_image.save(output_image, format="PNG")
                output_image.seek(0)
                return output_image

        finally:
            for img in images:
                if img:
                    img.close()

    @cached(ttl=604800)
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
                        .replace("&gt;", ">")
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
                            .replace("&gt;", ">")
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
                        text=f"u/{post_author} • r/{subreddit} • ⬆ {await self.format_number_str(upvotes)} • 💬 {await self.format_number_str(comments)}"
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

    @cached(ttl=604800)
    async def is_carousel_tiktok(self, link: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(link, timeout=5) as response:
                    if response.status == 200:
                        text = await response.text()
                        return ">Download All Images</button>" in text
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    @cached(ttl=604800)
    async def tiktok_has_tracking(self, link: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://who-shared.vercel.app/api/parse?url="
                    + urllib.parse.quote_plus(link),
                    timeout=5,
                ) as response:
                    if response.status == 200:
                        json_data = await response.json()
                        user = json_data["uniqueId"]
                        if user:
                            return True
                    else:
                        return False
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    @cached(ttl=604800)
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
            scaled_num = round(num / (1000 ** power), 1)
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
        await context.defer()
        if re.match(self.tiktok_pattern, link):
            await self.fix_tiktok(context.message, link, context, spoiler)
        elif re.match(self.instagram_pattern, link):
            await self.fix_instagram(context.message, link, context, spoiler)
        elif re.match(self.reddit_pattern, link):
            await self.fix_reddit(context.message, link, context, spoiler)
        elif re.match(self.twitter_pattern, link):
            await self.fix_twitter(context.message, link, context, spoiler)
        elif re.match(self.bluesky_pattern, link):
            await self.fix_bluesky(context.message, link, context, spoiler)
        # elif re.match(self.youtube_shorts_pattern, link):
        #    await self.fix_youtube_shorts(context.message, link, context, spoiler)
        else:
            embed = discord.Embed(
                color=discord.Color.red(),
            )
            embed.description = "Invalid social media link."
            await context.send(embed=embed)

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
            embed = discord.Embed(
                color=discord.Color.red(),
            )
            embed.description = "Invalid TikTok link."
            return await context.send(embed=embed)

        await self.fix_tiktok(context.message, link, context, spoiler)

    async def check_enabled(self, site: str, config, guild_id: int = None):
        if guild_id is None:
            if not self.config[site]["enabled"]:
                return False
        else:
            if not await self.config_cog.get_config_value(guild_id, site, "enabled"):
                return False
        return True

    async def check_tracking(self, site: str, config, user_id: int = None):
        if not await self.user_config_cog.get_config_value(user_id, site, "enabled"):
            return False
        return True

    async def fix_tiktok(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
        guild_id: int = None,
    ):
        if not await self.check_enabled("tiktok", self.config, guild_id):
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

        original_url = redirected_url

        tracking = False
        tracking_warning = ""
        if await self.tiktok_has_tracking(link) and await self.check_tracking(
            "tiktok", self.tracking, message.author.id
        ):
            tracking = True
            tracking_warning = "\n-# The link in your original message includes a tracking ID that may expose your TikTok account. [Learn more.](<https://keto.boats/stop-tracking>)"

        quickvids_url, likes, comments, views, author, author_link = (
            None,
            None,
            None,
            None,
            None,
            None,
        )
        if not spoiler:
            (
                quickvids_url,
                likes,
                comments,
                views,
                author,
                author_link,
            ) = await self.quickvids(link)
        if quickvids_url:
            redirected_url = quickvids_url
        else:
            redirected_url = redirected_url.replace("www.", "")
            redirected_url = redirected_url.replace(
                "tiktok.com", self.config["tiktok"]["url"]
            )

        org_msg = redirected_url if not spoiler else f"||{redirected_url}||"
        view = discord.ui.View(timeout=604800)
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
            if not "/photo/" in original_url:
                view.add_item(SummarizeTikTokButton(link))
            view.add_item(
                discord.ui.Button(
                    label="@" + author,
                    style=discord.ButtonStyle.url,
                    url=author_link,
                    emoji="👤",
                )
            )

        if tracking:
            msg = redirected_url + tracking_warning
        else:
            msg = redirected_url

        if context:
            msg = org_msg
            await context.send(
                msg,
                mention_author=False,
                view=view,
            )
            await self.config_cog.increment_link_fix_count("tiktok")
        else:
            msg = org_msg + tracking_warning
            if message.channel.permissions_for(message.guild.me).send_messages:
                fixed = await message.reply(
                    msg,
                    mention_author=False,
                    view=view,
                )
                await self.config_cog.increment_link_fix_count("tiktok")
                if tracking:
                    await asyncio.sleep(0.75)
                    with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                        await message.edit(suppress=True)
                    await asyncio.sleep(20)
                    await fixed.edit(content=org_msg)
                else:
                    await asyncio.sleep(0.75)
                    with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                        await message.edit(suppress=True)

    async def fix_instagram(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
        guild_id: int = None,
    ):
        if not await self.check_enabled("instagram", self.config, guild_id):
            return
        if f"<{link}>" in message.content:
            return
        spoiler = spoiler or (
            f"||{link}" in message.content and message.content.count("||") >= 2
        )
        tracking = False
        tracking_warning = ""

        if self.config["instagram"]["block-tracking"] and await self.check_tracking(
            "instagram", self.tracking, message.author.id
        ):
            tracking_pattern = r"\?igsh=[\w=]+"
            if re.search(tracking_pattern, link):
                link = re.sub(tracking_pattern, "", link)
                tracking = True
                tracking_warning = "\n-# The link in your original message includes a tracking ID that may expose your Instagram account. [Learn more.](<https://keto.boats/stop-tracking>)"

        link = link.replace("www.", "")
        link = link.replace("instagram.com", self.config["instagram"]["url"])

        session_id = self.session_id

        try:
            auth = aiohttp.BasicAuth(
                os.getenv("IG_API_USERNAME"), os.getenv("IG_API_PASSWORD")
            )
            async with aiohttp.ClientSession(
                auth=auth, headers={"User-Agent": "Keto - stkc.win"}
            ) as session:
                encoded_url = urllib.parse.quote(
                    link.replace(self.config["instagram"]["url"], "instagram.com")
                )
                pk_api_url = (
                    f"https://ketoinstaapi.stkc.win/media/pk_from_url?url={encoded_url}"
                )
                async with session.get(pk_api_url) as response:
                    if response.status == 200:
                        insta_id = (await response.text()).strip('"')

                        if insta_id:
                            info_api_url = "https://ketoinstaapi.stkc.win/media/info"
                            data = {
                                "sessionid": session_id,
                                "pk": str(insta_id),
                                "use_cache": "true",
                            }
                            headers = {
                                "Content-Type": "application/x-www-form-urlencoded",
                                "accept": "application/json",
                            }
                            async with session.post(
                                info_api_url, data=data, headers=headers
                            ) as info_response:
                                if info_response.status == 200:
                                    info_dict = await info_response.json()
                                    username = info_dict.get("user", {}).get(
                                        "username", "Unknown"
                                    )
                                    likes = info_dict.get("like_count", 0)
                                    comments = info_dict.get("comment_count", 0)
                                    views = info_dict.get("play_count", 0)
                                    video_url = info_dict.get("video_url")
                                    photo_url = (
                                        info_dict.get("image_versions2", {})
                                        .get("candidates", [{}])[0]
                                        .get("url")
                                    )

                                    view = discord.ui.View(timeout=604800)
                                    if likes is not None:
                                        view.add_item(
                                            discord.ui.Button(
                                                label=await self.format_number_str(
                                                    likes
                                                ),
                                                disabled=True,
                                                style=discord.ButtonStyle.red,
                                                emoji="🤍",
                                            )
                                        )
                                        view.add_item(
                                            discord.ui.Button(
                                                label=await self.format_number_str(
                                                    comments
                                                ),
                                                disabled=True,
                                                style=discord.ButtonStyle.blurple,
                                                emoji="💬",
                                            )
                                        )
                                        if views > 0:
                                            view.add_item(
                                                discord.ui.Button(
                                                    label=await self.format_number_str(
                                                        views
                                                    ),
                                                    disabled=True,
                                                    style=discord.ButtonStyle.blurple,
                                                    emoji="▶",
                                                )
                                            )
                                        if not "/p/" in link:
                                            view.add_item(
                                                SummarizeInstagramButton(link)
                                            )
                                        if username != "Unknown":
                                            view.add_item(
                                                discord.ui.Button(
                                                    label="@" + username,
                                                    style=discord.ButtonStyle.url,
                                                    url=f"https://instagram.com/{username}",
                                                    emoji="👤",
                                                )
                                            )

                                    if video_url or photo_url:
                                        media_url = (
                                            video_url if video_url else photo_url
                                        )
                                        async with session.get(
                                            media_url
                                        ) as media_response:
                                            if media_response.status == 200:
                                                content_length = int(
                                                    media_response.headers.get(
                                                        "Content-Length", 0
                                                    )
                                                )
                                                if content_length > 8 * 1024 * 1024:
                                                    raise ValueError(
                                                        "Instagram media too large"
                                                    )

                                                media_bytes = io.BytesIO(
                                                    await media_response.read()
                                                )
                                                media_bytes.seek(0)

                                                filename = (
                                                    "instagram_video.mp4"
                                                    if video_url
                                                    else "instagram_photo.jpg"
                                                )
                                                media_file = discord.File(
                                                    media_bytes, filename=filename
                                                )

                                                org_msg = ""
                                                warn_msg = org_msg + tracking_warning

                                                if context:
                                                    await context.send(
                                                        file=media_file, view=view
                                                    )
                                                else:
                                                    if message.channel.permissions_for(
                                                        message.guild.me
                                                    ).send_messages:
                                                        fixed = await message.reply(
                                                            warn_msg
                                                            if tracking
                                                            else org_msg,
                                                            mention_author=False,
                                                            view=view,
                                                            file=media_file,
                                                        )
                                                        if tracking:
                                                            await asyncio.sleep(0.75)
                                                            with suppress(
                                                                discord.errors.Forbidden,
                                                                discord.errors.NotFound,
                                                            ):
                                                                await message.edit(
                                                                    suppress=True
                                                                )
                                                            await asyncio.sleep(20)
                                                            await fixed.edit(
                                                                content=None,
                                                                view=view,
                                                            )
                                                        else:
                                                            await asyncio.sleep(0.75)
                                                            with suppress(
                                                                discord.errors.Forbidden,
                                                                discord.errors.NotFound,
                                                            ):
                                                                await message.edit(
                                                                    suppress=True
                                                                )

                                                return

        except Exception as e:
            print(f"Instagram API Error: {e}")
            pass

        link = urllib.parse.urljoin(link, urllib.parse.urlparse(link).path)
        if link.endswith("/"):
            link = link[:-1]

        org_msg = link if not spoiler else f"||{link}||"
        warn_msg = org_msg + tracking_warning

        if context:
            await context.send(org_msg, mention_author=False)
            await self.config_cog.increment_link_fix_count("instagram")
        else:
            if message.channel.permissions_for(message.guild.me).send_messages:
                fixed = await message.reply(
                    warn_msg if tracking else org_msg, mention_author=False
                )
                await self.config_cog.increment_link_fix_count("instagram")
                if tracking:
                    await asyncio.sleep(0.75)
                    with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                        await message.edit(suppress=True)
                    await asyncio.sleep(20)
                    await fixed.edit(content=org_msg)
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
        guild_id: int = None,
    ):
        if not await self.check_enabled("reddit", self.config, guild_id):
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

        embed, file = await self.build_reddit_embed(link)

        if embed is None:
            link = link.replace("www.", "")
            link = link.replace("old.reddit.com", "reddit.com")
            link = link.replace("reddit.com", self.config["reddit"]["url"])
            if context:
                await context.send(
                    link if not spoiler else f"||{link}||", mention_author=False
                )
                await self.config_cog.increment_link_fix_count("reddit")
            else:
                if message.channel.permissions_for(message.guild.me).send_messages:
                    await message.reply(
                        link if not spoiler else f"||{link}||", mention_author=False
                    )
                    await self.config_cog.increment_link_fix_count("reddit")
                    await asyncio.sleep(0.75)
                    with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                        await message.edit(suppress=True)
            return

        if is_nsfw and embed:
            footer = embed.footer.text
            embed.set_footer(text=f"NSFW • {footer}")

        if context:
            await context.send(embed=embed, file=file, mention_author=False)
            await self.config_cog.increment_link_fix_count("reddit")
        else:
            if message.channel.permissions_for(message.guild.me).send_messages:
                await message.reply(embed=embed, file=file, mention_author=False)
                await self.config_cog.increment_link_fix_count("reddit")
                await asyncio.sleep(0.75)
                with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                    await message.edit(suppress=True)

    async def fix_twitter(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
        guild_id: int = None,
    ):
        if not await self.check_enabled("twitter", self.config, guild_id):
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
            await self.config_cog.increment_link_fix_count("twitter")
        else:
            if message.channel.permissions_for(message.guild.me).send_messages:
                await message.reply(
                    link if not spoiler else f"||{link}||", mention_author=False
                )
                await self.config_cog.increment_link_fix_count("twitter")
                await asyncio.sleep(0.75)
                with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                    await message.edit(suppress=True)

    async def fix_youtube_shorts(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
        guild_id: int = None,
    ):
        if not await self.check_enabled("youtubeshorts", self.config, guild_id):
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

    async def fix_bluesky(
        self,
        message: discord.Message,
        link: str,
        context: Context = None,
        spoiler: bool = False,
        guild_id: int = None,
    ):
        if not await self.check_enabled("bluesky", self.config, guild_id):
            return
        if f"<{link}>" in message.content:
            return
        spoiler = spoiler or (
            f"||{link}" in message.content and message.content.count("||") >= 2
        )

        link = link.replace("www.", "")
        link = link.replace("bsky.app", self.config["bluesky"]["url"])

        if context:
            await context.send(
                link if not spoiler else f"||{link}||", mention_author=False
            )
            await self.config_cog.increment_link_fix_count("bluesky")
        else:
            if message.channel.permissions_for(message.guild.me).send_messages:
                await message.reply(
                    link if not spoiler else f"||{link}||", mention_author=False
                )
                await self.config_cog.increment_link_fix_count("bluesky")
                await asyncio.sleep(0.75)
                with suppress(discord.errors.Forbidden, discord.errors.NotFound):
                    await message.edit(suppress=True)

    @commands.command(name="setsessionid")
    @commands.is_owner()
    async def set_session_id(self, ctx, *, new_id: str):
        """Update the Instagram session ID (owner only)"""
        old_id = self.session_id

        try:
            self.session_id = new_id
            await ctx.message.add_reaction("✅")

            try:
                await ctx.message.delete()
            except:
                pass

        except Exception as e:
            self.session_id = old_id
            await ctx.send("Failed to update session ID.", delete_after=10)


async def setup(bot):
    await bot.add_cog(Socials(bot))
