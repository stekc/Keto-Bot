import io
import re

import fast_colorthief
from aiohttp import ClientSession

from utils.cache import cached_decorator


@cached_decorator(ttl=604800)
async def get_color(query):
    try:
        # Speed up color fetching for discord avatars
        if any(
            s in query
            for s in {"cdn.discordapp.com/icons/", "cdn.discordapp.com/avatars/"}
        ):
            query = re.sub(
                r"\?size=(32|64|128|256|512|1024|2048|4096)$", "?size=16", query
            )
        async with ClientSession() as session:
            async with session.get(query, timeout=5) as response:
                content = await response.read()

        color = fast_colorthief.get_dominant_color(io.BytesIO(content), quality=100)
        color = int(f"0x{color[0]:02x}{color[1]:02x}{color[2]:02x}", 16)
        return color
    except:
        return 0x505050
