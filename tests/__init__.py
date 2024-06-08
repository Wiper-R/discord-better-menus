from typing import List
import discord
from discord.ext.better_menus import AsyncIteratorPageSource


async def test_generator():
    for x in range(50):
        yield x



class MySource(AsyncIteratorPageSource):
    async def format_page(self, page: List) -> discord.Embed:
        print(page)
        return discord.Embed()
    
    async def get_num_entries() -> int:
        return 10
    
MySource(test_generator(), 10)
