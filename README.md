![top.gg - Upvotes](https://top.gg/api/widget/upvotes/1128948590467895396.svg?noavatar=true) ![top.gg - Owner](https://top.gg/api/widget/owner/1128948590467895396.svg?noavatar=true)

A Discord bot for fixing social media embeds (TikTok, Instagram, Twitter, Bluesky, Reddit and YouTube) with other cool features.

Setup with Docker (Recommended):

1. `git clone https://github.com/stekc/Keto-Bot`

2. Copy and rename .env.example to .env and config.json.example to config.json, then fill out the required fields.

3. `docker compose up` (add `-d` to run in the background and on startup)

Use `LOAD_ARGS="--only-load cogname,cogname2" docker compose up` to only load specific cogs.

Setup without Docker:

0. You may need to install dependencies manually. Refer to the docker-compose.yml file.

1. `git clone https://github.com/stekc/Keto-Bot`

2. Copy and rename .env.example to .env and config.json.example to config.json, then fill out the required fields.

3. `python3 -m venv .venv`

4. `source .venv/bin/activate`

5. `pip3 install -r requirements.txt`

6. `python3 main.py`

Use `python3 main.py --only-load cogname,cogname2` to only load specific cogs.

Credits:

- [GIRRewrite](https://github.com/DiscordGIR/GIRRewrite)
- [Python-Discord-Bot-Template](https://github.com/kkrypt0nn/Python-Discord-Bot-Template)

---

![Mashiro Shiina from The Pet Girl of Sakurasou](https://i.imgur.com/MZbB58z.jpg)
